/**
 * UI-9 — Machines : surface d'infrastructure honnête.
 *
 * DOM-free (vitest, environnement node) : assertions sur les chaînes
 * produites + lecture statique de machines.css pour le responsive.
 * La présence est DÉDUITE (pas de GET /machines) : le vocabulaire parle
 * d'activité, jamais de connexion garantie.
 */
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ApiError } from "../api";
import {
  activityLabelFr,
  filterMachineRows,
  findProbableDuplicates,
  formatRelativeFr,
  groupMachineRows,
  initialMachinesState,
  isMachinesDefaultState,
  machineDisplayTitle,
  setMachineWorkstation,
  workstationCandidates,
  workstationErrorFr,
  type MachineRow,
} from "../machinesApi";
import {
  machineCardHtml,
  machineDrawerBodyHtml,
  machineWorkstationSectionHtml,
  machinesEmptyHtml,
  machinesListHtml,
  machinesLoadingHtml,
  machinesNoMatchHtml,
  machinesPageHtml,
  machinesToolbarHtml,
  type MachineCardInfo,
  type MachinesPageData,
} from "./machines";

const NOW = new Date("2026-09-15T12:00:00.000Z").getTime();
const ago = (seconds: number): string => new Date(NOW - seconds * 1000).toISOString();

const M1 = "aaaaaaaa-0000-4111-8111-000000000001";
const M2 = "bbbbbbbb-0000-4111-8111-000000000002";

const row = (overrides: Partial<MachineRow> = {}): MachineRow => ({
  machineId: M1,
  displayName: "Poste de Flo",
  ownerUserId: null,
  lastSeenAt: null,
  lastActivityAt: ago(240),
  status: "online",
  statusSource: "derived",
  agentCount: 1,
  activeSessionCount: 1,
  version: null,
  workstationId: null,
  ...overrides,
});

const info =(overrides: Partial<MachineCardInfo> = {}): MachineCardInfo => ({
  agentNames: ["Claude"],
  activeSession: null,
  ...overrides,
});

const pageData = (overrides: Partial<MachinesPageData> = {}): MachinesPageData => ({
  rows: [row(), row({ machineId: M2, displayName: null, status: "offline", lastActivityAt: ago(7200), agentCount: 0, activeSessionCount: 0 })],
  agents: [],
  sessions: [],
  runtimes: [],
  state: initialMachinesState(),
  canonicalAvailable: false,
  problems: [],
  now: NOW,
  ...overrides,
});

describe("machineDisplayTitle", () => {
  it("utilise le nom canonique quand il existe", () => {
    expect(machineDisplayTitle(row())).toBe("Poste de Flo");
  });

  it("n'invente ni numéro ni nom quand aucun nom n'existe", () => {
    expect(machineDisplayTitle(row({ displayName: null }))).toBe("Machine sans nom enregistré");
    expect(machineDisplayTitle(row({ displayName: "   " }))).toBe("Machine sans nom enregistré");
    expect(machineDisplayTitle(row({ displayName: null }))).not.toMatch(/Machine \d/);
  });
});

describe("activityLabelFr", () => {
  it("parle d'activité observée pour du déduit, jamais de connexion", () => {
    expect(activityLabelFr("online", "derived").label).toBe("Activité récente");
    expect(activityLabelFr("idle", "derived").label).toBe("Peu d'activité récente");
    expect(activityLabelFr("offline", "derived").label).toBe("Aucune activité récente connue");
    for (const status of ["online", "idle", "offline"] as const) {
      const label = activityLabelFr(status, "derived");
      expect(label.label).not.toMatch(/En ligne|Hors ligne|Online|Offline/);
      expect(label.hint).toMatch(/déduite|non garantie/i);
    }
  });

  it("réserve En ligne / Hors ligne au canonique serveur", () => {
    expect(activityLabelFr("online", "canonical").label).toBe("En ligne");
    expect(activityLabelFr("offline", "canonical").label).toBe("Hors ligne");
  });
});

