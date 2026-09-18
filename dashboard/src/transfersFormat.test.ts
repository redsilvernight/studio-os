/**
 * UI-10 — Transferts : dérivation d'affichage (DOM-free).
 *
 * Vérifie que les libellés français correspondent aux statuts backend réels,
 * que la taille humaine tient ses bornes, que la recherche/les filtres/le tri
 * ne travaillent que sur les champs réellement chargés, et qu'aucune donnée
 * sensible n'est nécessaire à l'affichage.
 */
import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import type { Transfer } from "./transfersApi";
import {
  effectiveStatus,
  expiryLabelFr,
  filterTransfers,
  humanBytes,
  initialTransfersFilterState,
  isDownloadable,
  isExpired,
  isTransfersDefaultState,
  isUuid,
  normalizeStatus,
  recipientLabelFr,
  senderLabelFr,
  sortTransfers,
  transferCategoryFr,
  transferErrorMessage,
  transferProjectIds,
  visibleTransfers,
  type TransfersFilterContext,
} from "./transfersFormat";

const NOW = new Date("2026-09-15T12:00:00.000Z").getTime();
const iso = (offsetMs: number): string => new Date(NOW + offsetMs).toISOString();

function transfer(overrides: Partial<Transfer> = {}): Transfer {
  return {
    id: "aaaaaaaa-1111-4111-8111-000000000001",
    transfer_code: "TRF-ABCD1234",
    sender_user_id: "bbbbbbbb-2222-4222-8222-000000000002",
    recipient_user_id: null,
    project_id: null,
    task_id: null,
    build_id: null,
    category: "temporary",
    filename: "build.zip",
    object_key: "studio/unscoped/2026/09/aaaa/build.zip",
    content_type: "application/zip",
    size_bytes: 1536,
    sha256: null,
    content_md5: null,
    status: "ready",
    expires_at: iso(7 * 24 * 60 * 60 * 1000),
    created_at: iso(-3600_000),
    uploaded_at: iso(-3000_000),
    downloaded_at: null,
    deleted_at: null,
    ...overrides,
  };
}

const ctx: TransfersFilterContext = {
  now: NOW,
  projectNameById: new Map([["99999999-3333-4333-8333-000000000009", "Studio OS"]]),
  taskTitleById: new Map([["88888888-4444-4444-8444-000000000008", "Refonte UI"]]),
};

describe("humanBytes", () => {
  it("respecte les bornes octets / Ko / Mo / Go", () => {
    expect(humanBytes(0)).toBe("0 octets");
    expect(humanBytes(1)).toBe("1 octet");
    expect(humanBytes(1023)).toBe("1023 octets");
    expect(humanBytes(1024)).toBe("1 Ko");
    expect(humanBytes(1536)).toBe("1,5 Ko");
    expect(humanBytes(1024 * 1024)).toBe("1 Mo");
    expect(humanBytes(1024 * 1024 * 1024)).toBe("1 Go");
    expect(humanBytes(1024 * 1024 * 1024 * 1024)).toBe("1 To");
  });

  it("reste honnête quand la taille est absente ou invalide", () => {
    expect(humanBytes(null)).toBe("—");
    expect(humanBytes(undefined)).toBe("—");
    expect(humanBytes(-1)).toBe("—");
    expect(humanBytes(Number.NaN)).toBe("—");
  });
});

