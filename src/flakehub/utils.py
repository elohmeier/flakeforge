import hashlib
import io
import itertools
import json
import logging
import os
import pathlib
import subprocess
import tarfile
from datetime import datetime
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


# src: https://github.com/NixOS/nixpkgs/blob/a36fdb523f401b4036e836374fd3d6dab0880f88/pkgs/build-support/docker/stream_layered_image.py#L48
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


# src: https://github.com/NixOS/nixpkgs/blob/a36fdb523f401b4036e836374fd3d6dab0880f88/pkgs/build-support/docker/stream_layered_image.py#L48
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
        logger.debug("Creating layer %s from paths: %s", num, store_layer)

        # First, calculate the tarball checksum and the size.
        extract_checksum = ExtractChecksum()
        archive_paths_to(
            extract_checksum,
            store_layer,
            mtime=mtime,
        )
        (checksum, size) = extract_checksum.extract()
        logger.debug("Checksum: %s, size: %s", checksum, size)

        path = store_layer[0]
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

    logger.debug(
        "Customisation layer: %s (size: %s, checksum: %s)",
        conf["customisation_layer"],
        customisation_layer_size,
        checksum,
    )

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


class BuildImageError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def build_conf(flakeroot: str, image: str) -> str:
    logger.debug("Building image %s", image)

    cmd = ["nix", "build", "--no-link", "--print-out-paths", f"{flakeroot}#{image}"]
    logger.debug("Running command: %s", " ".join(cmd))

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as proc:
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            raise BuildImageError(f"Error building image {image}: {stderr}")
        nix_path = stdout.strip()

    logger.debug("Nix path: %s", nix_path)
    return nix_path
