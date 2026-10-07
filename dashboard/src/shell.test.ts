// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { parseRoute } from "./router";
import { mountAdminFlyout, paintConnection, shellHtml, shellNavGroups, connectionStatusHtml } from "./shell";
import { notFoundHtml } from "./views/notFound";

function authedShell(routeName: Parameters<typeof shellHtml>[0]): string {
  return shellHtml(routeName, true);
}

describe("shellNavGroups (UI-2)", () => {
  it("covers the target navigation with existing routes only", () => {
    const groups = shellNavGroups({ name: "dashboard" });
    expect(groups.map((group) => group.title)).toEqual(["Principal", "Administration", "Outils experts"]);
    expect(groups[0]?.items.map((item) => [item.label, item.href])).toEqual([
      ["Accueil", "#/"],
      ["Projets", "#/projects"],
      ["Travail", "#/tasks"],
      ["À valider", "#/decisions"],
      ["Agents", "#/agents"],
    ]);
    expect(groups[1]?.collapsible).toBe(true);
    expect(groups[1]?.items.map((item) => item.href)).toEqual([
      "#/administration",
      "#/machines",
      "#/accounts",
      "#/transfers",
      "#/vault",
      "#/library",
      "#/configuration/runtimes",
      "#/workspaces",
    ]);
    expect(groups[2]?.items.map((item) => item.href)).toEqual(["#/graphs/knowledge", "#/inspector"]);
  });

  it("keeps Administration collapsed unless the active page belongs to it", () => {
    expect(shellHtml({ name: "dashboard" }, true)).toContain('<details class="app-navgroup app-navgroup--secondary"><summary>');
    expect(shellHtml({ name: "machines" }, true)).toContain('<details class="app-navgroup app-navgroup--secondary" open>');
    expect(shellHtml({ name: "admin" }, true)).toContain('href="#/administration" aria-current="page"');
  });

  it("shows Espaces de travail in Administration on web and desktop, keeping five daily entries", () => {
    for (const desktop of [false, true]) {
      const groups = shellNavGroups({ name: "dashboard" }, desktop);
      expect(groups[0]?.items).toHaveLength(5);
      expect(groups[1]?.items.map((item) => item.label)).toEqual([
        "Vue d'ensemble",
        "Postes",
        "Comptes",
        "Transferts",
        "Vault",
        "Bibliothèque",
        "Configuration",
        "Espaces de travail",
      ]);
    }
  });

  it("keeps expert tools out of the Administration entry", () => {
    const groups = shellNavGroups({ name: "dashboard" });
    expect(groups[1]?.items.map((item) => item.href)).not.toContain("#/graphs/knowledge");
    expect(groups[1]?.items.map((item) => item.href)).not.toContain("#/inspector");
    expect(groups[2]?.title).toBe("Outils experts");
  });

  it("marks exactly one active item per route", () => {
    for (const route of [
      { name: "dashboard" },
      { name: "projects" },
      { name: "task", id: "t-1" },
      { name: "agents" },
      { name: "agent", id: "a-1" },
      { name: "libraryDetail", kind: "rules", id: "x" },
      { name: "vault" },
      { name: "vaultDetail", id: "n-1" },
    ] as const) {
      const active = shellNavGroups(route).flatMap((group) => group.items).filter((item) => item.active);
      expect(active).toHaveLength(1);
    }
  });

  it("activates Configuration inside Administration on every configuration route", () => {
    const active = shellNavGroups({ name: "configBindings" })
      .flatMap((group) => group.items)
      .filter((item) => item.active);
    expect(active.map((item) => item.label)).toEqual(["Configuration"]);
    expect(shellHtml({ name: "configApplication" }, true)).toContain('href="#/configuration/runtimes" aria-current="page"');
    expect(shellHtml({ name: "configIntegrations" }, true)).toContain('href="#/configuration/runtimes" aria-current="page"');
    expect(shellHtml({ name: "configBindings" }, true)).toContain('href="#/configuration/runtimes" aria-current="page"');
  });
});

