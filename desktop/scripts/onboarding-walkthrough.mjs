// P12 §8 — real P11 onboarding walkthrough over CDP against a throwaway API
// stack, through the real native folder-picker dialog.
//
// The native OS dialog (rfd::FileDialog via choose_folder) lives outside the
// WebView's DOM/CDP surface: this script drives everything Playwright can
// reach, then pauses with the dialog open and polls until a real OS
// selection lands (a human, or a computer-use agent, picks TARGET_FOLDER —
// printed below). It then resumes and completes the wizard through to the
// Dashboard, plus a relaunch check that the wizard does not reappear.
//
//   node scripts/onboarding-walkthrough.mjs   # needs a release build first

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { chromium } from "playwright-core";
import { desktopDir, repoRoot, toolEnv } from "./lib.mjs";

const exe = resolve(desktopDir, "src-tauri", "target", "release", "studio-desktop.exe");
const CDP_PORT = Number(process.env.STUDIO_ONBOARDING_CDP_PORT ?? 9339);
const APP_ORIGIN = "http://tauri.localhost";
const results = [];

function record(id, ok, evidence) {
  results.push({ id, status: ok ? "PASS" : "FAIL", evidence });
  console.log(`${ok ? "PASS" : "FAIL"}  ${id}  ${evidence}`);
}
const check = (id, cond, evidence) => record(id, Boolean(cond), evidence);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function killTree(pid) {
  if (pid) spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
}

async function startStack() {
  const child = spawn(
    "uv",
    ["run", "--all-packages", "python", resolve(desktopDir, "e2e", "gate_stack.py")],
    { cwd: repoRoot, env: toolEnv(), stdio: ["pipe", "pipe", "inherit"] },
  );
  const line = await new Promise((res, rej) => {
    const rl = createInterface({ input: child.stdout });
    rl.on("line", (l) => l.startsWith("{") && res(l));
    child.on("exit", (code) => rej(new Error(`gate stack exited early (${code})`)));
    setTimeout(() => rej(new Error("gate stack timeout")), 180_000);
  });
  return { child, info: JSON.parse(line) };
}

async function stopStack(stack) {
  stack.child.stdin.end();
  await new Promise((r) => {
    stack.child.on("exit", r);
    setTimeout(r, 30_000);
  });
}

async function attach(port) {
  for (let i = 0; i < 60; i++) {
    try {
      const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
      const page = browser.contexts()[0]?.pages().find((p) => p.url().startsWith(APP_ORIGIN));
      if (page) return { browser, page };
      await browser.close();
    } catch {
      /* not up yet */
    }
    await sleep(1000);
  }
  throw new Error("could not attach to the Desktop WebView over CDP");
}

function spawnApp(env) {
  return spawn(exe, [], { env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] });
}

// P12-authorized fixture: the onboarding "verification" step's identity
// check (service.py identity_view) reads the real OS keyring directly, not
// the env-first resolve_token() chain used for API auth - so exercising it
// requires a credential actually present there. Scoped to the disposable
// loopback gate-stack origin only; see machine_credential_fixture.py for the
// provenance-marker/refuse-to-overwrite/verify-on-cleanup guarantees.
const KEYRING_MARKER = join(tmpdir(), "studio-p12-machine-credential-marker.json");

function runFixture(action, origin, extraEnv = {}) {
  const result = spawnSync(
    "uv",
    ["run", "--all-packages", "python", resolve(desktopDir, "e2e", "machine_credential_fixture.py"), action, "--origin", origin],
    { cwd: repoRoot, env: { ...toolEnv(), ...extraEnv, STUDIO_P12_KEYRING_MARKER: KEYRING_MARKER }, encoding: "utf-8" },
  );
  if (result.status !== 0) {
    throw new Error(`machine_credential_fixture.py ${action} failed: ${(result.stderr || "").trim()}`);
  }
  return (result.stderr || "").trim();
}

