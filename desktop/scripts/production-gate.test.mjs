import assert from "node:assert/strict";
import { createServer } from "node:http";
import { afterEach, test } from "node:test";

import { parseArgs, runGate } from "./production-gate.mjs";

const servers = [];

afterEach(async () => {
  await Promise.all(servers.splice(0).map((server) => new Promise((resolve) => server.close(resolve))));
});

async function fixture(overrides = {}) {
  const state = {
    registration: overrides.registration ?? "present",
    missingRoute: overrides.missingRoute ?? false,
    betaOrigin: overrides.betaOrigin,
    stableMissing: overrides.stableMissing ?? false,
  };
  const server = createServer((request, response) => {
    const origin = `http://127.0.0.1:${server.address().port}`;
    const json = (status, body) => {
      response.writeHead(status, { "content-type": "application/json" });
      response.end(JSON.stringify(body));
    };
    if (request.url === "/healthz") return json(200, { status: "ok" });
    if (request.url === "/openapi.json") {
      const paths = {
        "/api/v1/auth/register": {},
        "/api/v1/auth/resend-verification": {},
        "/api/v1/auth/verify-email": {},
      };
      if (state.missingRoute) delete paths["/api/v1/auth/register"];
      return json(200, { paths });
    }
    if (request.url === "/api/v1/auth/register" && request.method === "POST") {
      if (state.registration === "closed") return json(404, { detail: { error_code: "registration_unavailable" } });
      return json(422, { detail: [{ type: "value_error" }] });
    }
    const releaseMatch = request.url.match(/^\/gh\/repos\/redsilvernight\/studio-os\/releases\/tags\/(desktop-dev|desktop-prod)$/);
    if (releaseMatch) {
      const tag = releaseMatch[1];
      if (tag === "desktop-prod" && state.stableMissing) return json(404, { message: "Not Found" });
      const suffix = tag === "desktop-dev" ? "dev" : "prod";
      const file = `StudiOS-Setup-${suffix}.exe`;
      return json(200, {
        draft: false,
        html_url: `${origin}/release/${tag}`,
        assets: [
          { name: "latest.json", browser_download_url: `${origin}/assets/${tag}/latest.json` },
          { name: file, size: 1234, digest: `sha256:${"a".repeat(64)}`, browser_download_url: `${origin}/assets/${tag}/${file}` },
        ],
      });
    }
    const manifestMatch = request.url.match(/^\/assets\/(desktop-dev|desktop-prod)\/latest\.json$/);
    if (manifestMatch) {
      const tag = manifestMatch[1];
      const suffix = tag === "desktop-dev" ? "dev" : "prod";
      const file = `StudiOS-Setup-${suffix}.exe`;
      return json(200, {
        schema_version: 1,
        version: tag === "desktop-dev" ? "1.0.1" : "1.0.0",
        channel: tag === "desktop-dev" ? "beta" : "stable",
        api_origin: tag === "desktop-dev" && state.betaOrigin ? state.betaOrigin : origin,
        artifacts: { ["windows-x86_64"]: { file, size_bytes: 1234, sha256: "a".repeat(64) } },
        platforms: { ["windows-x86_64"]: { url: `${origin}/assets/${tag}/${file}`, signature: "signed" } },
      });
    }
    return json(404, { message: "Not Found" });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  servers.push(server);
  const origin = `http://127.0.0.1:${server.address().port}`;
  return { origin, state };
}

function options(origin, extra = []) {
  return parseArgs([
    "--base-url", origin,
    "--expected-api-origin", origin,
    "--github-api-base", `${origin}/gh`,
    ...extra,
  ]);
}

test("passes the complete read-only public gate", async () => {
  const { origin } = await fixture();
  const result = await runGate(options(origin, ["--require-stable"]));
  assert.equal(result.ok, true);
  assert.deepEqual(result.checks.map((check) => check.status), ["pass", "pass", "pass", "pass"]);
});

test("fails when the beta manifest points to another API origin", async () => {
  const { origin, state } = await fixture();
  state.betaOrigin = "https://wrong.example.test";
  const result = await runGate(options(origin));
  assert.equal(result.ok, false);
  assert.match(result.checks.find((check) => check.name === "release.beta").details.error, /api_origin/);
});

test("fails when a required registration route is absent", async () => {
  const { origin } = await fixture({ missingRoute: true });
  const result = await runGate(options(origin));
  assert.equal(result.ok, false);
  assert.match(result.checks.find((check) => check.name === "instance.openapi").details.error, /missing registration routes/);
});

test("distinguishes a closed registration gate", async () => {
  const { origin } = await fixture({ registration: "closed" });
  const result = await runGate(options(origin, ["--registration", "closed"]));
  assert.equal(result.ok, true);
  assert.equal(result.checks.find((check) => check.name === "instance.registration.closed").details.status, 404);
});

test("distinguishes an open registration gate", async () => {
  const { origin } = await fixture({ registration: "open" });
  const result = await runGate(options(origin, ["--registration", "open"]));
  assert.equal(result.ok, true);
  assert.equal(result.checks.find((check) => check.name === "instance.registration.open").details.status, 422);
});

test("fails when the stable release is required but absent", async () => {
  const { origin } = await fixture({ stableMissing: true });
  const result = await runGate(options(origin, ["--require-stable"]));
  assert.equal(result.ok, false);
  assert.match(result.checks.find((check) => check.name === "release.stable").details.error, /status 404/);
});