describe("formatRelativeFr", () => {
  it("formule des durées relatives françaises", () => {
    expect(formatRelativeFr(ago(10), NOW)).toBe("à l'instant");
    expect(formatRelativeFr(ago(240), NOW)).toBe("il y a 4 min");
    expect(formatRelativeFr(ago(7200), NOW)).toBe("il y a 2 h");
    expect(formatRelativeFr(ago(90000), NOW)).toBe("il y a 1 jour");
    expect(formatRelativeFr(null, NOW)).toBeNull();
  });
});

describe("filterMachineRows", () => {
  const rows = [
    row(),
    row({ machineId: M2, displayName: "Serveur VPS", status: "offline" }),
  ];
  it("filtre en local sur le nom et l'identifiant", () => {
    expect(filterMachineRows(rows, { query: "vps", activity: "all" }).map((r) => r.machineId)).toEqual([M2]);
    expect(filterMachineRows(rows, { query: M1.slice(0, 8), activity: "all" }).map((r) => r.machineId)).toEqual([M1]);
  });

  it("filtre sur l'activité exacte", () => {
    expect(filterMachineRows(rows, { query: "", activity: "offline" }).map((r) => r.machineId)).toEqual([M2]);
    expect(filterMachineRows(rows, initialMachinesState())).toHaveLength(2);
  });

  it("état initial sans filtre ni recherche", () => {
    expect(isMachinesDefaultState(initialMachinesState())).toBe(true);
    expect(isMachinesDefaultState({ query: "x", activity: "all" })).toBe(false);
    expect(isMachinesDefaultState({ query: "", activity: "online" })).toBe(false);
  });
});

describe("machinesLoadingHtml", () => {
  it("affiche un squelette accessible sans changement brutal", () => {
    const html = machinesLoadingHtml();
    expect(html).toContain("Postes");
    expect(html).toContain("Administration / Postes");
    expect(html).toContain("Chargement");
    expect(html).toContain('role="status"');
  });
});

describe("machinesPageHtml nominal", () => {
  const html = machinesPageHtml(pageData());

  it("titre et description humains, liste de cartes sans table SQL", () => {
    expect(html).toContain("<h1>Postes</h1>");
    expect(html).toContain("Administration / Postes");
    expect(html).toContain("Revoir le poste sans activité");
    expect(html).toContain("Poste de Flo");
    expect(html).toContain("<ul");
    expect(html).not.toContain("<table>");
  });

  it("ne met jamais l'UUID en titre principal", () => {
    const titles = [...html.matchAll(/<h3 class="ds-list-title"[^>]*>(.*?)<\/h3>/g)].map((m) => m[1] ?? "");
    expect(titles).toHaveLength(2);
    expect(titles[0]).toContain("Poste de Flo");
    expect(titles[1]).toContain("Machine sans nom enregistré");
    for (const title of titles) {
      expect(title).not.toContain(M1);
      expect(title).not.toContain(M2);
    }
    expect(html).not.toContain(`title="${M1}"`);
  });

  it("activité déduite honnête, source visible, jamais couleur seule", () => {
    expect(html).toContain("Activité récente");
    expect(html).toContain("Aucune activité récente connue");
    expect(html).toContain("Déduit");
    expect(html).toContain("pas un état de connexion garanti");
    expect(html).not.toMatch(/En ligne|Hors ligne/);
    expect(html).toContain("Aucune mesure CPU, RAM ou disponibilité n'est collectée");
    expect(html).not.toMatch(/99\.9%|healthy|uptime/i);
  });

  it("horodate avec <time> et annonce la portée locale du filtre", () => {
    expect(html).toContain("<time datetime=");
    expect(html).toContain("recherche et filtre locaux");
    expect(html).toContain('role="search"');
    expect(html).toContain('aria-live="polite"');
  });

  it("français partout, aucune action inventée", () => {
    expect(html).toContain("Détails");
    expect(html).toContain("Actualiser");
    expect(html).toContain("Réinitialiser");
    expect(html).not.toMatch(/Online|Offline|Loading|Retry|New machine|Delete|Restart|Ping|Wake|Disable|Ban/);
    expect(html).not.toContain("+ Nouvelle machine");
  });

  it("recherche locale sur nom et identifiant uniquement", () => {
    const toolbar = machinesToolbarHtml(initialMachinesState(), 2, 2);
    expect(toolbar).toContain('placeholder="Filtrer par nom…"');
    expect(toolbar).toContain("Toutes les activités");
    expect(toolbar).not.toMatch(/serveur|server/i);
  });
});

