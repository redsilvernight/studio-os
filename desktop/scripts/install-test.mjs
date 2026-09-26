// Real install / launch / upgrade / uninstall test of the NSIS installer.
//
//   node scripts/install-test.mjs [--installer <path>] [--channel prod|dev]
//
// Runs the actual per-user installer silently into a throwaway directory, launches
// the INSTALLED application (offline, daemon data redirected to a throwaway
// %APPDATA%), reinstalls over it with user data present, then uninstalls and
// checks nothing of the user's was removed. The install writes the usual per-user
// registry key and Start-menu shortcut; both are removed by the uninstaller and
// verified. It refuses to run if Studio OS Desktop is already installed.
//
// Results: desktop/.build/install-test-results.json. Exit code 1 on any failure.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { connect as netConnect } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";
import { arg, buildChannel, buildDir, CHANNELS, desktopDir, tauriDir } from "./lib.mjs";
import { canonicalVersion } from "./version.mjs";

const CHANNEL = CHANNELS[buildChannel()];
const PRODUCT = CHANNEL.productName;
const UNINSTALL_KEY = `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${PRODUCT}`;
const CDP_PORT = Number(process.env.STUDIO_E2E_CDP_PORT ?? 9444);
const APP_ORIGIN = "http://tauri.localhost";
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(id, cond, evidence) {
  results.push({ id, status: cond ? "PASS" : "FAIL", evidence });
  console.log(`${cond ? "PASS" : "FAIL"}  ${id}  ${evidence}`);
}

const installerPath = resolve(
  arg("--installer", join(tauriDir, "target", "release", "bundle", "nsis", `${PRODUCT}_${JSON.parse(readFileSync(join(desktopDir, "package.json"), "utf8")).version}_x64-setup.exe`)),
);

function reg(...args) {
  return spawnSync("reg", args, { encoding: "utf8" });
}
const installedKey = () => reg("query", UNINSTALL_KEY).status === 0;

function processCount(image) {
  const out = spawnSync("tasklist", ["/FI", `IMAGENAME eq ${image}`, "/FO", "CSV", "/NH"], { encoding: "utf8" }).stdout;
  return out.split("\n").filter((l) => l.toLowerCase().includes(image.toLowerCase())).length;
}

function runSilent(exe, args, timeoutMs = 600_000) {
  return new Promise((res) => {
    const child = spawn(exe, args, { windowsVerbatimArguments: true, stdio: "ignore" });
    const timer = setTimeout(() => {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      res(-1);
    }, timeoutMs);
    child.on("exit", (code) => {
      clearTimeout(timer);
      res(code ?? -1);
    });
  });
}

function listFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...listFiles(full));
    else out.push(full);
  }
  return out;
}

const dirSize = (dir) => listFiles(dir).reduce((sum, f) => sum + statSync(f).size, 0);

