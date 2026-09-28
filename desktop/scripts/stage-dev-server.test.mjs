import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { devServerDist, stageDevServer } from "./stage-dev-server.mjs";

test("the Dev installer stages a bounded, buildable local server snapshot", () => {
  assert.equal(stageDevServer(), devServerDist);
  for (const path of [
    "pyproject.toml",
    "uv.lock",
    "packages/studio-client/pyproject.toml",
    "services/api/alembic.ini",
    "dashboard/package.json",
    "contracts/fixtures",
    "docker/api.Dockerfile",
    "docker/dashboard.Dockerfile",
    "Caddyfile",
    "docker-compose.yml",
  ]) {
    assert.equal(existsSync(join(devServerDist, path)), true, path);
  }
  assert.equal(existsSync(join(devServerDist, "dashboard", "node_modules")), false);
  assert.equal(existsSync(join(devServerDist, "services", "api", "__pycache__")), false);
  const compose = readFileSync(join(devServerDist, "docker-compose.yml"), "utf8");
  assert.match(compose, /127\.0\.0\.1:8765:80/);
  assert.match(compose, /127\.0\.0\.1:8766:9000/);
  assert.doesNotMatch(compose, /0\.0\.0\.0:/);
});
