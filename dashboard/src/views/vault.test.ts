/**
 * P14 — Vault : liste par portée + recherche/filtres serveur, détail rendu
 * de façon sûre, décision limitée par le rôle, historique des versions.
 *
 * DOM-free (vitest, environnement node) : assertions sur les chaînes produites
 * + lecture statique de vault.css. Aucune requête n'est émise ici.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  canDecideVaultNote,
  VAULT_STATUS_LABEL,
  VAULT_TREE_LIMIT,
  VAULT_TYPE_LABEL,
  vaultDecisionActionsHtml,
  vaultDetailHtml,
  vaultItemHtml,
  vaultListHtml,
  vaultPageHtml,
  vaultScopeLabel,
  vaultVersionsHtml,
  type VaultListState,
} from "./vault";
import type { VaultNote, VaultNoteSummary, VaultNoteVersion } from "../vaultApi";

const NOTE_ID = "11111111-1111-4111-8111-111111111111";
const PROJECT_ID = "22222222-2222-4222-8222-222222222222";

const summary = (overrides: Partial<VaultNoteSummary> = {}): VaultNoteSummary =>
  ({
    id: NOTE_ID,
    scope: "studio",
    project_id: null,
    slug: "cache-strategy",
    readable_id: "DEC-001",
    note_type: "decision",
    title: "Stratégie de cache",
    summary: "Redis avant PostgreSQL.",
    status: "validated",
    tags: ["cache", "redis"],
    links: [],
    anchors: [],
    content_hash: "h1",
    author_type: "user",
    author_id: "a1",
    version: 2,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }) as VaultNoteSummary;

const note = (overrides: Partial<VaultNote> = {}): VaultNote =>
  ({
    ...summary(),
    body: "# Contexte\n\n- Redis **d'abord**.\n- Jamais de cache local.",
    ...overrides,
  }) as VaultNote;

const version = (overrides: Partial<VaultNoteVersion> = {}): VaultNoteVersion =>
  ({
    note_id: NOTE_ID,
    version: 2,
    title: "Stratégie de cache",
    summary: "Redis avant PostgreSQL.",
    body: "## v2\n\nRedis d'abord.",
    status: "validated",
    tags: [],
    links: [],
    anchors: [],
    content_hash: "h2",
    change_summary: "Ajout de Redis",
    author_type: "user",
    author_id: "a1",
    created_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }) as VaultNoteVersion;

const blank: VaultListState = {
  scope: "studio",
  projectId: null,
  query: "",
  noteType: "all",
  status: "all",
};

/* ---------------- Liste : portée, recherche, filtres ---------------- */

describe("vaultPageHtml (page #/vault)", () => {
  it("bascule entre les portées studio et projet", () => {
    const studio = vaultPageHtml(blank, [], [], { searching: false });
    expect(studio).toContain('data-vault-scope="studio" aria-pressed="true"');
    expect(studio).toContain('data-vault-scope="project" aria-pressed="false"');
    expect(studio).not.toContain('id="vault-project"');

    const project = vaultPageHtml({ ...blank, scope: "project", projectId: PROJECT_ID }, [{ id: PROJECT_ID, name: "Studi'os" } as never], [], {
      searching: false,
    });
    expect(project).toContain('id="vault-project"');
    expect(project).toContain("Studi'os");
    expect(project).toContain('data-vault-scope="project" aria-pressed="true"');
  });

  it("filtre par type et par statut avec les libellés français réels", () => {
    const html = vaultPageHtml(blank, [], [], { searching: false });
    for (const label of Object.values(VAULT_TYPE_LABEL)) expect(html).toContain(label);
    for (const label of Object.values(VAULT_STATUS_LABEL)) expect(html).toContain(label);
    expect(html).toContain('id="vault-type"');
    expect(html).toContain('id="vault-status"');
    expect(html).toContain('id="vault-query"');
    expect(html).toContain('id="vault-reset"');
  });

  it("garde les valeurs courantes sélectionnées", () => {
    const html = vaultPageHtml(
      { ...blank, noteType: "rule", status: "proposed" },
      [],
      [],
      { searching: false },
    );
    expect(html).toContain('<option value="rule" selected>');
    expect(html).toContain('<option value="proposed" selected>');
  });

  it("annonce les résultats et la troncature quand une recherche court", () => {
    const html = vaultPageHtml(blank, [], [summary()], { searching: true, truncated: true, total: 12 });
    expect(html).toContain("12 résultat(s)");
    expect(html).toContain("liste tronquée");
    expect(html).toContain("recherche serveur");
  });

  it("distingue « aucun résultat » d'une portée vide", () => {
    expect(vaultPageHtml(blank, [], [], { searching: true })).toContain("Aucun résultat");
    expect(vaultPageHtml(blank, [], [], { searching: false })).toContain("Aucune note");
  });

  it("affiche l'échec de chargement sans laisser une liste vide silencieuse", () => {
    const html = vaultPageHtml(blank, [], [], { searching: false, error: "HTTP 503" });
    expect(html).toContain("Vault indisponible.");
    expect(html).toContain("HTTP 503");
  });
});

