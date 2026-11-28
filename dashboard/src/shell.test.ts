// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { parseRoute } from "./router";
import {
  mountAdminFlyout,
  paintConnection,
  breadcrumbHtml,
  shellHtml,
  shellNavGroups,
  studioSelectorHtml,
  connectionStatusHtml,
  syncStudioSelector,
} from "./shell";
import { notFoundHtml } from "./views/notFound";

function authedShell(routeName: Parameters<typeof shellHtml>[0]): string {
  return shellHtml(routeName, true);
}

describe("shellNavGroups (R2-coque, fiche E1)", () => {
  it("exposes the 7 daily entries in the mockup order", () => {
    const groups = shellNavGroups({ name: "dashboard" });
    expect(groups.map((group) => group.title)).toEqual(["Principal", "Studio"]);
    expect(groups[0]?.items.map((item) => [item.label, item.href])).toEqual([
      ["Aujourd'hui", "#/"],
      ["Projets", "#/projets"],
      ["Tâches", "#/taches"],
      ["À valider", "#/a-valider"],
      ["Équipe IA", "#/equipe-ia"],
      ["Connaissances", "#/connaissances/savoir-faire"],
      ["Fichiers", "#/connaissances/notes"],
    ]);
    expect(groups[0]?.items).toHaveLength(7);
  });

  it("shows Réglages, Abonnement and Aide in the Studio group for the owner", () => {
    const groups = shellNavGroups({ name: "dashboard" }, false, "simple", "owner", "Gratuit");
    expect(groups[1]?.items.map((item) => item.label)).toEqual(["Réglages", "Abonnement", "Aide"]);
    expect(groups[1]?.items.map((item) => item.href)).toEqual(["#/reglages", "#/abonnement", "#/aide"]);
    const subscription = groups[1]?.items.find((item) => item.label === "Abonnement");
    expect(subscription?.pill).toBe("Gratuit");
  });

  it("hides Abonnement for non-owner roles and keeps the plan pill for the owner", () => {
    for (const role of ["admin", "member", "viewer"] as const) {
      const groups = shellNavGroups({ name: "dashboard" }, false, "simple", role);
      expect(groups[1]?.items.map((item) => item.label)).toEqual(["Réglages", "Aide"]);
    }
    const pro = shellNavGroups({ name: "dashboard" }, false, "simple", "owner", "Pro");
    expect(pro[1]?.items.find((item) => item.label === "Abonnement")?.pill).toBe("Pro");
  });

  it("keeps one active item on legacy pages via the closest Studio entry", () => {
    const regales = (route: Parameters<typeof shellNavGroups>[0]): string[] =>
      shellNavGroups(route).flatMap((group) => group.items.filter((item) => item.active).map((item) => item.label));
    expect(regales({ name: "machines" })).toEqual(["Réglages"]);
    expect(regales({ name: "accounts" })).toEqual(["Réglages"]);
    expect(regales({ name: "admin" })).toEqual(["Réglages"]);
    expect(regales({ name: "configApplication" })).toEqual(["Réglages"]);
    expect(regales({ name: "inspector", stableKey: null })).toEqual(["Équipe IA"]);
    expect(regales({ name: "subscription" })).toEqual(["Abonnement"]);
    expect(regales({ name: "help" })).toEqual(["Aide"]);
  });

  it("marks exactly one active item per routed page", () => {
    for (const route of [
      { name: "dashboard" },
      { name: "projects" },
      { name: "task", id: "t-1" },
      { name: "agents" },
      { name: "agent", id: "a-1" },
      { name: "libraryDetail", kind: "rules", id: "x" },
      { name: "vault" },
      { name: "vaultDetail", id: "n-1" },
      { name: "subscription" },
      { name: "help" },
    ] as const) {
      const active = shellNavGroups(route).flatMap((group) => group.items).filter((item) => item.active);
      expect(active).toHaveLength(1);
    }
    // 404 : aucun repère actif inventé.
    expect(shellNavGroups({ name: "notFound", hash: "#/nope" }).flatMap((g) => g.items).filter((i) => i.active)).toHaveLength(0);
  });

  it("maps Connaissances to the library and Fichiers to the vault", () => {
    const active = (route: Parameters<typeof shellNavGroups>[0]): string[] =>
      shellNavGroups(route).flatMap((group) => group.items.filter((item) => item.active).map((item) => item.label));
    expect(active({ name: "library", kind: null })).toEqual(["Connaissances"]);
    expect(active({ name: "vaultAtlas" })).toEqual(["Fichiers"]);
    expect(active({ name: "decisions" })).toEqual(["À valider"]);
  });
});

