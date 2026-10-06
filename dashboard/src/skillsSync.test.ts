// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BridgeAnswer } from "./platform/contracts";
import type { SkillsSyncStatus } from "./skillsApi";
import { mountSkillsSync, resetSkillsSyncForTests, skillsDetailHtml, skillsIndicatorHtml } from "./skillsSync";
import { fakeDesktop } from "./testSupport/fakeDesktop";
import { webPlatform } from "./platform/web";

const flush = async (): Promise<void> => {
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
};

const status = (over: Partial<SkillsSyncStatus> = {}): SkillsSyncStatus => ({
  state: "up_to_date",
  last_check: "2026-10-05T10:00:00Z",
  last_successful_sync: "2026-10-05T10:00:00Z",
  auto_sync_enabled: true,
  ...over,
});

const answer = (payload: unknown): BridgeAnswer => ({ ok: true, response: { payload } }) as unknown as BridgeAnswer;

function platformWith(current: () => SkillsSyncStatus | "error", calls: string[] = []) {
  return fakeDesktop({
    request: async (command: string, payload: Record<string, unknown>) => {
      calls.push(`${command}:${JSON.stringify(payload)}`);
      if (command === "skills.status") {
        const value = current();
        return value === "error" ? ({ ok: false, error: { code: "internal" } } as unknown as BridgeAnswer) : answer(value);
      }
      if (command === "skills.preview") return answer({ diff: "- a\n+ b" });
      if (command === "skills.apply") return answer({});
      return answer({});
    },
  } as never);
}

beforeEach(() => {
  localStorage.clear();
  document.body.innerHTML =
    '<div id="ds-toast-region"></div><div class="app-me"><span id="connection-status"></span></div>';
});
afterEach(() => {
  resetSkillsSyncForTests();
  vi.useRealTimers();
});

describe("skills sync indicator", () => {
  it("renders a fixed label per state and never the daemon text", () => {
    const html = skillsDetailHtml(status({ state: "not_synced", error_message: "C:\\Users\\me\\secret" }), false);
    expect(html).not.toContain("secret");
    expect(html).toContain("hors ligne");
    expect(skillsIndicatorHtml(status({ state: "conflicts", conflicts: ["a", "b"] }))).toContain("conflits à résoudre (2)");
    expect(skillsIndicatorHtml(null, true)).toContain("état indisponible");
  });

  it("exposes the full pill label in the tooltip (no truncated « Skil… »)", () => {
    for (const html of [
      skillsIndicatorHtml(status({ state: "up_to_date" })),
      skillsIndicatorHtml(status({ state: "conflicts", conflicts: ["a"] })),
      skillsIndicatorHtml(null, true),
    ]) {
      const label = html.match(/<span class="app-connection-label">(.*?)<\/span>/)?.[1] ?? "";
      expect(label.length).toBeGreaterThan(0);
      expect(html).toContain(`title="${label}"`);
    }
  });

  it("does nothing on the web", async () => {
    mountSkillsSync(webPlatform);
    await flush();
    expect(document.getElementById("skills-sync")).toBeNull();
  });

  it("shows the state, notifies once for an update and opens the detail", async () => {
    const platform = platformWith(() => status({ state: "updated", added: ["x"], updated: ["y"] }));
    mountSkillsSync(platform);
    await flush();
    const button = document.getElementById("skills-sync");
    expect(button?.dataset["state"]).toBe("updated");
    expect(document.querySelectorAll(".ds-toast")).toHaveLength(1);
    button?.click();
    expect(document.getElementById("skills-sync-dialog")?.hasAttribute("hidden")).toBe(false);
    expect(document.getElementById("skills-sync-dialog-body")?.textContent).toContain("Ajoutés");
    resetSkillsSyncForTests();
    document.getElementById("skills-sync")?.remove();
    mountSkillsSync(platform);
    await flush();
    expect(document.querySelectorAll(".ds-toast")).toHaveLength(1);
  });

  it("stays silent when everything is up to date", async () => {
    mountSkillsSync(platformWith(() => status()));
    await flush();
    expect(document.getElementById("skills-sync")?.dataset["state"]).toBe("up_to_date");
    expect(document.querySelectorAll(".ds-toast")).toHaveLength(0);
  });

  it("falls back to an unavailable indicator when skills.status fails", async () => {
    mountSkillsSync(platformWith(() => "error"));
    await flush();
    expect(document.getElementById("skills-sync")?.dataset["state"]).toBe("unavailable");
  });

  it("previews the diff and retries with explicit confirmation", async () => {
    const calls: string[] = [];
    mountSkillsSync(platformWith(() => status({ state: "conflicts", conflicts: ["k"] }), calls));
    await flush();
    document.getElementById("skills-sync")?.click();
    document.querySelector<HTMLElement>('[data-skills-action="diff"]')?.click();
    await flush();
    expect(document.querySelector(".skills-sync-diff")?.textContent).toContain("+ b");
    document.querySelector<HTMLElement>('[data-skills-action="retry"]')?.click();
    await flush();
    expect(calls).toContain('skills.apply:{"confirm":true}');
  });

  it("overwrites conflicts only after a second confirmation", async () => {
    const calls: string[] = [];
    mountSkillsSync(platformWith(() => status({ state: "conflicts", conflicts: ["k"] }), calls));
    await flush();
    document.getElementById("skills-sync")?.click();
    const confirm = document.querySelector<HTMLElement>('[data-skills-action="overwrite-confirm"]');
    expect(confirm?.hasAttribute("hidden")).toBe(true);
    document.querySelector<HTMLElement>('[data-skills-action="overwrite"]')?.click();
    expect(calls.some((call) => call.startsWith("skills.apply"))).toBe(false);
    confirm?.click();
    await flush();
    expect(calls).toContain('skills.apply:{"confirm":true,"overwrite":true}');
  });

  it("toggles the automatic synchronization", async () => {
    const calls: string[] = [];
    mountSkillsSync(platformWith(() => status({ auto_sync_enabled: true }), calls));
    await flush();
    document.getElementById("skills-sync")?.click();
    document.querySelector<HTMLElement>('[data-skills-action="toggle"]')?.click();
    await flush();
    expect(calls).toContain('skills.configure:{"auto_sync":false}');
  });
});
