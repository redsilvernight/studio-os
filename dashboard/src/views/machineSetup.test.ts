// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import type { BridgeAnswer } from "../platform/contracts";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import { applySetup, hasPendingWork, previewSetup, setupErrorMessage, type SetupPlan } from "../setupApi";
import { renderIntegrations } from "./integrations";
import { setupSectionHtml } from "./machineSetup";

const WS = "11111111-2222-4333-8444-555555555555";
const flush = async (): Promise<void> => {
  for (let i = 0; i < 12; i += 1) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
};
const ok = (payload: unknown): BridgeAnswer => ({ ok: true, response: { payload } }) as unknown as BridgeAnswer;
const refused = (code: string): BridgeAnswer =>
  ({ ok: false, error: { code, component: "daemon", message: "x", retryable: false, correlation_id: null, details: {} } }) as unknown as BridgeAnswer;

const hook = (item_id: string, state: "missing" | "current" | "differs", extra: Record<string, unknown> = {}) => ({
  item_id,
  kind: "hook",
  harness: item_id.split(":")[1] ?? "x",
  state,
  managed: state !== "differs",
  lines_added: 0,
  lines_removed: 0,
  diff: "",
  diff_truncated: false,
  needs_registration: false,
  ...extra,
});

const makePlan = (over: Record<string, unknown> = {}): SetupPlan =>
  ({
    plan_id: "setup-1",
    plan_hash: "b".repeat(64),
    created_at: "2026-10-04T10:00:00Z",
    expires_at: "2026-10-04T10:10:00Z",
    requires_confirmation: true,
    harnesses: [
      { harness: "claude-code", detected: true },
      { harness: "opencode", detected: false },
    ],
    hooks: [
      hook("hook:claude-code", "missing", { needs_registration: true }),
      hook("guard", "differs", { lines_added: 2, lines_removed: 1, diff: "--- a/guard\n+++ b/guard\n-old\n+new", managed: false }),
    ],
    skills: { state: "checked", current: 1, missing: 2, outdated: 0, locally_modified: 1 },
    adapters: { state: "checked", workspaces: 1, checked: 4, drifted: 0 },
    ...over,
  }) as SetupPlan;

interface Rig {
  calls: { command: string; payload: Record<string, unknown> }[];
  plan: SetupPlan;
  onApply: () => BridgeAnswer;
}

function rig(plan: SetupPlan = makePlan()) {
  const state: Rig = {
    calls: [],
    plan,
    onApply: () =>
      ok({
        plan_id: "setup-1",
        hooks: [
          { item_id: "hook:claude-code", outcome: "written", backed_up: false },
          { item_id: "guard", outcome: "written", backed_up: true },
        ],
        skills: { outcome: "synced", written: 2, left_modified: 1 },
        backups_created: true,
      }),
  };
  const platform = fakeDesktop({
    request: (async (command: string, payload: Record<string, unknown> = {}) => {
      if (command !== "skills.check" && command !== "launch.get_settings") state.calls.push({ command, payload });
      if (command === "harness.detect") return ok({ harnesses: [] });
      if (command === "setup.plan") return ok(state.plan);
      if (command === "setup.apply") return state.onApply();
      return refused("not_supported");
    }) as never,
  });
  return { platform, state };
}

