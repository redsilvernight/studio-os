# Studi'OS Desktop (P2 foundation)

Thin Tauri 2 shell around the shared Dashboard build. Architecture, bridge, capabilities, gate matrix and limits: [`docs/DESKTOP_P2_FOUNDATION.md`](../docs/DESKTOP_P2_FOUNDATION.md).

## Prerequisites (Windows)

Node ≥ 22.18, Rust stable (MSVC), Visual Studio Build Tools with the C++ workload, WebView2, and `uv` with Python for the sidecar spike. Check them with:

```bash
cd desktop
npm ci && (cd ../dashboard && npm ci)
npm run prereqs
```

## Commands

```bash
npm run build                # Dashboard + src-tauri/target/release/studio-desktop.exe
npm run build:with-sidecar   # same, plus the frozen daemon spike
npm run dev                  # Vite dev server + Tauri window
npm run test:rust            # cargo tests (allowlist, navigation, bridge, sidecar)
npm run gate                 # build with sidecar, then real E2E against a throwaway API stack
```

`--api-url <origin>` (build scripts) sets the API origin baked into the build. The server must list `http://tauri.localhost` in `STUDIO_CORS_ORIGINS` for the packaged Desktop to reach it.
