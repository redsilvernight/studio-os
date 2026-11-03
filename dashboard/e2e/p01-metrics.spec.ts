/**
 * P01-metrics — mesure de la baseline du budget UI, sans aucune modification de
 * `dashboard/src` (cf. docs/ux/desktop-dashboard-v2/targets.md, P01-success-metrics).
 *
 * Ce que la spec relève, par écran et par parcours, à 1440×900 :
 * - `majors`  : éléments majeurs visibles par défaut (C3). Un élément majeur est
 *               une entrée de navigation de premier niveau, un bloc / carte /
 *               section de premier niveau d'une page, ou un onglet d'un détail
 *               (vocabulaire targets.md § « Conditions de mesure »). Un contrôle
 *               à l'intérieur d'un bloc (bouton, ligne de liste) n'en est pas un.
 *               Cible : ≤ 7.
 * - `uuids`   : occurrences d'un UUID complet ou d'un préfixe hexadécimal de
 *               8 caractères dans le texte rendu par défaut — `innerText` plus
 *               `title` / `aria-label` / `placeholder`, sections repliées exclues
 *               (C2). Cible : 0.
 * - `connection` : indicateurs de connexion visibles (`data-testid=connection-status`).
 *               Cible : exactement 1 (C4).
 * - `clics`   : nombre de clics jusqu'à la destination du parcours (C1), pour
 *               S1–S4 de targets.md.
 * - `bundle`  : taille gzip de la fermeture de chargement initiale (chunk d'entrée
 *               + imports statiques transitifs de `dist/`), cible ≤ 60 kB
 *               (INITIAL_JS_GZIP_BUDGET de scripts/analyze-bundle.mjs).
 *
 * Sortie : `e2e/p01-metrics.json`, écrit une fois en `afterAll` si `P01_METRICS_WRITE=1` — écran → valeur,
 * cible, `over_budget`, plus la date de mesure et le SHA du commit mesuré.
 *
 * Contrat de la baseline : un dépassement de cible ne fait PAS échouer le test.
 * Il est enregistré `over_budget: true` et se lit dans le rapport de run. Seul un
 * écran qui ne peut pas être atteint, ou une mesure impossible à produire, échoue :
 * une baseline silencieusement vide ne vaut rien.
 */
import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { go, login, newCaptured, P1, T1, type Captured } from "./support/ui16-stub";

const VIEWPORT = { width: 1440, height: 900 } as const;

/** Cibles issues de targets.md (C1–C4) et de scripts/analyze-bundle.mjs. */
const TARGET_MAJORS = 7;
const TARGET_UUIDS = 0;
const TARGET_CONNECTION = 1;
const TARGET_BUNDLE_GZIP_BYTES = 60 * 1024;
const MAX_CLICKS: Record<ScenarioId, number> = { S1: 1, S2: 2, S3: 2, S4: 2 };

const UUID_FULL_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
/** Préfixe hexadécimal de 8 caractères, isolé d'un UUID ou d'une chaîne hex plus longue. */
const HEX8_PREFIX_RE = /(?<![0-9a-fA-F-])[0-9a-fA-F]{8}(?![0-9a-fA-F-])/g;

const ROADMAP_ID = "r-p01";

interface Screen {
  id: string;
  label: string;
  /** Route hash mesurée. */
  hash: string;
  /** Éléments majeurs de cet écran (vocabulaire C3). */
  majors: string;
  /** Locator qui prouve que l'écran est rendu. */
  ready: string;
  /** La roadmap a besoin de son jeu de données (10 phases, 8 terminées). */
  needsRoadmap?: boolean;
}

type ScenarioId = "S1" | "S2" | "S3" | "S4";

interface Journey {
  id: ScenarioId;
  label: string;
  entry: string;
  /** Destination atteinte après le décompte : sélecteur qui doit devenir visible. */
  destination: string;
  run: (page: Page) => Promise<number>;
}

/** Mesure à seuil maximal (`value > target` = dépassement). */
interface Budget {
  value: number;
  target: number;
  over_budget: boolean;
}

/** Mesure à seuil exact (écart par rapport à `target` = dépassement). */
interface ExactMeasure {
  value: number;
  target: number;
  over_budget: boolean;
}

interface ScreenReport {
  label: string;
  hash: string;
  majors: Budget & { selector: string; data_major: number };
  uuids: Budget & { uuid: number; hex8: number; samples: string[] };
  connection: ExactMeasure;
}

interface JourneyReport {
  label: string;
  entry: string;
  clicks: Budget & { destination: string };
}