describe("shellHtml (UI-2)", () => {
  it("labels navigation and landmarks in French", () => {
    const html = authedShell({ name: "dashboard" });
    expect(html).toContain('aria-label="Navigation principale"');
    expect(html).toContain("Accueil");
    expect(html).toContain("Bibliothèque");
    expect(html).toContain("Travail");
    expect(html).toContain("À valider");
    expect(html).toContain("Configuration");
    expect(html).toContain("Espaces de travail");
    expect(html).toContain("Aller au contenu");
    expect(html).toContain("Se déconnecter");
  });

  it("names the nav landmark, not the complementary aside (UI-14)", () => {
    const html = authedShell({ name: "dashboard" });
    expect(html).toContain('<nav class="app-nav" aria-label="Navigation principale">');
    expect(html).not.toMatch(/<aside[^>]*aria-label/);
    expect(html).toContain('<main id="view" tabindex="-1">');
  });

  it("keeps the internal demo route out of the navigation", () => {
    expect(authedShell({ name: "designSystem" })).not.toContain("#/design-system");
    expect(authedShell({ name: "dashboard" })).not.toContain("design-system");
  });

  it("shows no fake global search and no fake notifications", () => {
    const html = authedShell({ name: "dashboard" });
    expect(html).not.toMatch(/type="search"/i);
    expect(html).not.toMatch(/notification|cloche|recherche globale/i);
  });

  it("links Agents to the real page, no longer upcoming", () => {
    const html = authedShell({ name: "dashboard" });
    expect(html).toContain('<span class="app-navlabel">Agents</span>');
    expect(html).toContain('href="#/agents"');
    expect(html).not.toContain("Bientôt");
  });

  it("marks the agents link active on list and detail", () => {
    expect(authedShell({ name: "agents" })).toContain('href="#/agents" aria-current="page"');
    expect(authedShell({ name: "agent", id: "a-1" })).toContain('href="#/agents" aria-current="page"');
  });

  it("sets aria-current on the active link only", () => {
    const html = authedShell({ name: "tasks" });
    expect(html.match(/aria-current="page"/g)).toHaveLength(1);
    expect(html).toContain('href="#/tasks" aria-current="page"');
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

  it("separates Administration after the daily entries, with Configuration inside", () => {
    const doc = parse(shellHtml(parseRoute("#/"), true));
    const groups = [...doc.querySelectorAll(".app-navgroup")];
    expect(groups).toHaveLength(3);
    expect(groups[1]?.tagName).toBe("DETAILS");
    expect(groups[0]?.querySelectorAll("a")).toHaveLength(5);
    expect(groups[1]?.textContent).toContain("Configuration");
    expect(groups[2]?.textContent).toContain("Inspecteur");
  });

  it("offers sign-out from the avatar block only when signed in", () => {
    expect(parse(shellHtml(parseRoute("#/"), true)).querySelector(".app-me #token-clear")).not.toBeNull();
    const anon = parse(shellHtml(parseRoute("#/"), false));
    expect(anon.querySelector("#token-clear")).toBeNull();
    expect(anon.querySelector(".app-me #token-input")).not.toBeNull();
  });

  it("repaints the status and its action in place, never duplicating them (P03-status)", () => {
    document.body.innerHTML = shellHtml(parseRoute("#/"), true);
    const down = { level: "error" as const, label: "Serveur injoignable", href: "#/configuration/application" };
    paintConnection({ ...down, action: { kind: "retry", label: "Réessayer" } }, document);
    paintConnection({ ...down, title: "Serveur injoignable — détail", action: { kind: "retry", label: "Réessayer" } }, document);
    expect(document.querySelectorAll("#connection-status")).toHaveLength(1);
    expect(document.querySelectorAll("#connection-action")).toHaveLength(1);
    expect(document.querySelector("#connection-status")?.getAttribute("title")).toBe("Serveur injoignable — détail");
    paintConnection({ level: "ok", label: "Connecté", href: "#/configuration/application", action: null }, document);
    expect(document.querySelectorAll("#connection-status")).toHaveLength(1);
    expect(document.querySelector("#connection-action")).toBeNull();
  });

  it("exposes the full footer label in the DOM and in the tooltip (no truncated « Co… »)", () => {
    const html = connectionStatusHtml({ level: "ok", label: "Connecté", href: "#/configuration/application" });
    expect(html).toContain('title="Connecté"');
    expect(html).toContain('<span class="app-connection-label">Connecté</span>');
    const long = connectionStatusHtml({ level: "warn", label: "Assistant local en reprise", href: "#/configuration/application" });
    expect(long).toContain('title="Assistant local en reprise"');
    expect(long).toContain("Assistant local en reprise");
  });
});

describe("parseRoute notFound (UI-2)", () => {
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

  it("routes the Administration entry to its overview", () => {
    expect(parseRoute("#/administration")).toEqual({ name: "admin" });
    expect(parseRoute("#/admin")).toEqual({ name: "admin" });
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

describe("mountAdminFlyout (P03-shell)", () => {
  it("keeps the rail flyout closed on admin pages and closes it on outside click or Escape", () => {
    expect(window.matchMedia("(min-width: 901px) and (max-width: 1399.98px)").matches).toBe(true);
    document.body.innerHTML = shellHtml(parseRoute("#/inspector"), true);
    const groups = [...document.querySelectorAll("details.app-navgroup--secondary")] as HTMLDetailsElement[];
    expect(groups).toHaveLength(2);
    const admin = groups[1] as HTMLDetailsElement;
    expect(admin.open).toBe(true);
    mountAdminFlyout();
    expect(admin.open).toBe(false);

    admin.open = true;
    document.getElementById("view")?.click();
    expect(admin.open).toBe(false);

    admin.open = true;
    const link = admin.querySelector("a") as HTMLAnchorElement;
    link.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(admin.open).toBe(false);
    expect(document.activeElement).toBe(admin.querySelector("summary"));
  });
});