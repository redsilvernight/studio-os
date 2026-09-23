// P12-A §11/§12 — real root confirmation (A -> B transition) and Desktop-level
// Git detection, driven through the actual onboarding "dossier" screen (the
// only wired UI surface that calls workspace.confirm_roots / save_config),
// over CDP against a throwaway API stack, with the real native folder picker.
//
// A first real association (root A, no prior workspace) is followed by a
// forced resume at the "dossier" step with the workspace already on file:
// picking a different real folder there exercises the SAME production
// `associateFolder()` branch that fetches `current_roots` and threads a fresh
// `root_confirmation_id` through `workspace.save_config` - a genuine A -> B
// transition, not a fixture replay.
//
//   node scripts/p12-root-transition.mjs
//   node scripts/p12-root-transition.mjs --git-absent   # separate PATH-stripped run for git_absent

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { chromium } from "playwright-core";
import { desktopDir, repoRoot, toolEnv } from "./lib.mjs";

const exe = resolve(desktopDir, "src-tauri", "target", "release", "studio-desktop.exe");
const CDP_PORT = Number(process.env.STUDIO_P12_CDP_PORT ?? 9341);
const APP_ORIGIN = "http://tauri.localhost";
const GIT_ABSENT_RUN = process.argv.includes("--git-absent");
const results = [];

function record(id, ok, evidence) {
  results.push({ id, status: ok ? "PASS" : "FAIL", evidence });
  console.log(`${ok ? "PASS" : "FAIL"}  ${id}  ${evidence}`);
}
const check = (id, cond, evidence) => record(id, Boolean(cond), evidence);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const killTree = (pid) => pid && spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });

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

