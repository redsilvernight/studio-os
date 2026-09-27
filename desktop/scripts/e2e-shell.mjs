// P3 Desktop shell E2E: drives the REAL packaged Desktop (WebView2) over CDP.
// No Postgres/sidecar needed: a tiny loopback HTTP server plays "studio server".
//
//   node scripts/build.mjs --api-url http://127.0.0.1:59999   # dead default server
//   node scripts/e2e-shell.mjs
//
// Covers: runtime server_origin (validation, CSP enforcement before relaunch,
// explicit relaunch, effect after), connection state, login error UX, native
// APIs exposed only to the Desktop page. Results: desktop/.build/e2e-shell-results.json.

import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";
import { buildDir, desktopDir } from "./lib.mjs";

const exe = resolve(desktopDir, "src-tauri", "target", "release", "studio-desktop.exe");
const CDP_PORT = Number(process.env.STUDIO_E2E_CDP_PORT ?? 9334);
const LIVE_PORT = 59998; // the "studio server" we switch to
const DEAD_ORIGIN = "http://127.0.0.1:59999"; // build-time default, nothing listens
const LIVE_ORIGIN = `http://127.0.0.1:${LIVE_PORT}`;
const APP_ORIGIN = "http://tauri.localhost";
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(id, cond, evidence) {
  results.push({ id, status: cond ? "PASS" : "FAIL", evidence });
  console.log(`${cond ? "PASS" : "FAIL"}  ${id}  ${evidence}`);
}

function killApp() {
  spawnSync("taskkill", ["/IM", "studio-desktop.exe", "/T", "/F"], { stdio: "ignore" });
}

// A5: what the "studio server" saw and answers for the onboarding journey.
const SESSION_TOKEN = "e2e-a5-session-token";
const a5 = { registers: [], projects: [], urls: [] };

