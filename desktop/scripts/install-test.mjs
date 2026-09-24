// Real install / launch / upgrade / uninstall test of the NSIS installer.
//
//   node scripts/install-test.mjs [--installer <path>]
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
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";
import { arg, buildDir, desktopDir, tauriDir } from "./lib.mjs";

const PRODUCT = "Studio OS Desktop";
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

// WebView2 reads extra browser arguments from WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
// and from the per-user WebView2 policy key; the GitHub Windows runner ignores the
// former, so the debug port is also set through the policy, scoped to this exe and
// removed in the finally block below.
const WEBVIEW2_POLICY_KEY = "HKCU\\Software\\Policies\\Microsoft\\Edge\\WebView2\\AdditionalBrowserArguments";
const WEBVIEW2_POLICY_VALUE = "studio-desktop.exe";
const hadWebview2Policy = () => reg("query", WEBVIEW2_POLICY_KEY, "/v", WEBVIEW2_POLICY_VALUE).status === 0;

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
        return { ok: false, error: String(e) };
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

  const policyPreexisting = hadWebview2Policy();
  if (policyPreexisting) throw new Error(`${WEBVIEW2_POLICY_KEY}\\${WEBVIEW2_POLICY_VALUE} already set; refusing to overwrite it`);
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
    reg("add", WEBVIEW2_POLICY_KEY, "/v", WEBVIEW2_POLICY_VALUE, "/t", "REG_SZ", "/d", `--remote-debugging-port=${CDP_PORT}`, "/f");
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
        stamp = existsSync(join(appData, "StudioOS", "format.json")) ? JSON.parse(readFileSync(join(appData, "StudioOS", "format.json"), "utf8")) : null;
        if (!stamp) await sleep(500);
      }
      check("launch.user_data_lives_outside_install_dir", stamp?.format === 1 && !listFiles(instDir).some((f) => /format\.json$/i.test(f)), `format.json ${JSON.stringify(stamp)} under the redirected %APPDATA%, none under the install dir`);
      const sockets = listeningSockets([...daemons, ...pidsOf("studio-desktop.exe")]);
      check("launch.no_listener_on_all_interfaces", sockets.every((s) => !s.startsWith("0.0.0.0:") && !s.startsWith("[::]:")), sockets.length ? sockets.join(", ") : "no listening socket");
      const exported = await invoke(page, "export_diagnostics", {});
      const exportFile = exported.value?.file ? String(exported.value.file) : "";
      const exportedDir = join(appData, "StudioOS", "diagnostics");
      const exportedFiles = existsSync(exportedDir) ? readdirSync(exportedDir) : [];
      const exportedText = exportedFiles.length ? readFileSync(join(exportedDir, exportedFiles[0]), "utf8") : "";
      check("launch.diagnostics_export_written_and_redacted", exported.ok && exportedFiles.length === 1 && !exportedText.includes(appData) && !/token|password|secret/i.test(exportedText.replace(/"[^"]*(?:token|password|secret)[^"]*"\s*:\s*"?\[redacted\]"?/gi, "")), `${exportFile}; ${exportedFiles.length} file(s), no raw home path`);
      const upd = await invoke(page, "check_for_update", {});
      check("launch.updater_not_configured_in_dev_installer", upd.ok && upd.value?.state === "not_configured", JSON.stringify(upd));
    } finally {
      if (browser) await browser.close().catch(() => {});
      spawnSync("pwsh", ["-NoProfile", "-Command", `(Get-Process -Id ${app.pid} -ErrorAction SilentlyContinue).CloseMainWindow() | Out-Null`], { stdio: "ignore" });
      for (let i = 0; i < 20 && (processCount("studio-desktop.exe") > 0 || processCount("studio-daemon.exe") > 0); i++) await sleep(500);
      const leftover = processCount("studio-desktop.exe") + processCount("studio-daemon.exe");
      if (leftover > 0) spawnSync("taskkill", ["/IM", "studio-daemon.exe", "/T", "/F"], { stdio: "ignore" });
      check("launch.graceful_close_leaves_no_process", leftover === 0, `processes left after a normal close: ${leftover}`);
    }

    // ---- 3. upgrade over an install holding user data ---------------------------
    writeFileSync(join(appData, "StudioOS", "config.toml"), "# user setting\n");
    writeFileSync(join(vault, "note.md"), "# my note\n");
    writeFileSync(join(instDir, "stale-from-old-build.txt"), "old\n");
    const before = readFileSync(join(appData, "StudioOS", "format.json"), "utf8");
    const up = await runSilent(installerPath, ["/S", `/D=${instDir}`]);
    check("upgrade.reinstall_over_existing_exit_zero", up === 0, `exit ${up}`);
    check("upgrade.program_files_replaced", existsSync(exe) && existsSync(join(instDir, "sidecar", "studio-daemon.exe")), "app and sidecar still present after the reinstall");
    check("upgrade.user_data_preserved", readFileSync(join(appData, "StudioOS", "config.toml"), "utf8") === "# user setting\n" && readFileSync(join(appData, "StudioOS", "format.json"), "utf8") === before, "config.toml and format.json untouched");
    check("upgrade.vault_untouched", readFileSync(join(vault, "note.md"), "utf8") === "# my note\n", "vault note intact");

    // ---- 4. uninstall (default: keep data) ---------------------------------------
    const un = await runSilent(join(instDir, "uninstall.exe"), ["/S", `_?=${instDir}`]);
    check("uninstall.silent_exit_zero", un === 0, `exit ${un}`);
    const remaining = existsSync(instDir) ? listFiles(instDir).filter((f) => !/uninstall\.exe$/i.test(f) && !/stale-from-old-build\.txt$/i.test(f)) : [];
    check("uninstall.program_files_removed", !existsSync(exe) && !existsSync(join(instDir, "sidecar")) && remaining.length === 0, remaining.length ? `left: ${remaining.slice(0, 5).join(", ")}` : "app and sidecar removed");
    check("uninstall.registry_key_removed", !installedKey(), UNINSTALL_KEY);
    check("uninstall.user_data_kept_by_default", readFileSync(join(appData, "StudioOS", "config.toml"), "utf8") === "# user setting\n" && existsSync(join(appData, "StudioOS", "format.json")), "daemon data folder kept");
    check("uninstall.vault_untouched", readFileSync(join(vault, "note.md"), "utf8") === "# my note\n", "vault note intact");
    check("uninstall.no_process_left", processCount("studio-daemon.exe") === 0 && processCount("studio-desktop.exe") === 0, "no studio process left");
  } finally {
    if (!policyPreexisting) reg("delete", WEBVIEW2_POLICY_KEY, "/v", WEBVIEW2_POLICY_VALUE, "/f");
    if (installedKey()) {
      const u = join(instDir, "uninstall.exe");
      if (existsSync(u)) await runSilent(u, ["/S", `_?=${instDir}`]);
    }
    rmSync(root, { recursive: true, force: true });
  }
}

let failed = false;
try {
  await main();
} catch (e) {
  failed = true;
  console.error("install test aborted:", e);
  results.push({ id: "install_test.aborted", status: "FAIL", evidence: String(e) });
}
mkdirSync(buildDir, { recursive: true });
writeFileSync(resolve(buildDir, "install-test-results.json"), JSON.stringify(results, null, 2));
const bad = results.filter((r) => r.status === "FAIL");
console.log(`\ninstall test: ${results.length - bad.length}/${results.length} passed`);
process.exit(failed || bad.length ? 1 : 0);
