/**
 * UI-16 — Clôture de la refonte UI/UX : cohérence finale et non-régression.
 *
 * Cette suite ne duplique pas UI-13/14/15 : elle vérifie ce que la phase de
 * polish a changé (copy humaine, erreurs lisibles, confirmations, liens,
 * réservations, titres uniques, scroll après navigation) et rejoue en stress
 * les invariants historiques (double-soumission, modale, tiroir, navigation).
 * API entièrement stubbée ; zéro pageerror, zéro violation CSP.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { globalOverflow, go, LIB_ID, login, newCaptured, P1, T1, UUID_RE, ISO_RE, expectClean, watchErrors } from "./support/ui16-stub";

const ROUTES = [
  "#/",
  "#/projects",
  `#/projects/${P1}`,
  `#/projects/${P1}/tasks`,
  `#/projects/${P1}/claims`,
  `#/projects/${P1}/activity`,
  `#/projects/${P1}/decisions`,
  "#/tasks",
  `#/tasks/${T1}`,
  "#/agents",
  "#/agents/ag-claude",
  "#/library",
  "#/library/rules",
  `#/library/rules/${LIB_ID}`,
  "#/decisions",
  "#/machines",
  "#/transfers",
  "#/inspector",
  "#/configuration/runtimes",
  "#/configuration/runtimes/rt1",
  "#/configuration/bindings",
  "#/configuration/project",
  "#/design-system",
];

/** Écouteurs actifs sur document/window, par type (ajouts − retraits). */
async function installListenerProbe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const live = new Map<string, Set<EventListenerOrEventListenerObject>>();
    const key = (target: EventTarget, type: string): string | null =>
      target === document ? `document:${type}` : target === window ? `window:${type}` : null;
    const add = EventTarget.prototype.addEventListener;
    const remove = EventTarget.prototype.removeEventListener;
    EventTarget.prototype.addEventListener = function (this: EventTarget, type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions) {
      const k = key(this, type);
      if (k !== null && listener !== null) {
        if (!live.has(k)) live.set(k, new Set());
        live.get(k)!.add(listener);
      }
      return add.call(this, type, listener as EventListenerOrEventListenerObject, options);
    } as typeof EventTarget.prototype.addEventListener;
    EventTarget.prototype.removeEventListener = function (this: EventTarget, type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | EventListenerOptions) {
      const k = key(this, type);
      if (k !== null && listener !== null) live.get(k)?.delete(listener);
      return remove.call(this, type, listener as EventListenerOrEventListenerObject, options);
    } as typeof EventTarget.prototype.removeEventListener;
    (window as unknown as { __liveListeners: () => Record<string, number> }).__liveListeners = () =>
      Object.fromEntries([...live.entries()].map(([k, v]) => [k, v.size]));
  });
}

async function liveListeners(page: Page): Promise<Record<string, number>> {
  return page.evaluate(() => (window as unknown as { __liveListeners: () => Record<string, number> }).__liveListeners());
}

