{ overlay }: { config, lib, pkgs, ... }:

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
    extraFlags = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Extra flags to pass to flakehub.";
    };
  };

  config = mkIf cfg.enable {

    nixpkgs.overlays = [ overlay ];

    systemd.services.flakehub = {
      description = "flakehub";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      wants = [ "network.target" ];

      path = with pkgs; [ gitMinimal nixFlakes ];
      environment = {
        HOME = "/var/lib/flakehub";
      };

      serviceConfig = {
        ExecStart = "${cfg.package}/bin/flakehub --host ${cfg.listenAddress} --port ${toString cfg.listenPort} --cache-dir /var/cache/flakehub ${concatStringsSep " " cfg.extraFlags} ${cfg.flakeRoot}";
        DynamicUser = true;
        StateDirectory = "flakehub";
        CacheDirectory = "flakehub";
        Restart = "always";
        WorkingDirectory = "/var/lib/flakehub";
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        NoNewPrivileges = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictAddressFamilies = "AF_UNIX AF_INET AF_INET6";
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        SystemCallArchitectures = "native";
      };
    };

  };

}
