/**
 * UI-6 — Agents IA : cartes calmes, activité DERIVED honnête, français,
 * CSP, détail justifié par les données, dégradations honnêtes.
 *
 * DOM-free (vitest, node) : assertions sur les chaînes produites +
 * lecture statique de agents.css pour le responsive.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  agentCardHtml,
  agentDetailHtml,
  agentNotFoundHtml,
  agentSignalHtml,
  agentWorkSummaryHtml,
  agentsListHtml,
  agentsLoadingHtml,
  buildAgentNames,
} from "./agents";
import type { AgentActivity } from "../agentsApi";

const A1 = "aaaaaaaa-0000-4111-8111-000000000001";
const M1 = "bbbbbbbb-0000-4111-8111-000000000001";
const T1 = "cccccccc-0000-4111-8111-000000000001";
const P1 = "11111111-2222-4333-8444-555555555555";

const agentOf = (extra: Record<string, unknown> = {}) =>
  ({
    id: A1,
    machine_id: M1,
    display_name: "Claude Atlas",
    agent_kind: "code",
    agent_profile: "Revue et correction",
    harness: "opencode",
    provider: "anthropic",
    model: "claude-test",
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-17T10:00:00Z",
    version: 2,
    ...extra,
  }) as never;

const taskOf = (extra: Record<string, unknown> = {}) =>
  ({
    id: T1,
    project_id: P1,
    readable_id: "T-9",
    title: "Corriger l'authentification",
    description: null,
    status: "in_progress",
    claimed_by_machine_id: M1,
    claimed_by_agent_id: A1,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-17T11:00:00Z",
    version: 3,
    ...extra,
  }) as never;

const projectOf = () =>
  ({
    id: P1,
    slug: "phare",
    name: "Binding of Apotheosis",
    description: null,
    archived: false,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    version: 7,
  }) as never;

const names = buildAgentNames([taskOf()], [projectOf()]);

const activityOf = (signal: AgentActivity["signal"], extra: Partial<AgentActivity> = {}): AgentActivity => ({
  signal,
  openSession: null,
  lastActivityAt: "2026-09-18T11:55:00Z",
  lastActivitySource: "ai-work",
  workCount: 1,
  sessionCount: 0,
  ...extra,
});

const openSession = () =>
  ({
    id: "s1",
    task_id: T1,
    machine_id: M1,
    agent_id: A1,
    started_at: "2026-09-18T11:00:00Z",
    ended_at: null,
  }) as never;

const workOf = () =>
  ({
    id: "w1",
    task_id: T1,
    project_id: P1,
    agent_id: A1,
    machine_id: M1,
    summary: "Corriger l'authentification",
    status: "started",
    changed_files: [],
    tests_run: [],
    started_at: "2026-09-18T11:50:00Z",
    ended_at: null,
    agent_profile: null,
    harness: null,
    provider: null,
    model: null,
  }) as never;

describe("agentSignalHtml (DERIVED, vocabulaire honnête)", () => {
  it("ne présente jamais une présence calculée comme canonique", () => {
    for (const signal of ["open-session", "recent", "past", "none", "unknown"] as const) {
      const html = agentSignalHtml(activityOf(signal));
      expect(html).not.toMatch(/>\s*En ligne\s*</);
      expect(html).not.toContain("En ligne");
    }
  });

  it("explicite chaque état en français, couleur jamais seul signal", () => {
    expect(agentSignalHtml(activityOf("open-session"))).toContain("Session de travail ouverte");
    expect(agentSignalHtml(activityOf("open-session"))).toContain("pas une preuve de connexion");
    expect(agentSignalHtml(activityOf("recent"))).toContain("Actif récemment");
    expect(agentSignalHtml(activityOf("recent"))).toContain("pas une présence garantie");
    expect(agentSignalHtml(activityOf("past"))).toContain("Dernière activité");
    expect(agentSignalHtml(activityOf("none"))).toContain("Aucune activité observée");
    expect(agentSignalHtml(activityOf("unknown"))).toContain("Activité inconnue");
  });
});

describe("agentWorkSummaryHtml (relations réelles uniquement)", () => {
  it("affiche la session ouverte avec tâche et projet liés", () => {
    const html = agentWorkSummaryHtml(agentOf(), activityOf("open-session", { openSession: openSession() }), [], [], [taskOf()], names);
    expect(html).toContain("Travaille sur");
    expect(html).toContain("Corriger l'authentification");
    expect(html).toContain(`#/tasks/${T1}`);
    expect(html).toContain("Binding of Apotheosis");
    expect(html).toContain(`#/projects/${P1}`);
  });

  it("replie sur le dernier AI work observé, jamais inventé", () => {
    const html = agentWorkSummaryHtml(agentOf(), activityOf("recent"), [], [workOf()], [], names);
    expect(html).toContain("Dernier travail observé");
    expect(html).toContain("Commencé");
    expect(html).toContain(`#/tasks/${T1}`);
  });

  it("dégrade honnêtement quand les secondaires sont indisponibles", () => {
    const html = agentWorkSummaryHtml(agentOf(), activityOf("unknown"), [], [], [], names);
    expect(html).toContain("Travail inconnu");
    expect(html).not.toContain("Aucun travail observé");
  });

  it("n'affirme rien sans preuve quand tout est chargé", () => {
    const html = agentWorkSummaryHtml(agentOf(), activityOf("none"), [], [], [], names);
    expect(html).toContain("Aucun travail observé");
  });
});

describe("agentCardHtml (identité d'abord, technique en second)", () => {
  const html = agentCardHtml(agentOf(), activityOf("recent"), [], [workOf()], [taskOf()], names);

  it("priorise nom, nature déclarée et activité, sans rôle fabriqué", () => {
    expect(html).toContain("Claude Atlas");
    expect(html).toContain(`#/agents/${A1}`);
    expect(html).toContain("Nature déclarée");
    expect(html).toContain("Actif récemment");
    expect(html).not.toMatch(/rôle/i);
  });

  it("distingue agent et machine, affiche la technique déclarée", () => {
    expect(html).toContain("Exécuté sur la machine");
    expect(html).toContain(M1.slice(0, 8));
    expect(html).toContain('href="#/machines"');
    expect(html).toContain("Modèle déclaré");
    expect(html).not.toContain("Définition associée");
  });

  it("ne simule aucune association agent-definition", () => {
    expect(html).not.toContain("agent-definitions");
    expect(html).not.toContain("Bibliothèque");
  });

  it("contient ni style ni handler inline (CSP)", () => {
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
  });
});

describe("agentsListHtml (liste calme, empty utile)", () => {
  const activities = new Map([[A1, activityOf("recent")]]);

  it("liste nominale : en-tête FR, recherche locale, cartes sobres", () => {
    const html = agentsListHtml([agentOf()], activities, { sessions: [], aiWork: [workOf()], tasks: [taskOf()] }, names, "", true);
    expect(html).toContain("<h1>Agents IA</h1>");
    expect(html).toContain("collaborateurs logiciels");
    expect(html).toContain('id="agents-search"');
    expect(html).toContain("recherche locale");
    expect(html).toContain("Claude Atlas");
  });

  it("empty state explique l'agent sans bouton de création fictif", () => {
    const html = agentsListHtml([], new Map(), { sessions: [], aiWork: [], tasks: [] }, names, "", true);
    expect(html).toContain("Aucun agent enregistré");
    expect(html).toContain("identité de travail");
    expect(html).not.toContain("Créer un agent");
    expect(html).not.toContain("Nouvel agent");
  });

  it("source secondaire en échec : liste sans activité affirmée", () => {
    const html = agentsListHtml([agentOf()], new Map(), { sessions: [], aiWork: [], tasks: [] }, names, "", false);
    expect(html).toContain("Activité inconnue");
    expect(html).toContain("n'affirme aucune activité");
    expect(html).not.toContain("Actif récemment");
    expect(html).not.toContain("Aucune activité observée");
  });

  it("recherche sans résultat : état dédié, pas de page vide", () => {
    const html = agentsListHtml([agentOf()], activities, { sessions: [], aiWork: [], tasks: [] }, names, "zzz", true);
    expect(html).toContain("Aucun résultat pour cette recherche");
    expect(html).not.toContain("Claude Atlas");
  });

  it("français partout, CSP respectée", () => {
    const html = agentsListHtml([agentOf()], activities, { sessions: [], aiWork: [], tasks: [] }, names, "", true);
    expect(html).toContain("affiché(s)");
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
  });
});

describe("agentsLoadingHtml", () => {
  it("squelette DS avec en-tête, sans contenu fictif", () => {
    const html = agentsLoadingHtml();
    expect(html).toContain("<h1>Agents IA</h1>");
    expect(html).toContain("Chargement");
  });
});

describe("agentDetailHtml (fiche justifiée par les données)", () => {
  const html = agentDetailHtml(agentOf(), activityOf("open-session", { openSession: openSession() }), [openSession()], [workOf()], names);

  it("répond qui / travail / environnement, hiérarchie h1→h2", () => {
    expect(html).toContain("<h1>Claude Atlas</h1>");
    expect(html).toContain("<h2>Activité</h2>");
    expect(html).toContain("<h2>Travail actuel</h2>");
    expect(html).toContain("<h2>Résumé</h2>");
    expect(html).toContain("<h2>Travail produit</h2>");
    expect(html).toContain("<h2>Sessions</h2>");
    expect(html).toContain("<h2>Environnement</h2>");
    expect(html).toContain("Travaille sur");
    expect(html).toContain("Corriger l");
  });

  it("sessions honnêtes, relecture renvoyée vers UI-8", () => {
    expect(html).toContain("pas preuve de connexion");
    expect(html).toContain("Review (UI-8)");
    expect(html).not.toContain("Approuver");
  });

  it("environnement sans fusion agent/machine/runtime", () => {
    expect(html).toContain("n'est pas une sous-catégorie");
    expect(html).toContain('href="#/machines"');
    expect(html).toContain('href="#/configuration/runtimes"');
    expect(html).toContain("sans lien backend");
  });

  it("technique en divulgation progressive, CSP respectée", () => {
    expect(html).toContain("<details");
    expect(html).toContain("Informations techniques");
    expect(html).toContain(A1);
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
  });
});

describe("agentNotFoundHtml", () => {
  it("état explicite avec retour, sans fuite d'ID brut", () => {
    const html = agentNotFoundHtml(A1);
    expect(html).toContain("Agent introuvable");
    expect(html).toContain('href="#/agents"');
    expect(html).toContain(A1.slice(0, 8));
    expect(html).not.toContain(A1);
  });
});

describe("agents.css (responsive, pas de remplissage artificiel)", () => {
  const css = readFileSync(join(__dirname, "agents.css"), "utf8");

  it("colonne étroite aérée, empilement mobile, reduced-motion", () => {
    expect(css).toContain("max-width: 860px");
    expect(css).toContain("@media (max-width: 640px)");
    expect(css).toContain("prefers-reduced-motion");
  });

  it("aucun tableau technique, aucun remplissage viewport", () => {
    expect(css).not.toContain("<table");
    expect(css).not.toMatch(/100vh|100vw/);
  });
});
