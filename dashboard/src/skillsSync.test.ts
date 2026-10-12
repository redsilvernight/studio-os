// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BridgeAnswer } from "./platform/contracts";
import type { SkillsSyncStatus, SkillsPreviewResult } from "./skillsApi";
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

const previewResult = (): SkillsPreviewResult => ({
  skills: ["delegate", "graphify"].map((stable_key, index) => ({
    stable_key, version: 3, preview_hash: String(index + 1).repeat(64), diff: "--- local\n+++ library\n@@ -1 +1 @@\n- a\n+ b",
    targets: [{ harness: "agents", state: "locally_modified" }, { harness: "assistant", state: "current" }],
  })), current: 2, missing: 0, outdated: 0, locally_modified: 2, diff: "- a\n+ b", checked_at: "2026-10-05T10:00:00Z",
});

function platformWith(current: () => SkillsSyncStatus | "error", calls: string[] = [], plan = previewResult()) {
  return fakeDesktop({
    request: async (command: string, payload: Record<string, unknown>) => {
      calls.push(`${command}:${JSON.stringify(payload)}`);
      if (command === "skills.status") {
        const value = current();
        return value === "error" ? ({ ok: false, error: { code: "internal" } } as unknown as BridgeAnswer) : answer(value);
      }
      if (command === "skills.preview") return answer(plan);
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
    expect(document.querySelectorAll(".ds-toast")).toHaveLength(0);
    expect(document.getElementById("skills-sync-dialog-body")?.textContent).toContain("Ajoutés");
    resetSkillsSyncForTests();
    document.getElementById("skills-sync")?.remove();
    mountSkillsSync(platform);
    await flush();
    expect(document.querySelectorAll(".ds-toast")).toHaveLength(0);
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

  it("identifies skills and keeps comparisons collapsed until requested", async () => {
    const calls: string[] = [];
    mountSkillsSync(platformWith(() => status({ state: "conflicts", conflicts: ["k"] }), calls));
    await flush();
    document.getElementById("skills-sync")?.click();
    await flush();
    const row = document.querySelector<HTMLElement>('[data-skill="delegate"]');
    expect(row?.textContent).toContain(".agents/skills/delegate/SKILL.md");
    expect(row?.querySelector("details")?.open).toBe(false);
    row?.querySelector<HTMLElement>("summary")?.click();
    expect(document.querySelector(".skills-sync-diff")?.textContent).toContain("+ b");
    expect(calls.some((call) => call.startsWith("skills.apply"))).toBe(false);
  });

  it("applies only explicit per-skill choices after reviewing the replacements", async () => {
    const calls: string[] = [];
    mountSkillsSync(platformWith(() => status({ state: "conflicts", conflicts: ["k"] }), calls));
    await flush();
    document.getElementById("skills-sync")?.click();
    await flush();
    const apply = document.querySelector<HTMLButtonElement>('[data-skills-action="apply"]');
    expect(apply?.disabled).toBe(true);
    const choice = document.querySelector<HTMLSelectElement>('[data-skills-choice="delegate"]')!;
    choice.value = "library";
    choice.dispatchEvent(new Event("change"));
    expect(apply?.textContent).toBe("Appliquer 1 choix");
    apply?.click();
    expect(calls.some((call) => call.startsWith("skills.apply"))).toBe(false);
    expect(document.querySelector(".skills-sync-confirmation")?.textContent).toContain("delegate");
    expect(document.querySelector(".skills-sync-confirmation")?.textContent).not.toContain("graphify");
    document.querySelector<HTMLElement>('[data-skills-action="confirm"]')?.click();
    await flush();
    expect(calls).toContain('skills.apply:{"confirm":true,"resolutions":[{"stable_key":"delegate","choice":"library","preview_hash":"' + "1".repeat(64) + '"}]}');
    expect(calls.filter((call) => call.startsWith("skills.apply"))).toHaveLength(1);
  });

  it("keeps local choices without authorizing a global overwrite", async () => {
    const calls: string[] = [];
    mountSkillsSync(platformWith(() => status({ state: "conflicts", conflicts: ["k"] }), calls));
    await flush();
    document.getElementById("skills-sync")?.click();
    await flush();
    const choice = document.querySelector<HTMLSelectElement>('[data-skills-choice="delegate"]')!;
    choice.value = "local";
    choice.dispatchEvent(new Event("change"));
    document.querySelector<HTMLElement>('[data-skills-action="apply"]')?.click();
    expect(document.querySelector('[data-skills-action="confirm"]')?.textContent).toBe("Confirmer les choix");
    document.querySelector<HTMLElement>('[data-skills-action="confirm"]')?.click();
    await flush();
    expect(calls.find((call) => call.startsWith("skills.apply"))).toContain('"choice":"local"');
    expect(calls.find((call) => call.startsWith("skills.apply"))).not.toContain('"overwrite"');
    expect(document.querySelector("#skills-sync-dialog-body")?.textContent).toContain("restent personnalisées");
  });

  it("preserves the selection and keyboard focus through an idle status poll", async () => {
    vi.useFakeTimers();
    mountSkillsSync(platformWith(() => status({ state: "conflicts", conflicts: ["k"] })));
    await vi.advanceTimersByTimeAsync(0);
    document.getElementById("skills-sync")?.click();
    await vi.advanceTimersByTimeAsync(0);
    const choice = document.querySelector<HTMLSelectElement>('[data-skills-choice="delegate"]')!;
    choice.value = "library";
    choice.dispatchEvent(new Event("change"));
    choice.focus();
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.querySelector('[data-skills-choice="delegate"]')).toBe(choice);
    expect(choice.value).toBe("library");
    expect(document.activeElement).toBe(choice);
  });

  it("does not enable targeted writes against an older daemon preview", async () => {
    const plan = previewResult();
    for (const entry of plan.skills ?? []) delete entry.preview_hash;
    mountSkillsSync(platformWith(() => status({ state: "conflicts", conflicts: ["k"] }), [], plan));
    await flush();
    document.getElementById("skills-sync")?.click();
    await flush();
    expect(document.querySelector('[data-skills-action="apply"]')).toBeNull();
    expect(document.querySelector<HTMLSelectElement>("[data-skills-choice]")?.disabled).toBe(true);
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("Mettez à jour");
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
