import { describe, expect, it } from "vitest";
import {
  dsAgentBadge,
  dsAvatar,
  dsBadge,
  dsDrawerHtml,
  dsEmptyState,
  dsErrorState,
  dsField,
  dsHeroCard,
  dsMetric,
  dsModalHtml,
  dsPageHeader,
  dsProgress,
  dsSectionHeader,
  dsSkeleton,
  dsStateHtml,
  dsStatus,
  dsStatusDot,
  dsTabsHtml,
  dsTechDetails,
} from "./ds";

describe("dsBadge", () => {
  it("renders a labelled badge with a tone class", () => {
    const html = dsBadge("En attente", "warning");
    expect(html).toContain("ds-badge--warning");
    expect(html).toContain("En attente");
  });

  it("escapes user content", () => {
    expect(dsBadge("<script>", "danger")).not.toContain("<script>");
  });
});

describe("dsStatus", () => {
  it("always pairs the dot with an explicit text label", () => {
    const html = dsStatus("danger", "Bloqué");
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain("Bloqué");
    expect(html).toContain("ds-status--danger");
  });
});

describe("dsPageHeader", () => {
  it("renders title, description and actions", () => {
    const html = dsPageHeader("Accueil", "Résumé calme.", [
      { label: "Créer", variant: "primary", id: "create" },
      { label: "Voir tout", href: "#/tasks" },
    ]);
    expect(html).toContain("<h1>Accueil</h1>");
    expect(html).toContain("Résumé calme.");
    expect(html).toContain('id="create"');
    expect(html).toContain('href="#/tasks"');
  });
});

describe("dsSectionHeader", () => {
  it("renders a see-all link when provided", () => {
    expect(dsSectionHeader("Tâches", { label: "Voir tout", href: "#/tasks" })).toContain("Voir tout");
    expect(dsSectionHeader("Tâches")).not.toContain("<a");
  });
});

describe("dsMetric", () => {
  it("renders a strong value with its label", () => {
    const html = dsMetric("Tâches en cours", 4);
    expect(html).toContain("4");
    expect(html).toContain("Tâches en cours");
  });
});

describe("dsEmptyState", () => {
  it("explains and offers an action, announced as a status", () => {
    const html = dsEmptyState("Aucune tâche", "Créez-en une.", {
      label: "Créer",
      href: "#/tasks",
    });
    expect(html).toContain('role="status"');
    expect(html).toContain("Aucune tâche");
    expect(html).toContain("Créez-en une.");
    expect(html).toContain("#/tasks");
  });
});

describe("dsSkeleton", () => {
  it("announces loading once and hides decorative bars", () => {
    const html = dsSkeleton(2);
    expect(html).toContain('role="status"');
    expect(html).toContain("Chargement en cours");
    expect(html).toContain('aria-hidden="true"');
    expect(html).not.toContain("aria-label=");
  });
});

describe("dsField", () => {
  it("associates hint and error with the control", () => {
    const html = dsField("nom", "Nom", `<input class="ds-input" id="FIELD" type="text" />`, "Aide.", "Requis.");
    expect(html).toContain('for="nom"');
    expect(html).toContain('id="nom-hint"');
    expect(html).toContain('id="nom-error"');
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain('aria-describedby="nom-hint nom-error"');
  });
});

describe("dsProgress", () => {
  it("renders a native progress with a text label and clamps the value", () => {
    const html = dsProgress(120, 100, "Terminé");
    expect(html).toContain("<progress");
    expect(html).toContain('value="100"');
    expect(html).toContain("Terminé");
  });
});

describe("dsAvatar / dsAgentBadge", () => {
  it("derives initials and keeps the full name accessible", () => {
    const html = dsAvatar("Amina Benali");
    expect(html).toContain("AB");
    expect(html).toContain('role="img"');
    expect(html).toContain('aria-label="Amina Benali"');
    expect(dsAgentBadge("Auxiliaire")).toContain("ds-badge--ai");
  });

  it("announces the agent name only once inside a badge", () => {
    const html = dsAgentBadge("Auxiliaire");
    expect(html).toContain('aria-hidden="true"');
    expect(html).not.toContain('aria-label="Auxiliaire"');
    expect(html.match(/Auxiliaire/g)).toHaveLength(1);
  });
});