const SCREENS: readonly Screen[] = [
  {
    id: "accueil",
    label: "Accueil",
    hash: "#/",
    majors: "#view .home > *",
    ready: "#view .home",
  },
  {
    id: "travail",
    label: "Travail",
    hash: "#/tasks",
    majors: "#view .tasks > :is(section.tasks-group, .tasks-scopes, .tasks-toolbar)",
    ready: "#view .tasks",
  },
  {
    id: "a-valider",
    label: "À valider",
    hash: "#/decisions",
    // Onglets du détail + section de premier niveau du panneau actif.
    majors: "#view .ds-tabs > .ds-tab, #view .ds-tabpanel:not([hidden]) > div > section",
    ready: "#view .review-section",
  },
  {
    id: "projet",
    label: "Projet (onglets)",
    hash: `#/projects/${P1}`,
    majors: "#view [data-ws-tab], #view .workspace-more > summary.ds-tab",
    ready: "#workspace-panel",
  },
  {
    id: "roadmap",
    label: "Roadmap",
    hash: `#/projects/${P1}/roadmap`,
    majors: "#view [data-major]",
    ready: "#view .roadmap-phase-strip",
    needsRoadmap: true,
  },
  {
    id: "fiche-tache",
    label: "Fiche tâche",
    hash: `#/tasks/${T1}`,
    majors: "#view .task-detail-hero, #view .task-detail-main > section",
    ready: "#view .task-detail-hero",
  },
];

/* ------------------------------------------------------------------ fixtures */

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

/** Plan actif : 8 phases terminées repliées, étape courante visible. */
function roadmapFixture(): Record<string, unknown> {
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
    title: "Plan P01",
    objective: "Mesurer la baseline du budget UI",
    status: "active",
    revision_no: 2,
    approved_revision_no: 2,
    version: 4,
    progress: { done: 8, total: 10, skipped: 0, ratio: 0.8 },
    current_step_key: "S9",
    phases,
  };
}

async function mockRoadmapApi(page: Page): Promise<void> {
  const full = roadmapFixture();
  const summary = { ...full, phases: undefined };
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route(new RegExp(`/api/v1/projects/${P1}/roadmaps(\\?.*)?$`), (route) => route.fulfill(json([summary])));
  await page.route(new RegExp(`/api/v1/roadmaps/${ROADMAP_ID}$`), (route) => route.fulfill(json(full)));
  await page.route(new RegExp(`/api/v1/roadmaps/${ROADMAP_ID}/revisions`), (route) => route.fulfill(json([])));
}

/* ------------------------------------------------------------------- mesure */

/**
 * Éléments visibles par défaut : ni `display: none` / `visibility: hidden` /
 * opacité nulle sur l'élément ou un ancêtre, ni boîte nulle, ni contenu d'un
 * `<details>` replié (même règle que p06-targets).
 */
async function visibleCount(page: Page, selector: string): Promise<number> {
  return page.locator(selector).evaluateAll((els) =>
    els.filter((el) => {
      const hidden = (node: Element): boolean => {
        const style = window.getComputedStyle(node);
        return style.display === "none" || style.visibility === "hidden" || style.opacity === "0";
      };
      if (hidden(el)) return false;
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return false;
      let parent: Element | null = el.parentElement;
      while (parent !== null) {
        if (hidden(parent)) return false;
        if (parent.tagName === "DETAILS" && !parent.hasAttribute("open")) return false;
        parent = parent.parentElement;
      }
      return true;
    }).length,
  );
}

/** Occurrences d'identifiants techniques dans le rendu visible par défaut. */
async function countUuidHits(
  page: Page,
): Promise<{ uuid: number; hex8: number; samples: string[] }> {
  const { text, attrs } = await page.evaluate(() => {
    const inClosedDetails = (el: Element): boolean => {
      const details = el.closest("details");
      return details !== null && !(details as HTMLDetailsElement).open;
    };
    const collected: string[] = [];
    for (const attr of ["title", "aria-label", "placeholder"]) {
      for (const el of Array.from(document.querySelectorAll(`[${attr}]`))) {
        if (inClosedDetails(el)) continue;
        const value = el.getAttribute(attr);
        if (value !== null && value.trim() !== "") collected.push(`${attr}="${value}"`);
      }
    }
    return { text: document.body.innerText, attrs: collected };
  });

  const haystacks: string[] = [text, ...attrs];
  let uuid = 0;
  let hex8 = 0;
  const samples: string[] = [];
  for (const value of haystacks) {
    for (const hit of value.matchAll(UUID_FULL_RE)) {
      uuid += 1;
      if (samples.length < 6) samples.push(`UUID ${hit[0]}`);
    }
    for (const hit of value.matchAll(HEX8_PREFIX_RE)) {
      hex8 += 1;
      if (samples.length < 6) samples.push(`hex8 ${hit[0]}`);
    }
  }
  return { uuid, hex8, samples };
}

