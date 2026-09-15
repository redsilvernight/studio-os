import { defineConfig } from "vite";

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
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
