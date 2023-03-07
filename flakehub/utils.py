import hashlib
import io
import itertools
import json
import os
import pathlib
import sys
import tarfile
from datetime import datetime
from typing import Dict, Tuple


def archive_paths_to(obj, paths, mtime):
    """
    Writes the given store paths as a tar file to the given stream.

    obj: Stream to write to. Should have a 'write' method.
    paths: List of store paths.
    """

    # gettarinfo makes the paths relative, this makes them
    # absolute again
    def append_root(ti):
        ti.name = "/" + ti.name
        return ti

    def apply_filters(ti):
        ti.mtime = mtime
        ti.uid = 0
        ti.gid = 0
        ti.uname = "root"
        ti.gname = "root"
        return ti

    def nix_root(ti):
        ti.mode = 0o0555  # r-xr-xr-x
        return ti

    def dir(path):
        ti = tarfile.TarInfo(path)
        ti.type = tarfile.DIRTYPE
        return ti

    with tarfile.open(fileobj=obj, mode="w|") as tar:
        # To be consistent with the docker utilities, we need to have
        # these directories first when building layer tarballs.
        tar.addfile(apply_filters(nix_root(dir("/nix"))))
        tar.addfile(apply_filters(nix_root(dir("/nix/store"))))

        for path in paths:
            path = pathlib.Path(path)
            if path.is_symlink():
                files = [path]
            else:
                files = itertools.chain([path], path.rglob("*"))

            for filename in sorted(files):
                ti = append_root(tar.gettarinfo(filename))

                # copy hardlinks as regular files
                if ti.islnk():
                    ti.type = tarfile.REGTYPE
                    ti.linkname = ""
                    ti.size = filename.stat().st_size

                ti = apply_filters(ti)
                if ti.isfile():
                    with open(filename, "rb") as f:
                        tar.addfile(ti, f)
                else:
                    tar.addfile(ti)


class ExtractChecksum:
    """
    A writable stream which only calculates the final file size and
    sha256sum, while discarding the actual contents.
    """

    def __init__(self):
        self._digest = hashlib.sha256()
        self._size = 0

    def write(self, data):
        self._digest.update(data)
        self._size += len(data)

    def extract(self):
        """
        Returns: Hex-encoded sha256sum and size as a tuple.
        """
        return (self._digest.hexdigest(), self._size)


def get_manifest(
    nixConfPath: str,
) -> Tuple[Dict[str, Tuple[str, str, int]], Dict, bytes]:

    digest_map = {}
    layers = []

    with open(nixConfPath) as f:
        conf = json.load(f)

    mtime = int(datetime.fromisoformat(conf["created"]).timestamp())

    for num, store_layer in enumerate(conf["store_layers"]):
        print("Creating layer", num, "from paths:", store_layer, file=sys.stderr)

        # First, calculate the tarball checksum and the size.
        extract_checksum = ExtractChecksum()
        archive_paths_to(
            extract_checksum,
            store_layer,
            mtime=mtime,
        )
        (checksum, size) = extract_checksum.extract()
        print("Checksum:", checksum, file=sys.stderr)
        print("Size:", size, file=sys.stderr)

        path = store_layer[0]
        print(path)
        layers.append(
            {
                "mediaType": "application/vnd.docker.image.rootfs.diff.tar",
                "size": size,
                "digest": f"sha256:{checksum}",
            }
        )
        digest_map[checksum] = (path, "store_layer", mtime)

    checksum_path = os.path.join(conf["customisation_layer"], "checksum")
    with open(checksum_path) as f:
        checksum = f.read().strip()
    assert len(checksum) == 64, f"Invalid sha256 at ${checksum_path}."
    customisation_layer_size = os.path.getsize(
        os.path.join(conf["customisation_layer"], "layer.tar")
    )

    print("Customisation layer:", conf["customisation_layer"], file=sys.stderr)
    print("Customisation layer checksum:", checksum, file=sys.stderr)
    print("Customisation layer size:", customisation_layer_size, file=sys.stderr)

    layers.append(
        {
            "mediaType": "application/vnd.docker.image.rootfs.diff.tar",
            "size": customisation_layer_size,
            "digest": f"sha256:{checksum}",
        }
    )
    digest_map[checksum] = (conf["customisation_layer"], "customisation_layer", mtime)

    config = {
        "created": datetime.fromisoformat(conf["created"]).isoformat(),
        "architecture": conf["architecture"],
        "os": "linux",
        "config": conf["config"],
        "rootfs": {
            "type": "layers",
            "diff_ids": ["sha256:" + checksum for checksum in digest_map.keys()],
        },
        "history": [
            {
                "created": datetime.fromisoformat(conf["created"]).isoformat(),
                "comment": "store path: {}".format(path),
            }
            for path, _, _ in digest_map.values()
        ],
    }

    config_data = json.dumps(config).encode("utf-8")
    config_checksum = hashlib.sha256(config_data).hexdigest()

    digest_map[config_checksum] = ("config", "config", mtime)

    return (
        digest_map,
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "config": {
                "mediaType": "application/vnd.docker.container.image.v1+json",
                "size": len(config_data),
                "digest": f"sha256:{config_checksum}",
            },
            "layers": layers,
        },
        config_data,
    )


def get_store_layer_tar(store_path: str, mtime: int) -> io.BytesIO:
    buffer = io.BytesIO()
    archive_paths_to(buffer, [store_path], mtime=mtime)
    buffer.seek(0)
    return buffer
