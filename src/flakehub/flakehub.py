import argparse
import logging
import os

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


def server(flakeroot, debug, cache_dir):
    cache = {}

    async def v2(_):
        return JSONResponse({})

    async def v2_manifests(
        request,
    ):
        image = request.path_params["image"]
        tag = request.path_params["tag"]
        logger.debug("image: %s, tag: %s", image, tag)

        if image not in cache:
            try:
                conf_path = build_conf(flakeroot, image)
            except BuildImageError as e:
                return JSONResponse(
                    content={
                        "errors": [
                            {
                                "code": "MANIFEST_UNKNOWN",
                                "message": str(e),
                                "detail": {
                                    "Tag": tag,
                                },
                            }
                        ]
                    },
                    status_code=404,
                )
            cache[image] = get_manifest(conf_path)
        _, manifest, _ = cache[image]

        return JSONResponse(
            manifest,
            media_type="application/vnd.docker.distribution.manifest.v2+json",
        )

    async def v2_blobs(request):
        image = request.path_params["image"]
        digest = request.path_params["digest"]

        logger.debug("image: %s, digest: %s", image, digest)

        if image not in cache:
            try:
                conf_path = build_conf(flakeroot, image)
            except BuildImageError as e:
                return JSONResponse(
                    content={
                        "errors": [
                            {
                                "code": "MANIFEST_UNKNOWN",
                                "message": str(e),
                                "detail": {
                                    "Digest": digest,
                                },
                            }
                        ]
                    },
                    status_code=404,
                )
            cache[image] = get_manifest(conf_path)
        digest_map, _, config_data = cache[image]

        res, media_type, mtime = digest_map[digest]
        logger.debug("res: %s, media_type: %s, mtime: %s", res, media_type, mtime)

        if media_type == "config":
            return Response(
                config_data, media_type="application/vnd.docker.container.image.v1+json"
            )
        elif media_type == "store_layer":
            cached_path = get_store_layer_tar_path(cache_dir, digest, res, mtime)
            return FileResponse(cached_path, media_type="application/x-tar")
        elif media_type == "customisation_layer":
            tar_path = os.path.join(res, "layer.tar")
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
