{
  description = "Plataforma de Evaluacion de Madurez de Ciberseguridad - entorno de desarrollo";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python312
              pkgs.uv
              pkgs.ruff
              pkgs.docker-compose
              pkgs.redis
              pkgs.nodejs_22
            ];

            shellHook = ''
              export UV_PYTHON=${pkgs.python312}/bin/python3.12
              echo "Backend: cd backend && uv sync && uv run pytest"
              echo "Redis para dev local (workers, o tests que lo necesiten): redis-server --daemonize yes"
              echo "Frontend: cd frontend && npm install && npm run dev"
            '';
          };
        });
    };
}
