/**
 * P06-targets — mesure des cibles C1–C4 de docs/ux/desktop-dashboard-v2/targets.md
 * sur les parcours S1–S4, aux viewports 1440×900 et 2560×1440.
 *
 * Rappel des critères mesurés ici (contrôle humain C1 exclu, non automatisable) :
 * - C1 : une action primaire « verbe + objet » visible, ≤ cible de clics jusqu'à
 *        la destination du parcours.
 * - C2 : aucun UUID ni préfixe hex de 8 caractères dans innerText / title /
 *        aria-label / placeholder par défaut (sections repliées).
 * - C3 : ≤ 7 éléments [data-major] visibles hors sections repliées par page,
 *        navigation principale = 5 quotidiennes + 1 entrée Administration.
 * - C4 : exactement 1 [data-testid=connection-status] par page.
 *
 * Contrainte : aucun fichier de dashboard/src n'est modifié. Si un critère
 * échoue réellement (côté produit), le test doit être marqué test.fixme avec un
 * commentaire précis (page, sélecteur, valeur mesurée), et l'écart est listé
 * dans le message final.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
import {
  expectClean,
  globalOverflow,
  login,
  newCaptured,
  watchErrors,
  P1,
  type Captured,
} from "./support/ui16-stub";

const ROADMAP_ID = "r-p06";

const VIEWPORTS = [
  { width: 1440, height: 900, label: "1440×900" },
  { width: 2560, height: 1440, label: "2560×1440" },
] as const;

type Viewport = (typeof VIEWPORTS)[number];
type ScenarioId = "S1" | "S2" | "S3" | "S4";

/** Nombre de clics maximal autorisé par la cible C1. */
const MAX_CLICKS: Record<ScenarioId, number> = { S1: 1, S2: 2, S3: 2, S4: 2 };

/** Verbes d'action primaire admis (cible C1 : « verbe + objet »). */
const PRIMARY_VERB_RE = /^(reprendre|ouvrir|approuver|trancher|examiner|accepter|continuer|démarrer|prendre|modifier)/i;

const UUID_FULL_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
/** Préfixe hexadécimal de 8 caractères, isolé d'un UUID ou d'une chaîne hex plus longue. */
const HEX8_PREFIX_RE = /(?<![0-9a-fA-F-])[0-9a-fA-F]{8}(?![0-9a-fA-F-])/;

const P06_JSON = (body: unknown, status = 200): { status: number; contentType: string; body: string } => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

interface Scenario {
  id: ScenarioId;
  label: string;
  /** Page d'entrée du parcours (mesurée avant C1). */
  entry: string;
  setup: (page: Page, captured: Captured) => Promise<void>;
}

/**
 * Roadmap active avec 8 phases terminées : le plan replie les phases faites en
 * un seul élément et laisse l'étape courante visible sans défilement.
 */
function roadmapStep(key: string, title: string, state: string) {
  return {
    id: `st-${key}`,
    roadmap_id: ROADMAP_ID,
    phase_id: "ph",
    key,
    position: 0,
    title,
    state,
    available: state === "in_progress",
    waiting_on: [],
    acceptance_criteria: ["Le parcours S4 est mesurable"],
    depends_on: [],
    tasks: [],
    linked_tasks: [],
    criteria_checked: [],
  };
}

function roadmapFixture() {
  const phases = Array.from({ length: 10 }, (_, index) => {
    const done = index < 8;
    const key = done ? `D${index + 1}` : index === 8 ? "S9" : "S10";
    const state = done ? "done" : index === 8 ? "in_progress" : "not_started";
    return {
      id: `ph${index + 1}`,
      roadmap_id: ROADMAP_ID,
      key: `P${index + 1}`,
      position: index,
      title: `Phase ${index + 1}`,
      progress: { done: done ? 1 : 0, total: 1, skipped: 0, ratio: done ? 1 : 0 },
      steps: [roadmapStep(key, `Étape ${index + 1}`, state)],
    };
  });
  return {
    id: ROADMAP_ID,
    project_id: P1,
    title: "Plan P06",
    objective: "Mesurer les cibles C1–C4 sur le parcours Projet → roadmap",
    status: "active",
    revision_no: 2,
    approved_revision_no: 2,
    version: 4,
    progress: { done: 8, total: 10, skipped: 0, ratio: 0.8 },
    current_step_key: "S9",
    phases,
  };
}