async function measureScreen(page: Page, screen: Screen): Promise<ScreenReport> {
  const majors = await visibleCount(page, screen.majors);
  const dataMajor = await visibleCount(page, "#view [data-major]");
  const hits = await countUuidHits(page);
  const uuids = hits.uuid + hits.hex8;
  const connection = await visibleCount(page, '[data-testid="connection-status"]');

  return {
    label: screen.label,
    hash: screen.hash,
    majors: {
      value: majors,
      target: TARGET_MAJORS,
      over_budget: majors > TARGET_MAJORS,
      selector: screen.majors,
      data_major: dataMajor,
    },
    uuids: {
      value: uuids,
      target: TARGET_UUIDS,
      over_budget: uuids > TARGET_UUIDS,
      ...hits,
    },
    connection: {
      value: connection,
      target: TARGET_CONNECTION,
      over_budget: connection !== TARGET_CONNECTION,
    },
  };
}

/* ---------------------------------------------------------------- parcours */

/**
 * Rejoue S1–S4 comme targets.md les décrit et renvoie le nombre de clics
 * effectués jusqu'à la destination. Le sélecteur de destination doit devenir
 * visible : un parcours qui n'aboutit pas est une régression, pas un budget.
 */
const JOURNEYS: readonly Journey[] = [
  {
    id: "S1",
    label: "Accueil → tâche",
    entry: "#/",
    destination: ".task-detail-hero",
    run: async (page) => {
      const primary = page.locator(".home-section--work .ds-hero .ds-hero-actions a.ds-btn--primary").first();
      await expect(primary).toBeVisible();
      await primary.click();
      return 1;
    },
  },
  {
    id: "S2",
    label: "Travail → reprise",
    entry: "#/tasks",
    destination: ".task-detail-hero",
    run: async (page) => {
      await expect(page.locator('#view [data-scope="now"]')).toHaveAttribute("aria-pressed", "true");
      const link = page.locator('#view .task-row a[href^="#/tasks/"]').first();
      await expect(link).toBeVisible();
      await link.click();
      // « Reprendre » vit dans le héros de la fiche : aucun clic supplémentaire.
      await expect(page.locator(".task-detail-hero .ds-hero-actions .ds-btn--primary")).toHaveCount(1);
      return 1;
    },
  },
  {
    id: "S3",
    label: "À valider → décision",
    entry: "#/decisions",
    destination: ".review-hero .ds-hero-actions .ds-btn--primary",
    run: async () => 0,
  },
  {
    id: "S4",
    label: "Projet → roadmap",
    entry: "#/projects",
    destination: "[data-current-step]",
    run: async (page) => {
      await page.locator(`#view a[data-open="${P1}"]`).first().click();
      await expect(page.locator("#workspace-panel")).toBeVisible();
      await page.locator('[data-ws-tab="roadmap"]').first().click();
      await expect(page.locator("[data-current-step]")).toBeVisible({ timeout: 15_000 });
      return 2;
    },
  },
];

/* ------------------------------------------------------------------ bundle */

/** Racine du paquet dashboard (contient playwright.config.ts). */
function dashboardRoot(): string {
  for (const candidate of [process.cwd(), path.resolve(process.cwd(), "..")]) {
    if (existsSync(path.join(candidate, "playwright.config.ts"))) return candidate;
  }
  return process.cwd();
}

/**
 * Taille gzip de la fermeture de chargement initiale : chunk d'entrée désigné
 * par `dist/index.html` + imports statiques transitifs (les imports dynamiques
 * sont exclus par construction). Même définition et même compression que
 * `npm run analyze:bundle`.
 */
function measureBundle(root: string): { entry: string; chunks: string[]; gzip_bytes: number } {
  const dist = path.join(root, "dist");
  const html = readFileSync(path.join(dist, "index.html"), "utf8");
  const entry = /<script[^>]+src="\/assets\/([^"]+\.js)"/.exec(html)?.[1];
  if (entry === undefined) throw new Error("dist/index.html ne déclare aucun chunk d'entrée");

  const chunks: string[] = [];
  let gzipBytes = 0;
  const queue = [entry];
  while (queue.length > 0) {
    const name = queue.shift() as string;
    if (chunks.includes(name)) continue;
    const code = readFileSync(path.join(dist, "assets", name));
    chunks.push(name);
    gzipBytes += gzipSync(code).length;
    const text = code.toString("utf8");
    for (const match of text.matchAll(/from"\.\/([\w.-]+\.js)"/g)) queue.push(match[1] as string);
    for (const match of text.matchAll(/import"\.\/([\w.-]+\.js)"/g)) queue.push(match[1] as string);
  }
  return { entry, chunks, gzip_bytes: gzipBytes };
}