test.describe("UI-16 copy, routes et liens", () => {
  test("balayage des routes : un seul h1, aucune route morte, copy humaine, dates et identifiants lisibles", async ({ page }) => {
    test.setTimeout(180_000);
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, "#/", newCaptured());
    const forbidden: Array<[string, RegExp]> = [
      ["endpoint HTTP", /\b(GET|POST|PATCH|PUT|DELETE) \/[a-z]/],
      ["jargon idempotence", /idempot/i],
      ["ancien titre", /Décisions & Review/],
      ["libellé Recharger", /Recharger/],
      ["code de phase", /\bUI-\d+\b/],
      ["jargon claim", /\bclaims?\b/i],
      ["valeur brute", /\bundefined\b|\[object |\bNaN\b|\bnull\b/],
      ["statut brut", /\b(created|in_progress|completed)\b/],
    ];
    for (const hash of ROUTES) {
      if (hash !== "#/") await go(page, hash);
      const view = page.locator("#view");
      await expect(view.locator("h1"), `${hash} : exactement un h1`).toHaveCount(1);
      const text = await view.innerText();
      expect(text, `${hash} : pas de page introuvable`).not.toContain("Page introuvable");
      for (const [label, re] of forbidden) {
        // L'Inspecteur est la surface technique : son pied de formulaire cite l'endpoint.
        if (label === "endpoint HTTP" && hash === "#/inspector") continue;
        expect(text, `${hash} : ${label}`).not.toMatch(re);
      }
      expect(text, `${hash} : horodatage ISO en clair`).not.toMatch(ISO_RE);
      if (hash !== "#/design-system") expect(text, `${hash} : UUID complet en clair`).not.toMatch(UUID_RE);
      expect(await page.locator("[style]").count(), `${hash} : style inline`).toBe(0);
    }
    expectClean(watch);
  });

  test("liens internes : aucun CTA ne mène à une route fictive", async ({ page }) => {
    test.setTimeout(240_000);
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, "#/", newCaptured());
    const hrefs = new Set<string>();
    for (const hash of ROUTES) {
      if (hash !== "#/") await go(page, hash);
      const found = await page.locator('#view a[href^="#/"], .app-sidebar a[href^="#/"]').evaluateAll((els) => els.map((el) => el.getAttribute("href") ?? ""));
      for (const href of found) hrefs.add(href);
    }
    expect([...hrefs].filter((href) => /undefined|null|\[object/.test(href)), "liens construits avec une valeur vide").toEqual([]);
    expect(hrefs.size).toBeGreaterThan(20);
    let current = await page.evaluate(() => window.location.hash);
    for (const href of hrefs) {
      if (href === current) continue;
      await go(page, href);
      current = href;
      await expect(page.locator("#view"), `${href} : route fictive`).not.toContainText("Page introuvable");
    }
    expectClean(watch);
  });

  test("route inconnue : page explicite, retour à l'Accueil fonctionnel", async ({ page }) => {
    const watch = watchErrors(page);
    await login(page, "#/", newCaptured());
    await go(page, "#/nimportequoi");
    await expect(page.locator("#view h1")).toContainText("Page introuvable");
    await page.locator("#view").getByRole("link", { name: /Retour à l'Accueil/ }).click();
    await expect(page.locator("#view h1")).toContainText("Accueil");
    expectClean(watch);
  });

  test("statuts cohérents : français partout, jamais la clé brute du contrat", async ({ page }) => {
    const watch = watchErrors(page);
    await login(page, "#/", newCaptured());
    const home = await page.locator("#view").innerText();
    for (const label of ["Bloquée", "En cours", "À faire"]) expect(home).toContain(label);
    await go(page, "#/tasks");
    const tasks = await page.locator("#view").innerText();
    for (const label of ["Bloqué", "En cours", "À faire", "Terminé"]) expect(tasks).toContain(label);
    await go(page, `#/tasks/${T1}`);
    await expect(page.locator("#view")).toContainText("Bloqué");
    await go(page, "#/library/rules");
    const library = await page.locator("#view").innerText();
    expect(library).toContain("Actif");
    expect(library).toContain("Brouillon");
    expect(library).not.toMatch(/\b(draft|deprecated)\b/);
    expectClean(watch);
  });

  test("dates lisibles : format fr-FR, jamais un timestamp ISO comme information principale", async ({ page }) => {
    await login(page, "#/", newCaptured());
    await go(page, "#/transfers");
    const text = await page.locator("#view").innerText();
    expect(text).toMatch(/\d{2}\/\d{2}\/\d{4}/);
    expect(text).not.toMatch(ISO_RE);
  });
});

test.describe("UI-16 erreurs, confirmations, formulaires", () => {
  test("erreur humaine : phrase d'abord, code technique ensuite (403 création de projet)", async ({ page }) => {
    const watch = watchErrors(page);
    await login(page, "#/projects", newCaptured(), { createProjectStatus: 403, createProjectError: { detail: { error_code: "forbidden" } } });
    await page.locator("#project-new").click();
    await page.locator("#project-slug").fill("nouveau");
    await page.locator("#project-name").fill("Nouveau projet");
    await page.locator("#project-create-submit").click();
    const error = page.locator("#project-create-error");
    await expect(error).toBeVisible();
    const text = (await error.innerText()).trim();
    expect(text.startsWith("Vous n'avez pas les droits nécessaires")).toBe(true);
    expect(text).toContain("(HTTP 403 · forbidden)");
    expectClean(watch);
  });

  test("401 : la session terminée renvoie au login avec un message explicite, sans crash", async ({ page }) => {
    const watch = watchErrors(page);
    await login(page, "#/machines", newCaptured(), { tasksUnauthorized: true });
    await page.evaluate(() => {
      location.hash = "#/tasks";
    });
    await expect(page.getByTestId("login-notice")).toContainText("Votre session a expiré ou a été révoquée");
    await expect(page.locator("#login-form")).toBeVisible();
    expectClean(watch);
  });

  test("dégradation partielle : l'Accueil garde projets et tâches quand la file d'examen échoue", async ({ page }) => {
    const watch = watchErrors(page);
    await login(page, "#/", newCaptured(), { reviewQueueFails: true });
    const view = page.locator("#view");
    await expect(view).toContainText("Jeu Phare");
    await expect(view).toContainText("Caméra Android bloquée");
    await expect(view).toContainText("Le serveur a rencontré une erreur");
    expectClean(watch);
  });

  test("confirmation destructive : le message dit ce qui arrive ; refuser n'envoie rien", async ({ page }) => {
    const watch = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/configuration/bindings", captured);
    const del = page.locator("[data-delete-binding]").first();
    await expect(del).toBeVisible();
    let message = "";
    page.once("dialog", (dialog) => {
      message = dialog.message();
      void dialog.dismiss();
    });
    await del.click();
    expect(message).toContain("Cette règle d'affectation disparaît");
    expect(message).toContain("le runtime visé n'est pas supprimé");
    expect(captured.bindingDeletes).toEqual([]);
    page.once("dialog", (dialog) => void dialog.accept());
    await del.click();
    await expect.poll(() => captured.bindingDeletes.length).toBe(1);
    expectClean(watch);
  });

  test("réservations : vocabulaire propre, statut et type en français, libération confirmée", async ({ page }) => {
    const watch = watchErrors(page);
    const captured = newCaptured();
    await login(page, `#/projects/${P1}/claims`, captured);
    const view = page.locator("#view");
    await expect(view).toContainText("sans jamais bloquer Git");
    await expect(view.locator("table tbody")).toContainText("Active");
    await expect(view.locator("table tbody")).toContainText("Fichier");
    await expect(view).not.toContainText("verrou souple");
    let message = "";
    page.once("dialog", (dialog) => {
      message = dialog.message();
      void dialog.dismiss();
    });
    await view.locator("[data-release]").click();
    expect(message).toContain("Libérer cette réservation ?");
    expect(captured.claimReleases).toEqual([]);
    page.once("dialog", (dialog) => void dialog.accept());
    await view.locator("[data-release]").click();
    await expect.poll(() => captured.claimReleases.length).toBe(1);
    expectClean(watch);
  });

  test("FilePicker : l'input natif est conservé (un fichier, libellé, clavier, nom affiché)", async ({ page }) => {
    const watch = watchErrors(page);
    await login(page, "#/transfers", newCaptured());
    await page.locator("#transfer-upload-open, #view [data-transfer-upload-open]").first().click();
    const dialog = page.locator("[role=dialog]:visible");
    await expect(dialog).toBeVisible();
    const input = dialog.locator('input[type="file"]');
    await expect(input).toHaveCount(1);
    expect(await input.getAttribute("multiple")).toBeNull();
    await expect(dialog.getByLabel("Fichier")).toHaveCount(1);
    await input.focus();
    await expect(input).toBeFocused();
    await input.setInputFiles({ name: "rapport-de-build.zip", mimeType: "application/zip", buffer: Buffer.from("contenu") });
    await expect(dialog.locator("[data-file-info]")).toContainText("rapport-de-build.zip");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expectClean(watch);
  });
});

test.describe("UI-16 navigation, focus et stress", () => {
  test("navigation : la nouvelle page démarre en haut, titre visible sous la barre", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 600 });
    await login(page, "#/", newCaptured());
    for (const [from, to] of [
      ["#/tasks", "#/decisions"],
      ["#/library/rules", "#/projects"],
      ["#/", "#/tasks"],
    ] as const) {
      if ((await page.evaluate(() => window.location.hash)) !== from) await go(page, from);
      await page.evaluate(() => window.scrollTo(0, 200));
      await page.locator(`.app-sidebar a[href="${to}"]`).click();
      await expect(page.locator("#view h1")).toBeVisible();
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
      const top = await page.locator("#view h1").evaluate((el) => el.getBoundingClientRect().top);
      expect(top, `${from} → ${to} : titre masqué par la barre`).toBeGreaterThanOrEqual(60);
      await expect(page.locator("#view")).toBeFocused();
    }
    expectClean(watch);
  });

  test("stress navigation ×10 : shell et vue uniques, requêtes stables, aucun écouteur en trop", async ({ page }) => {
    test.setTimeout(180_000);
    await installListenerProbe(page);
    const watch = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/", captured);
    const cycle = ["#/tasks", "#/library/rules", "#/decisions", "#/transfers", "#/configuration/bindings", "#/"];
    const perCycle: number[] = [];
    let baseline: Record<string, number> | null = null;
    for (let i = 0; i < 10; i += 1) {
      const before = captured.apiCalls.length;
      for (const hash of cycle) {
        if ((await page.evaluate(() => window.location.hash)) !== hash) await go(page, hash);
      }
      perCycle.push(captured.apiCalls.length - before);
      expect(await page.locator(".app-shell").count()).toBe(1);
      expect(await page.locator("#view").count()).toBe(1);
      expect(await page.locator("main").count()).toBe(1);
      expect(await page.locator("#ds-toast-region").count()).toBe(1);
      const live = await liveListeners(page);
      if (i === 0) baseline = live;
      else expect(live, `cycle ${i + 1} : écouteurs document/window`).toEqual(baseline);
    }
    // Chaque cycle refait les mêmes requêtes : pas de fetch qui dérive.
    expect(new Set(perCycle.slice(1)).size, `requêtes par cycle : ${perCycle.join(",")}`).toBe(1);
    expectClean(watch);
  });

  test("stress modale ×10 : piège de focus, Échap, retour focus, aucun écouteur en trop", async ({ page }) => {
    test.setTimeout(120_000);
    await installListenerProbe(page);
    const watch = watchErrors(page);
    await login(page, "#/projects", newCaptured());
    const trigger = page.locator("#project-new");
    const dialog = page.locator("#project-create-dialog");
    let baseline: Record<string, number> | null = null;
    for (let i = 0; i < 10; i += 1) {
      await trigger.click();
      await expect(dialog).toBeVisible();
      for (let t = 0; t < 8; t += 1) {
        await page.keyboard.press("Tab");
        expect(await dialog.evaluate((el) => el.contains(document.activeElement)), `cycle ${i + 1} : focus hors modale`).toBe(true);
      }
      await page.keyboard.press("Shift+Tab");
      expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(trigger).toBeFocused();
      const live = await liveListeners(page);
      if (i === 0) baseline = live;
      else expect(live, `cycle ${i + 1} : écouteurs document/window`).toEqual(baseline);
    }
    expect(await page.locator("[role=dialog]").count()).toBe(1);
    expectClean(watch);
  });

  test("stress tiroir ×10 : ouverture, fermeture, retour focus, aucun écouteur en trop", async ({ page }) => {
    test.setTimeout(120_000);
    await installListenerProbe(page);
    const watch = watchErrors(page);
    await login(page, "#/machines", newCaptured());
    const trigger = page.locator("[data-machine-details]").first();
    const drawer = page.locator("#machine-drawer");
    let baseline: Record<string, number> | null = null;
    for (let i = 0; i < 10; i += 1) {
      await trigger.click();
      await expect(drawer).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(drawer).toBeHidden();
      await expect(trigger).toBeFocused();
      const live = await liveListeners(page);
      if (i === 0) baseline = live;
      else expect(live, `cycle ${i + 1} : écouteurs document/window`).toEqual(baseline);
    }
    expectClean(watch);
  });

  test("double soumission ×20 : une seule création par tentative, bouton verrouillé", async ({ page }) => {
    test.setTimeout(240_000);
    const watch = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/tasks", captured, { createTaskDelayMs: 150 });
    const dialog = page.locator("#task-create-dialog");
    for (let i = 1; i <= 20; i += 1) {
      await page.locator("#task-new").click();
      await expect(dialog).toBeVisible();
      await dialog.locator("#task-title").fill(`Tâche de stress ${i}`);
      await dialog.locator("#task-project").selectOption(P1);
      const submit = dialog.locator("#task-create-submit");
      await submit.click();
      await expect(submit).toBeDisabled();
      await page.evaluate(() => {
        const form = document.querySelector<HTMLFormElement>("#task-create-form");
        form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      });
      await expect(dialog).toBeHidden();
      expect(captured.taskPosts, `tentative ${i}`).toBe(i);
    }
    expectClean(watch);
  });

  test("clavier : skip-link, navigation, onglets, formulaire, action destructive", async ({ page }) => {
    const watch = watchErrors(page);
    await login(page, "#/", newCaptured());
    // Le jeton n'est gardé qu'en mémoire : pas de rechargement, on repart du haut de page.
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo(0, 0);
    });
    await page.keyboard.press("Tab");
    await expect(page.locator(".ds-skip-link")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#view")).toBeFocused();
    // Onglets du workspace : flèches, sélection, panneau associé.
    await go(page, `#/projects/${P1}/tasks`);
    const tabs = page.locator('#view [role="tab"]');
    await tabs.first().focus();
    await page.keyboard.press("ArrowRight");
    await expect(tabs.nth(1)).toBeFocused();
    // Formulaire : Entrée dans un champ vide déclenche la validation accessible, pas de crash.
    await go(page, "#/projects");
    await page.locator("#project-new").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#project-create-dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    // Action destructive au clavier : la confirmation native s'ouvre et bloque.
    await go(page, "#/configuration/bindings");
    let asked = false;
    page.once("dialog", (dialog) => {
      asked = true;
      void dialog.dismiss();
    });
    await page.locator("[data-delete-binding]").first().focus();
    await page.keyboard.press("Enter");
    await expect.poll(() => asked).toBe(true);
    expectClean(watch);
  });

  test("connexion et déconnexion : le cycle complet fonctionne", async ({ page }) => {
    const watch = watchErrors(page);
    await login(page, "#/", newCaptured());
    await page.locator("#token-clear").click();
    await expect(page.locator("#login-form")).toBeVisible();
    await page.fill("#login-email", "e2e@example.test");
    await page.fill("#login-password", "e2e-secret");
    await page.locator("#login-form button[type=submit]").click();
    await expect(page.locator(".app-sidebar")).toBeVisible();
    await expect(page.locator("#view h1")).toContainText("Accueil");
    expectClean(watch);
  });
});

