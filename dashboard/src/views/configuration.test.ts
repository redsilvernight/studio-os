import { describe, expect, it } from "vitest";
import type { RuntimeRegistration, RuntimeStatus } from "../runtimesApi";
import type { RuntimeBinding } from "../bindingsApi";
import type { RuntimeCapabilities, RuntimeTarget } from "../libraryFormat";
import {
  bindingScopeLabel,
  bindingScopeDescription,
  bindingTargetHtml,
  capabilitySummary,
  configTabsHtml,
  createRuntimeFormHtml,
  filterBindings,
  filterRuntimes,
  initialBindingsState,
  initialRuntimesState,
  isBindingsDefaultState,
  isRuntimesDefaultState,
  runtimeHumanTitle,
  runtimeStatusFr,
  runtimeStatusTone,
  runtimeTargetSummary,
  runtimeDetailHtml,
  safeMetadataEntries,
  runtimesPageHtml,
} from "./configuration";

const caps = (overrides: Partial<RuntimeCapabilities> = {}): RuntimeCapabilities => ({
  coding: false,
  tools: [],
  local: false,
  ...overrides,
});

const target = (overrides: Partial<RuntimeTarget>): RuntimeTarget =>
  ({ capabilities: caps(), ...overrides }) as RuntimeTarget;

const runtime = (overrides: Partial<RuntimeRegistration> = {}): RuntimeRegistration =>
  ({
    id: "rt-1",
    owner_user_id: "owner-1",
    machine_id: null,
    harness_ref: "harness-a",
    provider_ref: "provider-a",
    model_ref: "model-a",
    capabilities: caps(),
    capability_source: "declared",
    runtime_metadata: {},
    status: "active" as RuntimeStatus,
    version: 1,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: null,
    ...overrides,
  }) as RuntimeRegistration;

const binding = (overrides: Partial<RuntimeBinding> = {}): RuntimeBinding =>
  ({
    id: "bind-1",
    level: "user",
    owner_user_id: "owner-1",
    project_id: null,
    target_kind: "agent_definition",
    target_stable_key: "review-helper",
    target: target({ runtime_id: "rt-1" }),
    created_at: "2026-09-01T10:00:00Z",
    ...overrides,
  }) as RuntimeBinding;

describe("configTabsHtml", () => {
  it("liste les domaines réels (Runtimes / Bindings / Projet) en français", () => {
    const html = configTabsHtml("bindings");
    expect(html).toContain("#/configuration/runtimes");
    expect(html).toContain("#/configuration/bindings");
    expect(html).toContain("#/configuration/project");
    expect(html).toContain("Runtimes");
    expect(html).toContain("Bindings");
    expect(html).toContain("Projet");
    expect(html).toMatch(/class="tab active" href="#\/configuration\/bindings"/);
    expect(html).toContain('aria-current="page"');
  });

  it("ne fabrique aucune surface inexistante (pas de Compte / Notifications / API Keys)", () => {
    const html = configTabsHtml("runtimes");
    expect(html).not.toMatch(/notifications|api keys|appearance|security|profile/i);
  });
});

describe("runtimeTargetSummary", () => {
  it("affiche la référence registre et les ancres ouvertes", () => {
    const html = runtimeTargetSummary(
      target({ runtime_id: "rt1", harness_ref: "any-harness", provider_ref: "any-provider", model_ref: "any-model" }),
    );
    expect(html).toContain("rt1");
    expect(html).toContain("any-harness");
    expect(html).toContain("any-provider");
    expect(html).toContain("any-model");
  });

  it("affiche un tiret sans ancre", () => {
    expect(runtimeTargetSummary(target({}))).toContain("—");
  });
});

describe("capabilitySummary", () => {
  it("résume les capacités déclarées sans score ni déduction", () => {
    const html = capabilitySummary(caps({ coding: true, context_window: 128000, tools: ["shell"] }));
    expect(html).toContain("Coding = yes");
    expect(html).toContain("Context window = 128000");
    expect(html).not.toMatch(/puissance|\/100|score/i);
  });

  it("dit honnêtement qu'aucune capacité n'est déclarée", () => {
    expect(capabilitySummary(caps())).toContain("Aucune capacité déclarée");
  });
});

