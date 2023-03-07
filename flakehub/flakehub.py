import os

from starlette.applications import Starlette
from starlette.config import Config
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .utils import get_manifest, get_store_layer_tar

config = Config(".env")

DEBUG = config("DEBUG", cast=bool, default=False)

IMAGE_CONF_PATH = config(
    "IMAGE_CONF_PATH",
    default="/nix/store/0vciq38r8whz5a4ckyqm6zwx6417avml-bash-stream-layered-conf.json",
)

digest_map, manifest, config_data = get_manifest(IMAGE_CONF_PATH)


async def v2(_):
    return JSONResponse({})


async def v2_manifests(
    request,
):
    image = request.path_params["image"]
    tag = request.path_params["tag"]
    print(image, tag)

    return JSONResponse(
        manifest,
        media_type="application/vnd.docker.distribution.manifest.v2+json",
    )


async def v2_blobs(request):
    image = request.path_params["image"]
    digest = request.path_params["digest"]

    print(image, digest)

    res, media_type, mtime = digest_map[digest]
    print(res, media_type, mtime)

    if media_type == "config":
        return Response(
            config_data, media_type="application/vnd.docker.container.image.v1+json"
        )
    elif media_type == "store_layer":
        return StreamingResponse(
            get_store_layer_tar(res, mtime), media_type="application/x-tar"
        )
    elif media_type == "customisation_layer":
        tar_path = os.path.join(res, "layer.tar")
        return FileResponse(tar_path, media_type="application/x-tar")
    else:
        raise NotImplementedError()


app = Starlette(
    debug=DEBUG,
    routes=[
        Route("/v2/", v2),
        Route("/v2/{image}/manifests/{tag}", v2_manifests),
        Route("/v2/{image}/blobs/sha256:{digest}", v2_blobs),
    ],
)
