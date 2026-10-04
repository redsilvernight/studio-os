// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { parseRoute } from "./router";
import { shellHtml, shellNavGroups, syncAuthState } from "./shell";
import { notFoundHtml } from "./views/notFound";

function authedShell(routeName: Parameters<typeof shellHtml>[0]): string {
  return shellHtml(routeName, true);
}

describe("shellNavGroups (UI-2)", () => {
  it("covers the target navigation with existing routes only", () => {
    const groups = shellNavGroups({ name: "dashboard" });
    expect(groups.map((group) => group.title)).toEqual(["Principal", "Administration"]);
    expect(groups[0]?.items.map((item) => [item.label, item.href])).toEqual([
      ["Accueil", "#/"],
      ["Projets", "#/projects"],
      ["Travail", "#/tasks"],
      ["À valider", "#/decisions"],
      ["Agents", "#/agents"],
    ]);
    expect(groups[1]?.collapsible).toBe(true);
    expect(groups[1]?.items.map((item) => item.href)).toEqual([
      "#/library",
      "#/graphs/knowledge",
      "#/transfers",
      "#/machines",
      "#/accounts",
      "#/inspector",
    ]);
  });

  it("keeps Administration collapsed unless the active page belongs to it", () => {
    expect(shellHtml({ name: "dashboard" }, true)).toContain('<details class="app-navgroup app-navgroup--secondary"><summary>Administration');
    expect(shellHtml({ name: "machines" }, true)).toContain('<details class="app-navgroup app-navgroup--secondary" open>');
  });

  it("puts Dossiers in Administration on desktop, keeping five daily entries", () => {
    const groups = shellNavGroups({ name: "dashboard" }, true);
    expect(groups[0]?.items).toHaveLength(5);
    expect(groups[1]?.items[0]?.href).toBe(groups[1]?.items.find((item) => item.icon === "folder")?.href);
  });

  it("marks exactly one active item per route", () => {
    for (const route of [
      { name: "dashboard" },
      { name: "projects" },
      { name: "task", id: "t-1" },
      { name: "agents" },
      { name: "agent", id: "a-1" },
      { name: "libraryDetail", kind: "rules", id: "x" },
    ] as const) {
      const active = shellNavGroups(route).flatMap((group) => group.items).filter((item) => item.active);
      expect(active).toHaveLength(1);
    }
  });

  it("leaves groups inactive on configuration routes (Paramètres foot link carries it)", () => {
    const active = shellNavGroups({ name: "configBindings" })
      .flatMap((group) => group.items)
      .filter((item) => item.active);
    expect(active).toHaveLength(0);
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
    expect(html).toContain("Paramètres");
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
    expect(html).toContain("<span>Agents</span>");
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

  it("exposes exactly one connection-status with avatar, dot and short label", () => {
    for (const authed of [true, false]) {
      const html = shellHtml({ name: "dashboard" }, authed);
      expect(html.match(/data-testid="connection-status"/g)).toHaveLength(1);
      expect(html).toContain("ds-avatar");
      expect(html).toContain("app-connection-dot");
      expect(html).toContain(authed ? "Connecté" : "Non connecté");
    }
  });

  it("removes the duplicated topbar and account states, keeps logout and token form", () => {
    const authed = shellHtml({ name: "dashboard" }, true);
    expect(authed).not.toContain('id="token-state"');
    expect(authed).not.toContain("jeton masqué");
    expect(authed).toContain('id="token-clear"');
    expect(authed).toContain("Se déconnecter");
    const anon = shellHtml({ name: "dashboard" }, false);
    expect(anon).not.toContain('id="token-state"');
    expect(anon).toContain('id="token-input"');
    expect(anon).toContain('id="token-set"');
    expect(anon).toContain("Non connecté");
  });

  it("links the indicator to Application on desktop, Runtimes on web", () => {
    expect(shellHtml({ name: "dashboard" }, true, true)).toContain('data-testid="connection-status"');
    expect(shellHtml({ name: "dashboard" }, true, true)).toContain('href="#/configuration/application"');
    expect(shellHtml({ name: "dashboard" }, true, false)).toContain('href="#/configuration/runtimes"');
  });

  it("syncAuthState keeps a single indicator with auth label", () => {
    document.body.innerHTML = shellHtml({ name: "dashboard" }, false);
    expect(document.querySelectorAll('[data-testid="connection-status"]')).toHaveLength(1);
    syncAuthState(true, document);
    expect(document.querySelectorAll('[data-testid="connection-status"]')).toHaveLength(1);
    expect(document.querySelector("#connection-status")?.textContent).toContain("Connecté");
    expect(document.querySelector("#token-state")).toBeNull();
    syncAuthState(false, document);
    expect(document.querySelector("#connection-status")?.textContent).toContain("Non connecté");
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
