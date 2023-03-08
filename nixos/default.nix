{ config, lib, pkgs, ... }:

with lib;
let
  cfg = config.services.flakehub;
in
{
  options.services.flakehub = {
    enable = mkEnableOption "flakehub";
    package = mkOption {
      type = types.package;
      default = pkgs.flakehub;
      defaultText = "pkgs.flakehub";
      description = "The flakehub package to use.";
    };
    listenAddress = mkOption {
      type = types.str;
      default = "127.0.0.1";
      description = "The address to listen on.";
    };
    listenPort = mkOption {
      type = types.port;
      default = 5000;
      description = "The port to listen on.";
    };
    flakeRoot = mkOption {
      type = types.str;
      example = "github:myuser/myrepo";
      description = "The flake root to serve images from.";
    };
  };

  config = mkIf cfg.enable {

    # systemd.services.flakehub = { };

  };

}
