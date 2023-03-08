{ bashInteractive
, buildPackages
, coreutils
, fakechroot
, fakeroot
, go
, jq
, lib
, runCommand
, storeDir ? builtins.storeDir
, symlinkJoin
, util-linux
, writeText
}:

let
  inherit (lib)
    optionals
    optionalString
    ;

  # The OCI Image specification recommends that configurations use values listed
  # in the Go Language document for GOARCH.
  # Reference: https://github.com/opencontainers/image-spec/blob/master/config.md#properties
  # For the mapping from Nixpkgs system parameters to GOARCH, we can reuse the
  # mapping from the go package.
  defaultArchitecture = go.GOARCH;
in
{
  # adapted from https://github.com/NixOS/nixpkgs/blob/a36fdb523f401b4036e836374fd3d6dab0880f88/pkgs/build-support/docker/default.nix#L830
  streamLayeredImageConf =
    {
      # Image Name
      name
    , # Image tag, the Nix's output hash will be used if null
      tag ? null
    , # Parent image, to append to.
      fromImage ? null
    , # Files to put on the image (a nix store path or list of paths).
      contents ? [ ]
    , # Docker config; e.g. what command to run on the container.
      config ? { }
    , # Image architecture, defaults to the architecture of the `hostPlatform` when unset
      architecture ? defaultArchitecture
    , # Time of creation of the image. Passing "now" will make the
      # created date be the time of building.
      created ? "1970-01-01T00:00:01Z"
    , # Optional bash script to run on the files prior to fixturizing the layer.
      extraCommands ? ""
    , # Optional bash script to run inside fakeroot environment.
      # Could be used for changing ownership of files in customisation layer.
      fakeRootCommands ? ""
    , # Whether to run fakeRootCommands in fakechroot as well, so that they
      # appear to run inside the image, but have access to the normal Nix store.
      # Perhaps this could be enabled on by default on pkgs.stdenv.buildPlatform.isLinux
      enableFakechroot ? false
    , # We pick 100 to ensure there is plenty of room for extension. I
      # believe the actual maximum is 128.
      maxLayers ? 100
    , # Whether to include store paths in the image. You generally want to leave
      # this on, but tooling may disable this to insert the store paths more
      # efficiently via other means, such as bind mounting the host store.
      includeStorePaths ? true
    , # Passthru arguments for the underlying derivation.
      passthru ? { }
    ,
    }:
      assert
      (lib.assertMsg (maxLayers > 1)
        "the maxLayers argument of dockerTools.buildLayeredImage function must be greather than 1 (current value: ${toString maxLayers})");
      let
        baseName = baseNameOf name;

        baseJson = writeText "${baseName}-base.json" (builtins.toJSON {
          inherit config architecture;
          os = "linux";
        });

        contentsList = if builtins.isList contents then contents else [ contents ];

        # We store the customisation layer as a tarball, to make sure that
        # things like permissions set on 'extraCommands' are not overridden
        # by Nix. Then we precompute the sha256 for performance.
        customisationLayer = symlinkJoin {
          name = "${baseName}-customisation-layer";
          paths = contentsList;
          inherit extraCommands fakeRootCommands;
          nativeBuildInputs = [
            fakeroot
          ] ++ optionals enableFakechroot [
            fakechroot
            # for chroot
            coreutils
            # fakechroot needs getopt, which is provided by util-linux
            util-linux
          ];
          postBuild = ''
            mv $out old_out
            (cd old_out; eval "$extraCommands" )

            mkdir $out
            ${optionalString enableFakechroot ''
              export FAKECHROOT_EXCLUDE_PATH=/dev:/proc:/sys:${builtins.storeDir}:$out/layer.tar
            ''}
            ${optionalString enableFakechroot ''fakechroot chroot $PWD/old_out ''}fakeroot bash -c '
              source $stdenv/setup
              ${optionalString (!enableFakechroot) ''cd old_out''}
              eval "$fakeRootCommands"
              tar \
                --sort name \
                --numeric-owner --mtime "@$SOURCE_DATE_EPOCH" \
                --hard-dereference \
                -cf $out/layer.tar .
            '

            sha256sum $out/layer.tar \
              | cut -f 1 -d ' ' \
              > $out/checksum
          '';
        };

        closureRoots = lib.optionals includeStorePaths /* normally true */ (
          [ baseJson customisationLayer ]
        );
        overallClosure = writeText "closure" (lib.concatStringsSep " " closureRoots);

        # These derivations are only created as implementation details of docker-tools,
        # so they'll be excluded from the created images.
        unnecessaryDrvs = [ baseJson overallClosure customisationLayer ];

        conf = runCommand "${baseName}-conf.json"
          {
            inherit fromImage maxLayers created;
            imageName = lib.toLower name;
            preferLocalBuild = true;
            passthru.imageTag =
              if tag != null
              then tag
              else
                lib.head (lib.strings.splitString "-" (baseNameOf conf.outPath));
            paths = buildPackages.referencesByPopularity overallClosure;
            nativeBuildInputs = [ jq ];
          } ''
          ${if (tag == null) then ''
            outName="$(basename "$out")"
            outHash=$(echo "$outName" | cut -d - -f 1)

            imageTag=$outHash
          '' else ''
            imageTag="${tag}"
          ''}

          # convert "created" to iso format
          if [[ "$created" != "now" ]]; then
              created="$(date -Iseconds -d "$created")"
          fi

          paths() {
            cat $paths ${lib.concatMapStringsSep " "
                           (path: "| (grep -v ${path} || true)")
                           unnecessaryDrvs}
          }

          # Compute the number of layers that are already used by a potential
          # 'fromImage' as well as the customization layer. Ensure that there is
          # still at least one layer available to store the image contents.
          usedLayers=0

          # subtract number of base image layers
          if [[ -n "$fromImage" ]]; then
            (( usedLayers += $(tar -xOf "$fromImage" manifest.json | jq '.[0].Layers | length') ))
          fi

          # one layer will be taken up by the customisation layer
          (( usedLayers += 1 ))

          if ! (( $usedLayers < $maxLayers )); then
            echo >&2 "Error: usedLayers $usedLayers layers to store 'fromImage' and" \
                      "'extraCommands', but only maxLayers=$maxLayers were" \
                      "allowed. At least 1 layer is required to store contents."
            exit 1
          fi
          availableLayers=$(( maxLayers - usedLayers ))

          # Create $maxLayers worth of Docker Layers, one layer per store path
          # unless there are more paths than $maxLayers. In that case, create
          # $maxLayers-1 for the most popular layers, and smush the remainaing
          # store paths in to one final layer.
          #
          # The following code is fiddly w.r.t. ensuring every layer is
          # created, and that no paths are missed. If you change the
          # following lines, double-check that your code behaves properly
          # when the number of layers equals:
          #      maxLayers-1, maxLayers, and maxLayers+1, 0
          paths |
            jq -sR '
              rtrimstr("\n") | split("\n")
                | (.[:$maxLayers-1] | map([.])) + [ .[$maxLayers-1:] ]
                | map(select(length > 0))
              ' \
              --argjson maxLayers "$availableLayers" > store_layers.json

          # The index on $store_layers is necessary because the --slurpfile
          # automatically reads the file as an array.
          cat ${baseJson} | jq '
            . + {
              "store_dir": $store_dir,
              "from_image": $from_image,
              "store_layers": $store_layers[0],
              "customisation_layer", $customisation_layer,
              "repo_tag": $repo_tag,
              "created": $created
            }
            ' --arg store_dir "${storeDir}" \
              --argjson from_image ${if fromImage == null then "null" else "'\"${fromImage}\"'"} \
              --slurpfile store_layers store_layers.json \
              --arg customisation_layer ${customisationLayer} \
              --arg repo_tag "$imageName:$imageTag" \
              --arg created "$created" |
            tee $out
        '';
      in
      conf;
}
