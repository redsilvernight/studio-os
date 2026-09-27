import { readFileSync } from "node:fs";
import { defineConfig, loadEnv } from "vite";
import { buildDashboardCsp, CSP_REPORT_ONLY_HEADER } from "./csp-policy";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
  version: string;
};

// Vite never puts `.env`/`.env.local` into `process.env` while evaluating the
// config, so `loadEnv` is required for `VITE_STUDIO_API_PROXY` to actually
// work (otherwise the dev proxy silently falls back to localhost:8000).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const API_TARGET =
    env.VITE_STUDIO_API_PROXY || process.env.VITE_STUDIO_API_PROXY || "http://localhost:8000";

  return {
    // C1: the version this bundle declares to the API (`X-Studio-Client-Version`).
    define: { __STUDIO_CLIENT_VERSION__: JSON.stringify(pkg.version) },
    server: {
      port: 5173,
      proxy: {
        "/api": { target: API_TARGET, changeOrigin: true },
        "/openapi.json": { target: API_TARGET, changeOrigin: true },
        "/healthz": { target: API_TARGET, changeOrigin: true },
      },
    },
    // E2E only (DEC-0061): serve the Report-Only policy on the preview server
    // so Playwright detects violations. Never an enforcement header here.
    preview: {
      port: 4173,
      // IPv4 loopback explicitly: CI and Playwright probe 127.0.0.1, while
      // Vite would otherwise bind ::1 on some hosts (DEC-0061 e2e).
      host: "127.0.0.1",
      headers: { [CSP_REPORT_ONLY_HEADER]: buildDashboardCsp() },
    },
    test: {
      include: ["src/**/*.test.ts"],
      environment: "node",
    },
  };
});
