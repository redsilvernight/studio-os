// Desktop E2E: drives the REAL packaged Desktop (WebView2) over CDP against a
// throwaway API stack. Nothing here mocks the shell, the sidecar or the server.
//
//   node scripts/e2e.mjs            # needs `npm run build:with-sidecar` first
//
// Every check records PASS/FAIL with its evidence; results are written to
// desktop/.build/e2e-results.json. Exit code 1 if any check fails.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { chromium } from "playwright-core";
import { buildDir, desktopDir, repoRoot, toolEnv } from "./lib.mjs";

const exe = resolve(desktopDir, "src-tauri", "target", "release", "studio-desktop.exe");
const CDP_PORT = Number(process.env.STUDIO_E2E_CDP_PORT ?? 9333);
const APP_ORIGIN = "http://tauri.localhost";
const results = [];

function record(id, ok, evidence) {
  results.push({ id, status: ok ? "PASS" : "FAIL", evidence });
  console.log(`${ok ? "PASS" : "FAIL"}  ${id}  ${evidence}`);
}
const check = (id, cond, evidence) => record(id, Boolean(cond), evidence);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function killTree(pid) {
  spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
}

function processCount(imageName) {
  const out = spawnSync("tasklist", ["/FI", `IMAGENAME eq ${imageName}`, "/FO", "CSV", "/NH"], {
    encoding: "utf8",
  }).stdout;
  return out.split("\n").filter((l) => l.toLowerCase().includes(imageName.toLowerCase())).length;
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

let counter = 0;
const bridgeRequest = (command, payload) => {
  counter += 1;
  return {
    kind: "request",
    protocol: "studio.local/v1",
    message_id: `e2e-req-${counter}`,
    correlation_id: `e2e-cor-${counter}`,
    sent_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    command,
    payload,
    deadline_ms: null,
  };
};

async function main() {
  if (!existsSync(exe)) throw new Error(`missing ${exe} - run: npm run build:with-sidecar`);
  const stack = await startStack();
  const { api, email, password, project, admin_id: adminId, machine_id: machineId, machine_token: machineToken } = stack.info;
  console.log(`stack up: ${api} (database ${stack.info.database})`);

  const app = spawn(exe, [], {
    env: {
      ...process.env,
      STUDIO_CLIENT_API_BASE_URL: `${api}/api/v1`,
      STUDIO_CLIENT_MACHINE_ID: machineId,
      STUDIO_CLIENT_MACHINE_TOKEN: machineToken,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${CDP_PORT}`,
    },
    stdio: "ignore",
  });
  let browser;
  try {
    const attached = await attach();
    browser = attached.browser;
    const page = attached.page;
    const consoleMessages = [];
    const responses = [];
    page.on("console", (m) => consoleMessages.push(m.text()));
    page.on("response", (r) => responses.push({ url: r.url(), status: r.status(), headers: r.headers() }));
    const pages = () => browser.contexts()[0].pages().length;

    // ---- A. Embedded Dashboard -------------------------------------------------
    await page.waitForSelector("#login-form", { timeout: 30_000 });
    check("dashboard.loaded", page.url().startsWith(`${APP_ORIGIN}/`), `page ${page.url()}`);
    const hasInvoke = await page.evaluate(() => typeof window.__TAURI__?.core?.invoke === "function");
    check("desktop.adapter_detected", hasInvoke, "window.__TAURI__.core.invoke injected in the packaged page");
    const cspHeader = await page.evaluate(async () => {
      const r = await fetch("/index.html");
      return r.headers.get("content-security-policy");
    });
    check(
      "csp.enforced",
      cspHeader && cspHeader.includes("default-src 'self'") && cspHeader.includes("frame-ancestors 'none'"),
      `CSP header on the packaged page: ${(cspHeader ?? "").slice(0, 200)}`,
    );

    // ---- B. Auth + REST + CORS (real server, enforced CSP) ----------------------
    await page.fill("#login-email", "gate-admin@example.test");
    await page.fill("#login-password", "wrong-password-on-purpose");
    await page.click("#login-form button[type=submit]");
    await page.waitForSelector("#login-form [role=alert], #login-form .error, [role=alert]", { timeout: 15_000 });
    const badLogin = responses.find((r) => r.url.endsWith("/api/v1/auth/token"));
    check("auth.wrong_password_rejected", badLogin && badLogin.status >= 400, `POST /auth/token -> ${badLogin?.status}`);

    await page.fill("#login-password", password);
    await page.click("#login-form button[type=submit]");
    await page.waitForFunction(() => !document.querySelector("#login-form"), null, { timeout: 30_000 });
    const okLogin = responses.filter((r) => r.url.endsWith("/api/v1/auth/token")).at(-1);
    check("auth.login_ok_from_tauri_origin", okLogin?.status === 200, `POST /auth/token -> ${okLogin?.status}`);
    const acao = okLogin?.headers["access-control-allow-origin"];
    check("cors.exact_origin_never_wildcard", acao === APP_ORIGIN, `Access-Control-Allow-Origin: ${acao}`);
    await sleep(1500);
    const apiCalls = responses.filter((r) => r.url.startsWith(`${api}/api/v1/`) && !r.url.endsWith("/auth/token"));
    check(
      "rest.authenticated_calls_ok",
      apiCalls.length > 0 && apiCalls.every((r) => r.status < 400),
      `${apiCalls.length} authenticated REST responses, statuses ${[...new Set(apiCalls.map((r) => r.status))]}`,
    );
    const csp = consoleMessages.filter((m) => /content security policy/i.test(m));
    check("csp.no_violation_in_dashboard_flow", csp.length === 0, `${csp.length} CSP violation messages: ${csp[0] ?? "-"}`);

    // Independent token for SSE/CORS probes (the app's own token stays in memory).
    const tokenRes = await fetch(`${api}/api/v1/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Origin: APP_ORIGIN },
      body: JSON.stringify({ email, password }),
    });
    const token = (await tokenRes.json()).access_token;
    const projects = await (await fetch(`${api}/api/v1/projects`, { headers: { Authorization: `Bearer ${token}` } })).json();
    const projectId = projects.find((p) => p.slug === project)?.id;

    const pre = await fetch(`${api}/api/v1/projects`, {
      method: "OPTIONS",
      headers: {
        Origin: APP_ORIGIN,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
      },
    });
    check("cors.preflight_allows_tauri_origin", pre.headers.get("access-control-allow-origin") === APP_ORIGIN, `preflight -> ${pre.status}`);
    const evil = await fetch(`${api}/api/v1/projects`, {
      method: "OPTIONS",
      headers: { Origin: "http://evil.test", "Access-Control-Request-Method": "GET" },
    });
    check("cors.other_origin_refused", !evil.headers.get("access-control-allow-origin"), `Origin http://evil.test -> ${evil.status}, ACAO ${evil.headers.get("access-control-allow-origin")}`);

    // ---- C. SSE from the packaged WebView -------------------------------------
    const sseRun = page.evaluate(
      async ({ api, token, projectId }) => {
        const ctrl = new AbortController();
        const res = await fetch(`${api}/api/v1/events/stream?project=${projectId}`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: ctrl.signal,
        });
        const out = { status: res.status, type: res.headers.get("content-type"), frame: null };
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        const deadline = Date.now() + 20_000;
        while (Date.now() < deadline && !out.frame) {
          const chunk = await Promise.race([
            reader.read(),
            new Promise((r) => setTimeout(() => r({ timeout: true }), 3000)),
          ]);
          if (chunk.timeout) continue;
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          if (buffer.includes("data:")) out.frame = buffer.slice(0, 200);
        }
        ctrl.abort();
        return out;
      },
      { api, token, projectId },
    );
    await sleep(1500);
    const emit = await fetch(`${api}/api/v1/events`, {
      method: "POST",
      headers: { Authorization: `Bearer ${machineToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        event_id: crypto.randomUUID(),
        event_type: "task.created",
        project_id: projectId,
        actor_type: "user",
        actor_id: adminId,
        client_timestamp: new Date().toISOString(),
        payload: { source: "desktop-p2-gate" },
      }),
    });
    console.log(`emit event -> ${emit.status}`);
    const sseResult = await sseRun;
    check(
      "sse.stream_opens_from_tauri_origin",
      sseResult.status === 200 && /text\/event-stream/.test(sseResult.type ?? ""),
      `GET /events/stream -> ${sseResult.status} ${sseResult.type}`,
    );
    check("sse.frame_delivered", Boolean(sseResult.frame), `first frame: ${JSON.stringify(sseResult.frame ?? null)}`);

    // ---- D. Settings identity (version, mode, protocol) ------------------------
    await page.evaluate(() => {
      location.hash = "#/configuration/application";
    });
    await page.waitForFunction(() => document.body.innerText.includes("Studi'OS Desktop"), null, { timeout: 15_000 });
    const text = await page.evaluate(() => document.body.innerText);
    check("settings.shows_identity", text.includes("Studi'OS Desktop") && text.includes("0.1.0") && text.includes("studio.local/v1"), "Settings > Application shows product, version and protocol");
    check("settings.shows_desktop_mode", /Desktop/.test(text) && !/Application Desktop non utilisée/.test(text), "mode Desktop displayed, no web-mode fallback text");
    await page.reload();
    await page.waitForFunction(() => document.body.innerText.includes("Studi'OS Desktop") || !!document.querySelector("#login-form"), null, { timeout: 15_000 });
    check("routing.reload_keeps_app", page.url().startsWith(`${APP_ORIGIN}/`), `after reload: ${page.url()}`);

    // ---- E. Bridge: allowlist, typed errors, refused primitives ----------------
    const info = (await invoke(page, "desktop_info")).value;
    check("bridge.desktop_info_typed", info?.protocol === "studio.local/v1" && info?.mode === "desktop", `desktop_info ${JSON.stringify({ v: info?.desktop_version, mode: info?.mode, protocol: info?.protocol })}`);
    for (const name of ["execute_shell", "spawn_process", "read_file", "write_file", "proxy_http", "execute", "run_command", "plugin:shell|execute", "plugin:fs|read_file", "plugin:http|fetch", "plugin:opener|open_url"]) {
      const out = await invoke(page, name, {});
      check(`bridge.refuses.${name}`, !out.ok, `invoke(${name}) -> ${out.ok ? "ACCEPTED" : out.error.slice(0, 90)}`);
    }
    const hs = await invoke(page, "bridge_request", { request: bridgeRequest("runtime.handshake", { peer: info.peer }) });
    check("bridge.handshake_compatible", hs.ok && hs.value.kind === "response" && hs.value.payload?.outcome === "compatible", `handshake outcome ${hs.value?.payload?.outcome ?? JSON.stringify(hs.value?.error?.code)}`);
    const profile = { profile_id: "default", server_origin: api };
    const started = await invoke(page, "bridge_request", { request: bridgeRequest("daemon.start", { action: "start", profile }) });
    check("daemon.starts_real_runtime", started.ok && started.value?.payload?.outcome === "ok", `daemon.start -> ${started.value?.payload?.outcome}`);
    await sleep(500);
    const st = await invoke(page, "bridge_request", { request: bridgeRequest("daemon.status", { action: "status", profile }) });
    const status = st.value?.payload?.status;
    check("daemon.sidecar_answers_status", st.ok && status?.state === "running" && Number.isInteger(status?.instance?.pid), `daemon.status -> ${status?.state}, sidecar pid ${status?.instance?.pid}${status ? "" : ` raw=${JSON.stringify(st.value).slice(0, 400)}`}`);
    const idv = await invoke(page, "bridge_request", { request: bridgeRequest("identity.get_view", {}) });
    const idText = JSON.stringify(idv.value);
    const secretStatus = idv.value?.payload?.secrets?.[0]?.status;
    check("keyring.usable_from_frozen_sidecar", idv.ok && ["present", "absent"].includes(secretStatus), `identity.get_view secret status: ${secretStatus} (keyring_unavailable would fail this check)`);
    check("keyring.no_raw_secret_to_renderer", !/token|password|"secret_value"|eyJ/i.test(idText.replace(/secret_reference|secrets|SecretReference|lookup_key|machine_credential|secret_absent|secret_store/gi, "")), "identity view carries references and status only");
    const unserved = await invoke(page, "bridge_request", { request: bridgeRequest("workspace.save_config", {}) });
    check("bridge.valid_but_unserved_is_not_supported", unserved.ok && unserved.value.error?.code === "not_supported", `workspace.save_config -> ${unserved.value?.error?.code}`);
    const unknown = await invoke(page, "bridge_request", { request: bridgeRequest("shell.execute", {}) });
    check("bridge.unknown_command_refused", unknown.ok && unknown.value.error?.code === "unknown_command", `shell.execute -> ${unknown.value?.error?.code}`);
    const badProtocol = await invoke(page, "bridge_request", { request: { ...bridgeRequest("daemon.status", { action: "status", profile }), protocol: "studio.local/v2" } });
    check("bridge.other_protocol_fails_closed", badProtocol.ok && badProtocol.value.error?.code === "protocol_incompatible", `v2 -> ${badProtocol.value?.error?.code}`);

    // ---- F. Safe navigation ----------------------------------------------------
    const before = page.url();
    const attempts = ["javascript:document.title='pwned'", "file:///C:/Windows/win.ini", "data:text/html,<h1>x</h1>", "ftp://example.test/x", "http://tauri.localhost@evil.test/", "about:blank", "blob:http://tauri.localhost/x"];
    for (const target of attempts) {
      await page.evaluate((t) => { try { location.assign(t); } catch { /* refused */ } }, target).catch(() => {});
      await sleep(600);
      const url = page.url();
      check(`navigation.blocks.${target.split(":")[0]}${target.includes("@") ? "_credentials" : ""}`, url.startsWith(`${APP_ORIGIN}/`) && (await page.evaluate(() => document.title)) !== "pwned", `after location.assign -> ${url === before ? "unchanged" : url}`);
    }
    for (const target of ["file:///C:/Windows/win.ini", "about:blank", "javascript:alert(1)"]) {
      await page.evaluate((t) => { window.open(t, "_blank"); }, target).catch(() => {});
      await sleep(500);
      check(`popup.denied.${target.split(":")[0]}`, pages() === 1, `window.open(${target.split(":")[0]}) -> ${pages()} webview page(s)`);
    }
    await page.evaluate(() => { window.open("http://127.0.0.1:1/p2-gate-external", "_blank"); });
    await sleep(800);
    check("navigation.external_http_never_enters_webview", pages() === 1 && page.url().startsWith(`${APP_ORIGIN}/`), "window.open(http external) handed to the system browser (a dead loopback page); no WebView created");

    // ---- G. Process observation ----------------------------------------------
    const info2 = (await invoke(page, "desktop_info")).value;
    check("process.running_state_observed", info2.sidecar.state === "running" && Number.isInteger(info2.sidecar.pid), `desktop_info.sidecar ${JSON.stringify(info2.sidecar)}`);
    const sidecarProcessesBefore = processCount("studio-daemon.exe");
    killTree(info2.sidecar.pid);
    await sleep(1500);
    const info3 = (await invoke(page, "desktop_info")).value;
    check("process.termination_detected", info3.sidecar.state === "exited", `after kill: ${JSON.stringify(info3.sidecar)}`);
    const rehandshake = await invoke(page, "bridge_request", { request: bridgeRequest("runtime.handshake", { peer: info.peer }) });
    check("process.recovered_sidecar_renegotiates", rehandshake.ok && rehandshake.value?.payload?.outcome === "compatible", `handshake on the restarted sidecar -> ${rehandshake.value?.payload?.outcome ?? JSON.stringify(rehandshake.value?.error?.code)}`);
    const after = await invoke(page, "bridge_request", { request: bridgeRequest("daemon.status", { action: "status", profile }) });
    check("process.request_after_exit_recovers_once", after.ok && after.value?.payload?.status?.state === "stopped", `daemon.status after restart -> ${after.value?.payload?.status?.state}${after.value?.payload?.status ? "" : ` raw=${JSON.stringify(after.value).slice(0, 400)}`}`);
    check("process.single_sidecar_after_recovery", processCount("studio-daemon.exe") === sidecarProcessesBefore, `studio-daemon.exe processes (the onedir sidecar is a single process): ${processCount("studio-daemon.exe")}, before the kill: ${sidecarProcessesBefore}`);

    let abandoned = null;
    let lastAnswer = null;
    for (let round = 0; round < 6 && abandoned === null; round += 1) {
      const current = (await invoke(page, "desktop_info")).value.sidecar;
      if (current.state === "running") {
        killTree(current.pid);
        await sleep(1000);
      }
      lastAnswer = await invoke(page, "bridge_request", { request: bridgeRequest("runtime.handshake", { peer: info.peer }) });
      const observed = (await invoke(page, "desktop_info")).value.sidecar;
      if (observed.state === "abandoned") abandoned = observed;
    }
    check("process.restart_bounded_then_abandoned", abandoned !== null && abandoned.attempts === 3, `sidecar after repeated crashes: ${JSON.stringify(abandoned)}`);
    check("process.abandoned_sidecar_is_refused_not_respawned", lastAnswer !== null && (!lastAnswer.ok || lastAnswer.value?.kind === "error"), `answer while abandoned: ${JSON.stringify(lastAnswer).slice(0, 200)}`);
    check("process.no_sidecar_running_once_abandoned", processCount("studio-daemon.exe") === 0, `studio-daemon.exe processes: ${processCount("studio-daemon.exe")}`);

    // ---- H. Network error handling (server down) ------------------------------
    await stopStack(stack);
    stack.stopped = true;
    await page.evaluate(() => { location.hash = "#/"; });
    await page.reload();
    await page.waitForFunction(() => !!document.querySelector("#login-form"), null, { timeout: 15_000 });
    await page.fill("#login-email", email);
    await page.fill("#login-password", password);
    await page.click("#login-form button[type=submit]");
    await sleep(2500);
    const stillUp = await page.evaluate(() => !!document.querySelector("#login-form"));
    const failure = await page.evaluate(() => document.body.innerText);
    check("network.server_down_is_handled", stillUp && /échec|erreur|impossible|réseau|connexion/i.test(failure), "login form stays, a visible error is shown (no crash, no blank page)");
  } finally {
    if (browser) await browser.close().catch(() => {});
    killTree(app.pid);
    if (!stack.stopped) await stopStack(stack);
  }
  check("process.no_sidecar_left_after_app_exit", (await (async () => { await sleep(1500); return processCount("studio-daemon.exe"); })()) === 0, "no studio-daemon.exe after the app is closed");
}

let failed = false;
try {
  await main();
} catch (e) {
  failed = true;
  console.error("E2E aborted:", e);
  results.push({ id: "e2e.aborted", status: "FAIL", evidence: String(e) });
}
mkdirSync(buildDir, { recursive: true });
writeFileSync(resolve(buildDir, "e2e-results.json"), JSON.stringify(results, null, 2));
const bad = results.filter((r) => r.status === "FAIL");
console.log(`\nE2E: ${results.length - bad.length}/${results.length} passed`);
process.exit(failed || bad.length ? 1 : 0);
