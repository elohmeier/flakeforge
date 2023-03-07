{
  description = "flakehub";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self
    , flake-utils
    , nixpkgs
    }:
    flake-utils.lib.eachDefaultSystem
      (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        packages = {
          docker-image-stream = pkgs.dockerTools.streamLayeredImage {
            name = "bash-stream-layered";
            contents = [ pkgs.bashInteractive ];
          };
        };
      });
}