async function main() {
  if (!existsSync(exe)) throw new Error(`missing ${exe} - run: npm run build:with-sidecar`);
  const stack = await startStack();
  const { api, email, password, machine_id: machineId, machine_token: machineToken } = stack.info;
  console.log(`stack up: ${api} (database ${stack.info.database})`);

  let fixtureCreated = false;
  let app = null;
  let browser = null;
  try {
    const createdEvidence = runFixture("create", api, { P12_MACHINE_TOKEN: machineToken });
    fixtureCreated = true;
    check(
      "onboarding.machine_credential_fixture_created",
      true,
      `real OS keyring entry created for studio-os/${api} (${createdEvidence}); token value never logged`,
    );

  const profileRoot = mkdtempSync(join(tmpdir(), "studio-onboarding-profile-"));
  const appData = join(profileRoot, "appdata");
  const localAppData = join(profileRoot, "localappdata");
  const webviewData = join(profileRoot, "webview2");
  const targetFolder = join(profileRoot, "workspace");
  mkdirSync(appData, { recursive: true });
  mkdirSync(localAppData, { recursive: true });
  mkdirSync(webviewData, { recursive: true });
  mkdirSync(join(targetFolder, "vault"), { recursive: true });
  writeFileSync(
    join(targetFolder, "vault", "README.md"),
    "# P12 onboarding walkthrough\n\nDisposable memory seed for the P11 wizard's Knowledge step.\n",
  );
  console.log(`profile: ${profileRoot}`);
  console.log(`TARGET_FOLDER (select this exact folder in the native dialog): ${targetFolder}`);

  const env = {
    APPDATA: appData,
    LOCALAPPDATA: localAppData,
    WEBVIEW2_USER_DATA_FOLDER: webviewData,
    STUDIO_CLIENT_API_BASE_URL: `${api}/api/v1`,
    STUDIO_CLIENT_MACHINE_ID: machineId,
    STUDIO_CLIENT_MACHINE_TOKEN: machineToken,
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${CDP_PORT}`,
  };

  app = spawnApp(env);
  {
    let attached = await attach(CDP_PORT);
    browser = attached.browser;
    let page = attached.page;

    await page.waitForSelector('[data-testid="onboarding-step"][data-step="bienvenue"]', { timeout: 30_000 });
    check("onboarding.first_run_shows_bienvenue", true, "onboarding step on first launch: bienvenue");
    await page.click('[data-action="start"]');

    await page.waitForSelector('[data-testid="onboarding-step"][data-step="connexion"]', { timeout: 15_000 });

    // The onboarding step's own server-origin form is a separate setting from
    // the STUDIO_CLIENT_API_BASE_URL env var passed to the process: it drives
    // the CSP-gated `connect-src` the renderer is actually allowed to fetch,
    // and (per shell_commands.rs) first-time configuration always trips
    // restart_required, so the new origin only becomes reachable after the
    // app is relaunched with the same (persisted) profile.
    await page.waitForSelector('[data-testid="server-origin-form"]', { timeout: 15_000 });
    await page.fill("#server-origin-input", api);
    await page.click('[data-testid="server-origin-form"] button[type=submit]');
    await sleep(1000);
    const originState = await page.evaluate(async () => {
      // @ts-expect-error - Tauri injects this global in the desktop shell
      return window.__TAURI__.core.invoke("get_server_origin");
    });
    check(
      "onboarding.server_origin_configured",
      originState.configured != null,
      `configured=${originState.configured} applied=${originState.applied} restart_required=${originState.restart_required}`,
    );

    if (originState.restart_required) {
      await browser.close();
      browser = null;
      killTree(app.pid);
      await sleep(1500);
      app = spawnApp(env);
      const reattached = await attach(CDP_PORT);
      browser = reattached.browser;
      page = reattached.page;
      // Onboarding progress before completion is not persisted: a relaunch
      // starts the wizard over at "bienvenue", so replay the start click.
      await page.waitForSelector('[data-testid="onboarding-step"][data-step="bienvenue"]', { timeout: 30_000 });
      await page.click('[data-action="start"]');
      await page.waitForSelector('[data-testid="onboarding-step"][data-step="connexion"]', { timeout: 15_000 });
      check("onboarding.server_origin_restart_applied", true, "relaunched with the same profile to apply the new CSP connect-src");
    }

    await page.waitForSelector("#login-form", { timeout: 15_000 });
    await page.fill("#login-email", email);
    await page.fill("#login-password", password);
    await page.click("#login-form button[type=submit]");
    await page.waitForSelector('[data-action="next"]:not([disabled])', { timeout: 20_000 });
    check("onboarding.connexion_login_ok", true, `logged in as ${email}, server probe ok`);
    await page.click('[data-action="next"]');

    await page.waitForSelector('[data-testid="onboarding-step"][data-step="verification"]', { timeout: 15_000 });
    await page.waitForSelector('[data-action="next"]:not([disabled])', { timeout: 20_000 });
    check("onboarding.verification_machine_recognized", true, "verification step: next enabled (machine recognized)");
    await page.click('[data-action="next"]');

    await page.waitForSelector('[data-testid="onboarding-step"][data-step="projet"]', { timeout: 15_000 });
    await page.waitForSelector('[data-testid="project-list"] input[name="project"]', { timeout: 20_000 });
    await page.click('[data-testid="project-list"] input[name="project"]');
    await page.waitForSelector('[data-action="next"]:not([disabled])', { timeout: 5_000 });
    check("onboarding.projet_selected", true, "existing gate project selected from the server-backed list");
    await page.click('[data-action="next"]');

    await page.waitForSelector('[data-testid="onboarding-step"][data-step="dossier"]', { timeout: 15_000 });
    await page.click('[data-action="pick"]');
    check("onboarding.native_picker_opened", true, "rfd::FileDialog opened via choose_folder; waiting for a real OS selection");
    console.log("=".repeat(78));
    console.log("MANUAL/computer-use STEP: the real native OS folder-picker is now open.");
    console.log(`Select this exact P12-controlled folder: ${targetFolder}`);
    console.log("=".repeat(78));

    await page.waitForSelector('[data-action="associate"]:not([disabled])', { timeout: 900_000 });
    const pickedText = await page
      .evaluate(() => document.querySelector(".settings-rows dd")?.textContent ?? "")
      .catch(() => "");
    check("onboarding.native_picker_returned_selection", true, `picked: ${pickedText}`);
    await page.click('[data-action="associate"]');

    await page.waitForSelector('[data-testid="onboarding-step"][data-step="memoire"]', { timeout: 20_000 });
    const memoireForm = await page.$('[data-testid="memory-folder-form"]');
    if (memoireForm) {
      await page.click('[data-testid="memory-folder-form"] button[type=submit]');
      await sleep(1500);
    }
    check("onboarding.memoire_knowledge_enabled", Boolean(memoireForm), "markdown-files knowledge provider activated on the picked folder's vault/");
    await page.click('[data-action="next"]');

    await page.waitForSelector('[data-testid="onboarding-step"][data-step="environnement"]', { timeout: 20_000 });
    check("onboarding.environnement_probed", true, "git/code-graph/harness probe rendered");
    await page.click('[data-action="next"]');

    await page.waitForSelector('[data-testid="onboarding-step"][data-step="assistant"]', { timeout: 15_000 });
    const skipAssistant = await page.$('[data-action="skip"]');
    await page.click(skipAssistant ? '[data-action="skip"]' : '[data-action="next"]');
    check("onboarding.assistant_step_not_applied", true, "no harness preview/apply invoked; real Claude Code/OpenCode configs untouched");

    await page.waitForSelector('[data-testid="onboarding-step"][data-step="final"]', { timeout: 20_000 });
    check("onboarding.final_summary_shown", true, "revalidated summary rendered before finishing");
    await page.click('[data-action="finish"]');

    await page.waitForFunction(() => !document.querySelector('[data-testid="onboarding-step"]'), null, { timeout: 20_000 });
    const dashboardText = await page.evaluate(() => document.body.innerText);
    check(
      "onboarding.completion_reaches_dashboard",
      page.url().startsWith(`${APP_ORIGIN}/`) && !dashboardText.includes("Bienvenue dans Studi'OS"),
      `page ${page.url()}`,
    );

    await browser.close();
    browser = null;
    killTree(app.pid);
    await sleep(1500);

    app = spawnApp(env);
    const reattached = await attach(CDP_PORT);
    browser = reattached.browser;
    page = reattached.page;
    await sleep(2000);
    const relaunchText = await page.evaluate(() => document.body.innerText);
    check(
      "onboarding.relaunch_skips_wizard_shows_dashboard",
      !relaunchText.includes("Bienvenue dans Studi'OS") && !relaunchText.includes("Configuration terminée"),
      `after relaunch with the same profile: ${page.url()}`,
    );
  }
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (app) killTree(app.pid);
    if (fixtureCreated) {
      try {
        const cleanupEvidence = runFixture("cleanup", api);
        check(
          "onboarding.machine_credential_fixture_cleaned_up",
          true,
          `real OS keyring entry removed & verified absent for studio-os/${api} (${cleanupEvidence})`,
        );
      } catch (err) {
        check("onboarding.machine_credential_fixture_cleaned_up", false, String(err));
      }
    }
    await stopStack(stack);
  }

  const failed = results.filter((r) => r.status === "FAIL");
  console.log(`\nonboarding walkthrough: ${results.length - failed.length}/${results.length} passed`);
  if (failed.length) process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