async function attach() {
  for (let i = 0; i < 60; i++) {
    try {
      const browser = await chromium.connectOverCDP(`http://127.0.0.1:${CDP_PORT}`);
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

const KEYRING_MARKER = join(tmpdir(), "studio-p12-roottrans-credential-marker.json");
function runFixture(action, origin, extraEnv = {}) {
  const result = spawnSync(
    "uv",
    ["run", "--all-packages", "python", resolve(desktopDir, "e2e", "machine_credential_fixture.py"), action, "--origin", origin],
    { cwd: repoRoot, env: { ...toolEnv(), ...extraEnv, STUDIO_P12_KEYRING_MARKER: KEYRING_MARKER }, encoding: "utf-8" },
  );
  if (result.status !== 0) throw new Error(`machine_credential_fixture.py ${action} failed: ${(result.stderr || "").trim()}`);
  return (result.stderr || "").trim();
}

const invoke = (page, name, args) =>
  page.evaluate(
    async ({ name, args }) => {
      try {
        return { ok: true, value: await window.__TAURI__.core.invoke(name, args) };
      } catch (e) {
        return { ok: false, error: String(e) };
      }
    },
    { name, args },
  );

let counter = 0;
const bridgeRequest = (command, payload) => {
  counter += 1;
  return {
    kind: "request",
    protocol: "studio.local/v1",
    message_id: `p12rt-req-${counter}`,
    correlation_id: `p12rt-cor-${counter}`,
    sent_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    command,
    payload,
  };
};
const bridge = async (page, command, payload) => {
  const answer = await invoke(page, "bridge_request", { request: bridgeRequest(command, payload) });
  if (!answer.ok) return { ok: false, error: { code: "transport_error", message: answer.error } };
  const envelope = answer.value;
  if (envelope.error) return { ok: false, error: envelope.error };
  return { ok: true, value: envelope.payload };
};

/** PATH with every directory that resolves `git`/`git.exe` removed - scoped to
 * the child process tree this env is passed to; the real machine's git install
 * is untouched. */
function pathWithoutGit() {
  const entries = (process.env.PATH ?? process.env.Path ?? "").split(delimiter).filter(Boolean);
  const kept = entries.filter((dir) => !existsSync(join(dir, "git.exe")) && !existsSync(join(dir, "git")));
  return kept.join(delimiter);
}

async function runWizardToDossier(page, api, email, password) {
  await page.waitForSelector('[data-testid="onboarding-step"][data-step="bienvenue"]', { timeout: 30_000 });
  check("root_transition.first_run_shows_bienvenue", true, "onboarding step on first launch: bienvenue");
  await page.click('[data-action="start"]');

  await page.waitForSelector('[data-testid="onboarding-step"][data-step="connexion"]', { timeout: 15_000 });
  await page.waitForSelector('[data-testid="server-origin-form"]', { timeout: 15_000 });
  await page.fill("#server-origin-input", api);
  await page.click('[data-testid="server-origin-form"] button[type=submit]');
  await sleep(1000);
  const originState = await page.evaluate(async () => window.__TAURI__.core.invoke("get_server_origin"));
  console.error(`DIAG originState: ${JSON.stringify(originState)}`);
  try {
    const diag = await page.evaluate(async () => window.__TAURI__.core.invoke("get_diagnostics"));
    console.error(`DIAG get_diagnostics: ${JSON.stringify(diag)}`);
  } catch (e) {
    console.error(`DIAG get_diagnostics failed: ${e}`);
  }
  let currentPage = page;
  if (originState.restart_required) {
    return { restart: true };
  }
  await currentPage.waitForSelector("#login-form", { timeout: 15_000 });
  await currentPage.fill("#login-email", email);
  await currentPage.fill("#login-password", password);
  await currentPage.click("#login-form button[type=submit]");
  await currentPage.waitForSelector('[data-action="next"]:not([disabled])', { timeout: 20_000 });
  check("root_transition.connexion_login_ok", true, `logged in as ${email}`);
  await currentPage.click('[data-action="next"]');

  await currentPage.waitForSelector('[data-testid="onboarding-step"][data-step="verification"]', { timeout: 15_000 });
  await currentPage.waitForSelector('[data-action="next"]:not([disabled])', { timeout: 20_000 });
  check("root_transition.verification_machine_recognized", true, "verification step: next enabled");
  await currentPage.click('[data-action="next"]');

  await currentPage.waitForSelector('[data-testid="onboarding-step"][data-step="projet"]', { timeout: 15_000 });
  await currentPage.waitForSelector('[data-testid="project-list"] input[name="project"]', { timeout: 20_000 });
  await currentPage.click('[data-testid="project-list"] input[name="project"]');
  await currentPage.waitForSelector('[data-action="next"]:not([disabled])', { timeout: 5_000 });
  check("root_transition.projet_selected", true, "existing gate project selected");
  await currentPage.click('[data-action="next"]');

  await currentPage.waitForSelector('[data-testid="onboarding-step"][data-step="dossier"]', { timeout: 15_000 });
  return { restart: false, page: currentPage };
}

async function pickAndAssociate(page, targetFolder, label) {
  await page.click('[data-action="pick"]');
  console.log("=".repeat(78));
  console.log(`MANUAL/computer-use STEP (${label}): the real native OS folder-picker is now open.`);
  console.log(`Select this exact P12-controlled folder: ${targetFolder}`);
  console.log("=".repeat(78));
  await page.waitForSelector('[data-action="associate"]:not([disabled])', { timeout: 900_000 });
  const pickedText = await page.evaluate(() => document.querySelector(".settings-rows dd")?.textContent ?? "");
  check(`root_transition.native_picker_returned_selection.${label}`, true, `picked: ${pickedText}`);
  await page.click('[data-action="associate"]');
  await sleep(1500);
}

async function main() {
  if (!existsSync(exe)) throw new Error(`missing ${exe} - run: npm run build:with-sidecar`);
  const base = resolve(tmpdir(), "p12-root-transition");
  const rootA = join(base, "rootA");
  const rootB = join(base, "rootB");
  const rootC = join(base, "rootC");
  for (const p of [rootA, rootB, rootC]) if (!existsSync(p)) throw new Error(`missing fixture folder ${p} - create it before running this script`);

  const stack = await startStack();
  const { api, email, password, machine_id: machineId, machine_token: machineToken } = stack.info;
  console.log(`stack up: ${api} (database ${stack.info.database})`);

  let fixtureCreated = false;
  let app = null;
  let browser = null;
  try {
    const createdEvidence = runFixture("create", api, { P12_MACHINE_TOKEN: machineToken });
    fixtureCreated = true;
    check("root_transition.machine_credential_fixture_created", true, `real OS keyring entry created (${createdEvidence})`);

    const profileRoot = mkdtempSync(join(tmpdir(), "studio-roottrans-profile-"));
    const appData = join(profileRoot, "appdata");
    const localAppData = join(profileRoot, "localappdata");
    const webviewData = join(profileRoot, "webview2");
    const configDir = join(profileRoot, "config");
    for (const d of [appData, localAppData, webviewData, configDir]) spawnSync("cmd", ["/c", "mkdir", d]);

    const env = {
      APPDATA: appData,
      LOCALAPPDATA: localAppData,
      WEBVIEW2_USER_DATA_FOLDER: webviewData,
      STUDIO_DESKTOP_CONFIG_DIR: configDir,
      STUDIO_CLIENT_API_BASE_URL: `${api}/api/v1`,
      STUDIO_CLIENT_MACHINE_ID: machineId,
      STUDIO_CLIENT_MACHINE_TOKEN: machineToken,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${CDP_PORT}`,
      ...(GIT_ABSENT_RUN ? { PATH: pathWithoutGit(), Path: pathWithoutGit() } : {}),
    };

    app = spawnApp(env);
    let attached = await attach();
    browser = attached.browser;
    let page = attached.page;

    let wiz;
    try {
      wiz = await runWizardToDossier(page, api, email, password);
    } catch (err) {
      const diagUrl = page.url();
      const diagText = await page.evaluate(() => document.body.innerText).catch(() => "<unreadable>");
      console.error(`DIAG at failure: url=${diagUrl}\n--- body text ---\n${diagText}\n--- end body text ---`);
      throw err;
    }
    if (wiz.restart) {
      await browser.close();
      browser = null;
      killTree(app.pid);
      await sleep(1500);
      app = spawnApp(env);
      attached = await attach();
      browser = attached.browser;
      page = attached.page;
      await page.waitForSelector('[data-testid="onboarding-step"][data-step="bienvenue"]', { timeout: 30_000 });
      await page.click('[data-action="start"]');
      await page.waitForSelector('[data-testid="onboarding-step"][data-step="connexion"]', { timeout: 15_000 });
      check("root_transition.server_origin_restart_applied", true, "relaunched with the same profile to apply the new CSP connect-src");
      await page.waitForSelector("#login-form", { timeout: 15_000 });
      await page.fill("#login-email", email);
      await page.fill("#login-password", password);
      await page.click("#login-form button[type=submit]");
      await page.waitForSelector('[data-action="next"]:not([disabled])', { timeout: 20_000 });
      await page.click('[data-action="next"]');
      await page.waitForSelector('[data-testid="onboarding-step"][data-step="verification"]', { timeout: 15_000 });
      await page.waitForSelector('[data-action="next"]:not([disabled])', { timeout: 20_000 });
      await page.click('[data-action="next"]');
      await page.waitForSelector('[data-testid="onboarding-step"][data-step="projet"]', { timeout: 15_000 });
      await page.waitForSelector('[data-testid="project-list"] input[name="project"]', { timeout: 20_000 });
      await page.click('[data-testid="project-list"] input[name="project"]');
      await page.waitForSelector('[data-action="next"]:not([disabled])', { timeout: 5_000 });
      await page.click('[data-action="next"]');
      await page.waitForSelector('[data-testid="onboarding-step"][data-step="dossier"]', { timeout: 15_000 });
      wiz = { restart: false, page };
    }
    page = wiz.page ?? page;

    // ---- root A: initial real association (no prior workspace) ----------
    await pickAndAssociate(page, rootA, "rootA");

    const stateAfterA = await page.evaluate(() => JSON.parse(localStorage.getItem("studio-os.onboarding.v1") ?? "{}"));
    check("root_transition.root_a_workspace_id_assigned", Boolean(stateAfterA.workspaceId), `workspaceId=${stateAfterA.workspaceId}`);
    const workspaceId = stateAfterA.workspaceId;

    const cfgAfterA = await bridge(page, "workspace.get_config", { workspace_id: workspaceId });
    const rootsAfterA = cfgAfterA.ok ? cfgAfterA.value.roots?.workspace_root : null;
    check("root_transition.root_a_persisted", cfgAfterA.ok && rootsAfterA === rootA, `stored workspace_root=${rootsAfterA}`);

    if (GIT_ABSENT_RUN) {
      const gitA = await bridge(page, "workspace.git_status", { workspace_id: workspaceId });
      check("git_detection.absent_when_git_not_on_path", gitA.ok && gitA.value.state === "git_absent", `git_status=${JSON.stringify(gitA.value ?? gitA.error)}`);
      return; // this run only proves git_absent; the transition below needs a real git binary
    }

    const gitA = await bridge(page, "workspace.git_status", { workspace_id: workspaceId });
    check("git_detection.root_a_valid_repo", gitA.ok && gitA.value.state === "valid" && gitA.value.branch === "main", `git_status=${JSON.stringify(gitA.value ?? gitA.error)}`);

    // ---- forced resume at "dossier" with the workspace already on file ---
    // Same production router (main.ts: loadOnboardingState().status !== "completed")
    // used to resume an interrupted first run; here it resumes at "dossier"
    // with `workspaceId` from the real root-A association still in state, so
    // the next pick exercises associateFolder()'s existingId (transition)
    // branch instead of the initial-create branch.
    await page.evaluate((wid) => {
      const raw = JSON.parse(localStorage.getItem("studio-os.onboarding.v1"));
      raw.current = "dossier";
      raw.status = "in_progress";
      raw.workspaceId = wid;
      localStorage.setItem("studio-os.onboarding.v1", JSON.stringify(raw));
    }, workspaceId);
    await page.reload();
    await page.waitForSelector('[data-testid="onboarding-step"][data-step="dossier"]', { timeout: 20_000 });
    check("root_transition.resumed_at_dossier_with_existing_workspace", true, "router resumed onboarding at dossier with the real workspaceId already in state");

    // ---- root A -> root B: the real transition (main gate) ---------------
    await pickAndAssociate(page, rootB, "rootB");

    const cfgAfterB = await bridge(page, "workspace.get_config", { workspace_id: workspaceId });
    const rootsAfterB = cfgAfterB.ok ? cfgAfterB.value.roots?.workspace_root : null;
    check(
      "root_transition.MAIN_GATE_root_a_to_root_b_transition",
      cfgAfterB.ok && rootsAfterB === rootB && rootsAfterB !== rootA,
      `workspace_root moved from ${rootA} to ${rootsAfterB}`,
    );

    const gitB = await bridge(page, "workspace.git_status", { workspace_id: workspaceId });
    check("git_detection.root_b_valid_repo_different_branch", gitB.ok && gitB.value.state === "valid" && gitB.value.branch === "feature-b", `git_status=${JSON.stringify(gitB.value ?? gitB.error)}`);

    // ---- mismatch: a stale current_roots snapshot on a real transition must be refused ----
    // Same LocalWorkspaceConfig shape as the product's own associateFolder() (view.ts),
    // so a refusal here proves the root-mismatch guard, not a schema-validation reject.
    const stateForStale = await page.evaluate(() => JSON.parse(localStorage.getItem("studio-os.onboarding.v1") ?? "{}"));
    const identityForStale = await bridge(page, "identity.get_view", {});
    check("root_transition.identity_profile_readable", identityForStale.ok && Boolean(identityForStale.value?.profile), `profile=${JSON.stringify(identityForStale.value?.profile)}`);
    const staleConfirm = await bridge(page, "workspace.confirm_roots", { roots: { workspace_root: rootC, repo_roots: [] } });
    check("root_transition.stale_confirm_issued", staleConfirm.ok, `root_confirmation_id=${staleConfirm.value?.root_confirmation_id}`);
    const staleNow = new Date().toISOString();
    const staleSave = await bridge(page, "workspace.save_config", {
      config: {
        schema_version: 1,
        workspace_id: workspaceId,
        profile: identityForStale.value?.profile,
        project_id: stateForStale.projectId,
        ...(stateForStale.projectSlug ? { project_slug: stateForStale.projectSlug } : {}),
        roots: { workspace_root: rootC, repo_roots: [] },
        created_at: staleNow,
        updated_at: staleNow,
      },
      current_roots: { workspace_root: rootA, repo_roots: [] }, // stale: store now has rootB, not rootA
      root_confirmation_id: staleConfirm.value?.root_confirmation_id,
    });
    check(
      "root_transition.stale_current_roots_refused",
      !staleSave.ok,
      `save with stale current_roots -> ${staleSave.ok ? "accepted (DEFECT)" : JSON.stringify(staleSave.error)}`,
    );
    const cfgStillB = await bridge(page, "workspace.get_config", { workspace_id: workspaceId });
    check(
      "root_transition.refused_transition_did_not_mutate_store",
      cfgStillB.ok && cfgStillB.value.roots?.workspace_root === rootB,
      `workspace_root after refused attempt=${cfgStillB.value?.roots?.workspace_root}`,
    );

    // ---- root B -> root C: a second real transition, onto a non-git folder ----
    await page.evaluate((wid) => {
      const raw = JSON.parse(localStorage.getItem("studio-os.onboarding.v1"));
      raw.current = "dossier";
      raw.status = "in_progress";
      raw.workspaceId = wid;
      localStorage.setItem("studio-os.onboarding.v1", JSON.stringify(raw));
    }, workspaceId);
    await page.reload();
    await page.waitForSelector('[data-testid="onboarding-step"][data-step="dossier"]', { timeout: 20_000 });
    await pickAndAssociate(page, rootC, "rootC");

    const cfgAfterC = await bridge(page, "workspace.get_config", { workspace_id: workspaceId });
    check("root_transition.root_b_to_root_c_transition", cfgAfterC.ok && cfgAfterC.value.roots?.workspace_root === rootC, `workspace_root=${cfgAfterC.value?.roots?.workspace_root}`);
    const gitC = await bridge(page, "workspace.git_status", { workspace_id: workspaceId });
    check("git_detection.root_c_not_a_repo", gitC.ok && gitC.value.state === "not_a_repo", `git_status=${JSON.stringify(gitC.value ?? gitC.error)}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (app) killTree(app.pid);
    if (fixtureCreated) {
      try {
        const cleanupEvidence = runFixture("cleanup", api);
        check("root_transition.machine_credential_fixture_cleaned_up", true, `real OS keyring entry removed & verified absent (${cleanupEvidence})`);
      } catch (err) {
        check("root_transition.machine_credential_fixture_cleaned_up", false, String(err));
      }
    }
    await stopStack(stack);
  }

  const failed = results.filter((r) => r.status === "FAIL");
  console.log(`\np12-root-transition${GIT_ABSENT_RUN ? " (git-absent)" : ""}: ${results.length - failed.length}/${results.length} passed`);
  if (failed.length) process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