describe("machinesListHtml / machineCardHtml", () => {
  it("résume agents et session sans reconstruire les métiers", () => {
    const html = machineCardHtml(row(), info(), NOW);
    expect(html).toContain("Agent observé");
    expect(html).toContain("Aucune session en cours");
    expect(html).not.toContain("#/agents");
    expect(html).not.toContain("Review");
  });

  it("n'ouvre aucun lien vers une route agents inexistante", () => {
    const html = machinesListHtml([row()], new Map([[M1, info()]]), NOW);
    expect(html).not.toMatch(/#\/agents/);
  });
});

describe("machineDrawerBodyHtml", () => {
  const agents = [
    { id: "ag1", machine_id: M1, display_name: "Claude", agent_kind: "dev" },
    { id: "ag2", machine_id: M1, display_name: "Qwen", agent_kind: "" },
  ] as never[];
  const sessions = [
    { id: "s1", task_id: "t1", machine_id: M1, agent_id: "ag1", started_at: ago(300), ended_at: null },
    { id: "s2", task_id: "t2", machine_id: M1, agent_id: null, started_at: ago(7200), ended_at: ago(7000) },
  ] as never[];
  const runtimes = [
    { id: "rt1", machine_id: M1, harness_ref: "opencode", provider_ref: "anthropic", model_ref: null, status: "active" },
    { id: "rt2", machine_id: "autre", harness_ref: "x", provider_ref: null, model_ref: null, status: "active" },
  ] as never[];

  const html = machineDrawerBodyHtml(row(), agents, sessions, runtimes, NOW);

  it("hiérarchise résumé, utilisation, environnement puis technique", () => {
    const summary = html.indexOf("Dernière activité connue");
    const usage = html.indexOf("Utilisation récente");
    const env = html.indexOf("Environnement");
    const tech = html.indexOf("Informations techniques");
    expect(summary).toBeGreaterThan(-1);
    expect(usage).toBeGreaterThan(summary);
    expect(env).toBeGreaterThan(usage);
    expect(tech).toBeGreaterThan(env);
  });

  it("montre agents, sessions liées aux tâches et runtimes liés", () => {
    expect(html).toContain('href="#/agents/ag1">Claude</a>');
    expect(html).toContain('href="#/agents/ag2">Qwen</a>');
    expect(html).toContain('href="#/tasks/t1"');
    expect(html).toContain("opencode · anthropic");
    expect(html).toContain('href="#/configuration/runtimes/rt1"');
    expect(html).not.toContain("rt2");
  });

  it("replie le technique et documente l'absence de révocation", () => {
    expect(html).toContain("<details");
    expect(html).toContain(M1);
    expect(html).toContain("Révocation");
    expect(html).not.toMatch(/Supprimer|Redémarrer|Déconnecter/);
  });

  it("aucune section vide : messages sobres quand rien n'est lié", () => {
    const bare = machineDrawerBodyHtml(row({ machineId: M2, displayName: null }), [], [], [], NOW);
    expect(bare).toContain("Aucune session observée");
    expect(bare).toContain("Aucun runtime rattaché");
    expect(bare).toContain("Non renseigné");
  });

  it("inclut un bouton Renommer dans les informations techniques", () => {
    expect(html).toContain('data-machine-rename="');
    expect(html).toContain("Renommer");
    expect(html).toContain('data-machine-version="');
  });
});

const OWNER = "cccccccc-0000-4111-8111-00000000000c";
const M3 = "dddddddd-0000-4111-8111-000000000003";
const M4 = "eeeeeeee-0000-4111-8111-000000000004";

describe("groupMachineRows", () => {
  it("imbrique les machines d'outil sous leur poste et garde les racines héritées", () => {
    const desk = row({ machineId: M1, displayName: "PC Flo", ownerUserId: OWNER, version: 1 });
    const tool = row({ machineId: M2, displayName: "Claude Code", ownerUserId: OWNER, version: 1, workstationId: M1 });
    const legacy = row({ machineId: M3, displayName: "Vieux poste", ownerUserId: OWNER, version: 1 });
    const orphan = row({ machineId: M4, displayName: "Orphelin", workstationId: "absent" });
    const groups = groupMachineRows([tool, desk, legacy, orphan]);
    expect(groups.map((group) => group.root.machineId)).toEqual([M1, M3, M4]);
    expect(groups[0]?.children.map((child) => child.machineId)).toEqual([M2]);
    expect(groups[1]?.children).toEqual([]);
  });

  it("rend les machines rattachées dans une sous-liste étiquetée", () => {
    const html = machinesListHtml(
      [row({ displayName: "PC Flo" }), row({ machineId: M2, displayName: "Outil", workstationId: M1 })],
      new Map(),
      NOW,
    );
    expect(html).toContain('class="machine-group"');
    expect(html).toContain('aria-label="Machines rattachées au poste PC Flo"');
    expect(html.indexOf("PC Flo")).toBeLessThan(html.indexOf("Outil"));
  });
});

describe("findProbableDuplicates", () => {
  const a = row({ machineId: M1, displayName: "Codex", ownerUserId: OWNER, workstationId: M3 });
  const b = row({ machineId: M2, displayName: " codex ", ownerUserId: OWNER, workstationId: M3 });

  it("même propriétaire, même poste, même nom insensible à la casse", () => {
    const duplicates = findProbableDuplicates([a, b]);
    expect(duplicates.get(M2)).toEqual({ targetId: M1, others: [M1] });
    expect(duplicates.get(M1)?.targetId).toBe(M1);
  });

  it("ignore un autre poste, un autre propriétaire ou un nom absent", () => {
    expect(findProbableDuplicates([a, { ...b, workstationId: null }]).size).toBe(0);
    expect(findProbableDuplicates([a, { ...b, ownerUserId: "autre" }]).size).toBe(0);
    expect(findProbableDuplicates([{ ...a, displayName: null }, { ...b, displayName: null }]).size).toBe(0);
  });

  it("affiche le badge et la commande d'administration exacte", () => {
    const html = machinesListHtml([a, b], new Map(), NOW);
    expect(html).toContain("Doublon probable");
    expect(html).toContain(`studio-admin merge-machines --from ${M2} --into ${M1}`);
    expect(html).not.toContain(`--from ${M1}`);
  });
});

describe("rattachement à un poste", () => {
  const desk = row({ machineId: M1, displayName: "PC Flo", ownerUserId: OWNER, version: 2 });
  const tool = row({ machineId: M2, displayName: "Outil", ownerUserId: OWNER, version: 5 });
  const foreign = row({ machineId: M3, displayName: "Autre", ownerUserId: "autre", version: 1 });

  it("propose les postes racines du même propriétaire", () => {
    expect(workstationCandidates(tool, [desk, tool, foreign]).map((r) => r.machineId)).toEqual([M1]);
    const html = machineWorkstationSectionHtml(tool, [desk, tool, foreign]);
    expect(html).toContain('<label for="machine-workstation-select">');
    expect(html).toContain(`<option value="${M1}">PC Flo</option>`);
    expect(html).toContain(`data-machine-attach="${M2}" data-machine-version="5"`);
    expect(html).toContain("Rattacher à ce poste");
    expect(html).not.toContain("Autre");
  });

  it("propose Détacher pour une machine rattachée, rien pour un poste parent", () => {
    const attached = { ...tool, workstationId: M1 };
    const html = machineWorkstationSectionHtml(attached, [desk, attached]);
    expect(html).toContain(`data-machine-detach="${M2}"`);
    expect(html).toContain("PC Flo");
    const parent = machineWorkstationSectionHtml(desk, [desk, attached]);
    expect(parent).toContain("1 machine(s) d'outil rattachée(s)");
    expect(parent).not.toMatch(/data-machine-(attach|detach)/);
  });

  it("appelle PUT /workstation avec If-Match-Version", async () => {
    const put = vi.fn(async () => ({
      response: { ok: true, status: 200 },
      data: { id: M2, version: 6, workstation_id: M1 },
    }));
    const updated = await setMachineWorkstation({ PUT: put } as never, M2, M1, 5);
    expect(updated.version).toBe(6);
    expect(put).toHaveBeenCalledWith("/api/v1/machines/{machine_id}/workstation", {
      params: { path: { machine_id: M2 }, header: { "If-Match-Version": 5 } },
      body: { workstation_id: M1 },
    });
  });

  it("traduit 409 et 404 en français", async () => {
    const put = vi.fn(async () => ({
      response: { ok: false, status: 409 },
      error: { detail: { error_code: "workstation_invalid", message: "x" } },
    }));
    const failure = await setMachineWorkstation({ PUT: put } as never, M2, null, 5).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(workstationErrorFr(failure)).toContain("Rattachement refusé");
    const conflict = new ApiError({ status: 409, errorCode: "version_conflict", message: "", serverVersion: 7 });
    expect(workstationErrorFr(conflict)).toContain("modifié entre-temps");
    const missing = new ApiError({ status: 404, errorCode: null, message: "", serverVersion: null });
    expect(workstationErrorFr(missing)).toContain("introuvable");
  });
});

describe("empty / erreur partielle", () => {
  it("l'état vide explique la machine sans CTA fictif", () => {
    const html = machinesEmptyHtml();
    expect(html).toContain("Aucun poste observé");
    expect(html).toMatch(/environnement enregistré/);
    expect(html).toMatch(/enregistre ses propres postes/);
    expect(html).not.toContain("<a");
    expect(html).not.toContain("<button");
  });

  it("aucun résultat de filtre invite à ajuster, sans tout perdre", () => {
    expect(machinesNoMatchHtml()).toContain("Aucun poste ne correspond");
  });

  it("une source secondaire en panne dégrade sans masquer la liste", () => {
    const html = machinesPageHtml(pageData({ problems: ["sessions indisponibles (HTTP 500)"] }));
    expect(html).toContain("Données partielles");
    expect(html).toContain("Poste de Flo");
  });
});

describe("CSP et responsive statique", () => {
  it("aucun style inline ni handler inline dans le HTML produit", () => {
    const html = machinesPageHtml(pageData()) + machineDrawerBodyHtml(row(), [], [], [], NOW);
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
    expect(html).not.toContain("javascript:");
  });

  it("machines.css : une seule colonne, repli mobile, pas de table minuscule", () => {
    const css = readFileSync(join(__dirname, "machines.css"), "utf-8");
    expect(css).toContain("@media (max-width: 640px)");
    expect(css).toContain("prefers-reduced-motion");
    expect(css).not.toMatch(/grid-template-columns:\s*1fr\s+1fr/);
    expect(css).not.toContain("<table>");
  });

  it("aucune modification globale : tokens/shell/components intacts", () => {
    for (const file of ["../ds/tokens.css", "../ds/components.css", "../shell.css"]) {
      const css = readFileSync(join(__dirname, file), "utf-8");
      expect(css).not.toContain("machines");
    }
  });
});