/** Routes roadmap spécifiques, enregistrées après login pour primer sur le stub générique. */
async function mockRoadmapApi(page: Page): Promise<void> {
  const full = roadmapFixture();
  const summary = { ...full, phases: undefined };
  await page.route(new RegExp(`/api/v1/projects/${P1}/roadmaps(\\?.*)?$`), (route) => route.fulfill(P06_JSON([summary])));
  await page.route(new RegExp(`/api/v1/roadmaps/${ROADMAP_ID}$`), (route) => route.fulfill(P06_JSON(full)));
  await page.route(new RegExp(`/api/v1/roadmaps/${ROADMAP_ID}/revisions`), (route) => route.fulfill(P06_JSON([])));
}

const SCENARIOS: Scenario[] = [
  {
    id: "S1",
    label: "Accueil → tâche",
    entry: "#/",
    setup: async (page, captured) => {
      await login(page, "#/", captured);
    },
  },
  {
    id: "S2",
    label: "Travail → reprise",
    entry: "#/tasks",
    setup: async (page, captured) => {
      await login(page, "#/tasks", captured);
    },
  },
  {
    id: "S3",
    label: "À valider → décision",
    entry: "#/decisions",
    setup: async (page, captured) => {
      await login(page, "#/decisions", captured);
    },
  },
  {
    id: "S4",
    label: "Projet → roadmap",
    entry: "#/projects",
    setup: async (page, captured) => {
      await login(page, "#/projects", captured);
      await mockRoadmapApi(page);
    },
  },
];

async function auditPage(
  page: Page,
  scenario: Scenario,
  viewport: Viewport,
  point: "entrée" | "destination",
): Promise<string[]> {
  const failures: string[] = [];
  const where = `${scenario.id} ${point} (${viewport.label})`;

  failures.push(...(await checkC2(page, where)));
  failures.push(...(await checkC3(page, where)));
  failures.push(...(await checkC4(page, where)));

  return failures;
}

/** C2 — aucun identifiant technique dans le contenu ou les attributs par défaut. */
async function checkC2(page: Page, where: string): Promise<string[]> {
  const { text, attrs } = await page.evaluate(() => {
    const inClosedDetails = (el: Element): boolean => {
      const details = el.closest("details");
      return details !== null && !(details as HTMLDetailsElement).open;
    };
    const collected: { attr: string; value: string }[] = [];
    for (const attr of ["title", "aria-label", "placeholder"]) {
      for (const el of Array.from(document.querySelectorAll(`[${attr}]`))) {
        if (inClosedDetails(el)) continue;
        const value = el.getAttribute(attr);
        if (value !== null && value.trim() !== "") collected.push({ attr, value });
      }
    }
    return { text: document.body.innerText, attrs: collected };
  });

  const haystacks: { origin: string; value: string }[] = [
    { origin: "innerText", value: text },
    ...attrs.map((entry) => ({ origin: entry.attr, value: entry.value })),
  ];

  const hits: string[] = [];
  for (const { origin, value } of haystacks) {
    const uuid = value.match(UUID_FULL_RE);
    if (uuid !== null) hits.push(`${origin}="${value.slice(0, 120)}" → UUID ${uuid[0]}`);
    const hex = value.match(HEX8_PREFIX_RE);
    if (hex !== null) hits.push(`${origin}="${value.slice(0, 120)}" → préfixe hex 8 ${hex[0]}`);
  }

  if (hits.length > 0) {
    return [`C2 échec ${where} : ${hits.length} identifiant(s) technique(s) exposé(s) par défaut — ${hits.slice(0, 6).join(" | ")}`];
  }
  return [];
}

