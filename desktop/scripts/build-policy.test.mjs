import assert from "node:assert/strict";
import test from "node:test";

import { allowInsecureOrigin, DEFAULT_API_URL, validateBuildApiUrl } from "./lib.mjs";

test("the product default remains the loopback development server", () => {
  assert.equal(DEFAULT_API_URL, "http://127.0.0.1:8000");
});

test("default build policy accepts HTTPS and loopback HTTP", () => {
  for (const origin of ["https://example.com", "http://127.0.0.1", "http://localhost"]) {
    assert.equal(validateBuildApiUrl(origin), origin);
  }
});

test("default build policy rejects every remote HTTP origin", () => {
  const provisionalIpOrigin = `http://${[100, 124, 49, 80].join(".")}`;
  for (const origin of ["http://remote.example", provisionalIpOrigin]) {
    assert.throws(() => validateBuildApiUrl(origin), /requires STUDIO_DESKTOP_ALLOW_INSECURE_ORIGIN=1/);
  }
});

test("remote HTTP requires the exact explicit build opt-in", () => {
  assert.equal(allowInsecureOrigin({ STUDIO_DESKTOP_ALLOW_INSECURE_ORIGIN: "1" }), true);
  for (const value of [undefined, "", "0", "true", "yes"]) {
    assert.equal(allowInsecureOrigin({ STUDIO_DESKTOP_ALLOW_INSECURE_ORIGIN: value }), false);
  }
  assert.equal(validateBuildApiUrl("http://deploy.example", true), "http://deploy.example");
});

test("the build origin is exact and fails closed", () => {
  for (const invalid of [
    "ftp://example.com",
    "https://user:password@example.com",
    "https://example.com/api",
    "https://example.com?query=1",
    "https://example.com/#fragment",
    "http://tauri.localhost",
    "https://*.example.com",
  ]) {
    assert.throws(() => validateBuildApiUrl(invalid, true));
  }
});

test("the storage origin of pre-signed uploads joins connect-src only when given", async () => {
  const { desktopCsp, overlay } = await import("./make-config.mjs");
  const connect = (csp) => csp.split("; ").find((d) => d.startsWith("connect-src "));
  assert.equal(connect(desktopCsp("https://studio.example")), "connect-src 'self' ipc: http://ipc.localhost https://studio.example");
  assert.equal(
    connect(desktopCsp("https://studio.example", "https://storage.example:8443")),
    "connect-src 'self' ipc: http://ipc.localhost https://studio.example https://storage.example:8443",
  );
  // Same origin twice is listed once.
  assert.equal(connect(desktopCsp("https://studio.example", "https://studio.example")).split(" ").length, 5);
  assert.match(overlay({ apiUrl: "https://a.example", storageUrl: "https://s.example" }).app.security.csp, /https:\/\/s\.example/);
});
