# flakehub

Generate container images using [Nix](https://nixos.org) and serve them via an [Docker Registry HTTP API V2](https://docs.docker.com/registry/spec/api/) compatible HTTP API.

Container image tarballs are generated on the fly and not stored in the Nix store to save disk space.


## Acknowledgements

- Inspired by [Nixery](https://github.com/tazjin/nixery), providing a more generic approach.
- Using code from [Nixpkgs/dockerTools](https://github.com/NixOS/nixpkgs/blob/379ab86ded0f5bb7b5f0b7d8d6c7d9b1e15b80da/pkgs/build-support/docker/default.nix#L830) to provide the on the fly container image tarfile generation.