describe("runtimeHumanTitle", () => {
  it("privilégie les références humaines", () => {
    expect(runtimeHumanTitle(runtime())).toBe("harness-a · provider-a · model-a");
  });

  it("ne fabrique jamais un titre à partir d'un UUID seul", () => {
    const title = runtimeHumanTitle(runtime({ harness_ref: null, provider_ref: null, model_ref: null, machine_id: "m-1" }));
    expect(title).toBe("Runtime rattaché à une machine");
    expect(title).not.toContain("m-1");
  });

  it("signale un runtime sans référence", () => {
    expect(runtimeHumanTitle(runtime({ harness_ref: null, provider_ref: null, model_ref: null, machine_id: null }))).toBe(
      "Runtime sans référence déclarée",
    );
  });
});

describe("runtimeStatusFr / tone", () => {
  it("traduit les états canoniques sans en inventer", () => {
    expect(runtimeStatusFr("active")).toBe("Actif");
    expect(runtimeStatusFr("revoked")).toBe("Révoqué");
    expect(runtimeStatusTone("active")).toBe("success");
    expect(runtimeStatusTone("revoked")).toBe("neutral");
  });
});

describe("safeMetadataEntries", () => {
  it("filtre défensivement toute clé ressemblant à un secret", () => {
    const entries = safeMetadataEntries({
      region: "eu-west",
      api_key: "should-never-render",
      Authorization: "Bearer x",
      my_token: "secret",
      password: "p",
      note: 42,
    });
    const keys = entries.map((entry) => entry.key);
    expect(keys).toEqual(["note", "region"]);
    expect(JSON.stringify(entries)).not.toMatch(/should-never-render|Bearer x/);
  });

  it("masque les valeurs structurées et trie les clés", () => {
    const entries = safeMetadataEntries({ b: { nested: true }, a: "flat" });
    expect(entries.map((entry) => entry.key)).toEqual(["a", "b"]);
    expect(entries[1]?.value).toBe("[valeur structurée masquée]");
  });
});

describe("filterRuntimes", () => {
  const runtimes = [
    runtime({ id: "r1", provider_ref: "provider-a", model_ref: "model-big", machine_id: "m1" }),
    runtime({ id: "r2", provider_ref: "provider-b", model_ref: "model-small", machine_id: null }),
    runtime({ id: "r3", provider_ref: "provider-a", model_ref: null, harness_ref: null, status: "revoked" }),
  ];

  it("recherche dans harness/provider/model/identifiant", () => {
    expect(filterRuntimes(runtimes, { ...initialRuntimesState(), query: "model-big" }).map((r) => r.id)).toEqual(["r1"]);
    expect(filterRuntimes(runtimes, { ...initialRuntimesState(), query: "provider-a" }).map((r) => r.id)).toEqual([
      "r1",
      "r3",
    ]);
    expect(filterRuntimes(runtimes, { ...initialRuntimesState(), query: "r2" }).map((r) => r.id)).toEqual(["r2"]);
  });

  it("filtre par provider, machine et statut", () => {
    expect(filterRuntimes(runtimes, { ...initialRuntimesState(), provider: "provider-a" }).map((r) => r.id)).toEqual([
      "r1",
      "r3",
    ]);
    expect(filterRuntimes(runtimes, { ...initialRuntimesState(), machine: "m1" }).map((r) => r.id)).toEqual(["r1"]);
    expect(filterRuntimes(runtimes, { ...initialRuntimesState(), status: "revoked" }).map((r) => r.id)).toEqual(["r3"]);
  });

  it("détecte l'état par défaut et le réinitialise", () => {
    expect(isRuntimesDefaultState(initialRuntimesState())).toBe(true);
    expect(isRuntimesDefaultState({ ...initialRuntimesState(), query: "x" })).toBe(false);
    expect(isRuntimesDefaultState({ ...initialRuntimesState(), includeRevoked: true })).toBe(false);
  });
});

describe("filterBindings", () => {
  const bindings = [
    binding({ id: "b1", level: "user", target_stable_key: "review-helper" }),
    binding({ id: "b2", level: "project_default", project_id: "p1", target_stable_key: "build-helper" }),
    binding({ id: "b3", level: "studio_default", target_stable_key: "ops" }),
  ];

  it("filtre par niveau et par clé logique", () => {
    expect(filterBindings(bindings, { ...initialBindingsState(), scope: "user" }).map((b) => b.id)).toEqual(["b1"]);
    expect(filterBindings(bindings, { ...initialBindingsState(), query: "build" }).map((b) => b.id)).toEqual(["b2"]);
  });

  it("détecte l'état par défaut", () => {
    expect(isBindingsDefaultState(initialBindingsState())).toBe(true);
    expect(isBindingsDefaultState({ ...initialBindingsState(), scope: "user" })).toBe(false);
  });
});

