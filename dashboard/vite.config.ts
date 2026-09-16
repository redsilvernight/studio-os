import { defineConfig } from "vite";
import { buildDashboardCsp, CSP_REPORT_ONLY_HEADER } from "./csp-policy";

const API_TARGET = process.env.VITE_STUDIO_API_PROXY ?? "http://localhost:8000";

export default defineConfig({
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
});
