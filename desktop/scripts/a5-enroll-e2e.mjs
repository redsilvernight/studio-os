// A5 — self-registered user enrolls this Desktop without any admin (DEC-0130).
// Real packaged Desktop (WebView2 over CDP) + real daemon sidecar + real OS
// keyring + a throwaway API stack (gate_stack.py) with public registration on
// and a file e-mail backend, so the verification link is read from disk.
//
//   node scripts/build.mjs --api-url http://127.0.0.1:8765 --sidecar
//   STUDIO_GATE_PG_ADMIN_URL=postgresql://… node scripts/a5-enroll-e2e.mjs
//
// Journey: register → verify (link from the .eml) → P11 wizard « Connexion »
// → « Vérification » : « Enregistrer ce poste » → keyring holds a credential
// owned by that user → « Projet » : « En attente d'accès » → admin grants one
// project → the machine sees exactly that project, not the other one. No
// secret in the profile folder. Results: desktop/.build/a5-enroll-results.json.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { randomUUID } from "node:crypto";
import { chromium } from "playwright-core";
import { buildDir, desktopDir, repoRoot, toolEnv } from "./lib.mjs";

const exe = resolve(desktopDir, "src-tauri", "target", "release", "studio-desktop.exe");
const CDP_PORT = Number(process.env.STUDIO_A5_CDP_PORT ?? 9341);
const API = "http://127.0.0.1:8765";
const APP_ORIGIN = "http://tauri.localhost";
const PASSWORD = `a5-${randomUUID()}`;
const EMAIL = `ada-${randomUUID().slice(0, 8)}@example.test`;
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(id, cond, evidence) {
  results.push({ id, status: cond ? "PASS" : "FAIL", evidence });
  console.log(`${cond ? "PASS" : "FAIL"}  ${id}  ${evidence}`);
}

function probe(action, extra = []) {
  const run = spawnSync(
    "uv",
    ["run", "--all-packages", "python", resolve(desktopDir, "e2e", "a5_enroll_probe.py"), action, "--origin", API, ...extra],
    { cwd: repoRoot, env: toolEnv(), encoding: "utf-8" },
  );
  if (run.status !== 0) throw new Error(`a5_enroll_probe ${action}: ${(run.stderr || "").trim().slice(-300)}`);
  return run.stdout.trim();
}

async function startStack(mailDir) {
  const child = spawn("uv", ["run", "--all-packages", "python", resolve(desktopDir, "e2e", "gate_stack.py")], {
    cwd: repoRoot,
    env: toolEnv({
      STUDIO_ENVIRONMENT: "dev",
      STUDIO_PUBLIC_REGISTRATION_ENABLED: "true",
      STUDIO_EMAIL_BACKEND: "file",
      STUDIO_EMAIL_FROM: "studio@example.test",
      STUDIO_EMAIL_FILE_DIR: mailDir,
      STUDIO_ACCOUNT_EMAIL_COOLDOWN_SECONDS: "0",
      STUDIO_PUBLIC_BASE_URL: "http://127.0.0.1:5173",
    }),
    stdio: ["pipe", "pipe", "inherit"],
  });
  const line = await new Promise((res, rej) => {
    createInterface({ input: child.stdout }).on("line", (l) => l.startsWith("{") && res(l));
    child.on("exit", (code) => rej(new Error(`gate stack exited early (${code})`)));
    setTimeout(() => rej(new Error("gate stack timeout")), 180_000);
  });
  return { child, info: JSON.parse(line) };
}

async function api(path, { method = "GET", token, body, key } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (key) headers["Idempotency-Key"] = key;
  const response = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const text = await response.text();
  return { status: response.status, json: text ? JSON.parse(text) : null };
}

async function login(email, password) {
  const answer = await api("/api/v1/auth/token", { method: "POST", body: { email, password } });
  if (answer.status !== 200) throw new Error(`login ${email}: HTTP ${answer.status}`);
  return answer.json.access_token;
}

