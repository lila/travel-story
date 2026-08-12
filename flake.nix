{
  description = "Travel Story development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; config.allowBroken = true; };
          python = pkgs.python312;
          travel-story = python.pkgs.buildPythonApplication {
            pname = "travel-story";
            version = "0.1.0";
            pyproject = true;
            src = self;

            build-system = [ python.pkgs.setuptools ];
            nativeBuildInputs = [ pkgs.makeWrapper ];
            dependencies = with python.pkgs; [
              markdown
              pillow
              staticmap
            ];

            nativeCheckInputs = [ python.pkgs.pytestCheckHook ];
            pythonImportsCheck = [ "story" ];

            postFixup = ''
              wrapProgram $out/bin/story \
                --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.exiftool ]}
            '';
          };
        in
        {
          default = travel-story;
          inherit travel-story;
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/story";
        };
      });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; config.allowBroken = true; };
          install-osxphotos = pkgs.writeShellApplication {
            name = "story-install-osxphotos";
            runtimeInputs = [ pkgs.uv ];
            text = ''
              uv tool install --python ${pkgs.python313}/bin/python osxphotos
              echo "OSXPhotos installed. If 'osxphotos' is not found, add $HOME/.local/bin to PATH."
            '';
          };
        in
        {
          default = pkgs.mkShell {
            inputsFrom = [ self.packages.${system}.default ];
            packages = [
              self.packages.${system}.default
              pkgs.exiftool
              pkgs.python312.pkgs.pytest
              pkgs.uv
              install-osxphotos
            ];
            shellHook = ''
              export PATH="$HOME/.local/bin:$PATH"
            '';
          };
        });
    };
}