describe("vaultItemHtml / vaultListHtml", () => {
  it("relie la note et montre portée, type, statut et version", () => {
    const html = vaultItemHtml(summary());
    expect(html).toContain(`href="#/vault/${NOTE_ID}"`);
    expect(html).toContain("Stratégie de cache");
    expect(html).toContain("cache-strategy");
    expect(html).toContain("DEC-001");
    expect(html).toContain("Studio");
    expect(html).toContain("v2");
    expect(html).toContain("Validée");
    expect(html).toContain("Décision");
  });

  it("retombe sur le slug quand le titre est vide", () => {
    expect(vaultItemHtml(summary({ title: "   " }))).toContain("cache-strategy");
  });

  it("étiquette une note de projet « Projet »", () => {
    expect(vaultScopeLabel("project")).toBe("Projet");
    expect(vaultItemHtml(summary({ scope: "project", project_id: PROJECT_ID }))).toContain("Projet");
  });

  it("échappe les contenus venus du serveur", () => {
    const html = vaultItemHtml(summary({ title: '<img src=x onerror="alert(1)">' }));
    expect(html).not.toContain("<img src=x");
    expect(html).toContain("&lt;img");
  });

  it("donne un état vide explicite sans ligne factice", () => {
    const html = vaultListHtml([], { searching: false });
    expect(html).toContain("Aucune note");
    expect(html).not.toContain("<li");
  });
});

/* ---------------- Détail : rendu sûr, liens, ancres ---------------- */

describe("vaultDetailHtml", () => {
  const html = vaultDetailHtml(
    note({
      links: [{ target_note_id: "33333333-3333-4333-8333-333333333333", kind: "links_to" }],
      anchors: ["src/cache.ts"],
    }),
    "admin",
  );

  it("rend le corps Markdown échappé, jamais du HTML brut", () => {
    const hostile = vaultDetailHtml(note({ body: "# Titre\n<script>alert(1)</script>" }), null);
    expect(hostile).toContain("<h2>Titre</h2>");
    expect(hostile).not.toContain("<script>");
    expect(hostile).toContain("&lt;script&gt;");
  });

  it("rend listes et gras comme le reste du dashboard", () => {
    expect(html).toContain("<li>Redis <strong>d'abord</strong>.</li>");
    expect(html).toContain("Jamais de cache local.");
  });

  it("montre liens et ancres", () => {
    expect(html).toContain('href="#/vault/33333333-3333-4333-8333-333333333333"');
    expect(html).toContain("src/cache.ts");
    expect(html).toContain("Renvoie vers");
  });

  it("annonce l'absence de liens et d'ancres", () => {
    const bare = vaultDetailHtml(note({ links: [], anchors: [] }), null);
    expect(bare).toContain("Aucun lien déclaré.");
    expect(bare).toContain("Aucune ancre.");
  });

  it("replie les informations techniques", () => {
    expect(html).toContain("<details class=\"vault-tech\"");
    expect(html).toContain(NOTE_ID);
    expect(html).toContain("cache, redis");
  });

  it("gère une note sans tags sans casser", () => {
    expect(vaultDetailHtml(note({ tags: undefined }), null)).toContain("Mots-clés");
  });
});

/* ---------------- Décision : proposed seulement, selon le rôle ---------------- */

describe("canDecideVaultNote", () => {
  it("ne tranche qu'une note proposée", () => {
    expect(canDecideVaultNote("studio", "proposed", "admin")).toBe(true);
    for (const status of ["draft", "validated", "superseded", "archived"] as const) {
      expect(canDecideVaultNote("studio", status, "admin")).toBe(false);
    }
  });

  it("réserve les notes studio à l'admin", () => {
    expect(canDecideVaultNote("studio", "proposed", "developer")).toBe(false);
    expect(canDecideVaultNote("studio", "proposed", "agent")).toBe(false);
    expect(canDecideVaultNote("studio", "proposed", "readonly")).toBe(false);
    expect(canDecideVaultNote("studio", "proposed", null)).toBe(false);
  });

  it("ouvre les notes de projet à tout rôle écrivant", () => {
    for (const role of ["admin", "developer", "agent"] as const) {
      expect(canDecideVaultNote("project", "proposed", role)).toBe(true);
    }
    expect(canDecideVaultNote("project", "proposed", "readonly")).toBe(false);
    expect(canDecideVaultNote("project", "proposed", null)).toBe(false);
  });
});

