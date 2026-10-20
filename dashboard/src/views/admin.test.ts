// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import { fetchCanonicalMachines } from "../machinesApi";
import { ADMIN_FAMILIES, adminIndicators, adminOverviewHtml, loadAdminOverview, renderAdmin, type AdminOverviewData } from "./admin";

vi.mock("../machinesApi", async (original) => ({ ...await original<typeof import("../machinesApi")>(), fetchCanonicalMachines: vi.fn() }));
vi.mock("../desktopShell", () => ({ getDesktopShell: () => null, refreshDaemon: vi.fn() }));

function snapshot(): AdminOverviewData {
  return {
    checkedAt: "2026-10-20T10:00:00Z",
    machines: { data: [{ id: "m1", owner_user_id: "u1", display_name: "Bureau", status: "online", last_seen_at: "2026-10-20T10:00:00Z", created_at: "2026-10-20T10:00:00Z", updated_at: "2026-10-20T10:00:00Z", version: 1 }] },
    runtimes: { data: [{ id: "r1", status: "active", harness_ref: "codex", provider_ref: "openai", model_ref: "configured" } as never] },
    bindings: { data: [{ id: "b1", target: { runtime_id: "r1" } } as never] },
    queue: { data: { items: [], generated_at: "2026-10-20T09:59:00Z" } },
    storage: { data: { consumed_bytes: 1024, quota_bytes: 4096, remaining_bytes: 3072 } },
    daemon: null,
  };
}

afterEach(() => { vi.clearAllMocks(); document.body.innerHTML = ""; });

describe("adminOverviewHtml (P05-admin)", () => {
  it("mène aux 6 familles en 1 clic, sans identifiant visible", () => {
    expect(ADMIN_FAMILIES.map((f) => f.href)).toEqual([
      "#/machines",
      "#/accounts",
      "#/transfers",
      "#/library",
      "#/configuration/runtimes",
      "#/workspaces",
    ]);
    const html = adminOverviewHtml();
    expect(html).toContain("<h1>Administration</h1>");
    expect(html.match(/<h1>/g)).toHaveLength(1);
    expect(html).toContain("Voir les postes");
    for (const family of ADMIN_FAMILIES) {
      expect(html).toContain(`href="${family.href}"`);
      expect(html).toContain(family.title);
    }
    expect(html).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/i);
    expect(html).not.toContain("Connecté");
  });

  it("le chargement ne prétend pas que le système est sain", () => {
    const html = adminOverviewHtml();
    expect(html).toContain("Chargement des indicateurs");
    expect(html).not.toContain("Aucun problème détecté");
    expect(html).not.toContain("#/graphs");
  });

  it("état sain borné aux données consultées, portée et fraîcheur explicites", () => {
    const data = snapshot();
    expect(adminIndicators(data).filter((card) => card.attention)).toHaveLength(0);
    const html = adminOverviewHtml(data);
    expect(html).toContain("Aucun problème détecté dans les données consultées");
    expect(html).toContain("Consulté le");
    expect(html).toContain("Actualisation manuelle");
    expect(html).toContain("La synchronisation des autres postes n'est pas observable");
    expect(html).toContain('href="#/transfers"');
    expect(html).toContain("1 Ko utilisés");
  });

  it("poste hors ligne : compte serveur, nom et page de résolution", () => {
    const data = snapshot();
    data.machines = { data: [
      { ...data.machines.data![0]!, status: "offline" },
      { ...data.machines.data![0]!, id: "dashboard", display_name: "Dashboard", status: "offline" },
    ] };
    const card = adminIndicators(data)[0]!;
    expect(card).toMatchObject({ value: "1 hors ligne", href: "#/machines", attention: true });
    expect(card.detail).toContain("Bureau");
    expect(card.detail).not.toContain("Dashboard");
  });

  it("configuration absente et liaison vers runtime révoqué sont actionnables", () => {
    const data = snapshot();
    data.runtimes = { data: [] };
    const card = adminIndicators(data).find((item) => item.title === "Configuration")!;
    expect(card).toMatchObject({ value: "À compléter", href: "#/configuration/bindings", attention: true });
    expect(card.detail).toContain("Aucun runtime actif");
    expect(card.detail).toContain("1 liaison(s) vers un runtime absent ou révoqué");
  });

  it("les erreurs et restrictions ne deviennent jamais des zéros sains", () => {
    const data = snapshot();
    data.machines = { error: "Accès refusé" };
    data.queue = { error: "Serveur indisponible" };
    data.storage = { error: "Quota indisponible" };
    const cards = adminIndicators(data);
    for (const title of ["Postes", "Validations", "Stockage"]) {
      expect(cards.find((item) => item.title === title)).toMatchObject({ value: "État inconnu", attention: true });
    }
    expect(adminOverviewHtml(data)).not.toContain("Aucun problème détecté");
    expect(adminOverviewHtml(data)).toContain("Accès refusé");
  });

  it("synchronisation locale en erreur : état observé et action diagnostic", () => {
    const data = snapshot();
    data.daemon = { data: { kind: "state", state: "running", health: { heartbeat: "healthy", outboxReplay: "auth_error", gitWatchers: { healthy: 0, total: 0 }, observedAt: "2026-10-20T09:59:00Z" } } };
    expect(adminIndicators(data).find((card) => card.title === "Synchronisation")).toMatchObject({ value: "Authentification refusée", href: "#/configuration/application", attention: true });
    expect(adminOverviewHtml(data)).toContain("Observation locale");
  });

  it("quota épuisé : signale la consommation réelle", () => {
    const data = snapshot();
    data.storage = { data: { consumed_bytes: 4096, quota_bytes: 4096, remaining_bytes: 0 } };
    expect(adminIndicators(data).find((card) => card.title === "Stockage")).toMatchObject({ value: "4 Ko utilisés", href: "#/transfers", attention: true });
  });
});

describe("chargement Administration", () => {
  it("conserve une panne partielle sans perdre les autres sources", async () => {
    vi.mocked(fetchCanonicalMachines).mockRejectedValue(new Error("machine indisponible"));
    const GET = vi.fn(async (path: string) => ({
      data: path.endsWith("review-queue") ? { items: [], generated_at: "2026-10-20T09:59:00Z" } : path.endsWith("consumption") ? { consumed_bytes: 42, quota_bytes: 100, remaining_bytes: 58 } : [],
      response: new Response(null, { status: 200 }),
    }));
    const data = await loadAdminOverview({ client: { GET } as unknown as StudioClient, authed: true, now: () => new Date("2026-10-20T10:00:00Z") });
    expect(data.machines.error).toContain("machine indisponible");
    expect(data.storage.data?.consumed_bytes).toBe(42);
    expect(data.checkedAt).toBe("2026-10-20T10:00:00.000Z");
    expect(data.daemon).toBeNull();
    expect(GET).toHaveBeenCalledTimes(4);
  });

  it("aucune lecture sans connexion", async () => {
    const GET = vi.fn();
    const root = document.createElement("div");
    await renderAdmin(root, { client: { GET } as unknown as StudioClient, authed: false });
    expect(GET).not.toHaveBeenCalled();
    expect(root.textContent).toContain("Connectez-vous");
  });
});
