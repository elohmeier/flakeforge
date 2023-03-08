# flakehub

Generate container images using [Nix](https://nixos.org) and serve them via an [Docker Registry HTTP API V2](https://docs.docker.com/registry/spec/api/) compatible HTTP API.

Container image tarballs are generated on the fly and cached by flakehub (but not stored in the Nix store to save disk space).


## How to use

Create a flake.nix ([example repo](https://github.com/elohmeier/flakehub-example)) file to specify the container image (sample below for `x86_64-linux`, tested successfully with `aarch64-linux` as well):

```nix
{
  description = "flakehub example";

  inputs = {
    flakehub.url = "github:elohmeier/flakehub";
    flakehub.inputs.nixpkgs.follows = "nixpkgs";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-22.11";
  };

  outputs = { self, flakehub, nixpkgs }: {

    packages.x86_64-linux.my-bash-image = flakehub.packages.x86_64-linux.flakehubTools.streamLayeredImageConf {
      name = "bash-stream-layered";
      contents = [ nixpkgs.legacyPackages.x86_64-linux.bashInteractive ];
    };

  };
}
```

Run flakenix using `nix run github:elohmeier/flakehub -- $(pwd)` or `nix run github:elohmeier/flakehub -- github:myuser/myrepo` (flakehub is running `nix build ${flakeroot}#${image}` internally).

Use `docker pull localhost:5000/my-bash-image` (package name specified above) to pull the image using Docker.

Use `docker run -it localhost:5000/my-bash-image bash` to start a container with bash.


## How does it work

`streamLayeredImageConf` generates a config file specifying the layers and docker configuration (essentially the same code as in [dockerTools.streamLayeredImage](https://github.com/NixOS/nixpkgs/blob/379ab86ded0f5bb7b5f0b7d8d6c7d9b1e15b80da/pkgs/build-support/docker/default.nix#L830)). That file is picked up by flakehub (using a `nix build` call) and exposed via a [Starlette](https://www.starlette.io/)-based webserver.


## Limitations

Currently this is in a proof of concept state. I'm using it in a Kubernetes cluster to provide container images to the nodes.

- no tag support (not handled, always returns the same image by package name)
- no HTTPS support
- minimal registry API implementation (manifest & digest endpoints only)
- no compression (only tar images)


## Acknowledgements

- Inspired by [Nixery](https://github.com/tazjin/nixery), which provides more generic approach.
- Using code from [Nixpkgs/dockerTools](https://github.com/NixOS/nixpkgs/blob/379ab86ded0f5bb7b5f0b7d8d6c7d9b1e15b80da/pkgs/build-support/docker/default.nix#L830) to provide the on the fly container image tarfile generation.