async function mount(platform: ReturnType<typeof fakeDesktop>) {
  const root = document.createElement("main");
  document.body.append(root);
  await renderIntegrations(root, WS, platform);
  return root;
}
const click = async (root: HTMLElement, selector: string): Promise<void> => {
  root.querySelector<HTMLElement>(selector)?.click();
  await flush();
};
const setup = (state: Rig) => state.calls.filter((c) => c.command.startsWith("setup."));

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("« Configurer ce poste » — aperçu", () => {
  it("n'écrit rien avant la confirmation et montre chaque étape", async () => {
    const { platform, state } = rig();
    const root = await mount(platform);
    expect(setup(state)).toEqual([]);
    await click(root, "[data-action=preview-setup]");
    expect(setup(state).map((c) => c.command)).toEqual(["setup.plan"]);
    expect(root.querySelector("[data-testid=setup-harnesses]")?.textContent).toContain("claude-code");
    expect(root.querySelector("[data-testid=setup-harnesses]")?.textContent).not.toContain("opencode");
    expect(root.querySelector("[data-testid=needs-registration]")?.textContent).toContain("À enregistrer dans les réglages de l'outil (étape manuelle)");
    expect(root.querySelector("[data-testid=setup-skills]")?.textContent).toContain("jamais écrasées");
    expect(root.querySelector("[data-testid=setup-adapters]")?.textContent).toContain("Lecture seule");
    expect(root.querySelector("[data-testid=setup-adapters]")?.textContent).not.toContain("commande de développement");
    expect(root.querySelector("[data-testid=setup-mcp]")?.textContent).toContain("jamais déclaré configuré");
  });

  it("nomme les fichiers en clair, sans jargon", async () => {
    const plan = makePlan({
      hooks: [
        hook("hook:claude-code", "missing", { needs_registration: true }),
        hook("guard", "current", { kind: "guard" }),
        hook("plugin:opencode", "current", { kind: "plugin" }),
      ],
    });
    const text = setupSectionHtml({ plan });
    expect(text).not.toContain("Garde Git");
    expect(text).not.toContain("Extension de session");
    expect(text).toContain("Script de démarrage de session (claude-code)");
    expect(text).toContain("Script de protection Git (x)");
    expect(text).toContain("Extension de l'outil (opencode)");
  });

  it("renvoie aux cartes de harnais pour le MCP au lieu d'y répéter leurs badges", () => {
    const html = setupSectionHtml({ plan: makePlan() }, [
      { adapter_id: "claude-code", display_name: "Claude Code", state: "detected" } as never,
      { adapter_id: "opencode", display_name: "OpenCode", state: "configured" } as never,
    ]);
    const mcp = html.slice(html.indexOf('data-testid="setup-mcp"'));
    expect(mcp).not.toContain("ds-badge");
    expect(mcp).not.toContain("Claude Code");
    expect(mcp).toContain("2 outils IA chargés");
    expect(mcp).toContain("carte ci-dessous");
    expect(mcp).toContain("jamais déclaré configuré");
  });

  it("replie chaque diff dans un détail et annonce le nombre de lignes", async () => {
    const { platform } = rig();
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    const details = root.querySelector<HTMLDetailsElement>("details.setup-diff")!;
    expect(details.querySelector("summary")?.textContent).toBe("Voir les 3 lignes modifiées");
    expect(details.querySelector("[data-testid=setup-diff]")?.textContent).toContain("+new");
    expect(details.hasAttribute("open")).toBe(false);
  });

  it("résume avant la confirmation ce qui restera inchangé", async () => {
    const { platform } = rig();
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    const plan = root.querySelector("[data-testid=setup-plan]")!;
    expect(plan.querySelector("[data-testid=setup-summary]")?.textContent).toContain("1 fichier restera inchangé");
    expect(plan.innerHTML.indexOf("setup-summary")).toBeLessThan(plan.innerHTML.indexOf('data-action="confirm-setup"'));
  });

  it("n'annonce plus de fichier à laisser tel quel quand la case est cochée", () => {
    expect(setupSectionHtml({ plan: makePlan() })).toContain("1 fichier restera inchangé");
    expect(setupSectionHtml({ plan: makePlan(), overwrite: ["guard"] })).not.toContain("restera inchangé");
  });

  it("montre le diff d'un fichier divergent, case de remplacement décochée par défaut", async () => {
    const { platform } = rig();
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    expect(root.querySelector("[data-testid=setup-diff]")?.textContent).toContain("+new");
    expect(root.querySelector("[data-setup-item=guard]")?.textContent).toContain("Fichier qui n'est pas géré par Studi'OS");
    const box = root.querySelector<HTMLInputElement>("[data-setup-overwrite=guard]");
    expect(box?.checked).toBe(false);
    expect(box?.closest("label")?.textContent).toContain("Remplacer ce fichier par la version gérée");
    expect(root.querySelector("[data-setup-overwrite=hook\\:claude-code]")).toBeNull();
  });

  it("explique en clair une copie gérée qui s'écarte de la version actuelle", () => {
    const html = setupSectionHtml({
      plan: makePlan({ hooks: [hook("guard", "differs", { managed: true, lines_added: 1, lines_removed: 1, diff: "+x\n-y" })] }),
    });
    expect(html).toContain("Copie gérée différente de la version actuelle (obsolète ou modifiée)");
    expect(html).toContain("Voir les 2 lignes modifiées");
  });

  it("échappe le contenu d'un diff étranger", () => {
    const html = setupSectionHtml({
      plan: makePlan({ hooks: [hook("guard", "differs", { diff: "<img src=x onerror=alert(1)>", managed: false })] }),
    });
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  it("dit que tout est déjà configuré et n'offre pas d'application", async () => {
    const plan = makePlan({
      hooks: [hook("hook:claude-code", "current")],
      skills: { state: "checked", current: 3, missing: 0, outdated: 0, locally_modified: 0 },
    });
    const { platform } = rig(plan);
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    expect(root.querySelector("[data-testid=setup-nothing]")?.textContent).toContain("rien à écrire");
    expect(root.querySelector("[data-action=confirm-setup]")).toBeNull();
    expect(hasPendingWork(plan)).toBe(false);
  });

  it("annuler referme l'aperçu sans rien envoyer d'autre", async () => {
    const { platform, state } = rig();
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    await click(root, "[data-action=cancel-setup]");
    expect(root.querySelector("[data-testid=setup-plan]")).toBeNull();
    expect(setup(state).map((c) => c.command)).toEqual(["setup.plan"]);
  });

  it("signale une skills indisponible sans proposer de synchronisation", async () => {
    const plan = makePlan({ skills: { state: "unavailable", reason: "not_signed_in" } });
    const { platform } = rig(plan);
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    expect(root.querySelector("[data-testid=setup-skills]")?.textContent).toContain("pas connecté");
    expect(root.querySelector("[data-setup-skills]")).toBeNull();
  });
});

describe("« Configurer ce poste » — application", () => {
  it("lie la confirmation à l'aperçu et ne remplace que les fichiers cochés", async () => {
    const { platform, state } = rig();
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    root.querySelector<HTMLInputElement>("[data-setup-overwrite=guard]")!.checked = true;
    await click(root, "[data-action=confirm-setup]");
    const apply = setup(state).find((c) => c.command === "setup.apply")!;
    expect(apply.payload).toEqual({
      plan_id: "setup-1",
      plan_hash: "b".repeat(64),
      confirmed: true,
      overwrite_items: ["guard"],
      sync_skills: true,
    });
  });

  it("sans case cochée, aucun remplacement n'est demandé", async () => {
    const { platform, state } = rig();
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    await click(root, "[data-action=confirm-setup]");
    const apply = setup(state).find((c) => c.command === "setup.apply")!;
    expect(apply.payload["overwrite_items"]).toEqual([]);
  });

  it("n'affiche comme écrit que le rapport de l'assistant", async () => {
    const { platform, state } = rig();
    state.onApply = () =>
      ok({
        plan_id: "setup-1",
        hooks: [
          { item_id: "hook:claude-code", outcome: "failed", backed_up: false },
          { item_id: "guard", outcome: "skipped", backed_up: false },
        ],
        skills: { outcome: "unavailable", written: 0, left_modified: 0 },
        backups_created: false,
      });
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    await click(root, "[data-action=confirm-setup]");
    const result = root.querySelector("[data-testid=setup-result]")!;
    expect(result.querySelector("[data-setup-result=hook\\:claude-code]")?.getAttribute("data-outcome")).toBe("failed");
    expect(result.textContent).not.toContain("Écrit et relu</span>");
    expect(result.querySelector("[data-setup-result=guard]")?.textContent).toContain("Laissé tel quel");
    expect(root.querySelector("[data-action=confirm-setup]")).toBeNull();
  });

  it("rapporte écriture, sauvegarde et skills synchronisées", async () => {
    const { platform } = rig();
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    await click(root, "[data-action=confirm-setup]");
    const result = root.querySelector("[data-testid=setup-result]")!;
    expect(result.querySelector("[data-setup-result=guard]")?.textContent).toContain("sauvegarde créée");
    expect(result.querySelector("[data-testid=setup-result-skills]")?.textContent).toContain("2 fichier(s) écrit(s)");
    expect(result.textContent).toContain("1 modifiée(s) localement");
  });

  it("un aperçu expiré revient au bouton, avec un message", async () => {
    const { platform, state } = rig();
    state.onApply = () => refused("plan_expired");
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    await click(root, "[data-action=confirm-setup]");
    expect(root.querySelector("[data-testid=setup-error]")?.textContent).toContain("expiré");
    expect(root.querySelector("[data-testid=setup-plan]")).toBeNull();
    expect(root.querySelector("[data-action=preview-setup]")).not.toBeNull();
  });

  it("un échec technique garde l'aperçu et ne prétend rien d'écrit", async () => {
    const { platform, state } = rig();
    state.onApply = () => refused("internal_error");
    const root = await mount(platform);
    await click(root, "[data-action=preview-setup]");
    await click(root, "[data-action=confirm-setup]");
    expect(root.querySelector("[data-testid=setup-error]")?.textContent).toContain("Aucune modification n'a été confirmée");
    expect(root.querySelector("[data-testid=setup-result]")).toBeNull();
    expect(root.querySelector("[data-testid=setup-plan]")).not.toBeNull();
  });
});

describe("setupApi", () => {
  it("envoie des commandes setup.* et traduit les refus", async () => {
    const { platform, state } = rig();
    const plan = await previewSetup(platform);
    expect(plan.ok).toBe(true);
    if (plan.ok) {
      await applySetup(platform, plan.value, ["guard"], false);
    }
    expect(setup(state).map((c) => c.command)).toEqual(["setup.plan", "setup.apply"]);
    expect(setupErrorMessage({ code: "capability_missing", component: "daemon", message: "x", retryable: false } as never)).toContain("Desktop");
    expect(setupErrorMessage(null)).toContain("Aucune modification");
  });
});
