import { describe, expect, it } from "vitest";
import {
  dsAgentBadge,
  dsAvatar,
  dsBadge,
  dsDrawerHtml,
  dsEmptyState,
  dsField,
  dsMetric,
  dsModalHtml,
  dsPageHeader,
  dsProgress,
  dsSectionHeader,
  dsSkeleton,
  dsStatus,
  dsTabsHtml,
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
  it("is announced busy and hides decorative bars", () => {
    const html = dsSkeleton(2);
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("Chargement en cours");
    expect(html).toContain('aria-hidden="true"');
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
    expect(html).toContain('aria-label="Amina Benali"');
    expect(dsAgentBadge("Auxiliaire")).toContain("ds-badge--ai");
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