describe("dsTabsHtml", () => {
  it("marks exactly one selected tab with tablist semantics", () => {
    const html = dsTabsHtml("demo", [
      { id: "a", label: "Liste", panel: "<p>A</p>" },
      { id: "b", label: "Tableau", panel: "<p>B</p>" },
    ]);
    expect(html).toContain('role="tablist"');
    expect(html).toContain('role="tabpanel"');
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1);
    expect(html).toContain("hidden");
  });

  it("names the tablist in French when a label is provided", () => {
    const html = dsTabsHtml(
      "decisions-main",
      [
        { id: "a", label: "À examiner", panel: "<p>A</p>" },
        { id: "b", label: "Décisions", panel: "<p>B</p>" },
      ],
      "a",
      "Décisions",
    );
    expect(html).toContain('aria-label="Décisions"');
  });

  it("falls back to the technical id when no label is provided", () => {
    const html = dsTabsHtml("demo", [{ id: "a", label: "Liste", panel: "<p>A</p>" }]);
    expect(html).toContain('aria-label="demo"');
  });
});

describe("dsModalHtml / dsDrawerHtml", () => {
  it("renders hidden accessible dialogs", () => {
    for (const html of [
      dsModalHtml({ id: "m", title: "Modale", body: "<p>corps</p>" }),
      dsDrawerHtml({ id: "d", title: "Tiroir", body: "<p>corps</p>" }),
    ]) {
      expect(html).toContain('role="dialog"');
      expect(html).toContain('aria-modal="true"');
      expect(html).toContain("hidden");
    }
  });
});

describe("dialog wiring contract", () => {
  it("exposes data-ds-close hooks for the addEventListener wiring (covered in browser by e2e/ds.spec.ts)", () => {
    const html = dsModalHtml({
      id: "m",
      title: "Modale",
      body: "<p>corps</p>",
      actions: [{ label: "Fermer", variant: "primary" }],
    });
    expect(html).toContain("data-ds-close");
  });
});

describe("dsHeroCard", () => {
  const hero = () =>
    dsHeroCard({
      eyebrow: "Agents / Fiche",
      title: "Travaille sur « Valider »",
      body: "Résumé calme.",
      status: dsStatusDot("info", "Session ouverte"),
      primary: { label: "Ouvrir le travail", href: "#/travail" },
      secondary: [
        { label: "Voir la tâche", href: "#/taches" },
        { label: "Voir le projet", href: "#/projets" },
      ],
    });

  it("renders a single primary button action, secondaries as discreet links", () => {
    const html = hero();
    expect(html).toContain("ds-hero");
    expect(html).toContain("<h2>Travaille sur « Valider »</h2>");
    expect(html.match(/ds-btn--primary/g)).toHaveLength(1);
    expect(html).toContain('class="ds-hero-link"');
    expect(html).not.toContain("<button");
  });

  it("escapes user content but keeps the pre-rendered status fragment", () => {
    const html = dsHeroCard({
      title: "<script>",
      primary: { label: "<b>Ouvrir</b>", href: "#/x?a=<b>" },
      secondary: [{ label: "<i>Voir</i>", href: "#/y" }],
    });
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<b>Ouvrir</b>");
    expect(html).not.toContain("<i>Voir</i>");
  });

  it("omits optional blocks when absent", () => {
    const html = dsHeroCard({ title: "Titre seul", primary: { label: "Ouvrir", href: "#/x" } });
    expect(html).not.toContain("ds-hero-eyebrow");
    expect(html).not.toContain("ds-hero-body");
    expect(html).not.toContain("ds-hero-status");
  });
});

describe("dsStatusDot", () => {
  it("pairs the dot with a visible label by default, like dsStatus", () => {
    const html = dsStatusDot("danger", "Bloqué");
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain("Bloqué");
    expect(html).toContain("ds-status--danger");
    expect(html).not.toContain("ds-sr-only");
  });

  it("moves the label to screen readers only when compact", () => {
    const html = dsStatusDot("warning", "En attente", true);
    expect(html).toContain("ds-status--warning");
    expect(html).toContain('<span class="ds-sr-only">En attente</span>');
  });

  it("escapes the label", () => {
    expect(dsStatusDot("info", "<script>", true)).not.toContain("<script>");
  });
});

describe("dsTechDetails", () => {
  it("is closed by default with a dl list and mono values", () => {
    const html = dsTechDetails([
      { label: "Identifiant", value: "aaaaaaaa-0000-4111-8111-000000000001", mono: true },
      { label: "Révision", value: "v3", mono: true },
      { label: "Créé le", value: "il y a 12 min" },
    ]);
    expect(html).toContain("<details");
    expect(html).not.toContain("open");
    expect(html).toContain("Détails techniques");
    expect(html).toContain("<dl");
    expect(html).toContain("<code class=\"mono\">aaaaaaaa-0000-4111-8111-000000000001</code>");
    expect(html).not.toContain("Informations techniques");
  });

  it("accepts a custom summary and escapes labels, values and summary", () => {
    const html = dsTechDetails([{ label: "<b>Clé</b>", value: "<script>alert(1)</script>", mono: true }], "<i>Résumé</i>");
    expect(html).toContain("&lt;i&gt;Résumé&lt;/i&gt;");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<b>Clé</b>");
  });

  it("renders an empty string when there is nothing to disclose", () => {
    expect(dsTechDetails([])).toBe("");
  });
});

