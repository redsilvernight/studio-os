/**
 * Intégration IA — onglet du workspace. DOM-free : assertions sur les chaînes
 * produites. L'UI n'affirme que ce que le poste a rapporté ; l'action reste
 * une commande locale à copier.
 */
import { describe, expect, it } from "vitest";
import type { AiIntegrationStatus, ReportedMachineIntegration } from "../aiIntegrationApi";
import {
  RESYNC_COMMAND,
  aiIntegrationHtml,
  desiredHtml,
  machineItemHtml,
  machineVerdict,
  resyncInstructionHtml,
} from "./aiIntegration";

const MID = "11111111-2222-4333-8444-555555555555";

function machine(overrides: Partial<ReportedMachineIntegration>): ReportedMachineIntegration {
  return {
    machine_id: MID,
    display_name: "flo-laptop",
    status: "online",
    freshness: "fresh",
    reported_at: "2026-09-30T21:00:00Z",
    project_registered: true,
    harnesses: [],
    ...overrides,
  };
}

const inSync = (value: boolean) => ({
  checked_at: "2026-09-30T20:00:00Z",
  in_sync: value,
  summary: { absent: 0, obsolete: 0, modified: 0, incompatible: 0, up_to_date: 7 },
});

describe("machineVerdict", () => {
  it("jamais rapporté : rien n'est supposé, action proposée", () => {
    const v = machineVerdict(machine({ freshness: "never_reported", reported_at: null, project_registered: null }));
    expect(v.label).toBe("Pas encore configuré");
    expect(v.needsAction).toBe(true);
  });

  it("projet non enregistré, bundle en dérive et rapport ancien demandent une action", () => {
    expect(machineVerdict(machine({ project_registered: false })).label).toBe("Projet non enregistré");
    expect(machineVerdict(machine({ bootstrap: inSync(false) })).label).toBe("À mettre à jour");
    expect(machineVerdict(machine({ freshness: "stale" })).label).toBe("Rapport ancien");
  });

  it("à jour seulement si le poste l'a rapporté", () => {
    expect(machineVerdict(machine({ bootstrap: inSync(true) }))).toMatchObject({ label: "À jour", needsAction: false });
    expect(machineVerdict(machine({})).label).toBe("Rapport reçu");
  });
});

describe("desiredHtml", () => {
  it("résume en une ligne, sans liste ni empreinte", () => {
    const html = desiredHtml(
      { plan_hash: "abcdef0123456789", agent_keys: ["a", "b"], artifact_counts: { rule: 3, skill: 2 } },
      null,
    );
    expect(html).toContain("2 agents");
    expect(html).toContain("5 éléments");
    expect(html).not.toContain("abcdef01");
    expect(html).not.toContain("<ul");
  });

  it("affiche l'erreur publique, ou rien", () => {
    expect(desiredHtml(null, "bootstrap_plan_unavailable")).toContain("bootstrap_plan_unavailable");
    expect(desiredHtml(null, null)).toBe("");
  });
});

describe("resyncInstructionHtml", () => {
  it("donne la commande locale, masquée par défaut", () => {
    const html = resyncInstructionHtml(machine({}));
    expect(html).toContain(RESYNC_COMMAND);
    expect(html).toContain("sur le poste flo-laptop");
    expect(html).toContain("n'écrit rien sur le poste");
    expect(html).toContain("hidden");
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });
});

describe("machineItemHtml", () => {
  it("poste à jour : verdict et outils détectés, pas de bouton", () => {
    const html = machineItemHtml(
      machine({
        bootstrap: inSync(true),
        harnesses: [
          { harness_id: "claude-code", version: "1.2.3", detected: true, configured: true },
          { harness_id: "opencode", detected: false, configured: false },
        ],
      }),
    );
    expect(html).toContain("En ligne");
    expect(html).toContain("À jour");
    expect(html).toContain("claude-code");
    expect(html).not.toContain("opencode");
    expect(html).not.toContain("data-resync");
  });

  it("poste hors ligne au rapport ancien : bouton « Mettre à jour »", () => {
    const html = machineItemHtml(machine({ status: "offline", freshness: "stale" }));
    expect(html).toContain("Hors ligne");
    expect(html).toContain("Rapport ancien");
    expect(html).toContain("data-resync");
    expect(html).toContain("Mettre à jour");
  });

  it("jamais rapporté : « Aucun rapport » et pas d'outil affiché", () => {
    const html = machineItemHtml(machine({ freshness: "never_reported", reported_at: null, project_registered: null }));
    expect(html).toContain("Pas encore configuré");
    expect(html).toContain("Aucun rapport.");
    expect(html).not.toContain("Outils détectés");
  });

  it("n'expose plus le jargon technique", () => {
    const html = machineItemHtml(machine({ bootstrap: inSync(false) })).replace(RESYNC_COMMAND, "");
    expect(html).not.toMatch(/bundle|bootstrap|harnais|Resynchroniser/i);
  });
});

describe("aiIntegrationHtml", () => {
  it("résumé, configuration attendue et un poste par ligne", () => {
    const status: AiIntegrationStatus = {
      project_id: MID,
      desired: { plan_hash: "deadbeef", agent_keys: ["a"], artifact_counts: { rule: 1 } },
      desired_error: null,
      machines: [machine({ bootstrap: inSync(true) }), machine({ machine_id: "x", display_name: "pc-2" })],
    };
    const html = aiIntegrationHtml(status);
    expect(html).toContain("1 poste sur 2");
    expect(html).toContain("1 agent ");
    expect(html).toContain("flo-laptop");
    expect(html).toContain("pc-2");
    expect(html).not.toContain("État désiré");
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });

  it("aucun poste : état vide explicite", () => {
    const html = aiIntegrationHtml({ project_id: MID, desired: null, desired_error: null, machines: [] });
    expect(html).toContain("Aucun poste n'a encore donné de nouvelles");
    expect(html).not.toContain("poste sur");
  });
});