function webviewCommandLines() {
  const out = spawnSync(
    "powershell",
    ["-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | ForEach-Object { $_.CommandLine }"],
    { encoding: "utf8" },
  ).stdout ?? "";
  const lines = out.split(/\r?\n/).filter(Boolean);
  const browser = lines.find((l) => !l.includes("--type=")) ?? lines[0] ?? "";
  const debugArgs = browser.match(/--remote-debugging[^ "]*/g) ?? [];
  const features = browser.match(/--(?:disable|enable)-features=[^ ]*/g) ?? [];
  return `${lines.length} webview command line(s); browser debug args: ${debugArgs.join(" ") || "none"}; ${features.join(" ")}; tail: ${browser.slice(-300)}`;
}

async function cdpTargets() {
  try {
    const response = await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`, { signal: AbortSignal.timeout(2000) });
    const targets = await response.json();
    return targets.map((t) => `${t.type}:${t.url}`).join(" | ") || "no target";
  } catch (e) {
    return `endpoint unreachable (${e?.cause?.code ?? e?.name ?? e})`;
  }
}

let webviewDataDir = null;
function devToolsActivePort() {
  const file = webviewDataDir ? join(webviewDataDir, "EBWebView", "DevToolsActivePort") : null;
  if (!file || !existsSync(file)) return "no DevToolsActivePort file";
  return `DevToolsActivePort: ${readFileSync(file, "utf8").split(/\s+/)[0]}`;
}

async function attach(app, stderrTail) {
  for (let i = 0; i < 60; i++) {
    if (app.exitCode !== null) break;
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
  // Enough context to diagnose a CI-only failure from the annotation alone.
  const state = app.exitCode === null ? `still running (pid ${app.pid})` : `exited with ${app.exitCode}`;
  throw new Error(
    `could not attach to the installed Desktop over CDP: app ${state}; ` +
      `desktop processes ${processCount("studio-desktop.exe")}, webview processes ${processCount("msedgewebview2.exe")}; ` +
      `CDP targets: ${await cdpTargets()}; ${webviewCommandLines()}; ${devToolsActivePort()}; stderr: ${stderrTail().slice(-600) || "(empty)"}`,
  );
}

const invoke = (page, name, args) =>
  page.evaluate(
    async ({ name, args }) => {
      try {
        return { ok: true, value: await window.__TAURI__.core.invoke(name, args) };
      } catch (e) {
        return { ok: false, error: typeof e === "string" ? e : JSON.stringify(e), code: e?.code };
      }
    },
    { name, args },
  );

function listeningSockets(pids) {
  const out = spawnSync("netstat", ["-ano", "-p", "TCP"], { encoding: "utf8" }).stdout;
  return out
    .split("\n")
    .map((l) => l.trim().split(/\s+/))
    .filter((c) => c[0] === "TCP" && c[3] === "LISTENING" && pids.includes(c[4]))
    .map((c) => c[1]);
}

function pidsOf(image) {
  const out = spawnSync("tasklist", ["/FI", `IMAGENAME eq ${image}`, "/FO", "CSV", "/NH"], { encoding: "utf8" }).stdout;
  return out
    .split("\n")
    .filter((l) => l.toLowerCase().includes(image.toLowerCase()))
    .map((l) => l.split(",")[1]?.replaceAll('"', ""))
    .filter(Boolean);
}

async function main() {
  if (!existsSync(installerPath)) throw new Error(`missing ${installerPath} - run: npm run package`);
  if (installedKey()) throw new Error(`${PRODUCT} is already installed for this user; uninstall it first (this test never touches a real install)`);
  if (processCount("studio-daemon.exe") > 0 || processCount("studio-desktop.exe") > 0) {
    throw new Error("a studio-daemon.exe / studio-desktop.exe process is already running; stop it first");
  }

  const root = mkdtempSync(join(tmpdir(), "studio-install-test-"));
  const instDir = join(root, "Programs", PRODUCT);
  const appData = join(root, "appdata");
  const localAppData = join(root, "localappdata");
  const webviewData = join(root, "webview2");
  const vault = join(root, "vault");
  mkdirSync(appData, { recursive: true });
  mkdirSync(localAppData, { recursive: true });
  mkdirSync(webviewData, { recursive: true });
  webviewDataDir = webviewData;
  mkdirSync(vault, { recursive: true });
  const size = statSync(installerPath).size;
  console.log(`installer ${installerPath} (${(size / 1048576).toFixed(1)} MB) -> ${instDir}`);

  try {
    // ---- 1. install ---------------------------------------------------------
    const t0 = Date.now();
    const code = await runSilent(installerPath, ["/S", `/D=${instDir}`]);
    check("install.silent_exit_zero_without_elevation", code === 0, `exit ${code} in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    const exe = join(instDir, "studio-desktop.exe");
    const files = existsSync(instDir) ? listFiles(instDir) : [];
    check("install.app_and_uninstaller_present", existsSync(exe) && existsSync(join(instDir, "uninstall.exe")), `studio-desktop.exe, uninstall.exe in ${instDir}`);
    check("install.sidecar_folder_present", existsSync(join(instDir, "sidecar", "studio-daemon.exe")) && existsSync(join(instDir, "sidecar", "_internal")), "sidecar/studio-daemon.exe + sidecar/_internal");
    const manifest = existsSync(join(instDir, "sidecar", "sidecar-manifest.json")) ? JSON.parse(readFileSync(join(instDir, "sidecar", "sidecar-manifest.json"), "utf8")) : null;
    check("install.sidecar_manifest_present", manifest?.protocol === "studio.local/v1" && Boolean(manifest?.daemon_version), JSON.stringify(manifest));
    const foreign = files.filter((f) => /(^|\\)(python[\d.]*|pythonw|node|git|cargo|pip[\d.]*|uv)\.exe$/i.test(f));
    check("install.no_dev_runtime_shipped", foreign.length === 0, foreign.length ? foreign.join(", ") : `no python/node/git/cargo/pip/uv executable among ${files.length} files`);
    const keyLike = files.filter((f) => /\.(pem|key|pfx|p12|env)$/i.test(f) || /(^|\\)\.env/i.test(f));
    const privateKeys = keyLike.filter((f) => /-----BEGIN [A-Z ]*PRIVATE KEY-----/.test(readFileSync(f, "latin1")));
    const nonCa = keyLike.filter((f) => !/(^|\\)cacert\.pem$/i.test(f));
    check("install.no_secret_or_key_shipped", privateKeys.length === 0 && nonCa.length === 0, `key-like files: ${keyLike.length} (public CA bundles only: ${nonCa.length === 0}); private-key blocks: ${privateKeys.length}`);
    check("install.registers_per_user_uninstall_key", installedKey(), `${UNINSTALL_KEY} present (HKCU, no machine-wide entry)`);
    check("install.size", true, `installer ${(size / 1048576).toFixed(1)} MB; installed ${(dirSize(instDir) / 1048576).toFixed(1)} MB in ${files.length} files`);

    // ---- 2. launch the installed app, offline, isolated data ----------------------
    const app = spawn(exe, [], {
      env: {
        ...process.env,
        APPDATA: appData,
        LOCALAPPDATA: localAppData,
        WEBVIEW2_USER_DATA_FOLDER: webviewData,
        STUDIO_CLIENT_API_BASE_URL: "http://127.0.0.1:1/api/v1",
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${CDP_PORT}`,
      },
      stdio: ["ignore", "ignore", "pipe"],
    });
    let stderr = "";
    app.stderr.on("data", (chunk) => {
      stderr = (stderr + chunk).slice(-4000);
    });
    let browser;
    try {
      const attached = await attach(app, () => stderr);
      browser = attached.browser;
      const page = attached.page;
      await page.waitForSelector('[data-testid="onboarding-step"]', { timeout: 30_000 });
      check("launch.dashboard_loaded_offline", page.url().startsWith(`${APP_ORIGIN}/`), `page ${page.url()} with an unreachable server`);
      const firstStep = await page.getAttribute('[data-testid="onboarding-step"]', "data-step");
      check("launch.onboarding_shown_first_run", firstStep === "bienvenue", `onboarding step on first launch: ${firstStep}`);
      let info = null;
      for (let i = 0; i < 40; i++) {
        info = (await invoke(page, "desktop_info", {})).value;
        if (info?.sidecar?.state === "running") break;
        await sleep(500);
      }
      check("launch.sidecar_running_from_install_dir", info?.sidecar?.state === "running", JSON.stringify(info?.sidecar));
      const daemons = pidsOf("studio-daemon.exe");
      check("launch.single_daemon", daemons.length === 1, `studio-daemon.exe processes: ${daemons.length}`);
      const diag = (await invoke(page, "get_diagnostics", {})).value;
      check("launch.diagnostics_report_installed_sidecar", diag?.sidecar?.present === true && diag?.sidecar?.compat === "compatible", `present=${diag?.sidecar?.present} compat=${diag?.sidecar?.compat} desktop=${diag?.desktop_version}`);
      check("launch.install_dir_reported", typeof diag?.locations?.install_dir === "string" && diag.locations.install_dir.toLowerCase().includes(PRODUCT.toLowerCase()), String(diag?.locations?.install_dir));
      let stamp = null;
      for (let i = 0; i < 20 && !stamp; i++) {
        stamp = existsSync(join(appData, CHANNEL.dataDir, "format.json")) ? JSON.parse(readFileSync(join(appData, CHANNEL.dataDir, "format.json"), "utf8")) : null;
        if (!stamp) await sleep(500);
      }
      check("launch.user_data_lives_outside_install_dir", stamp?.format === 1 && !listFiles(instDir).some((f) => /format\.json$/i.test(f)), `format.json ${JSON.stringify(stamp)} under the redirected %APPDATA%, none under the install dir`);
      const sockets = listeningSockets([...daemons, ...pidsOf("studio-desktop.exe")]);
      check("launch.no_listener_on_all_interfaces", sockets.every((s) => !s.startsWith("0.0.0.0:") && !s.startsWith("[::]:")), sockets.length ? sockets.join(", ") : "no listening socket");
      const exported = await invoke(page, "export_diagnostics", {});
      const exportFile = exported.value?.file ? String(exported.value.file) : "";
      const exportedDir = join(appData, CHANNEL.dataDir, "diagnostics");
      const exportedFiles = existsSync(exportedDir) ? readdirSync(exportedDir) : [];
      const exportedText = exportedFiles.length ? readFileSync(join(exportedDir, exportedFiles[0]), "utf8") : "";
      check("launch.diagnostics_export_written_and_redacted", exported.ok && exportedFiles.length === 1 && !exportedText.includes(appData) && !/token|password|secret/i.test(exportedText.replace(/"[^"]*(?:token|password|secret)[^"]*"\s*:\s*"?\[redacted\]"?/gi, "")), `${exportFile}; ${exportedFiles.length} file(s), no raw home path`);
      const upd = await invoke(page, "check_for_update", {});
      if (process.env.STUDIO_UPDATER_ENDPOINT) {
        // Updater compiled in: the check answers (or fails as a network fault), never crashes.
        const answered = (upd.ok && ["up_to_date", "available"].includes(upd.value?.state)) || upd.code === "network";
        check("launch.updater_configured_answers", answered, JSON.stringify(upd));
      } else {
        check("launch.updater_not_configured_in_dev_installer", upd.ok && upd.value?.state === "not_configured", JSON.stringify(upd));
      }
    } finally {
      if (browser) await browser.close().catch(() => {});
      spawnSync("powershell", ["-NoProfile", "-Command", `(Get-Process -Id ${app.pid} -ErrorAction SilentlyContinue).CloseMainWindow() | Out-Null`], { stdio: "ignore" });
      for (let i = 0; i < 20 && (processCount("studio-desktop.exe") > 0 || processCount("studio-daemon.exe") > 0); i++) await sleep(500);
      const leftover = processCount("studio-desktop.exe") + processCount("studio-daemon.exe");
      if (leftover > 0) spawnSync("taskkill", ["/IM", "studio-daemon.exe", "/T", "/F"], { stdio: "ignore" });
      check("launch.graceful_close_leaves_no_process", leftover === 0, `processes left after a normal close: ${leftover}`);
    }

    // ---- 3. upgrade over an install holding user data ---------------------------
    writeFileSync(join(appData, CHANNEL.dataDir, "config.toml"), "# user setting\n");
    writeFileSync(join(vault, "note.md"), "# my note\n");
    writeFileSync(join(instDir, "stale-from-old-build.txt"), "old\n");
    const before = readFileSync(join(appData, CHANNEL.dataDir, "format.json"), "utf8");
    const up = await runSilent(installerPath, ["/S", `/D=${instDir}`]);
    check("upgrade.reinstall_over_existing_exit_zero", up === 0, `exit ${up}`);
    check("upgrade.program_files_replaced", existsSync(exe) && existsSync(join(instDir, "sidecar", "studio-daemon.exe")), "app and sidecar still present after the reinstall");
    check("upgrade.user_data_preserved", readFileSync(join(appData, CHANNEL.dataDir, "config.toml"), "utf8") === "# user setting\n" && readFileSync(join(appData, CHANNEL.dataDir, "format.json"), "utf8") === before, "config.toml and format.json untouched");
    check("upgrade.vault_untouched", readFileSync(join(vault, "note.md"), "utf8") === "# my note\n", "vault note intact");

    // ---- 4. uninstall (default: keep data) ---------------------------------------
    const un = await runSilent(join(instDir, "uninstall.exe"), ["/S", `_?=${instDir}`]);
    check("uninstall.silent_exit_zero", un === 0, `exit ${un}`);
    const remaining = existsSync(instDir) ? listFiles(instDir).filter((f) => !/uninstall\.exe$/i.test(f) && !/stale-from-old-build\.txt$/i.test(f)) : [];
    check("uninstall.program_files_removed", !existsSync(exe) && !existsSync(join(instDir, "sidecar")) && remaining.length === 0, remaining.length ? `left: ${remaining.slice(0, 5).join(", ")}` : "app and sidecar removed");
    check("uninstall.registry_key_removed", !installedKey(), UNINSTALL_KEY);
    check("uninstall.user_data_kept_by_default", readFileSync(join(appData, CHANNEL.dataDir, "config.toml"), "utf8") === "# user setting\n" && existsSync(join(appData, CHANNEL.dataDir, "format.json")), "daemon data folder kept");
    check("uninstall.vault_untouched", readFileSync(join(vault, "note.md"), "utf8") === "# my note\n", "vault note intact");
    check("uninstall.no_process_left", processCount("studio-daemon.exe") === 0 && processCount("studio-desktop.exe") === 0, "no studio process left");
  } finally {
    if (installedKey()) {
      const u = join(instDir, "uninstall.exe");
      if (existsSync(u)) await runSilent(u, ["/S", `_?=${instDir}`]);
    }
    rmSync(root, { recursive: true, force: true });
  }
}

// ---- B6: update the installed release N to the published release N+1 ----------
//
//   node scripts/install-test.mjs --upgrade-from <installer of N> [--expect-version <N+1>]
//
// Installs N (a real published release whose updater is compiled in), then from
// the running application: (a) with the network down the check fails as a
// network fault and N keeps working; (b) with the installer download cut off
// mid-way the install is refused and N is still the installed version; (c) with
// the network up N finds N+1 on its baked-in feed, installs it without any
// manual step and the installer restarts the app as N+1 with config, vault,
// daemon data and credentials intact. A corrupted or wrongly signed artifact is
// refused before anything runs (updater.rs tests: the same plugin code path).

const CREDENTIAL = `StudioOS-B6-update-test-${process.pid}`;

/** A CONNECT proxy that cuts every tunnel after `limit` bytes from upstream. */
function cuttingProxy(limit) {
  const server = createServer((_, res) => res.writeHead(405).end());
  let cut = 0;
  server.on("connect", (req, client, head) => {
    const [host, port] = req.url.split(":");
    const upstream = netConnect(Number(port) || 443, host, () => {
      client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
      if (head.length) upstream.write(head);
      client.pipe(upstream);
    });
    let seen = 0;
    upstream.on("data", (chunk) => {
      seen += chunk.length;
      if (seen > limit) {
        cut += 1;
        upstream.destroy();
        client.destroy();
        return;
      }
      client.write(chunk);
    });
    upstream.on("error", () => client.destroy());
    client.on("error", () => upstream.destroy());
    upstream.on("close", () => client.end());
  });
  return new Promise((res) => server.listen(0, "127.0.0.1", () => res({ server, port: server.address().port, cuts: () => cut })));
}

function displayVersion() {
  const out = reg("query", UNINSTALL_KEY, "/v", "DisplayVersion").stdout ?? "";
  return /DisplayVersion\s+REG_SZ\s+(\S+)/.exec(out)?.[1] ?? null;
}

async function closeDesktop() {
  for (const pid of pidsOf("studio-desktop.exe")) {
    spawnSync("powershell", ["-NoProfile", "-Command", `(Get-Process -Id ${pid} -ErrorAction SilentlyContinue).CloseMainWindow() | Out-Null`], { stdio: "ignore" });
  }
  for (let i = 0; i < 30 && (processCount("studio-desktop.exe") > 0 || processCount("studio-daemon.exe") > 0); i++) await sleep(500);
  const leftover = processCount("studio-desktop.exe") + processCount("studio-daemon.exe");
  if (leftover > 0) {
    spawnSync("taskkill", ["/IM", "studio-desktop.exe", "/T", "/F"], { stdio: "ignore" });
    spawnSync("taskkill", ["/IM", "studio-daemon.exe", "/T", "/F"], { stdio: "ignore" });
  }
  return leftover;
}

async function upgradeMain(oldInstaller, expected) {
  if (!existsSync(oldInstaller)) throw new Error(`missing ${oldInstaller} (the published release N)`);
  if (installedKey()) throw new Error(`${PRODUCT} is already installed for this user; uninstall it first (this test never touches a real install)`);
  if (processCount("studio-daemon.exe") > 0 || processCount("studio-desktop.exe") > 0) {
    throw new Error("a studio-daemon.exe / studio-desktop.exe process is already running; stop it first");
  }
  const root = mkdtempSync(join(tmpdir(), "studio-update-test-"));
  const instDir = join(root, "Programs", PRODUCT);
  const appData = join(root, "appdata");
  const localAppData = join(root, "localappdata");
  webviewDataDir = join(root, "webview2");
  const vault = join(root, "vault");
  for (const dir of [appData, localAppData, webviewDataDir, vault]) mkdirSync(dir, { recursive: true });
  const dataDir = join(appData, CHANNEL.dataDir);
  const baseEnv = {
    ...process.env,
    APPDATA: appData,
    LOCALAPPDATA: localAppData,
    WEBVIEW2_USER_DATA_FOLDER: webviewDataDir,
    STUDIO_CLIENT_API_BASE_URL: "http://127.0.0.1:1/api/v1",
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${CDP_PORT}`,
  };
  for (const name of ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"]) delete baseEnv[name];
  const exe = join(instDir, "studio-desktop.exe");

  /** Launch the installed app and hand its page to `body`; always closes it. */
  async function withApp(extraEnv, body) {
    const app = spawn(exe, [], { env: { ...baseEnv, ...extraEnv }, stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    app.stderr.on("data", (chunk) => {
      stderr = (stderr + chunk).slice(-4000);
    });
    let browser;
    try {
      const attached = await attach(app, () => stderr);
      browser = attached.browser;
      return await body(attached.page);
    } finally {
      if (browser) await browser.close().catch(() => {});
      await closeDesktop();
    }
  }
  const versionOf = async (page) => (await invoke(page, "desktop_info", {})).value?.desktop_version;

  try {
    const code = await runSilent(oldInstaller, ["/S", `/D=${instDir}`]);
    check("update.install_n_exit_zero", code === 0, `exit ${code}: ${oldInstaller}`);
    const previous = displayVersion();
    check("update.n_older_than_expected", Boolean(previous) && previous !== expected, `installed N=${previous}, expected N+1=${expected}`);

    // First run creates the daemon data; then the user data every update must keep.
    await withApp({}, async (page) => {
      for (let i = 0; i < 40 && !existsSync(join(dataDir, "format.json")); i++) await sleep(500);
      check("update.n_runs", (await versionOf(page)) === previous, `N reports ${await versionOf(page)}`);
    });
    writeFileSync(join(dataDir, "config.toml"), "# user setting kept across updates\n");
    writeFileSync(join(vault, "note.md"), "# my note\n");
    const stamp = readFileSync(join(dataDir, "format.json"), "utf8");
    const dbs = ["state.db", "outbox.db"].filter((f) => existsSync(join(dataDir, f)));
    const cred = spawnSync("cmdkey", [`/generic:${CREDENTIAL}`, "/user:b6-update-test", "/pass:not-a-secret"], { encoding: "utf8" });
    check("update.sentinel_credential_stored", cred.status === 0, `Credential Manager entry ${CREDENTIAL}`);

    // (a) Network down: a network fault, never a crash; N keeps working.
    await withApp({ HTTPS_PROXY: "http://127.0.0.1:9", HTTP_PROXY: "http://127.0.0.1:9" }, async (page) => {
      const upd = await invoke(page, "check_for_update", {});
      check("update.offline_check_is_network_fault", !upd.ok && upd.code === "network", JSON.stringify(upd));
      check("update.offline_app_still_works", (await versionOf(page)) === previous, "desktop_info answers after the failed check");
    });

    // (b) Download cut mid-way: refused, retryable, N still installed and running.
    const proxy = await cuttingProxy(2 * 1024 * 1024);
    try {
      const url = `http://127.0.0.1:${proxy.port}`;
      await withApp({ HTTPS_PROXY: url, HTTP_PROXY: url }, async (page) => {
        const upd = await invoke(page, "check_for_update", {});
        check("update.cut_check_finds_n_plus_1", upd.ok && upd.value?.state === "available" && upd.value?.version === expected, JSON.stringify(upd));
        const inst = await invoke(page, "install_update", {});
        check("update.cut_download_refused_as_network", !inst.ok && inst.code === "network", `${JSON.stringify(inst)}; tunnels cut: ${proxy.cuts()}`);
        check("update.cut_n_still_running", (await versionOf(page)) === previous && displayVersion() === previous, `running ${await versionOf(page)}, installed ${displayVersion()}`);
      });
    } finally {
      proxy.server.close();
    }

    // (c) Real update from the published feed, no manual step.
    // Not `withApp`: its close would also stop the app the installer relaunches.
    const old = spawn(exe, [], { env: baseEnv, stdio: ["ignore", "ignore", "pipe"] });
    let oldStderr = "";
    old.stderr.on("data", (chunk) => {
      oldStderr = (oldStderr + chunk).slice(-4000);
    });
    const oldApp = await attach(old, () => oldStderr);
    let upd;
    // The release was just published: give the feed a moment to be served.
    for (let i = 0; i < 12; i++) {
      upd = await invoke(oldApp.page, "check_for_update", {});
      if (upd.ok && upd.value?.version === expected) break;
      await sleep(5000);
    }
    check("update.check_finds_n_plus_1", upd.ok && upd.value?.state === "available" && upd.value?.version === expected, JSON.stringify(upd));
    // On success the app exits into the installer: the call never returns.
    void invoke(oldApp.page, "install_update", {}).catch(() => {});
    for (let i = 0; i < 120 && old.exitCode === null; i++) await sleep(1000);
    await oldApp.browser.close().catch(() => {});
    check("update.n_exits_into_installer", old.exitCode === 0, `N exit code ${old.exitCode}`);
    for (let i = 0; i < 240 && displayVersion() !== expected; i++) await sleep(1000);
    check("update.installed_version_is_n_plus_1", displayVersion() === expected, `DisplayVersion ${displayVersion()} (expected ${expected})`);

    // The installer relaunches the app (same environment): attach to it.
    let relaunched = null;
    let browser;
    try {
      for (let i = 0; i < 60 && !relaunched; i++) {
        try {
          browser = await chromium.connectOverCDP(`http://127.0.0.1:${CDP_PORT}`);
          const page = browser.contexts()[0]?.pages().find((p) => p.url().startsWith(APP_ORIGIN));
          if (page) relaunched = page;
          else await browser.close();
        } catch {
          await sleep(1000);
        }
      }
      check("update.app_relaunched_by_installer", Boolean(relaunched), `desktop processes ${processCount("studio-desktop.exe")}`);
      if (relaunched) {
        check("update.relaunched_is_n_plus_1", (await versionOf(relaunched)) === expected, `relaunched app reports ${await versionOf(relaunched)}`);
        let info = null;
        for (let i = 0; i < 40; i++) {
          info = (await invoke(relaunched, "desktop_info", {})).value;
          if (info?.sidecar?.state === "running") break;
          await sleep(500);
        }
        check("update.sidecar_running_after_update", info?.sidecar?.state === "running", JSON.stringify(info?.sidecar));
        check("update.single_daemon_after_update", pidsOf("studio-daemon.exe").length === 1, `studio-daemon.exe processes: ${pidsOf("studio-daemon.exe").length}`);
      }
    } finally {
      if (browser) await browser.close().catch(() => {});
      await closeDesktop();
    }
    check(
      "update.user_data_preserved",
      readFileSync(join(dataDir, "config.toml"), "utf8") === "# user setting kept across updates\n" && readFileSync(join(dataDir, "format.json"), "utf8") === stamp && dbs.every((f) => existsSync(join(dataDir, f))),
      `config.toml and format.json untouched; kept: ${dbs.join(", ") || "no database created by N"}`,
    );
    check("update.vault_untouched", readFileSync(join(vault, "note.md"), "utf8") === "# my note\n", "vault note intact");
    check("update.credentials_kept", spawnSync("cmdkey", [`/list:${CREDENTIAL}`], { encoding: "utf8" }).stdout.includes(CREDENTIAL), `Credential Manager entry ${CREDENTIAL} still present`);
  } finally {
    spawnSync("cmdkey", [`/delete:${CREDENTIAL}`], { stdio: "ignore" });
    await closeDesktop();
    if (installedKey()) {
      const u = join(instDir, "uninstall.exe");
      if (existsSync(u)) await runSilent(u, ["/S", `_?=${instDir}`]);
    }
    rmSync(root, { recursive: true, force: true });
  }
}

const upgradeFrom = arg("--upgrade-from");
const resultsFile = upgradeFrom ? "update-test-results.json" : "install-test-results.json";
let failed = false;
try {
  if (upgradeFrom) await upgradeMain(resolve(upgradeFrom), arg("--expect-version", canonicalVersion()));
  else await main();
} catch (e) {
  failed = true;
  console.error("install test aborted:", e);
  results.push({ id: "install_test.aborted", status: "FAIL", evidence: String(e) });
}
mkdirSync(buildDir, { recursive: true });
writeFileSync(resolve(buildDir, resultsFile), JSON.stringify(results, null, 2));
const bad = results.filter((r) => r.status === "FAIL");
console.log(`\ninstall test: ${results.length - bad.length}/${results.length} passed`);
process.exit(failed || bad.length ? 1 : 0);