/** C3 — ≤ 7 éléments majeurs visibles + navigation 5 quotidiennes + Administration. */
async function checkC3(page: Page, where: string): Promise<string[]> {
  const failures: string[] = [];

  const visibleMajor = await page.locator("[data-major]").evaluateAll((els) =>
    els.filter((el) => {
      const style = window.getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return false;
      let parent: Element | null = el.parentElement;
      while (parent !== null) {
        const parentStyle = window.getComputedStyle(parent);
        if (parentStyle.display === "none" || parentStyle.visibility === "hidden" || parentStyle.opacity === "0") return false;
        if (parent.tagName === "DETAILS" && !parent.hasAttribute("open")) return false;
        parent = parent.parentElement;
      }
      return true;
    }).length,
  );

  if (visibleMajor > 7) {
    failures.push(
      `C3 échec ${where} : ${visibleMajor} éléments [data-major] visibles (max 7) — page : ${page.url().replace(/^https?:\/\/[^/]+/, "")}`,
    );
  }

  const dailyCount = await page.locator(".app-navgroup").first().locator("a.app-navlink").count();
  if (dailyCount !== 5) {
    failures.push(`C3 échec nav ${where} : ${dailyCount} entrées quotidiennes (attendu 5)`);
  }
  const adminCount = await page.locator('.app-sidebar a[href="#/administration"]').count();
  if (adminCount !== 1) {
    failures.push(`C3 échec nav ${where} : ${adminCount} entrée(s) Administration (attendu 1)`);
  }

  return failures;
}

/** C4 — exactement un indicateur de connexion par page. */
async function checkC4(page: Page, where: string): Promise<string[]> {
  const count = await page.locator('[data-testid="connection-status"]').count();
  if (count !== 1) {
    return [`C4 échec ${where} : ${count} élément(s) [data-testid=connection-status] (attendu exactement 1)`];
  }
  return [];
}

async function aboveFold(page: Page, locator: Locator): Promise<boolean> {
  if ((await locator.count()) === 0) return false;
  if (!(await locator.first().isVisible())) return false;
  const box = await locator.first().boundingBox();
  const height = page.viewportSize()?.height ?? 0;
  return box !== null && box.y < height && box.y + box.height > 0;
}

/**
 * C1 — vérifie l'action primaire du parcours et rejoue le parcours en comptant
 * les clics jusqu'à la destination.
 */
