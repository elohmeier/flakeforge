import argparse
import logging
import os
import time
from functools import lru_cache

import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from flakehub.utils import (
    BuildImageError,
    build_conf,
    get_manifest,
    get_store_layer_tar_path,
)

logger = logging.getLogger(__name__)


def _unkown_manifest(tag):
    return JSONResponse(
        content={
            "errors": [
                {
                    "code": "MANIFEST_UNKNOWN",
                    "message": "manifest unknown",
                    "detail": {
                        "Tag": tag,
                    },
                }
            ]
        },
        status_code=404,
    )


def _unkown_blob(digest):
    return JSONResponse(
        content={
            "errors": [
                {
                    "code": "BLOB_UNKNOWN",
                    "message": "blob unknown to registry",
                    "detail": {
                        "Tag": digest,
                    },
                }
            ]
        },
        status_code=404,
    )


def server(flakeroot, debug, cache_dir):
    server_digest_map = {}

    @lru_cache()
    def _get_manifest(image, tag, ttl_hash=None):
        del ttl_hash
        return get_manifest(build_conf(flakeroot, image, tag))

    def _get_ttl_hash(seconds=10):
        return round(time.time() / seconds)

    async def v2(_):
        return JSONResponse({})

    async def v2_manifests(
        request,
    ):
        image = request.path_params["image"]
        tag = request.path_params["tag"]
        logger.debug("[v2_manifests] image: %s, tag: %s", image, tag)

        if tag.startswith("sha256:"):
            # pull manifest by digest
            try:
                dig = server_digest_map[tag.split(":", 1)[1]]
            except KeyError:
                return _unkown_manifest(tag)
            return Response(
                dig.data,
                media_type="application/vnd.docker.distribution.manifest.v2+json",
            )

        try:
            # pull manifest by tag
            digest_map, manifest_data = _get_manifest(image, tag, _get_ttl_hash())
            server_digest_map.update(digest_map)
        except BuildImageError as e:
            logger.error("Failed to build image: %s", e)
            return _unkown_manifest(tag)

        return Response(
            manifest_data,
            media_type="application/vnd.docker.distribution.manifest.v2+json",
        )

    async def v2_blobs(request):
        image = request.path_params["image"]
        digest = request.path_params["digest"]

        logger.debug("[v2_blobs] image: %s, digest: %s", image, digest)

        try:
            dig = server_digest_map[digest]
        except KeyError:
            return _unkown_blob(digest)

        if dig.media_type == "config":
            return Response(
                dig.data,
                media_type="application/vnd.docker.container.image.v1+json",
            )
        elif dig.media_type == "store_layer":
            cached_path = get_store_layer_tar_path(
                cache_dir, digest, dig.response, dig.mtime
            )
            return FileResponse(cached_path, media_type="application/x-tar")
        elif dig.media_type == "customisation_layer":
            tar_path = os.path.join(dig.response, "layer.tar")
            return FileResponse(tar_path, media_type="application/x-tar")
        else:
            raise NotImplementedError()

    return Starlette(
        debug=debug,
        routes=[
            Route("/v2/", v2),
            Route("/v2/{image}/manifests/{tag}", v2_manifests),
            Route("/v2/{image}/blobs/sha256:{digest}", v2_blobs),
        ],
    )


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host",
        "-H",
        default="127.0.0.1",
        help="Host to listen on (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        "-p",
        default=5000,
        type=int,
        help="Port to listen on (default: 5000)",
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Enable debug mode",
    )
    parser.add_argument(
        "--cache-dir",
        "-c",
        default="/tmp/flakehub",
        help="Cache directory (default: /tmp/flakehub)",
    )
    parser.add_argument("flakeroot", help="Path to the flake root")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    app = server(args.flakeroot, args.debug, args.cache_dir)
    uvicorn.run(app, host=args.host, port=args.port)  # type: ignore