describe("dsErrorState", () => {
  it("shares the empty-state template but announces as an alert", () => {
    const html = dsErrorState("Chargement impossible", "Réessayez plus tard.");
    expect(html).toContain('role="alert"');
    expect(html).toContain("ds-empty");
    expect(html).toContain("ds-empty--error");
    expect(html).toContain("<h3>Chargement impossible</h3>");
    expect(html).toContain("Réessayez plus tard.");
  });

  it("offers a retry without leaving the page: link or button", () => {
    const link = dsErrorState("Échec", "Message.", { label: "Réessayer", href: "#/ici" });
    expect(link).toContain('href="#/ici"');
    expect(link).toContain("ds-btn--primary");
    const button = dsErrorState("Échec", "Message.", { label: "Réessayer", id: "retry" });
    expect(button).toContain('<button class="ds-btn ds-btn--primary" type="button" id="retry">Réessayer</button>');
  });

  it("escapes user content", () => {
    expect(dsErrorState("<script>", "<b>gras</b>")).not.toContain("<script>");
  });
});

describe("dsStateHtml (les cinq états transverses)", () => {
  const options = { title: "Titre", message: "Message." };

  it("intouvable : l'adresse est rappelée avec un retour unique", () => {
    const html = dsStateHtml("notFound", {
      ...options,
      title: "Adresse inconnue",
      message: "« #/ancien-lien » n'existe pas ou a été déplacée.",
      action: { label: "Retour à l'accueil", href: "#/" },
      details: [{ label: "Route", value: "#/ancien-lien", mono: true }],
    });
    expect(html).toContain('role="status"');
    expect(html).toContain("Adresse inconnue");
    expect(html).toContain("#/ancien-lien");
    expect(html).toContain('<a class="ds-btn ds-btn--primary" href="#/">Retour à l\'accueil</a>');
    expect(html).toContain("<details");
    expect(html).toContain('<code class="mono">#/ancien-lien</code>');
  });

  it("vide : explication + action, sans identifiant par défaut", () => {
    const html = dsStateHtml("empty", { ...options, action: { label: "Lancer", id: "start" } });
    expect(html).toContain('role="status"');
    expect(html).toContain("<h3>Titre</h3>");
    expect(html).toContain('<button class="ds-btn ds-btn--primary" type="button" id="start">Lancer</button>');
    expect(html).not.toContain("<details");
  });

  it("chargement : squelette silencieux, aucune action ni bannière", () => {
    const html = dsStateHtml("loading", options);
    expect(html).toContain("ds-skeleton");
    expect(html).toContain("Chargement en cours");
    expect(html).not.toContain("ds-empty");
    expect(html).not.toContain("ds-notice");
  });

  it("erreur : cause, réessai primaire et détail discret", () => {
    const html = dsStateHtml("error", {
      ...options,
      action: { label: "Réessayer", id: "retry" },
      secondary: { label: "Voir la file", href: "#/offline" },
      details: [{ label: "Cause", value: "connexion" }],
    });
    expect(html).toContain('role="alert"');
    expect(html).toContain("ds-empty--error");
    expect(html).toContain('id="retry"');
    expect(html).toContain('class="ds-btn ds-btn--ghost" href="#/offline"');
  });

  it("hors ligne : statut dégradé, pas de seconde bannière de connexion", () => {
    const html = dsStateHtml("offline", {
      ...options,
      message: "La file locale reste active.",
      action: { label: "Reprendre quand reconnecté", href: "#/" },
      secondary: { label: "Voir la file", href: "#/offline" },
    });
    expect(html).toContain('role="status"');
    expect(html).toContain("ds-notice--warning");
    expect(html).toContain("Hors ligne.");
    expect(html).toContain("La file locale reste active.");
    expect(html.match(/class="ds-notice /g) ?? []).toHaveLength(1);
    expect(html.match(/ds-btn--primary/g) ?? []).toHaveLength(1);
  });

  it("échappe le contenu et n'ajoute aucun style ni gestionnaire (CSP)", () => {
    const html = dsStateHtml("empty", { title: "<script>x</script>", message: "<b>gras</b>" });
    expect(html).not.toContain("<script>");
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
  });
});
