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
        pkgs = import nixpkgs { inherit system; overlays = [ self.overlay ]; };
      in
      {
        packages = {
          docker-image-stream = pkgs.flakehubTools.streamLayeredImageConf {
            name = "bash-stream-layered";
            contents = [ pkgs.bashInteractive ];
          };

          flakehub = pkgs.flakehub;
          flakehubTools = pkgs.flakehubTools;
        };

        defaultPackage = pkgs.flakehub;
      }) // {
      nixosModules = rec {
        flakehub = import ./nixos { inherit (self) overlay; };
        default = flakehub;
      };

      overlay = self: super: {
        flakehub = with super.python3Packages; buildPythonApplication {
          pname = "flakehub";
          version = "0.0.1";
          src = ./src;
          propagatedBuildInputs = [ starlette uvicorn ];
        };
        flakehubTools = self.callPackage ./flakehub-tools { };
      };
    };
}
