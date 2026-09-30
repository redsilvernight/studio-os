/**
 * Intégration IA (AIB P6) — onglet du workspace. DOM-free : assertions sur les
 * chaînes produites. Le contrat est explicite : l'UI n'affirme jamais une
 * écriture qu'un poste n'a pas rapportée, et un poste hors ligne ou sans
 * rapport reste en mode instruction locale.
 */
import { describe, expect, it } from "vitest";
import type {
  AiIntegrationStatus,
  ReportedMachineIntegration,
} from "../aiIntegrationApi";
import {
  RESYNC_COMMAND,
  aiIntegrationHtml,
  desiredHtml,
  machineItemHtml,
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

describe("desiredHtml", () => {
  it("montre l'empreinte, les agents et les compteurs d'artefacts", () => {
    const html = desiredHtml(
      {
        plan_hash: "abcdef0123456789abcdef",
        agent_keys: ["studio-orchestrator", "review-helper"],
        artifact_counts: { rule: 3, skill: 2, agent_definition: 1 },
      },
      null,
    );
    expect(html).toContain("abcdef01…");
    expect(html).toContain("studio-orchestrator");
    expect(html).toContain("review-helper");
    expect(html).toContain("Agents");
    expect(html).toContain("Compétences");
    expect(html).toContain("Règles");
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });

  it("affiche l'erreur publique sans prétendre à un état valide", () => {
    const html = desiredHtml(null, "bootstrap_plan_unavailable");
    expect(html).toContain("État désiré indisponible");
    expect(html).toContain("bootstrap_plan_unavailable");
    expect(html).not.toContain("Agents attendus");
  });

  it("reste neutre quand rien n'est disponible", () => {
    expect(desiredHtml(null, null)).toContain("Aucun état désiré");
  });
});

describe("resyncInstructionHtml", () => {
  it("donne la commande locale à exécuter sur le poste, jamais une écriture supposée", () => {
    const html = resyncInstructionHtml(machine({}));
    expect(html).toContain(RESYNC_COMMAND);
    expect(html).toContain("sur le poste flo-laptop");
    expect(html).toContain("n'écrit rien sur le poste");
    expect(html).toContain("hidden");
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });
});

describe("machineItemHtml", () => {
  it("poste en ligne et à jour : présence, harnais et action de resynchronisation", () => {
    const html = machineItemHtml(
      machine({
        harnesses: [{ harness_id: "claude-code", version: "1.2.3", detected: true, configured: true }],
      }),
    );
    expect(html).toContain("En ligne");
    expect(html).toContain("Rapporté récemment");
    expect(html).toContain("claude-code");
    expect(html).toContain("Détecté");
    expect(html).toContain("Configuré pour Studi'OS");
    expect(html).toContain("data-resync");
    expect(html).toContain("Projet enregistré sur le poste");
  });

  it("poste hors ligne : état rapporté comme tel, jamais une réussite", () => {
    const html = machineItemHtml(machine({ status: "offline", freshness: "stale" }));
    expect(html).toContain("Hors ligne");
    expect(html).toContain("Rapport périmé");
    expect(html).not.toContain("Configuré pour Studi'OS");
  });

  it("poste n'ayant jamais rapporté : rien n'est supposé", () => {
    const html = machineItemHtml(
      machine({ freshness: "never_reported", reported_at: null, project_registered: null, harnesses: [] }),
    );
    expect(html).toContain("Jamais rapporté");
    expect(html).toContain("n'a jamais rapporté son état");
    expect(html).toContain("Enregistrement inconnu");
    expect(html).not.toContain("Non configuré");
  });

  it("bundle local rapporté : à jour, daté, avec les comptes par état", () => {
    const html = machineItemHtml(
      machine({
        bootstrap: {
          checked_at: "2026-09-30T20:00:00Z",
          in_sync: true,
          summary: { absent: 0, obsolete: 0, modified: 0, incompatible: 0, up_to_date: 7 },
        },
      }),
    );
    expect(html).toContain("Bundle à jour");
    expect(html).toContain("vérifié le");
    expect(html).toContain("À jour");
    expect(html).not.toContain("Bundle à mettre à jour");
  });

  it("bundle local en dérive : signalé comme à mettre à jour", () => {
    const html = machineItemHtml(
      machine({
        bootstrap: {
          checked_at: "2026-09-30T20:00:00Z",
          in_sync: false,
          summary: { absent: 2, obsolete: 1, modified: 0, incompatible: 0, up_to_date: 4 },
        },
      }),
    );
    expect(html).toContain("Bundle à mettre à jour");
    expect(html).toContain("Absents");
    expect(html).toContain("Obsolètes");
  });

  it("aucun contrôle local rapporté : le dit sans supposer", () => {
    const html = machineItemHtml(machine({ bootstrap: null }));
    expect(html).toContain("Aucun état de bootstrap local rapporté par le poste");
  });
});

describe("aiIntegrationHtml", () => {
  it("sépare état désiré et état rapporté, et liste chaque poste", () => {
    const status: AiIntegrationStatus = {
      project_id: MID,
      desired: { plan_hash: "deadbeefdeadbeef", agent_keys: ["a"], artifact_counts: { rule: 1 } },
      desired_error: null,
      machines: [machine({})],
    };
    const html = aiIntegrationHtml(status);
    expect(html).toContain("État désiré (serveur)");
    expect(html).toContain("Rapporté par les postes (1)");
    expect(html).toContain("flo-laptop");
    expect(html).toContain("Aucune écriture n'est affirmée");
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });

  it("aucun poste rapporté : état vide explicite, pas de tableau vide", () => {
    const html = aiIntegrationHtml({ project_id: MID, desired: null, desired_error: null, machines: [] });
    expect(html).toContain("Rapporté par les postes (0)");
    expect(html).toContain("Aucun poste n'a rapporté d'état");
  });
});
