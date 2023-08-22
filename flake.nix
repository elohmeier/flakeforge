{
  description = "flakeforge";

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
          docker-image-stream = pkgs.flakeforgeTools.streamLayeredImageConf {
            name = "bash-stream-layered";
            contents = [ pkgs.bashInteractive ];
          };

          flakeforge = pkgs.flakeforge;
          flakeforgeTools = pkgs.flakeforgeTools;
        };

        defaultPackage = pkgs.flakeforge;
      }) // {
      nixosModules = rec {
        flakeforge = import ./nixos { inherit (self) overlay; };
        default = flakeforge;
      };

      overlay = self: super: {
        flakeforge = with super.python3Packages; buildPythonApplication {
          pname = "flakeforge";
          version = "0.0.1";
          src = ./src;
          propagatedBuildInputs = [ starlette uvicorn ];
        };
        flakeforgeTools = self.callPackage ./flakeforge-tools { };
      };
    };
}