describe("vaultDecisionActionsHtml", () => {
  it("propose Valider et Refuser à l'admin sur une note studio proposée", () => {
    const html = vaultDecisionActionsHtml(note({ status: "proposed" }), "admin");
    expect(html).toContain(`data-vault-accept="${NOTE_ID}"`);
    expect(html).toContain(`data-vault-reject="${NOTE_ID}"`);
    expect(html).toContain("Valider");
    expect(html).toContain("Refuser");
  });

  it("n'affiche aucun bouton pour un rôle qui ne peut pas trancher", () => {
    expect(vaultDecisionActionsHtml(note({ status: "proposed", scope: "studio" }), "developer")).toBe("");
    expect(vaultDecisionActionsHtml(note({ status: "proposed", scope: "project" }), "readonly")).toBe("");
    expect(vaultDecisionActionsHtml(note({ status: "proposed" }), null)).toBe("");
    expect(vaultDecisionActionsHtml(note({ status: "validated" }), "admin")).toBe("");
  });

  it("prévoit un message d'erreur après une écriture refusée", () => {
    const html = vaultDecisionActionsHtml(note({ status: "proposed" }), "admin");
    expect(html).toContain("data-vault-msg");
    expect(html).toContain('role="alert"');
    expect(html).toContain("<div data-vault-msg class=\"ds-field-error\" role=\"alert\"></div>");
  });

  it("réaffiche le message d'écriture dans le HTML rendu (409 → rechargement)", () => {
    const html = vaultDetailHtml(note({ status: "proposed" }), "admin", {
      message: "Cet élément a été modifié ailleurs. Rechargement de la dernière version…",
    });
    expect(html).toContain("modifié ailleurs");
  });

  it("échappe un message d'erreur venu du serveur", () => {
    const html = vaultDetailHtml(note({ status: "proposed" }), "admin", { message: "<script>x</script>" });
    expect(html).not.toContain("<script>x");
    expect(html).toContain("&lt;script&gt;");
  });
});

/* ---------------- Historique des versions ---------------- */

describe("vaultVersionsHtml", () => {
  const versions = [version({ version: 1, status: "draft", body: "## v1\n\nPremier jet." }), version()];

  it("liste les versions de la plus récente à la plus ancienne", () => {
    const html = vaultVersionsHtml(versions, null);
    expect(html.indexOf("v2")).toBeLessThan(html.indexOf("v1"));
    expect(html).toContain("Brouillon");
    expect(html).toContain("Validée");
    expect(html).toContain("Ajout de Redis");
  });

  it("n'affiche le corps que de la version demandée", () => {
    const html = vaultVersionsHtml(versions, 1);
    expect(html).toContain("Premier jet.");
    expect(html).not.toContain("Redis d'abord.");
    expect(html).toContain('data-vault-show-version="1" aria-expanded="true"');
    expect(html).toContain('data-vault-show-version="2" aria-expanded="false"');
    expect(html).toContain('id="vault-version-2" hidden');
  });

  it("garde un bouton de bascule par version (clavier, aria-expanded)", () => {
    const html = vaultVersionsHtml(versions, null);
    expect(html.match(/data-vault-show-version="\d"/g) ?? []).toHaveLength(2);
    expect(html.match(/aria-controls="vault-version-\d"/g) ?? []).toHaveLength(2);
  });

  it("donne un état vide explicite", () => {
    expect(vaultVersionsHtml([], null)).toContain("Aucune version");
  });

  it("n'injecte pas le HTML d'une version historique", () => {
    const html = vaultVersionsHtml([version({ body: "<script>x</script>" })], 1);
    expect(html).not.toContain("<script>x");
  });
});

/* ---------------- Contrat de présentation ---------------- */

describe("vault.css", () => {
  const css = readFileSync(join(process.cwd(), "src/views/vault.css"), "utf8");

  it("n'utilise ni style ni script inline", () => {
    expect(css).not.toMatch(/style\s*=/);
    expect(css).not.toContain("<script");
  });

  it("passe en colonne sur petit écran", () => {
    expect(css).toContain("@media (max-width: 640px)");
  });

  it("garde des cibles cliquables d'au moins 36px", () => {
    expect(css).toContain("--ds-target-sm");
  });
});

describe("VAULT_TREE_LIMIT", () => {
  it("reste dans la plage serveur (1..200)", () => {
    expect(VAULT_TREE_LIMIT).toBeGreaterThanOrEqual(1);
    expect(VAULT_TREE_LIMIT).toBeLessThanOrEqual(200);
  });
});