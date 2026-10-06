import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { basename, join, relative } from "node:path";
import { pathToFileURL } from "node:url";

import { buildDir, desktopDir, repoRoot } from "./lib.mjs";

export const devServerDist = join(buildDir, "dev-server");

const EXCLUDED = new Set([
  ".build",
  ".git",
  ".mypy_cache",
  ".pytest_cache",
  ".ruff_cache",
  ".venv",
  "__pycache__",
  "dist",
  "node_modules",
  "target",
]);

function copy(source, destination) {
  cpSync(source, destination, {
    recursive: true,
    // Local env files may hold real secrets; the packaged stack generates its own.
    filter: (path) =>
      !relative(source, path)
        .split(/[\\/]/u)
        .some((part) => EXCLUDED.has(part) || part.startsWith(".env")),
  });
}

export function stageDevServer() {
  rmSync(devServerDist, { recursive: true, force: true });
  mkdirSync(devServerDist, { recursive: true });

  for (const file of ["pyproject.toml", "uv.lock"]) {
    const source = join(repoRoot, file);
    if (!existsSync(source)) throw new Error(`missing dev server build input: ${source}`);
    copy(source, join(devServerDist, basename(file)));
  }
  for (const directory of ["packages", "services", "dashboard", "contracts"]) {
    copy(join(repoRoot, directory), join(devServerDist, directory));
  }

  const dockerDist = join(devServerDist, "docker");
  mkdirSync(dockerDist, { recursive: true });
  for (const file of ["api.Dockerfile", "dashboard.Dockerfile", "dashboard.nginx.conf"]) {
    copy(join(repoRoot, "docker", file), join(dockerDist, file));
  }
  for (const file of ["Caddyfile", "docker-compose.yml"]) {
    copy(join(desktopDir, "dev-server", file), join(devServerDist, file));
  }
  return devServerDist;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(`dev server resources: ${stageDevServer()}`);
}