describe("studioSelectorHtml (R2-coque, fiche E1)", () => {
  const studios = [
    { id: "a", name: "Atelier Phare", slug: "phare", plan: "Gratuit", status: "active" as const, role: "owner" as const },
    { id: "b", name: "Binaweb", slug: "binaweb", plan: "Pro", status: "active" as const, role: "member" as const },
    { id: "c", name: "ForkandFood", slug: "fork", plan: "Gratuit", status: "active" as const, role: "viewer" as const },
  ];

  it("renders a menu button with the role under the name", () => {
    const html = studioSelectorHtml({ status: "ready", studios, activeId: "a" });
    expect(html).toContain('aria-haspopup="menu"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("Atelier Phare");
    expect(html).toContain("Propriétaire");
    expect(html).toContain('role="menu"');
    expect(html).toContain('role="menuitemradio"');
    expect(html).toContain("Membre · Pro");
    expect(html).toContain("Lecture seule");
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
  });

  it("shows no menu and no chevron for a single studio", () => {
    const html = studioSelectorHtml({ status: "ready", studios: studios.slice(0, 1), activeId: "a" });
    expect(html).toContain('data-testid="studio-selector"');
    expect(html).not.toContain('aria-haspopup="menu"');
    expect(html).not.toContain("studio-menu");
  });

  it("announces suspended studios in text, never by color alone", () => {
    const html = studioSelectorHtml({
      status: "ready",
      studios: [{ ...studios[0]!, status: "suspended" as const }],
      activeId: "a",
    });
    expect(html).toContain("Propriétaire · Suspendu");
  });

  it("covers loading and error states with a retry", () => {
    expect(studioSelectorHtml({ status: "loading" })).toContain("Chargement du studio");
    const error = studioSelectorHtml({ status: "error" });
    expect(error).toContain("role=\"alert\"");
    expect(error).toContain('id="studio-retry"');
  });

  it("replaces the slot content in place", () => {
    document.body.innerHTML = shellHtml({ name: "dashboard" }, true);
    expect(document.querySelector("#studio-slot")?.textContent).toContain("Chargement du studio");
    syncStudioSelector(document, { status: "ready", studios, activeId: "b" });
    expect(document.querySelector("#studio-slot")?.textContent).toContain("Binaweb");
    expect(document.querySelectorAll("#studio-slot [data-testid='studio-selector']")).toHaveLength(1);
  });
});

describe("shellHtml (R2-coque, fiche E1)", () => {
  it("labels navigation and landmarks in French, mockup wording", () => {
    const html = authedShell({ name: "dashboard" });
    expect(html).toContain('aria-label="Navigation principale"');
    expect(html).toContain("Aujourd'hui");
    expect(html).toContain("À valider");
    expect(html).toContain("Équipe IA");
    expect(html).toContain("Connaissances");
    expect(html).toContain("Fichiers");
    expect(html).toContain("Réglages");
    expect(html).toContain("Abonnement");
    expect(html).toContain("Aide");
    expect(html).toContain("Studio");
    expect(html).toContain("Aller au contenu");
    expect(html).toContain("Se déconnecter");
  });

  it("renders the studio slot with a loading selector", () => {
    expect(authedShell({ name: "dashboard" })).toContain('id="studio-slot"');
    expect(authedShell({ name: "dashboard" })).toContain("Chargement du studio");
  });

  it("names the nav landmark, not the complementary aside (UI-14)", () => {
    const html = authedShell({ name: "dashboard" });
    expect(html).toContain('<nav class="app-nav" aria-label="Navigation principale">');
    expect(html).not.toMatch(/<aside[^>]*aria-label/);
    expect(html).toContain('<main id="view" tabindex="-1">');
  });

  it("keeps the internal demo route out of the navigation", () => {
    expect(authedShell({ name: "designSystem" })).not.toContain("#/reglages/avance/design-system");
    expect(authedShell({ name: "dashboard" })).not.toContain("design-system");
  });

  it("shows no fake global search and no fake notifications", () => {
    const html = authedShell({ name: "dashboard" });
    expect(html).not.toMatch(/type="search"/i);
    expect(html).not.toMatch(/notification|cloche|recherche globale/i);
  });

  it("sets aria-current on the active link only", () => {
    const html = authedShell({ name: "tasks" });
    expect(html.match(/aria-current="page"/g)).toHaveLength(1);
    expect(html).toContain('href="#/taches" aria-current="page"');
  });

  it("exposes the mobile drawer contract (menu button, scrim, labelled nav)", () => {
    const html = authedShell({ name: "dashboard" });
    expect(html).toContain('id="nav-open"');
    expect(html).toContain('aria-controls="app-sidebar"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('id="app-scrim"');
    expect(html).toContain('id="nav-close"');
    expect(html).toContain("<main");
    expect(html).toContain('id="ds-toast-region"');
  });

  it("contains no inline style or event-handler attributes (CSP)", () => {
    const html = authedShell({ name: "dashboard" });
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
  });
});

describe("shellHtml (P03-shell)", () => {
  function parse(html: string): Document {
    return new DOMParser().parseFromString(html, "text/html");
  }

  it("renders exactly one connection status and no other « Connecté » (C4)", () => {
    for (const authed of [true, false]) {
      const doc = parse(shellHtml(parseRoute("#/"), authed));
      const statuses = doc.querySelectorAll('[data-testid="connection-status"]');
      expect(statuses).toHaveLength(1);
      expect(statuses[0]?.closest(".app-me")).not.toBeNull();
      const text = doc.body.textContent ?? "";
      expect(text.split("Connecté").length - 1).toBe(authed ? 1 : 0);
    }
  });

  it("opens the « Aller à… » palette from the top of the sidebar", () => {
    const doc = parse(shellHtml(parseRoute("#/"), true));
    const opener = doc.querySelector("#palette-open");
    expect(opener?.closest(".app-sidebar")).not.toBeNull();
    expect(opener?.getAttribute("aria-keyshortcuts")).toBe("Control+K");
    expect(doc.querySelector("#app-palette")?.hasAttribute("hidden")).toBe(true);
    expect(doc.querySelector('#app-palette-input')?.getAttribute("type")).toBe("text");
    expect(doc.querySelector('input[type="search"]')).toBeNull();
  });

  it("lists seven daily entries then the Studio group", () => {
    const doc = parse(shellHtml(parseRoute("#/"), true));
    const groups = [...doc.querySelectorAll(".app-navgroup")];
    expect(groups).toHaveLength(2);
    expect(groups[0]?.querySelectorAll("a")).toHaveLength(7);
    expect(groups[1]?.textContent).toContain("Studio");
    expect(groups[1]?.textContent).toContain("Réglages");
    expect(groups[1]?.textContent).toContain("Abonnement");
    expect(groups[1]?.textContent).toContain("Aide");
    expect(groups[1]?.classList.contains("app-navgroup--admin")).toBe(true);
  });

  it("offers sign-out from the avatar block only when signed in", () => {
    expect(parse(shellHtml(parseRoute("#/"), true)).querySelector(".app-me #token-clear")).not.toBeNull();
    const anon = parse(shellHtml(parseRoute("#/"), false));
    expect(anon.querySelector("#token-clear")).toBeNull();
    expect(anon.querySelector(".app-me #token-input")).not.toBeNull();
  });

  it("repaints the status and its action in place, never duplicating them (P03-status)", () => {
    document.body.innerHTML = shellHtml(parseRoute("#/"), true);
    const down = { level: "error" as const, label: "Serveur injoignable", href: "#/reglages/application" };
    paintConnection({ ...down, action: { kind: "retry", label: "Réessayer" } }, document);
    paintConnection({ ...down, title: "Serveur injoignable — détail", action: { kind: "retry", label: "Réessayer" } }, document);
    expect(document.querySelectorAll("#connection-status")).toHaveLength(1);
    expect(document.querySelectorAll("#connection-action")).toHaveLength(1);
    expect(document.querySelector("#connection-status")?.getAttribute("title")).toBe("Serveur injoignable — détail");
    paintConnection({ level: "ok", label: "Connecté", href: "#/reglages/application", action: null }, document);
    expect(document.querySelectorAll("#connection-status")).toHaveLength(1);
    expect(document.querySelector("#connection-action")).toBeNull();
  });

  it("exposes the full footer label in the DOM and in the tooltip (no truncated « Co… »)", () => {
    const html = connectionStatusHtml({ level: "ok", label: "Connecté", href: "#/reglages/application" });
    expect(html).toContain('title="Connecté"');
    expect(html).toContain('<span class="app-connection-label">Connecté</span>');
    const long = connectionStatusHtml({ level: "warn", label: "Assistant local en reprise", href: "#/reglages/application" });
    expect(long).toContain('title="Assistant local en reprise"');
    expect(long).toContain("Assistant local en reprise");
  });
});

describe("parseRoute (R2-coque)", () => {
  it("routes unknown hashes to an explicit 404 instead of the dashboard", () => {
    expect(parseRoute("#/unknown")).toEqual({ name: "notFound", hash: "#/unknown" });
    expect(parseRoute("#/machines/extra")).toEqual({ name: "notFound", hash: "#/machines/extra" });
    expect(parseRoute("#/library/nope")).toEqual({ name: "notFound", hash: "#/library/nope" });
    expect(parseRoute("#/configuration/nope")).toEqual({ name: "notFound", hash: "#/configuration/nope" });
    expect(parseRoute("#/inspector/a/b")).toEqual({ name: "notFound", hash: "#/inspector/a/b" });
  });

  it("keeps the empty hash and local tab defaults on the dashboard", () => {
    expect(parseRoute("")).toEqual({ name: "dashboard" });
    expect(parseRoute("#/")).toEqual({ name: "dashboard" });
    expect(parseRoute("#/projects/abc/nope")).toEqual({ name: "project", id: "abc", tab: "overview" });
  });

  it("routes the Studio entries to their overview", () => {
    expect(parseRoute("#/reglages")).toEqual({ name: "admin" });
    expect(parseRoute("#/admin")).toEqual({ name: "admin" });
    expect(parseRoute("#/abonnement")).toEqual({ name: "subscription" });
    expect(parseRoute("#/aide")).toEqual({ name: "help" });
  });
});

describe("notFoundHtml (UI-2)", () => {
  it("explains in French and links back home", () => {
    const html = notFoundHtml("#/nope");
    expect(html).toContain("Page introuvable");
    expect(html).toContain('href="#/"');
    expect(html).toContain("#/nope");
  });

  it("escapes the hash", () => {
    expect(notFoundHtml('#/"<x>')).not.toContain("<x>");
  });
});

describe("mountAdminFlyout (P03-shell, legacy)", () => {
  it("is a no-op without collapsible groups but keeps the rail contract", () => {
    document.body.innerHTML = shellHtml(parseRoute("#/inspector"), true);
    expect(document.querySelectorAll("details.app-navgroup--secondary")).toHaveLength(0);
    expect(() => mountAdminFlyout()).not.toThrow();
    expect(document.querySelector('[href="#/equipe-ia"]')?.getAttribute("aria-current")).toBe("page");
  });
});

describe("breadcrumbHtml (R2-adresses)", () => {
  it("n'affiche rien sur une page principale", () => {
    expect(breadcrumbHtml(parseRoute("#/projets"))).toBe("");
  });

  it("remonte une sous-page, la page courante sans lien", () => {
    const html = breadcrumbHtml(parseRoute("#/reglages/moteurs/affectations"));
    expect(html).toContain(`aria-label="Fil d'Ariane"`);
    expect(html).toContain('<a href="#/reglages/moteurs">Moteurs IA</a>');
    expect(html).toContain('<li aria-current="page">Affectations</li>');
  });

  it("garde l'identifiant du projet dans le lien et l'échappe", () => {
    expect(breadcrumbHtml({ name: "project", id: 'a"b', tab: "tasks" })).toContain('href="#/projets/a&quot;b"');
  });
});
