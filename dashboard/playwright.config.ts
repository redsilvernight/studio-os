import { defineConfig } from "@playwright/test";

const previewPort = Number(process.env.STUDIO_DASHBOARD_PREVIEW_PORT ?? "4173");

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  use: {
    baseURL: `http://127.0.0.1:${previewPort}`,
  },
  webServer: {
    command: `npx vite preview --port ${previewPort} --strictPort`,
    url: `http://127.0.0.1:${previewPort}`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
