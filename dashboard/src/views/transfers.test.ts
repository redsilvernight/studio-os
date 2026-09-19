/**
 * UI-10 — Transferts : surface Infrastructure (DOM-free).
 *
 * Assertions sur les chaînes produites + lecture statique de transfers.css
 * pour le responsive. Le stockage (bucket, clé S3, URL signée) doit rester
 * invisible par défaut ; aucune action non adossée à un endpoint réel.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Transfer, TransferConsumption } from "../transfersApi";
import { initialTransfersFilterState, type TransfersFilterContext } from "../transfersFormat";
import {
  transferDrawerBodyHtml,
  transferStatusHtml,
  transfersEmptyHtml,
  transfersLoadingHtml,
  transfersPageHtml,
  transfersToolbarHtml,
  uploadModalBodyHtml,
  uploadProgressHtml,
  type TransfersPageData,
} from "./transfers";

const NOW = new Date("2026-09-15T12:00:00.000Z").getTime();
const PROJECT_ID = "99999999-3333-4333-8333-000000000009";
const TASK_ID = "88888888-4444-4444-8444-000000000008";
const RECIPIENT_ID = "cccccccc-5555-4555-8555-000000000003";

function transfer(overrides: Partial<Transfer> = {}): Transfer {
  return {
    id: "aaaaaaaa-1111-4111-8111-000000000001",
    transfer_code: "TRF-ABCD1234",
    sender_user_id: "bbbbbbbb-2222-4222-8222-000000000002",
    recipient_user_id: RECIPIENT_ID,
    project_id: PROJECT_ID,
    task_id: TASK_ID,
    build_id: null,
    category: "build",
    filename: "build-studio-os.zip",
    object_key: "studio/studio-os/2026/09/aaaa/build-studio-os.zip",
    content_type: "application/zip",
    size_bytes: 1536,
    sha256: "deadbeef",
    content_md5: "YWJjZA==",
    status: "ready",
    expires_at: new Date(NOW + 7 * 24 * 60 * 60 * 1000).toISOString(),
    created_at: new Date(NOW - 3600_000).toISOString(),
    uploaded_at: new Date(NOW - 3000_000).toISOString(),
    downloaded_at: null,
    deleted_at: null,
    ...overrides,
  };
}

const ctx: TransfersFilterContext = {
  now: NOW,
  projectNameById: new Map([[PROJECT_ID, "Studio OS"]]),
  taskTitleById: new Map([[TASK_ID, "Refonte UI"]]),
};

function pageData(overrides: Partial<TransfersPageData> = {}): TransfersPageData {
  return {
    transfers: [transfer()],
    state: initialTransfersFilterState(),
    ctx,
    projects: [{ id: PROJECT_ID, name: "Studio OS" } as TransfersPageData["projects"][number]],
    consumption: { consumed_bytes: 512, quota_bytes: 1024, remaining_bytes: 512, project_id: null } as TransferConsumption,
    problems: [],
    ...overrides,
  };
}

describe("transfersLoadingHtml", () => {
  it("affiche un squelette accessible", () => {
    const html = transfersLoadingHtml();
    expect(html).toContain("Transferts");
    expect(html).toContain('role="status"');
  });
});

describe("transfersPageHtml nominal", () => {
  const html = transfersPageHtml(pageData());

  it("titre, fichier, état et action primaire d'envoi", () => {
    expect(html).toContain("<h1>Transferts</h1>");
    expect(html).toContain("build-studio-os.zip");
    expect(html).toContain("TRF-ABCD1234");
    expect(html).toContain("Build");
    expect(html).toContain("1,5 Ko");
    expect(html).toContain("Disponible");
    expect(html).not.toContain("<table>");
    expect(html).toContain('id="transfer-upload-open"');
  });

  it("chaque état est nommé (jamais la couleur seule)", () => {
    expect(transferStatusHtml(transfer({ status: "ready" }), NOW)).toContain("Disponible");
    expect(transferStatusHtml(transfer({ status: "created" }), NOW)).toContain("En attente d'envoi");
    expect(transferStatusHtml(transfer({ status: "downloaded" }), NOW)).toContain("Téléchargé");
  });

  it("signale une expiration déduite", () => {
    const expired = transfer({ status: "ready", expires_at: new Date(NOW - 1000).toISOString() });
    const markup = transferStatusHtml(expired, NOW);
    expect(markup).toContain("Expiré");
    expect(markup).toContain("déduit");
  });

  it("n'expose ni bucket, ni clé S3, ni URL signée dans la liste", () => {
    expect(html).not.toContain("studio/studio-os/2026/09");
    expect(html).not.toContain("X-Amz");
    expect(html).not.toContain("download_url");
  });

  it("lie projet et tâche vers les routes réelles, sans route machine/agent", () => {
    expect(html).toContain(`href="#/projects/${PROJECT_ID}"`);
    expect(html).toContain(`href="#/tasks/${TASK_ID}"`);
    expect(html).not.toMatch(/#\/machines\//);
    expect(html).not.toMatch(/#\/agents\//);
  });

  it("ne contient aucun style ni handler inline (CSP)", () => {
    expect(html).not.toMatch(/\sstyle=/i);
    expect(html).not.toMatch(/\son[a-z]+=/i);
    expect(html).not.toContain("javascript:");
  });

  it("propose une action de téléchargement adossée à l'endpoint réel", () => {
    expect(html).toContain("data-transfer-download");
    expect(html).toContain("Télécharger");
  });

  it("n'expose aucune action de cycle de vie sans endpoint", () => {
    for (const forbidden of ["Supprimer", "Réessayer", "Renvoyer", "Partager", "Prolonger", "Révoquer"]) {
      expect(html).not.toContain(`>${forbidden}<`);
    }
    expect(html).not.toMatch(/data-transfer-(delete|cancel|retry|share|revoke|extend)/);
  });
});

describe("transfersPageHtml états", () => {
  it("état vide : explication + CTA d'envoi uniquement", () => {
    const html = transfersPageHtml(pageData({ transfers: [], projects: [] }));
    expect(html).toContain("Les transferts permettent d'échanger des fichiers via Studi'OS.");
    expect(html).toContain("data-transfer-upload-open");
    expect(html).not.toContain("transfers-toolbar");
  });

  it("aucun résultat : état dédié, liste principale conservée", () => {
    const html = transfersPageHtml(
      pageData({ state: { ...initialTransfersFilterState(), query: "introuvable" } }),
    );
    expect(html).toContain("Aucun transfert ne correspond");
  });

  it("signale des données secondaires partielles sans casser la liste", () => {
    const html = transfersPageHtml(pageData({ problems: ["projets indisponibles (HTTP 500)"] }));
    expect(html).toContain("Données partielles");
    expect(html).toContain("build-studio-os.zip");
  });
});

describe("toolbar", () => {
  it("recherche et filtres locaux explicites, options françaises", () => {
    const html = transfersToolbarHtml([transfer()], initialTransfersFilterState(), 1, ctx);
    expect(html).toContain('role="search"');
    expect(html).toContain("Tous les états");
    expect(html).toContain("Toutes les catégories");
    expect(html).toContain("Tous les projets");
    expect(html).toContain("Studio OS");
    expect(html).toContain("recherche et filtres locaux");
    expect(html).toContain("1 transfert(s) affiché(s) sur 1 chargé(s)");
  });
});

describe("transferDrawerBodyHtml", () => {
  const html = transferDrawerBodyHtml(transfer(), ctx);

  it("informations métier prioritaires, en français", () => {
    expect(html).toContain("build-studio-os.zip");
    expect(html).toContain("Catégorie");
    expect(html).toContain("Expéditeur");
    expect(html).toContain("Destinataire");
    expect(html).toContain("Expiration");
  });

  it("replie les informations techniques et n'expose aucun secret", () => {
    expect(html).toContain("<details");
    expect(html).toContain("Informations techniques");
    expect(html).toContain("Référence de stockage");
    expect(html).toContain("deadbeef");
    expect(html).not.toContain("X-Amz");
    expect(html).not.toContain("download_url");
    expect(html).not.toContain("token");
  });

  it("rappelle que les actions destructives ne sont pas proposées", () => {
    expect(html).toContain("Suppression, annulation, prolongation et renvoi ne sont pas proposés");
  });

  it("n'expose le téléchargement que pour un objet disponible", () => {
    expect(html).toContain("data-transfer-download");
    const draft = transferDrawerBodyHtml(transfer({ status: "created", uploaded_at: null }), ctx);
    expect(draft).toContain("Téléchargement indisponible");
    expect(draft).not.toContain("data-transfer-download");
  });
});

describe("uploadModalBodyHtml", () => {
  const html = uploadModalBodyHtml(pageData().projects, pageData().consumption);

  it("champ fichier labellisé, destinataire honnête, catégorie, quota advisory", () => {
    expect(html).toContain('type="file"');
    expect(html).toContain('for="transfer-file"');
    expect(html).toContain("Destinataire");
    expect(html).toContain("Aucun annuaire utilisateur");
    expect(html).toContain("Quota :");
    expect(html).toContain("512 octets restants");
  });

  it("gère l'absence de projets sans casser le formulaire", () => {
    const html = uploadModalBodyHtml([], null);
    expect(html).toContain("bucket partagé");
    expect(html).toContain('type="file"');
  });
});

describe("uploadProgressHtml", () => {
  it("n'affiche un pourcentage que lorsque des octets sont réellement mesurés", () => {
    expect(uploadProgressHtml({ phase: "hashing", uploadedBytes: 0, totalBytes: 100 })).not.toContain("<progress");
    const uploading = uploadProgressHtml({ phase: "uploading", uploadedBytes: 50, totalBytes: 100 });
    expect(uploading).toContain("50 %");
    expect(uploading).toContain("<progress");
    expect(uploadProgressHtml({ phase: "done", uploadedBytes: 100, totalBytes: 100 })).toContain("Envoyé.");
  });
});

describe("échappement", () => {
  it("échappe un nom de fichier hostile", () => {
    const html = transfersPageHtml(pageData({ transfers: [transfer({ filename: "<script>alert(1)</script>" })] }));
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain("&lt;script&gt;");
  });
});

describe("transfers.css", () => {
  const css = readFileSync(join(__dirname, "transfers.css"), "utf-8");

  it("prévoit le mobile 375, la réduction de mouvement et aucun global", () => {
    expect(css).toContain("@media (max-width: 640px)");
    expect(css).toContain("prefers-reduced-motion");
    expect(css).not.toContain("body {");
    expect(css).toContain(".transfer-row");
  });
});
