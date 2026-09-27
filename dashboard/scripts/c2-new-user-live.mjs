// C2 — runs `e2e/c2-new-user-live.spec.ts` against a real, throwaway API
// stack (`desktop/e2e/gate_stack.py`: scratch database, random admin, public
// registration on, e-mails written to a temp folder), then tears it down.
//
//   STUDIO_GATE_PG_ADMIN_URL=postgresql://… node scripts/c2-new-user-live.mjs
//
// The dashboard is served by `vite preview` (Playwright webServer) and calls
// `/api` on its own origin; the spec forwards those calls to the stack.

import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const dashboardDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(dashboardDir, "..");
const previewPort = Number(process.env.STUDIO_DASHBOARD_PREVIEW_PORT ?? "4173");
const shell = process.platform === "win32";

function run(command, args, env = {}) {
  const done = spawnSync(command, args, { cwd: dashboardDir, stdio: "inherit", shell, env: { ...process.env, ...env } });
  return done.status ?? 1;
}

async function startStack(mailDir) {
  const child = spawn("uv", ["run", "--all-packages", "python", join(repoRoot, "desktop", "e2e", "gate_stack.py")], {
    cwd: repoRoot,
    env: {
      ...process.env,
      STUDIO_ENVIRONMENT: "dev",
      STUDIO_PUBLIC_REGISTRATION_ENABLED: "true",
      STUDIO_EMAIL_BACKEND: "file",
      STUDIO_EMAIL_FROM: "studio@example.test",
      STUDIO_EMAIL_FILE_DIR: mailDir,
      STUDIO_ACCOUNT_EMAIL_COOLDOWN_SECONDS: "0",
      STUDIO_PUBLIC_BASE_URL: `http://127.0.0.1:${previewPort}`,
    },
    stdio: ["pipe", "pipe", "inherit"],
  });
  const line = await new Promise((res, rej) => {
    createInterface({ input: child.stdout }).on("line", (l) => l.startsWith("{") && res(l));
    child.on("exit", (code) => rej(new Error(`gate stack exited early (${code})`)));
    setTimeout(() => rej(new Error("gate stack timeout")), 180_000);
  });
  return { child, info: JSON.parse(line) };
}

async function main() {
  // Same-origin `/api`: build without VITE_STUDIO_API_URL.
  if (run("npx", ["vite", "build"], { VITE_STUDIO_API_URL: "" }) !== 0) throw new Error("dashboard build failed");
  const mailDir = join(mkdtempSync(join(tmpdir(), "studio-c2-web-")), "mail");
  mkdirSync(mailDir, { recursive: true });
  const stack = await startStack(mailDir);
  console.log(`stack up: ${stack.info.api} (database ${stack.info.database})`);
  let status = 1;
  try {
    const live = {
      api: stack.info.api,
      email: stack.info.email,
      password: stack.info.password,
      project: stack.info.project,
      mailDir,
    };
    status = run("npx", ["playwright", "test", "e2e/c2-new-user-live.spec.ts", "--reporter=list"], {
      STUDIO_C2_LIVE: JSON.stringify(live),
    });
  } finally {
    stack.child.stdin.end();
    await new Promise((r) => {
      stack.child.on("exit", r);
      setTimeout(r, 30_000);
    });
  }
  process.exit(status);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
