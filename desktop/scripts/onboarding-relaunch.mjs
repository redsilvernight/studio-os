// P12 proof for the post-completion relaunch path. Reuses only a disposable
// onboarding profile previously created by onboarding-walkthrough.mjs.

import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";
import { desktopDir } from "./lib.mjs";

const profileRoot = process.env.STUDIO_ONBOARDING_PROFILE;
if (!profileRoot) throw new Error("STUDIO_ONBOARDING_PROFILE is required");

const exe = process.env.STUDIO_ONBOARDING_EXE
  ? resolve(process.env.STUDIO_ONBOARDING_EXE)
  : resolve(desktopDir, "src-tauri", "target", "release", "studio-desktop.exe");
const port = Number(process.env.STUDIO_ONBOARDING_CDP_PORT ?? 9340);
const origin = "http://tauri.localhost";
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

async function attach() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
      const page = browser.contexts()[0]?.pages().find((candidate) => candidate.url().startsWith(origin));
      if (page) return { browser, page };
      await browser.close();
    } catch {
      // The WebView debug endpoint is not ready yet.
    }
    await sleep(500);
  }
  throw new Error("could not attach to the relaunched Desktop WebView");
}

const bridge = (page, command, payload) =>
  page.evaluate(
    async ({ command, payload }) => {
      const messageId = crypto.randomUUID();
      const answer = await window.__TAURI__.core.invoke("bridge_request", {
        request: {
          kind: "request",
          protocol: "studio.local/v1",
          message_id: messageId,
          correlation_id: messageId,
          sent_at: new Date().toISOString(),
          command,
          payload,
        },
      });
      return answer.error ? { ok: false, error: answer.error } : { ok: true, value: answer.payload };
    },
    { command, payload },
  );

async function main() {
  if (!existsSync(exe)) throw new Error(`missing executable: ${exe}`);
  const app = spawn(exe, [], {
    env: {
      ...process.env,
      APPDATA: join(profileRoot, "appdata"),
      LOCALAPPDATA: join(profileRoot, "localappdata"),
      WEBVIEW2_USER_DATA_FOLDER: join(profileRoot, "webview2"),
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}`,
    },
    stdio: "ignore",
  });
  let browser;
  try {
    let attached = await attach();
    browser = attached.browser;
    let page = attached.page;
    if (process.env.STUDIO_ONBOARDING_SEED_COMPLETED === "1") {
      await page.evaluate(() => {
        localStorage.setItem(
          "studio-os.onboarding.v1",
          JSON.stringify({
            schema: 1,
            status: "completed",
            current: "termine",
            projectId: "bde05502-46aa-4c52-82e1-24fb0f7085e3",
            projectName: "Desktop gate",
            projectSlug: "desktop-gate",
            workspaceId: "738e442f-afaa-466f-975e-c5fb6bec61cf",
            folderName: "workspace",
            completedAt: new Date().toISOString(),
          }),
        );
      });
      await page
        .evaluate(() => window.__TAURI__.core.invoke("restart_desktop"))
        .catch(() => undefined);
      await browser.close().catch(() => undefined);
      await sleep(3000);
      attached = await attach();
      browser = attached.browser;
      page = attached.page;
    }
    await page
      .waitForFunction(() => location.hash !== "#/bienvenue", null, { timeout: 30_000 })
      .catch(() => undefined);
    const state = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("studio-os.onboarding.v1") ?? "{}"),
    );
    const text = await page.locator("body").innerText();
    if (state.status !== "completed" || !state.workspaceId) {
      throw new Error(`completion state missing: ${JSON.stringify(state)}`);
    }
    if (text.includes("Bienvenue dans Studi'OS") || page.url().endsWith("#/bienvenue")) {
      throw new Error(`onboarding reappeared after completion: ${page.url()}`);
    }
    const workspace = await bridge(page, "workspace.get_config", { workspace_id: state.workspaceId });
    const knowledge = await bridge(page, "knowledge.status", { workspace_id: state.workspaceId });
    if (!workspace.ok || workspace.value?.workspace_id !== state.workspaceId) {
      throw new Error(`workspace identity not preserved: ${JSON.stringify(workspace)}`);
    }
    if (!knowledge.ok || knowledge.value?.state !== "ready") {
      throw new Error(`Knowledge is not ready after relaunch: ${JSON.stringify(knowledge)}`);
    }
    console.log(`PASS onboarding relaunch skips wizard: ${page.url()}`);
    console.log(`PASS workspace and Knowledge preserved: ${state.workspaceId}`);
  } finally {
    await browser?.close().catch(() => undefined);
    spawnSync("taskkill", ["/PID", String(app.pid), "/T", "/F"], { stdio: "ignore" });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