async function checkC1(page: Page, scenario: Scenario, viewport: Viewport): Promise<string[]> {
  const failures: string[] = [];
  const where = `${scenario.id} (${viewport.label})`;
  const reportClicks = (clicks: number): void => {
    if (clicks > MAX_CLICKS[scenario.id]) {
      failures.push(`C1 échec ${where} : ${clicks} clics jusqu'à la destination (cible ≤ ${MAX_CLICKS[scenario.id]})`);
    }
  };

  if (scenario.id === "S1") {
    const primary = page.locator(".home-section--work .ds-hero .ds-hero-actions a.ds-btn--primary");
    const count = await primary.count();
    if (count !== 1) {
      failures.push(`C1 échec ${where} : ${count} action(s) primaire(s) dans le héros « À faire maintenant » (attendu 1) — sélecteur .home-section--work .ds-hero .ds-hero-actions a.ds-btn--primary`);
      return failures;
    }
    const label = (await primary.innerText()).trim();
    const href = await primary.getAttribute("href");
    if (!PRIMARY_VERB_RE.test(label)) failures.push(`C1 échec ${where} : libellé « ${label} » sans « verbe + objet »`);
    if (href === null || !/^#\/tasks\/[^/]+$/.test(href)) failures.push(`C1 échec ${where} : action primaire « ${href} » sans lien vers une fiche tâche`);
    if (!(await aboveFold(page, primary))) failures.push(`C1 échec ${where} : action primaire hors de la ligne de flottaison`);
    await primary.click();
    await expect(page.locator(".task-detail-hero")).toBeVisible();
    await expect(page).toHaveURL(/#\/tasks\/[^/]+$/);
    reportClicks(1);
  } else if (scenario.id === "S2") {
    await expect(page.locator('#view [data-scope="now"]')).toHaveAttribute("aria-pressed", "true");
    const link = page.locator('#view .task-row a[href^="#/tasks/"]').first();
    if ((await link.count()) === 0) {
      failures.push(`C1 échec ${where} : aucune tâche dans la vue « Maintenant » (sélecteur #view .task-row a[href^="#/tasks/"])`);
      return failures;
    }
    await link.click();
    await expect(page.locator(".task-detail-hero")).toBeVisible();
    const primary = page.locator(".task-detail-hero .ds-hero-actions .ds-btn--primary");
    const count = await primary.count();
    if (count !== 1) {
      failures.push(`C1 échec ${where} : ${count} action(s) primaire(s) dans la fiche (attendu 1) — sélecteur .task-detail-hero .ds-hero-actions .ds-btn--primary`);
    } else {
      const label = (await primary.innerText()).trim();
      if (!PRIMARY_VERB_RE.test(label)) failures.push(`C1 échec ${where} : action de la fiche « ${label} » sans « verbe + objet »`);
      if (!(await aboveFold(page, primary))) failures.push(`C1 échec ${where} : action de la fiche hors ligne de flottaison`);
    }
    reportClicks(1);
  } else if (scenario.id === "S3") {
    const primary = page.locator(".review-hero .ds-hero-actions .ds-btn--primary");
    const count = await primary.count();
    if (count !== 1) {
      failures.push(`C1 échec ${where} : ${count} action(s) primaire(s) dans le héros « À valider » (attendu 1) — sélecteur .review-hero .ds-hero-actions .ds-btn--primary`);
    } else {
      const label = (await primary.innerText()).trim();
      if (!PRIMARY_VERB_RE.test(label)) failures.push(`C1 échec ${where} : action « ${label} » sans « verbe + objet »`);
      if (!(await aboveFold(page, primary))) failures.push(`C1 échec ${where} : action primaire hors ligne de flottaison`);
    }
    // L'action vit dans la file : aucun clic supplémentaire pour la rejoindre.
    reportClicks(0);
  } else {
    // S4 : Projet (1 clic) → onglet Roadmap (1 clic) = 2 clics.
    const card = page.locator(`#view a[data-open="${P1}"]`).first();
    if ((await card.count()) === 0) {
      failures.push(`C1 échec ${where} : carte projet introuvable (sélecteur #view a[data-open="${P1}"])`);
      return failures;
    }
    await card.click();
    await expect(page.locator("#workspace-panel")).toBeVisible();
    const tab = page.locator('[data-ws-tab="roadmap"]').first();
    if ((await tab.count()) === 0) {
      failures.push(`C1 échec ${where} : onglet Roadmap introuvable (sélecteur [data-ws-tab="roadmap"])`);
      return failures;
    }
    await tab.click();
    const current = page.locator("[data-current-step]");
    await expect(current).toBeVisible({ timeout: 15_000 });
    const currentCount = await page.locator("[data-current-step]").count();
    if (currentCount !== 1) {
      failures.push(`C1 échec ${where} : ${currentCount} étape(s) courante(s) (attendu 1) — sélecteur [data-current-step]`);
    } else {
      const stepCount = await current.locator(".roadmap-step").count();
      if (stepCount !== 1) failures.push(`C1 échec ${where} : ${stepCount} étape(s) dans la carte courante (attendu 1)`);
      if (!(await aboveFold(page, current))) failures.push(`C1 échec ${where} : étape courante hors ligne de flottaison`);
    }
    reportClicks(2);
  }

  return failures;
}

for (const viewport of VIEWPORTS) {
  test.describe(`P06-targets — ${viewport.label}`, () => {
    for (const scenario of SCENARIOS) {
      test(`${scenario.id} ${scenario.label} : C1–C4`, async ({ page }) => {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        const captured = newCaptured();
        const errors = watchErrors(page);

        await scenario.setup(page, captured);

        await expectClean(errors);
        expect(await globalOverflow(page), `overflow global entrée : ${scenario.id} ${viewport.label}`).toBe(0);

        const failures: string[] = [];
        failures.push(...(await auditPage(page, scenario, viewport, "entrée")));
        failures.push(...(await checkC1(page, scenario, viewport)));
        if (scenario.id !== "S3") {
          failures.push(...(await auditPage(page, scenario, viewport, "destination")));
        }

        await expectClean(errors);
        expect(await globalOverflow(page), `overflow global destination : ${scenario.id} ${viewport.label}`).toBe(0);

        if (failures.length > 0) {
          expect(false, failures.join(" ; ")).toBe(true);
        }
      });
    }
  });
}