function startLiveServer() {
  const server = createServer((req, res) => {
    res.setHeader("Access-Control-Allow-Origin", APP_ORIGIN);
    res.setHeader("Access-Control-Allow-Headers", "authorization,content-type,idempotency-key");
    res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
    if (req.method === "OPTIONS") return res.writeHead(204).end();
    res.setHeader("Content-Type", "application/json");
    a5.urls.push(`${req.method} ${req.url}`);
    if (req.url === "/healthz") return res.writeHead(200).end('{"status":"ok"}');
    if (req.url?.startsWith("/api/v1/auth/token")) return res.writeHead(200).end(JSON.stringify({ access_token: SESSION_TOKEN, token_type: "bearer", expires_in: 900 }));
    if (req.url === "/api/v1/auth/register" && req.method === "POST") {
      a5.registers.push({ key: req.headers["idempotency-key"] ?? null, auth: req.headers.authorization ?? null });
      return res.writeHead(202).end('{"status":"accepted"}');
    }
    if (req.url === "/api/v1/auth/me") {
      return res.writeHead(200).end(JSON.stringify({ user_id: "aaaaaaaa-0000-4111-8111-00000000a5a5", display_name: "Ada", email: "ada@example.test", role: "readonly", machine_id: null }));
    }
    if (req.url === "/api/v1/projects") return res.writeHead(200).end(JSON.stringify(a5.projects));
    if (req.url === "/api/v1/review-queue") return res.writeHead(200).end('{"items":[]}');
    return res.writeHead(200).end("[]");
  });
  return new Promise((r) => server.listen(LIVE_PORT, "127.0.0.1", () => r(server)));
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

function launch(configDir) {
  return spawn(exe, [], {
    env: {
      ...process.env,
      STUDIO_DESKTOP_CONFIG_DIR: configDir,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${CDP_PORT}`,
    },
    stdio: "ignore",
  });
}

async function main() {
  if (!existsSync(exe)) throw new Error(`missing ${exe} - run: node scripts/build.mjs --api-url ${DEAD_ORIGIN}`);
  killApp();
  const configDir = mkdtempSync(join(tmpdir(), "studio-desktop-e2e-"));
  const live = await startLiveServer();
  let browser;
  try {
    launch(configDir);
    let attached = await attach();
    browser = attached.browser;
    let page = attached.page;
    const messages = [];
    page.on("console", (m) => messages.push(m.text()));

    // This gate exercises the post-onboarding shell. Seed only the local
    // completion marker in its throwaway WebView profile so P11's first-run
    // redirect cannot replace the login surface under test.
    await page.evaluate(() => {
      localStorage.setItem(
        "studio-os.onboarding.v1",
        JSON.stringify({ schema: 1, status: "completed", current: "termine" }),
      );
      location.hash = "#/";
      location.reload();
    });

    // ---- 1. default (dead) server: login screen shows it, unreachable is understandable
    await page.waitForSelector("#login-form", { timeout: 30_000 });
    const shown = await page.textContent("[data-testid=login-server-effective]");
    check(
      "login.shows_server_in_use",
      shown?.startsWith("http://127.0.0.1:") && shown !== LIVE_ORIGIN,
      `login shows the packaged loopback default: ${shown}`,
    );
    await page.fill("#login-email", "a@example.test");
    await page.fill("#login-password", "whatever");
    await page.click("#login-form button[type=submit]");
    await page.waitForSelector("#login-error:not([hidden])", { timeout: 15_000 });
    const err = await page.textContent("#login-error");
    check("network.unreachable_message_at_login", /injoignable/i.test(err ?? ""), `login error: ${err}`);

    // ---- 2. native commands are typed, validated and cannot be tricked
    const s0 = await invoke(page, "get_server_origin", {});
    // `applied` is the user-saved origin this process allowed; null = the build default (DEAD_ORIGIN) is in use.
    check(
      "origin.initial_state",
      s0.ok && s0.value.applied === null && s0.value.configured === null && s0.value.restart_required === false,
      JSON.stringify(s0),
    );
    for (const bad of ["http://evil.example.com", "https://user:pw@studio.example.com", "ftp://x.example.com", "http://tauri.localhost", "not a url", ""]) {
      const r = await invoke(page, "set_server_origin", { origin: bad });
      const refused = r.ok ? r.value?.ok === false : true;
      check(`origin.refuses[${bad || "empty"}]`, refused, JSON.stringify(r).slice(0, 160));
    }
    const s1 = await invoke(page, "get_server_origin", {});
    check("origin.invalid_did_not_change_anything", s1.ok && s1.value.configured === null, JSON.stringify(s1));

    // ---- 3. valid change: stored, NOT applied until explicit relaunch (CSP still blocks)
    const saved = await invoke(page, "set_server_origin", { origin: LIVE_ORIGIN });
    check(
      "origin.valid_saved_restart_required",
      saved.ok && saved.value?.restart_required === true && saved.value.applied === null && saved.value.configured === LIVE_ORIGIN,
      JSON.stringify(saved),
    );
    const blocked = await page.evaluate(async (u) => {
      try {
        await fetch(`${u}/healthz`);
        return "allowed";
      } catch {
        return "blocked";
      }
    }, LIVE_ORIGIN);
    check("csp.new_origin_blocked_before_relaunch", blocked === "blocked", `fetch ${LIVE_ORIGIN} before relaunch -> ${blocked}`);
    const wild = await page.evaluate(async () => {
      try {
        await fetch("http://127.0.0.1:59997/healthz");
        return "allowed";
      } catch {
        return "blocked";
      }
    });
    check("csp.arbitrary_origin_blocked", wild === "blocked", `fetch other origin -> ${wild}`);

    // ---- 4. explicit relaunch, new origin applied
    // The process exits while answering: a closed page is the expected outcome.
    const restarted = await invoke(page, "restart_desktop", {}).catch((e) => ({ ok: true, value: `page closed (${String(e).slice(0, 40)})` }));
    check("origin.restart_command_accepted", restarted.ok, JSON.stringify(restarted));
    await browser.close().catch(() => undefined);
    await sleep(3000);
    attached = await attach();
    browser = attached.browser;
    page = attached.page;
    messages.length = 0;
    page.on("console", (m) => messages.push(m.text()));
    await page.waitForSelector("#login-form", { timeout: 30_000 });
    const s2 = await invoke(page, "get_server_origin", {});
    check(
      "origin.applied_after_relaunch",
      s2.ok && s2.value.applied === LIVE_ORIGIN && s2.value.restart_required === false,
      JSON.stringify(s2),
    );
    const reach = await page.evaluate(async (u) => {
      try {
        return (await fetch(`${u}/healthz`)).status;
      } catch (e) {
        return String(e);
      }
    }, LIVE_ORIGIN);
    check("csp.new_origin_allowed_after_relaunch", reach === 200, `fetch ${LIVE_ORIGIN}/healthz -> ${reach}`);

    // ---- 4b. A5: account creation from the Desktop login, on the applied origin
    await page.click("a[data-account-action=register]");
    await page.waitForSelector('[data-testid=account-screen][data-screen="register"]', { timeout: 10_000 });
    await page.fill("input[name=email]", "ada@example.test");
    await page.click("[data-testid=account-screen] form button[type=submit]");
    const sent = await page
      .waitForSelector('[data-testid=account-screen][data-screen="sent"]', { timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    check(
      "a5.register_from_desktop",
      sent && a5.registers.length === 1 && Boolean(a5.registers[0].key) && a5.registers[0].auth === null,
      `sent screen: ${sent}; server saw ${JSON.stringify(a5.registers)}`,
    );
    await page.click("[data-testid=account-screen] a[data-action=login]");
    const backToLogin = await page.waitForSelector("#login-form", { timeout: 10_000 }).then(() => true).catch(() => false);
    check("a5.back_to_login", backToLogin, "« Retour à la connexion » shows the login form again");

    // ---- 5. server reachable: the shell reflects the real supervisor state (sidecar shipped or not)
    const sidecarState = (await invoke(page, "desktop_info", {})).value?.sidecar?.state;
    const sidecarShipped = sidecarState !== "unavailable";
    await page.fill("#login-email", "a@example.test");
    await page.fill("#login-password", "whatever");
    await page.click("#login-form button[type=submit]");
    await page.waitForSelector("#shell-status", { timeout: 20_000 });
    if (!sidecarShipped) await page.waitForFunction(() => /Assistant local indisponible/.test(document.querySelector("#shell-status")?.textContent ?? ""), null, { timeout: 20_000 }).catch(() => undefined);
    const pill = await page.textContent("#shell-status");
    check("status.daemon_unavailable_pill", /Assistant local indisponible/.test(pill ?? "") === !sidecarShipped, `sidecar ${sidecarState}; pill: ${pill?.trim()}`);

    // ---- 5b. A5: active account without project waits, then reaches the dashboard
    await page.evaluate(() => {
      location.hash = "#/";
    });
    const waiting = await page.waitForSelector("[data-testid=awaiting-access]", { timeout: 15_000 }).then(() => true).catch(() => false);
    check("a5.awaiting_access", waiting, "Accueil shows « En attente d'accès » for a readonly account without project");
    a5.projects = [{ id: "11111111-2222-4333-8444-5555555555a5", slug: "phare", name: "Jeu Phare", description: null, archived: false, created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-10T10:00:00Z", version: 1 }];
    await page.click("[data-testid=awaiting-access-recheck]").catch(() => undefined);
    const granted = await page
      .waitForFunction(() => document.querySelector("[data-testid=awaiting-access]") === null && document.querySelector("#view") !== null, null, { timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    const viewText = (await page.textContent("#view").catch(() => ""))?.replace(/\s+/g, " ").slice(0, 160);
    check("a5.access_granted_dashboard", granted, `after recheck: view « ${viewText} »; last requests ${a5.urls.slice(-8).join(", ")}`);
    const stored = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
    const leaked = stored.includes(SESSION_TOKEN) || messages.some((m) => m.includes(SESSION_TOKEN));
    check("a5.no_token_in_storage_or_console", !leaked, "session token absent from localStorage, sessionStorage and console");

    // ---- 6. Settings > Application, Desktop mode
    await page.evaluate(() => {
      location.hash = "#/configuration/application";
    });
    await page.waitForSelector("[data-testid=server-section]", { timeout: 15_000 });
    const eff = await page.textContent("[data-testid=server-effective]");
    check("settings.effective_server", eff?.includes("59998"), `effective: ${eff}`);
    await page.evaluate(() => {
      document.querySelector("[data-testid=diagnostics]")?.setAttribute("open", "");
    });
    const logsEnabled = await page
      .waitForSelector("[data-testid=open-logs]", { state: "attached", timeout: 10_000 })
      .then(() => page.evaluate(() => document.querySelector("[data-testid=open-logs]")?.disabled === false))
      .catch(() => false);
    check("settings.logs_entry_enabled", logsEnabled, "open-logs button is a working entry (P10)");
    const daemonText = await page.textContent("[data-testid=daemon-state]");
    check("settings.daemon_state_from_p1", sidecarShipped ? /^(Arr\S+|D\S+marrage|En marche)$/u.test((daemonText ?? "").trim().normalize("NFC")) : /indisponible/i.test(daemonText ?? ""), `sidecar ${sidecarState}; daemon: ${daemonText}`);
    const serverState = await page.textContent("[data-testid=server-section]");
    check("settings.server_reachable", /Joignable/.test(serverState ?? ""), "server section says Joignable");
    const compat = await page.textContent("[data-testid=compatibility]");
    check("settings.compatibility_shown", /Compatible/.test(compat ?? ""), `compat: ${compat}`);

    // ---- 7. server goes away: recoverable without a restart
    live.close();
    live.closeAllConnections?.();
    // A failed API call (navigation) flips the state; nothing polls while connected.
    await page.evaluate(() => {
      location.hash = "#/projects";
    });
    await page.waitForFunction(() => /injoignable/i.test(document.querySelector("#shell-status")?.textContent ?? ""), null, { timeout: 30_000 }).catch(() => undefined);
    const down = await page.textContent("#shell-status");
    check("status.unreachable_pill", /injoignable/i.test(down ?? ""), `pill: ${down?.trim()}`);
    const back = await startLiveServer();
    await page.evaluate(() => document.querySelector("[data-action=retry]")?.click());
    await page.waitForFunction(() => !/injoignable/i.test(document.querySelector("#shell-status")?.textContent ?? "") , null, { timeout: 60_000 }).catch(() => undefined);
    const up = await page.textContent("#shell-status");
    check("status.recovers_without_restart", !/injoignable/i.test(up ?? ""), `pill: ${up?.trim()}`);
    back.close();

    const violations = messages.filter((m) => /content security policy/i.test(m) && !m.includes("59997") && !m.includes("59998") && !m.includes("127.0.0.1:59999"));
    check("csp.no_unexpected_violation", violations.length === 0, `${violations.length} unexpected: ${violations[0] ?? "-"}`);
  } finally {
    await browser?.close().catch(() => undefined);
    killApp();
    live.close();
    mkdirSync(buildDir, { recursive: true });
    writeFileSync(join(buildDir, "e2e-shell-results.json"), JSON.stringify(results, null, 2));
  }
  const failed = results.filter((r) => r.status === "FAIL");
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  killApp();
  process.exit(1);
});