describe("statuts", () => {
  it("traduit chaque statut backend réel en français", () => {
    expect(effectiveStatus(transfer({ status: "created" }), NOW).label).toBe("En attente d'envoi");
    expect(effectiveStatus(transfer({ status: "uploading" }), NOW).label).toBe("Envoi en cours");
    expect(effectiveStatus(transfer({ status: "ready" }), NOW).label).toBe("Disponible");
    expect(effectiveStatus(transfer({ status: "downloaded" }), NOW).label).toBe("Téléchargé");
    expect(effectiveStatus(transfer({ status: "expired" }), NOW).label).toBe("Expiré");
    expect(effectiveStatus(transfer({ status: "deleted" }), NOW).label).toBe("Supprimé");
  });

  it("dérive l'expiration de expires_at, en le signalant", () => {
    const expired = transfer({ status: "ready", expires_at: iso(-1000) });
    const status = effectiveStatus(expired, NOW);
    expect(status.key).toBe("expired");
    expect(status.derivedExpiry).toBe(true);
    expect(status.tone).toBe("danger");
    expect(isExpired(expired, NOW)).toBe(true);
  });

  it("ne dérive jamais une expiration sur un transfert supprimé", () => {
    const removed = transfer({ status: "deleted", expires_at: iso(-1000) });
    expect(effectiveStatus(removed, NOW).key).toBe("deleted");
    expect(effectiveStatus(removed, NOW).derivedExpiry).toBe(false);
    expect(isExpired(removed, NOW)).toBe(false);
  });

  it("n'utilise jamais la couleur seule : chaque statut porte un libellé", () => {
    for (const status of ["created", "uploading", "ready", "downloaded", "expired", "deleted"] as const) {
      const label = effectiveStatus(transfer({ status }), NOW);
      expect(label.label.length).toBeGreaterThan(0);
      expect(label.hint.length).toBeGreaterThan(0);
    }
  });

  it("normalise un statut inconnu sans inventer", () => {
    expect(normalizeStatus("ready")).toBe("ready");
    expect(normalizeStatus("wat")).toBe("created");
  });
});

describe("téléchargement", () => {
  it("disponible seulement si le fichier a été envoyé et n'est pas expiré/supprimé", () => {
    expect(isDownloadable(transfer({ status: "ready" }), NOW)).toBe(true);
    expect(isDownloadable(transfer({ status: "downloaded" }), NOW)).toBe(true);
    expect(isDownloadable(transfer({ status: "created" }), NOW)).toBe(false);
    expect(isDownloadable(transfer({ status: "uploading" }), NOW)).toBe(false);
    expect(isDownloadable(transfer({ status: "deleted" }), NOW)).toBe(false);
    expect(isDownloadable(transfer({ status: "ready", expires_at: iso(-1) }), NOW)).toBe(false);
  });
});

describe("catégorie, expiration, participants", () => {
  it("traduit les catégories", () => {
    expect(transferCategoryFr("temporary")).toBe("Temporaire");
    expect(transferCategoryFr("build")).toBe("Build");
    expect(transferCategoryFr("asset")).toBe("Ressource");
    expect(transferCategoryFr("raw_recording")).toBe("Enregistrement brut");
  });

  it("affiche une expiration lisible", () => {
    expect(expiryLabelFr(null, NOW)).toBe("Aucune expiration programmée");
    expect(expiryLabelFr(iso(-1000), NOW)).toMatch(/^Expiré depuis le /);
    expect(expiryLabelFr(iso(1000), NOW)).toMatch(/^Expire le /);
  });

  it("représente honnêtement l'expéditeur et le destinataire (aucun annuaire)", () => {
    expect(senderLabelFr(transfer())).toMatch(/^Utilisateur bbbbbbbb…$/);
    expect(recipientLabelFr(transfer())).toMatch(/^Diffusion/);
    expect(recipientLabelFr(transfer({ recipient_user_id: "cccccccc-5555-4555-8555-000000000003" }))).toMatch(
      /^Utilisateur cccccccc…$/,
    );
  });
});