test.describe("UI-16 responsive et accessibilité finales", () => {
  test("smoke 1440 → 375 : aucun overflow horizontal global sur les surfaces représentatives", async ({ page }) => {
    test.setTimeout(240_000);
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, "#/", newCaptured());
    const surfaces = ["#/", "#/tasks", "#/library/rules", "#/decisions", "#/transfers", "#/configuration/bindings", `#/projects/${P1}/claims`, "#/inspector"];
    for (const hash of surfaces) {
      if ((await page.evaluate(() => window.location.hash)) !== hash) await go(page, hash);
      for (const width of [1440, 1280, 1024, 900, 768, 640, 480, 375]) {
        await page.setViewportSize({ width, height: 800 });
        expect(await globalOverflow(page), `${hash} @${width}`).toBeLessThanOrEqual(1);
      }
    }
    expectClean(watch);
  });

  test("axe : surfaces retouchées, 0 critique/sérieuse, sans exclusion", async ({ page }) => {
    test.setTimeout(180_000);
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1280, height: 900 });
    await login(page, "#/", newCaptured());
    const surfaces = ["#/", `#/projects/${P1}/claims`, `#/projects/${P1}/decisions`, "#/decisions", "#/library/rules", "#/configuration/bindings", "#/configuration/runtimes", "#/inspector"];
    for (const hash of surfaces) {
      if ((await page.evaluate(() => window.location.hash)) !== hash) await go(page, hash);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const blocking = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
      expect(blocking.map((v) => `${hash} ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    }
    expectClean(watch);
  });

  test("mouvement réduit : aucune animation ni transition longue", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await login(page, "#/", newCaptured());
    await go(page, "#/projects");
    await page.locator("#project-new").click();
    const dialog = page.locator("#project-create-dialog");
    await expect(dialog).toBeVisible();
    const longest = await page.evaluate(() => {
      let max = 0;
      for (const el of document.querySelectorAll<HTMLElement>("*")) {
        const cs = getComputedStyle(el);
        for (const value of [cs.animationDuration, cs.transitionDuration]) {
          for (const part of value.split(",")) {
            const seconds = part.trim().endsWith("ms") ? parseFloat(part) / 1000 : parseFloat(part);
            if (Number.isFinite(seconds)) max = Math.max(max, seconds);
          }
        }
      }
      return max;
    });
    expect(longest).toBeLessThan(0.05);
  });
});
