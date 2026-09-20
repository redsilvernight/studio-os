// Derives the build-specific Tauri config overlay (never hand-edited).
//
//   node scripts/make-config.mjs [--api-url <origin>] [--sidecar]   # write .build/tauri.overlay.json
//   node scripts/make-config.mjs --check                            # base config CSP is in sync
//
// The Content-Security-Policy is built from the Dashboard's own policy module
// (dashboard/csp-policy.ts) so there is one definition; the desktop build only
// adds what the shell needs: the IPC origin and — because a Tauri CSP is static
// per build — the API origin this build talks to.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { arg, buildDir, dashboardDir, DEFAULT_API_URL, flag, overlayPath, tauriDir } from "./lib.mjs";

const { buildDashboardCsp } = await import(pathToFileURL(join(dashboardDir, "csp-policy.ts")).href);

export function apiOrigin(apiUrl) {
  const u = new URL(apiUrl);
  if (!["http:", "https:"].includes(u.protocol)) throw new Error(`API url must be http(s): ${apiUrl}`);
  return u.origin;
}

/** Desktop CSP: Dashboard policy + IPC + optional API origin; never framed. */
export function desktopCsp(apiUrl) {
  const extra = ["ipc:", "http://ipc.localhost", ...(apiUrl ? [apiOrigin(apiUrl)] : [])];
  return buildDashboardCsp({ connectExtra: extra }).replace("frame-ancestors 'self'", "frame-ancestors 'none'");
}

export function overlay({ apiUrl, sidecar }) {
  return {
    app: { security: { csp: desktopCsp(apiUrl) } },
    ...(sidecar ? { bundle: { externalBin: ["binaries/studio-daemon-spike"] } } : {}),
  };
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (flag("--check")) {
    const base = JSON.parse(readFileSync(join(tauriDir, "tauri.conf.json"), "utf8"));
    if (base.app.security.csp !== desktopCsp(undefined)) {
      console.error("tauri.conf.json CSP drifted from dashboard/csp-policy.ts. Expected:\n" + desktopCsp(undefined));
      process.exit(1);
    }
    console.log("tauri.conf.json CSP in sync with dashboard/csp-policy.ts");
  } else {
    const out = overlay({ apiUrl: arg("--api-url", process.env.STUDIO_DESKTOP_API_URL ?? DEFAULT_API_URL), sidecar: flag("--sidecar") });
    mkdirSync(buildDir, { recursive: true });
    writeFileSync(overlayPath, JSON.stringify(out, null, 2) + "\n");
    console.log(`wrote ${overlayPath}`);
  }
}
