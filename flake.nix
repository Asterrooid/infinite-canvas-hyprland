{
  description = "Infinite canvas and navigation tools for Hyprland";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs supportedSystems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs:
        let
          pythonEnv = pkgs.python3.withPackages (ps: with ps; [ evdev ]);
          runtimePath = pkgs.lib.makeBinPath [
            pythonEnv
            pkgs.jq
            pkgs.bash
            pkgs.coreutils
            pkgs.findutils
          ];
        in
        {
          default = pkgs.runCommand "hyprland-infinite-desktop"
            {
              nativeBuildInputs = [ pkgs.makeWrapper ];
              meta = with pkgs.lib; {
                description = "Infinite canvas and navigation tools for Hyprland";
                homepage = "https://github.com/Asterrooid/infinite-canvas-hyprland";
                license = licenses.mit;
                platforms = [ "x86_64-linux" "aarch64-linux" ];
                mainProgram = "canvas_zoom.py";
              };
            }
            ''
              mkdir -p $out/bin $out/lib/hyprland-infinite-desktop

              # Copy runtime scripts
              find ${./scripts} -maxdepth 1 -type f \( -name "*.py" -o -name "*.sh" \) -exec cp {} $out/lib/hyprland-infinite-desktop/ \;
              chmod +x $out/lib/hyprland-infinite-desktop/*.{py,sh}

              # Wrap Python scripts
              for file in $out/lib/hyprland-infinite-desktop/*.py; do
                name=$(basename "$file")
                makeWrapper "${pythonEnv}/bin/python3" "$out/bin/$name" \
                  --add-flags "$file" \
                  --prefix PATH : "${runtimePath}" \
                  --prefix PYTHONPATH : "$out/lib/hyprland-infinite-desktop"
              done

              # Wrap Bash scripts
              for file in $out/lib/hyprland-infinite-desktop/*.sh; do
                name=$(basename "$file")
                makeWrapper "${pkgs.bash}/bin/bash" "$out/bin/$name" \
                  --add-flags "$file" \
                  --prefix PATH : "${runtimePath}" \
                  --prefix PYTHONPATH : "$out/lib/hyprland-infinite-desktop"
              done

              # Friendly CLI command aliases
              ln -s $out/bin/canvas_zoom.py $out/bin/canvas-zoom
              ln -s $out/bin/floating_tile_toggle.py $out/bin/floating-tile-toggle
              ln -s $out/bin/infinite-desktop.sh $out/bin/infinite-desktop
              ln -s $out/bin/infinite_desktop_core.py $out/bin/infinite-desktop-core
              ln -s $out/bin/move_window.py $out/bin/move-window
              ln -s $out/bin/move_window_tiled.py $out/bin/move-window-tiled
              ln -s $out/bin/navigate_windows.py $out/bin/navigate-windows
              ln -s $out/bin/resize_window.py $out/bin/resize-window
            '';
        }
      );

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: with ps; [ evdev ]))
            pkgs.jq
            pkgs.bash
          ];
        };
      });
    };
}