function verificationSecret(mailDir) {
  for (let i = 0; i < 40; i++) {
    const files = existsSync(mailDir) ? readdirSync(mailDir).filter((f) => f.endsWith(".eml")) : [];
    for (const file of files) {
      const raw = readFileSync(join(mailDir, file), "utf-8").replace(/=\r?\n/g, "");
      if (!raw.includes(EMAIL)) continue;
      const match = /verify-email#token=(?:3D)?([A-Za-z0-9_-]+)/.exec(raw);
      if (match) return match[1];
    }
    spawnSync(process.execPath, ["-e", "setTimeout(()=>{},250)"]);
  }
  throw new Error("no verification e-mail found");
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

async function main() {
  if (!existsSync(exe)) throw new Error(`missing ${exe} - run: node scripts/build.mjs --api-url ${API} --sidecar`);
  probe("check-absent");
  const profileRoot = mkdtempSync(join(tmpdir(), "studio-a5-enroll-"));
  const mailDir = join(profileRoot, "mail");
  mkdirSync(mailDir, { recursive: true });
  const stack = await startStack(mailDir);
  console.log(`stack up: ${stack.info.api} (database ${stack.info.database})`);
  let app = null;
  let browser = null;
  let keyringTouched = false;
  try {
    const admin = await login(stack.info.email, stack.info.password);
    const projects = (await api("/api/v1/projects", { token: admin })).json;
    const gate = projects.find((p) => p.slug === stack.info.project);
    const other = await api("/api/v1/projects", {
      method: "POST",
      token: admin,
      key: randomUUID(),
      body: { slug: "a5-other", name: "Autre projet" },
    });
    check("setup.two_projects", gate && other.status === 201, `gate=${gate?.slug} other=HTTP ${other.status}`);

    // ---- self-registration, link read from the e-mail file
    const registered = await api("/api/v1/auth/register", { method: "POST", key: randomUUID(), body: { email: EMAIL } });
    const secret = verificationSecret(mailDir);
    const verified = await api("/api/v1/auth/verify-email", {
      method: "POST",
      body: { token: secret, password: PASSWORD, display_name: "Ada" },
    });
    check("register.self_registered_and_verified", registered.status === 202 && verified.status === 200, `register ${registered.status}, verify ${verified.status}`);
    const adaId = (await api("/api/v1/auth/me", { token: await login(EMAIL, PASSWORD) })).json.user_id;

    // ---- real Desktop, fresh profile: the P11 wizard opens
    const env = {
      APPDATA: join(profileRoot, "appdata"),
      LOCALAPPDATA: join(profileRoot, "localappdata"),
      WEBVIEW2_USER_DATA_FOLDER: join(profileRoot, "webview2"),
      STUDIO_DESKTOP_CONFIG_DIR: join(profileRoot, "config"),
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${CDP_PORT}`,
    };
    for (const dir of Object.values(env).slice(0, 4)) mkdirSync(dir, { recursive: true });
    app = spawn(exe, [], { env: { ...process.env, ...env }, stdio: "ignore" });
    const attached = await attach();
    browser = attached.browser;
    const page = attached.page;
    await page.waitForSelector('[data-testid="onboarding-step"][data-step="bienvenue"]', { timeout: 30_000 });
    await page.click('[data-action="start"]');
    // The step repaints once its server probe lands, which can wipe a form
    // filled too early: retry until the step shows the signed-in state.
    let loggedIn = false;
    for (let attempt = 0; attempt < 4 && !loggedIn; attempt++) {
      await page.waitForSelector("#login-form", { timeout: 20_000 });
      await sleep(1000);
      await page.fill("#login-email", EMAIL);
      await page.fill("#login-password", PASSWORD);
      await page.click("#login-form button[type=submit]");
      loggedIn = await page
        .waitForSelector('[data-action="next"]:not([disabled])', { timeout: 10_000 })
        .then(() => true)
        .catch(() => false);
    }
    const stepText = loggedIn ? "" : ((await page.textContent('[data-testid="onboarding-step"]').catch(() => "")) ?? "").replace(/\s+/g, " ").slice(0, 400);
    check("wizard.login_self_registered", loggedIn, loggedIn ? `logged in as the self-registered ${EMAIL}` : `step: ${stepText}`);
    if (!loggedIn) throw new Error("connexion step did not complete");
    await page.click('[data-action="next"]');

    // ---- « Vérification » : enroll without any admin
    const enroll = await page
      .waitForSelector('[data-action="enroll"]', { timeout: 30_000 })
      .then(() => true)
      .catch(() => false);
    check("wizard.enroll_offered", enroll, "« Enregistrer ce poste » shown for a machine without credential");
    keyringTouched = true;
    await page.click('[data-action="enroll"]');
    const notice = await page
      .waitForFunction(() => /Poste enregistr/.test(document.querySelector("[data-testid=onboarding-notice]")?.textContent ?? ""), null, { timeout: 30_000 })
      .then(() => true)
      .catch(async () => (await page.textContent("[data-testid=onboarding-error]").catch(() => null)) ?? false);
    check("wizard.enrolled", notice === true, `notice: ${notice === true ? "Poste enregistré." : notice}`);
    const nextEnabled = await page.evaluate(() => document.querySelector('[data-action="next"]')?.disabled === false);
    check("wizard.verification_passes", nextEnabled, "« Continuer » enabled: the daemon sees a present credential");

    let machine = JSON.parse(probe("probe", ["--other", other.json?.id ?? ""]));
    check(
      "keyring.credential_owned_by_user",
      machine.stored && machine.me_status === 200 && machine.owner_user_id === adaId,
      `stored=${machine.stored} /machines/me ${machine.me_status} owner=${machine.owner_user_id === adaId ? "the self-registered user" : machine.owner_user_id}`,
    );
    check("machine.no_project_before_grant", machine.projects_status === 200 && machine.project_slugs.length === 0, `projects: ${JSON.stringify(machine.project_slugs)}`);

    // ---- « Projet » : waits for access, then sees the granted project only
    await page.click('[data-action="next"]');
    const waiting = await page
      .waitForSelector('[data-testid="onboarding-awaiting-access"]', { timeout: 20_000 })
      .then(() => true)
      .catch(() => false);
    check("wizard.awaiting_access", waiting, "« En attente d'accès » in the Projet step");
    const grant = await api(`/api/v1/projects/${gate.id}/members/${adaId}`, { method: "PUT", token: admin });
    await page.click('[data-action="reload-projects"]');
    const listed = await page
      .waitForFunction((slug) => (document.querySelector("[data-testid=project-list]")?.textContent ?? "").length > 0, gate.slug, { timeout: 20_000 })
      .then(() => true)
      .catch(() => false);
    check("wizard.project_after_grant", grant.status === 201 && listed, `grant HTTP ${grant.status}; project list shown: ${listed}`);

    machine = JSON.parse(probe("probe", ["--other", other.json?.id ?? "", "--profile", profileRoot]));
    check(
      "machine.only_owner_projects",
      JSON.stringify(machine.project_slugs) === JSON.stringify([gate.slug]) && [403, 404].includes(machine.other_status),
      `machine sees ${JSON.stringify(machine.project_slugs)}; other project HTTP ${machine.other_status}`,
    );
    check("secrets.none_in_profile_folder", machine.leaks.length === 0, `files holding a secret: ${JSON.stringify(machine.leaks)}`);
  } finally {
    await browser?.close().catch(() => undefined);
    if (app?.pid) spawnSync("taskkill", ["/PID", String(app.pid), "/T", "/F"], { stdio: "ignore" });
    if (keyringTouched) {
      try {
        probe("cleanup");
        check("keyring.cleaned", true, "test credential removed from the OS keyring and verified absent");
      } catch (error) {
        check("keyring.cleaned", false, String(error));
      }
    }
    stack.child.stdin.end();
    await new Promise((r) => {
      stack.child.on("exit", r);
      setTimeout(r, 30_000);
    });
    mkdirSync(buildDir, { recursive: true });
    writeFileSync(join(buildDir, "a5-enroll-results.json"), JSON.stringify(results, null, 2));
  }
  const failed = results.filter((r) => r.status === "FAIL");
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
