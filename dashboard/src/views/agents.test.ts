/**
 * P05-agents — liste compacte (rôle, disponibilité, projet), technique
 * repliée en fiche, administration séparée. Aucune fonction experte perdue.
 *
 * DOM-free (vitest, node) : assertions sur les chaînes produites +
 * lecture statique de agents.css pour le responsive.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  agentAvailabilityGroup,
  agentDisplayName,
  agentHeroHtml,
  agentHeroTarget,
  agentNotFoundHtml,
  agentPrimaryProject,
  agentRoleLabel,
  agentRowHtml,
  agentSignalHtml,
  agentsListHtml,
  agentsLoadingHtml,
  agentDetailHtml,
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

describe("agentDisplayName / agentRoleLabel (C2 : humain d'abord)", () => {
  it("nom humain, repli générique sans identifiant", () => {
    expect(agentDisplayName(agentOf())).toBe("Claude Atlas");
    expect(agentDisplayName(agentOf({ display_name: "   " }))).toBe("Agent sans nom");
  });

  it("rôle déclaré ou null, jamais fabriqué", () => {
    expect(agentRoleLabel(agentOf())).toBe("code");
    expect(agentRoleLabel(agentOf({ agent_kind: "   " }))).toBeNull();
  });
});

describe("agentAvailabilityGroup (5 signaux → 3 groupes lisibles)", () => {
  it("session ouverte et récent restent distingués, le reste est inactif", () => {
    expect(agentAvailabilityGroup("open-session")).toBe("active");
    expect(agentAvailabilityGroup("recent")).toBe("recent");
    expect(agentAvailabilityGroup("past")).toBe("inactive");
    expect(agentAvailabilityGroup("none")).toBe("inactive");
    expect(agentAvailabilityGroup("unknown")).toBe("inactive");
  });
});

describe("agentPrimaryProject (même ordre honnête que le résumé)", () => {
  it("session ouverte d'abord, puis dernier travail, puis tâche prise", () => {
    const viaSession = agentPrimaryProject(
      agentOf(), activityOf("open-session", { openSession: openSession() }), [], [taskOf()], names,
    );
    expect(viaSession).toEqual({ id: P1, name: "Binding of Apotheosis" });
    const viaWork = agentPrimaryProject(agentOf(), activityOf("recent"), [workOf()], [], names);
    expect(viaWork).toEqual({ id: P1, name: "Binding of Apotheosis" });
    const viaClaim = agentPrimaryProject(agentOf(), activityOf("none"), [], [taskOf()], names);
    expect(viaClaim).toEqual({ id: P1, name: "Binding of Apotheosis" });
  });

  it("rien affirmé sans preuve", () => {
    expect(agentPrimaryProject(agentOf(), activityOf("none"), [], [], names)).toBeNull();
  });
});

describe("agentRowHtml (ligne compacte : nom + rôle + projet)", () => {
  const html = agentRowHtml(agentOf(), activityOf("recent"), { id: P1, name: "Binding of Apotheosis" });

  it("priorise nom, rôle et projet, lien vers la fiche", () => {
    expect(html).toContain("Claude Atlas");
    expect(html).toContain(`#/agents/${A1}`);
    expect(html).toContain("code · Binding of Apotheosis");
  });

  it("replies modèle, permissions et identifiants (fiche uniquement)", () => {
    expect(html).not.toContain("claude-test");
    expect(html).not.toContain("anthropic");
    expect(html).not.toContain("opencode");
    expect(html).not.toContain("Modèle déclaré");
    expect(html).not.toContain("Fournisseur");
    expect(html).not.toContain("Harnais");
    expect(html).not.toContain(M1);
    expect(html).not.toContain("Exécuté sur la machine");
  });

  it("libellés génériques sans identifiant quand rien n'est renseigné", () => {
    const bare = agentRowHtml(
      agentOf({ display_name: "  ", agent_kind: "  " }), activityOf("none"), null,
    );
    expect(bare).toContain("Agent sans nom");
    expect(bare).toContain("Rôle non renseigné · aucun projet");
    // C2 : aucun UUID hors fragment de route admit (#/agents/:id).
    expect(bare.replace(/href="[^"]*"/g, "")).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/);
    expect(bare).not.toContain(M1);
  });

  it("contient ni style ni handler inline (CSP)", () => {
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
  });
});

describe("agentHeroTarget / agentHeroHtml (C1 : une seule action primaire)", () => {
  it("session ouverte : titre honnête et primaire vers la tâche en 1 clic", () => {
    const target = agentHeroTarget(
      agentOf(), activityOf("open-session", { openSession: openSession() }), [openSession()], [], [taskOf()], names,
    );
    expect(target.title).toContain("Travaille sur");
    expect(target.taskId).toBe(T1);
    const html = agentHeroHtml(target);
    expect(html).toContain(`href="#/tasks/${T1}"`);
    expect(html).toContain("Ouvrir le travail");
    expect(html).toContain(`href="#/projects/${P1}"`);
    expect(html.match(/ds-btn--primary/g)?.length).toBe(1);
  });

  it("repli sur le dernier travail observé, jamais inventé", () => {
    const target = agentHeroTarget(agentOf(), activityOf("recent"), [], [workOf()], [], names);
    expect(target.title).toContain("Dernier travail");
    expect(target.taskId).toBe(T1);
    expect(agentHeroHtml(target)).toContain("Commencé");
  });

  it("dégrade honnêtement quand les secondaires sont indisponibles", () => {
    const target = agentHeroTarget(agentOf(), activityOf("unknown"), [], [], [], names);
    expect(target.title).toContain("Travail inconnu");
    expect(agentHeroHtml(target)).not.toContain("ds-btn--primary");
  });

  it("n'affirme rien sans preuve quand tout est chargé", () => {
    const target = agentHeroTarget(agentOf(), activityOf("none"), [], [], [], names);
    expect(target.title).toContain("Aucun travail observé");
    expect(agentHeroHtml(target)).not.toContain("#/tasks/");
  });

  it("contient ni style ni handler inline (CSP)", () => {
    const target = agentHeroTarget(
      agentOf(), activityOf("open-session", { openSession: openSession() }), [openSession()], [], [taskOf()], names,
    );
    const html = agentHeroHtml(target);
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
  });
});

describe("agentsListHtml (liste compacte groupée, empty utile)", () => {
  const activities = new Map([[A1, activityOf("open-session", { openSession: openSession() })]]);

  it("liste nominale : en-tête FR, recherche nom ou rôle, groupes de dispo", () => {
    const html = agentsListHtml([agentOf()], activities, { sessions: [openSession()], aiWork: [], tasks: [taskOf()] }, names, "", true);
    expect(html).toContain("<h1>Agents IA</h1>");
    expect(html).toContain("d'un coup d'œil");
    expect(html).toContain('id="agents-search"');
    expect(html).toContain("par nom ou rôle");
    expect(html).toContain("recherche locale");
    expect(html).toContain("En activité");
    expect(html).toContain("Claude Atlas");
    expect(html).toContain("code · Binding of Apotheosis");
  });

  it("technique et identifiants absents de la liste, projet prioritaire présent", () => {
    const html = agentsListHtml([agentOf()], activities, { sessions: [openSession()], aiWork: [], tasks: [taskOf()] }, names, "", true);
    expect(html).not.toContain("claude-test");
    expect(html).not.toContain("Modèle déclaré");
    expect(html).not.toContain(M1);
    expect(html).not.toContain("Exécuté sur la machine");
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

describe("agentDetailHtml (héros + expertes repliées + admin séparée)", () => {
  const html = agentDetailHtml(agentOf(), activityOf("open-session", { openSession: openSession() }), [openSession()], [workOf()], names);

  it("répond qui / travail / environnement, héros avec action unique", () => {
    expect(html).toContain("<h1>Claude Atlas</h1>");
    expect(html).toContain("Travail actuel");
    expect(html).toContain("Travaille sur");
    expect(html).toContain("Corriger l");
    expect(html).toContain(`href="#/tasks/${T1}"`);
    expect(html).toContain("<h2>Activité</h2>");
    expect(html).toContain("<h2>Travail réalisé</h2>");
    expect(html).toContain("<h2>Sessions</h2>");
    expect(html).toContain("<h2>Environnement</h2>");
    expect(html).not.toContain("<h2>Travail actuel</h2>");
    expect(html).not.toContain("<h2>Résumé</h2>");
  });

  it("sessions honnêtes, relecture renvoyée vers UI-8", () => {
    expect(html).toContain("pas preuve de connexion");
    expect(html).toContain("Décisions, onglet À valider");
    expect(html).not.toContain("Approuver");
  });

  it("environnement sans fusion agent/machine/runtime", () => {
    expect(html).toContain("n'est pas une sous-catégorie");
    expect(html).toContain('href="#/machines"');
    expect(html).toContain('href="#/configuration/runtimes"');
    expect(html).toContain("simple étiquette libre");
  });

  it("modèle, permissions et IDs repliés dans les détails techniques", () => {
    expect(html).toContain("<details");
    expect(html).toContain("Détails techniques · modèle, permissions, identifiants");
    expect(html).toContain("Modèle déclaré");
    expect(html).toContain("claude-test");
    expect(html).toContain("Permissions");
    expect(html).toContain("Aucune définition associée");
    expect(html).toContain("ds-tech");
    expect(html).toContain(A1);
  });

  it("administration séparée du quotidien, sans action à distance inventée", () => {
    expect(html).toContain("<h2>Administration</h2>");
    expect(html).toContain("séparée du quotidien");
    expect(html).toContain("Voir la machine");
    expect(html).toContain("Paramètres d'exécution");
    expect(html).toContain("aucune action à distance");
    expect(html).not.toContain("Révoquer");
  });

  it("technique CSP respectée", () => {
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
  });
});

describe("agentNotFoundHtml", () => {
  it("état explicite avec retour, sans fuite d'ID brut", () => {
    const html = agentNotFoundHtml(A1);
    expect(html).toContain("Agent introuvable");
    expect(html).toContain('href="#/agents"');
    expect(html).not.toContain(A1.slice(0, 8));
  });
});

describe("agents.css (liste compacte, pas de remplissage artificiel)", () => {
  const css = readFileSync(join(__dirname, "agents.css"), "utf8");

  it("colonne étroite aérée, lignes et groupes, empilement mobile, reduced-motion", () => {
    expect(css).toContain("max-width: 860px");
    expect(css).toContain(".agent-row");
    expect(css).toContain(".agents-group");
    expect(css).toContain("@media (max-width: 640px)");
    expect(css).toContain("prefers-reduced-motion");
  });

  it("aucun tableau technique, aucun remplissage viewport", () => {
    expect(css).not.toContain("<table");
    expect(css).not.toMatch(/100vh|100vw/);
  });
});