describe("recherche, filtres, tri", () => {
  const a = transfer({ id: "a", transfer_code: "TRF-AAAA1111", filename: "alpha.zip", created_at: iso(-1000) });
  const b = transfer({
    id: "b",
    transfer_code: "TRF-BBBB2222",
    filename: "beta.log",
    category: "build",
    status: "created",
    project_id: "99999999-3333-4333-8333-000000000009",
    task_id: "88888888-4444-4444-8444-000000000008",
    created_at: iso(-2000),
  });

  it("recherche uniquement dans les champs chargés", () => {
    const state = { ...initialTransfersFilterState(), query: "beta" };
    expect(filterTransfers([a, b], state, ctx).map((t) => t.id)).toEqual(["b"]);
    expect(filterTransfers([a, b], { ...state, query: "AAAA" }, ctx).map((t) => t.id)).toEqual(["a"]);
    expect(filterTransfers([a, b], { ...state, query: "studio os" }, ctx).map((t) => t.id)).toEqual(["b"]);
    expect(filterTransfers([a, b], { ...state, query: "refonte ui" }, ctx).map((t) => t.id)).toEqual(["b"]);
    expect(filterTransfers([a, b], { ...state, query: "AAAAAAAA" }, ctx)).toHaveLength(0);
  });

  it("filtre par état effectif (expiration incluse), catégorie et projet", () => {
    expect(filterTransfers([a, b], { ...initialTransfersFilterState(), status: "created" }, ctx).map((t) => t.id)).toEqual(["b"]);
    expect(filterTransfers([a, b], { ...initialTransfersFilterState(), category: "build" }, ctx).map((t) => t.id)).toEqual(["b"]);
    expect(
      filterTransfers([a, b], { ...initialTransfersFilterState(), projectId: "99999999-3333-4333-8333-000000000009" }, ctx).map((t) => t.id),
    ).toEqual(["b"]);
    const state = initialTransfersFilterState();
    expect(filterTransfers([a, b], state, ctx)).toHaveLength(2);
  });

  it("trie de façon déterministe (créé décroissant, puis code, puis id)", () => {
    const c = transfer({ id: "c", transfer_code: "TRF-AAAA0000", created_at: iso(-1000) });
    expect(sortTransfers([a, b, c]).map((t) => t.id)).toEqual(["a", "c", "b"]);
  });

  it("reconnaît l'état par défaut", () => {
    expect(isTransfersDefaultState(initialTransfersFilterState())).toBe(true);
    expect(isTransfersDefaultState({ ...initialTransfersFilterState(), query: "x" })).toBe(false);
    expect(isTransfersDefaultState({ ...initialTransfersFilterState(), status: "ready" })).toBe(false);
  });

  it("visibleTransfers combine tri et filtres", () => {
    expect(visibleTransfers([b, a], initialTransfersFilterState(), ctx).map((t) => t.id)).toEqual(["a", "b"]);
  });

  it("liste les projets distincts présents dans les transferts", () => {
    expect(transferProjectIds([a, b])).toEqual(["99999999-3333-4333-8333-000000000009"]);
  });
});

describe("erreurs actionnables", () => {
  it("expose la taille maximale sur 413 et le restant sur 507", () => {
    const tooLarge = new ApiError({
      status: 413,
      errorCode: "transfer_too_large",
      message: "transfer_too_large",
      serverVersion: null,
      details: { error_code: "transfer_too_large", size_bytes: 10, max_size_bytes: 1024 * 1024 * 1024 },
    });
    expect(transferErrorMessage(tooLarge)).toContain("1 Go");

    const quota = new ApiError({
      status: 507,
      errorCode: "quota_exceeded",
      message: "quota_exceeded",
      serverVersion: null,
      details: { quota_bytes: 10 * 1024 * 1024 * 1024, consumed_bytes: 9 * 1024 * 1024 * 1024 },
    });
    expect(transferErrorMessage(quota)).toContain("1 Go restants");
  });

  it("retombe sur un message générique sinon", () => {
    expect(transferErrorMessage(new Error("boom"))).toBe("boom");
  });
});

describe("isUuid", () => {
  it("valide les UUID et rejette le reste", () => {
    expect(isUuid("bbbbbbbb-2222-4222-8222-000000000002")).toBe(true);
    expect(isUuid(" pas-un-uuid ")).toBe(false);
    expect(isUuid("")).toBe(false);
  });
});