describe("bindingScopeLabel / description", () => {
  it("nomme françaisement les quatre niveaux stockés, session compris", () => {
    expect(bindingScopeLabel("user")).toContain("Personnel");
    expect(bindingScopeLabel("project_override")).toContain("Projet");
    expect(bindingScopeLabel("project_default")).toContain("Projet");
    expect(bindingScopeLabel("studio_default")).toContain("Studio");
    expect(bindingScopeLabel("session")).toContain("éphémère");
    for (const level of ["user", "project_override", "project_default", "studio_default"] as const) {
      expect(bindingScopeDescription(level)).not.toBe("");
    }
  });

  it("marque explicitement la confidentialité du niveau personnel", () => {
    expect(bindingScopeDescription("user")).toContain("Privé");
  });
});

describe("bindingTargetHtml", () => {
  it("résout un runtime_id du registre en titre humain", () => {
    const map = new Map([["rt-1", runtime()]]);
    const html = bindingTargetHtml(binding(), map);
    expect(html).toContain("harness-a · provider-a · model-a");
    expect(html).toContain("rt-1"); // visible en title technique, jamais comme libellé
  });

  it("retombe sur un libellé honnête si le runtime n'est pas chargé", () => {
    const html = bindingTargetHtml(binding(), new Map());
    expect(html).toContain("Runtime rt-1");
  });
});

describe("runtimesPageHtml (rendu)", () => {
  it("rend une page Paramètres française, sans table SQL, avec lien Inspecteur", () => {
    const html = runtimesPageHtml([runtime()]);
    expect(html).toContain("Paramètres");
    expect(html).toContain("Runtimes enregistrés");
    expect(html).toContain("environnement/cible d'exécution");
    expect(html).toContain("#/inspector");
    expect(html).toContain("#/configuration/runtimes/rt-1");
    expect(html).not.toContain("<table");
    expect(html).not.toMatch(/JSON\.stringify|puissance/i);
  });

  it("distingue empty / aucun résultat", () => {
    expect(runtimesPageHtml([])).toContain("Aucun runtime enregistré");
    const filtered = runtimesPageHtml([runtime()]);
    expect(filtered).not.toContain("Aucun runtime ne correspond");
  });

  it("ne fuite aucun secret et n'expose pas de style/handler inline (CSP)", () => {
    const html = runtimesPageHtml([runtime()]);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });
});

describe("runtimeDetailHtml", () => {
  it("hiérarchise les informations humaines, technique replié, liens réels", () => {
    const html = runtimeDetailHtml(runtime({ machine_id: "m-1", runtime_metadata: { region: "eu" } }), [], null);
    expect(html).toContain("Configuration du runtime");
    expect(html).toContain("Informations techniques");
    expect(html).toContain('href="#/machines"');
    expect(html).toContain('href="#/inspector"');
    expect(html).toContain("Capacités déclarées");
    expect(html).toContain("<details");
  });

  it("n'expose jamais un secret ni un JSON massif par défaut", () => {
    const html = runtimeDetailHtml(
      runtime({ runtime_metadata: { api_key: "never", authorization: "Bearer never", region: "eu" } }),
      null,
      "bindings indisponibles",
    );
    expect(html).not.toContain("never");
    expect(html).not.toContain('"region"');
    expect(html).toContain("region");
  });

  it("dégrade partiellement : le runtime reste consultable si les bindings échouent", () => {
    const html = runtimeDetailHtml(runtime(), null, "HTTP 503 · indisponible");
    expect(html).toContain("Configuration du runtime");
    expect(html).toContain("Bindings indisponibles");
    expect(html).toContain("le runtime reste consultable");
  });

  it("liste les bindings qui visent ce runtime avec leur niveau", () => {
    const html = runtimeDetailHtml(runtime(), [binding()], null);
    expect(html).toContain("Personnel (privé)");
    expect(html).toContain("review-helper");
  });
});

describe("createRuntimeFormHtml", () => {
  it("décrit la création réelle mais garde les refs ouvertes", () => {
    const html = createRuntimeFormHtml();
    expect(html).toContain("Déclarer un runtime");
    expect(html).toContain("chaînes ouvertes");
    expect(html).toContain("Un envoi répété ne crée pas de doublon.");
    expect(html).not.toContain("POST /runtimes");
    expect(html).not.toMatch(/anthropic|openai|ollama|gemini|mistral|gpt-4/i);
  });
});