function gitSha(): string {
  for (const cwd of [dashboardRoot(), path.resolve(dashboardRoot(), "..")]) {
    try {
      return execFileSync("git", ["rev-parse", "HEAD"], { cwd, encoding: "utf8" }).trim();
    } catch {
      // Répertoire hors dépôt : on tente le parent, sinon « unknown ».
    }
  }
  return "unknown";
}

/* ------------------------------------------------------------------ rapport */

const report = {
  generated_at: "",
  git_sha: "",
  viewport: `${VIEWPORT.width}×${VIEWPORT.height}`,
  source: "dashboard/e2e/p01-metrics.spec.ts",
  targets: {
    majors: TARGET_MAJORS,
    uuids: TARGET_UUIDS,
    connection: TARGET_CONNECTION,
    initial_js_gzip_bytes: TARGET_BUNDLE_GZIP_BYTES,
  },
  screens: {} as Record<string, ScreenReport>,
  journeys: {} as Record<string, JourneyReport>,
  bundle: undefined as
    | ({ source: string; entry: string; chunks: string[]; gzip_bytes: number; gzip_kb: number } & Budget)
    | undefined,
};

test.afterAll(async () => {
  // La suite e2e complète (CI comprise) mesure sans réécrire la baseline commitée.
  if (process.env.P01_METRICS_WRITE !== "1") return;
  report.generated_at = new Date().toISOString();
  report.git_sha = gitSha();
  await writeFile(
    path.join(dashboardRoot(), "e2e", "p01-metrics.json"),
    `${JSON.stringify(report, null, 2)}\n`,
    "utf8",
  );
});

test.beforeAll(() => {
  const bundle = measureBundle(dashboardRoot());
  report.bundle = {
    source: "dist/ (npm run build, fermeture d'imports statiques)",
    entry: bundle.entry,
    chunks: bundle.chunks,
    gzip_bytes: bundle.gzip_bytes,
    gzip_kb: Number((bundle.gzip_bytes / 1024).toFixed(2)),
    value: bundle.gzip_bytes,
    target: TARGET_BUNDLE_GZIP_BYTES,
    over_budget: bundle.gzip_bytes > TARGET_BUNDLE_GZIP_BYTES,
  };
});

async function open(page: Page, captured: Captured, hash: string, needsRoadmap: boolean): Promise<void> {
  await login(page, "#/", captured);
  if (needsRoadmap) await mockRoadmapApi(page);
  if (hash !== "#/") await go(page, hash);
}

for (const screen of SCREENS) {
  test(`baseline ${screen.id} — ${screen.label}`, async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await open(page, newCaptured(), screen.hash, screen.needsRoadmap === true);
    await expect(page.locator(screen.ready)).toBeVisible({ timeout: 15_000 });
    report.screens[screen.id] = await measureScreen(page, screen);
    // Erreur de rendu = mesure invalide : ici on échoue, pas de « baseline » muette.
    expect(report.screens[screen.id], `mesure absente pour ${screen.id}`).toBeTruthy();
  });
}

for (const journey of JOURNEYS) {
  test(`baseline ${journey.id} — ${journey.label}`, async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    const captured = newCaptured();
    await login(page, journey.entry, captured);
    if (journey.id === "S4") await mockRoadmapApi(page);

    const clicks = await journey.run(page);
    await expect(page.locator(journey.destination).first()).toBeVisible({ timeout: 15_000 });

    report.journeys[journey.id] = {
      label: journey.label,
      entry: journey.entry,
      clicks: {
        value: clicks,
        target: MAX_CLICKS[journey.id],
        over_budget: clicks > MAX_CLICKS[journey.id],
        destination: journey.destination,
      },
    };
  });
}

test("baseline bundle — chargement initial gzip", async () => {
  expect(report.bundle, "mesure du bundle absente (beforeAll ?)").toBeTruthy();
  expect(report.bundle?.chunks.length, "la fermeture initiale doit contenir le chunk d'entrée").toBeGreaterThan(0);
});
