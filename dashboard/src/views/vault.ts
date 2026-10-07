/**
 * P14 — Vault : connaissances transverse (studio) et par projet.
 *
 * - Liste : navigation par portée (Studio / projet courant via le sélecteur,
 *   prérempli du projet sélectionné), recherche serveur (`GET /vault/search`
 *   dès qu'une requête est saisie, sinon `GET /vault/tree` paginé),
 *   filtres par type et statut (requêtes serveur, jamais inventés).
 * - Détail : corps Markdown rendu de façon sûre (`renderNoteMarkdown`,
 *   même rendu que les notes de version — échappement puis titres/listes/
 *   gras), liens vers les notes liées, ancres.
 * - Validation : `proposed → validated` (accepter), `proposed → archived`
 *   (refuser), boutons visibles seulement si le rôle le permet (portée
 *   studio : admin ; portée projet : rôle d'écriture, `readonly` exclu —
 *   le serveur revérifie l'appartenance projet), envoi avec
 *   `expected_version`, `409` → message humain + rechargement serveur.
 * - Historique : liste des versions immuables + affichage d'une version.
 *
 * Libellés FR en surface ; slugs, types, statuts et JSON restent anglais.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { fetchIdentity } from "../identityApi";
import { renderNoteMarkdown } from "../releaseNotes";
import { dsBadge, dsEmptyState, dsNotify, dsPageHeader, dsSkeleton } from "../ds/ds";
import { uiState } from "../store";
import { describeError, esc, fmtTime } from "../ui";
import {
  getVaultNote,
  listVaultTree,
  listVaultVersions,
  searchVault,
  updateVaultNote,
  type VaultNote,
  type VaultNoteStatus,
  type VaultNoteSummary,
  type VaultNoteType,
  type VaultNoteVersion,
} from "../vaultApi";
import type { components } from "../openapi-schema";

type Project = components["schemas"]["Project"];
type VaultNoteLinkKind = NonNullable<VaultNote["links"]>[number]["kind"];
type AuthRole = components["schemas"]["AuthIdentity"]["role"];

export interface VaultContext {
  client: StudioClient;
  authed: boolean;
}

export type VaultScopeFilter = "studio" | "project";

export interface VaultListState {
  scope: VaultScopeFilter;
  projectId: string | null;
  query: string;
  noteType: VaultNoteType | "all";
  status: VaultNoteStatus | "all";
}

export const VAULT_TYPE_LABEL: Record<VaultNoteType, string> = {
  decision: "Décision",
  rule: "Règle",
  convention: "Convention",
  procedure: "Procédure",
  reference: "Référence",
  lesson: "Leçon",
  note: "Note",
};

export const VAULT_STATUS_LABEL: Record<VaultNoteStatus, string> = {
  draft: "Brouillon",
  proposed: "Proposée",
  validated: "Validée",
  superseded: "Remplacée",
  archived: "Archivée",
};

const VAULT_STATUS_TONE: Record<VaultNoteStatus, "neutral" | "info" | "success" | "warning"> = {
  draft: "neutral",
  proposed: "info",
  validated: "success",
  superseded: "warning",
  archived: "neutral",
};

/** Nature d'un lien : slug anglais côté API, libellé français en surface. */
export const VAULT_LINK_LABEL: Record<VaultNoteLinkKind, string> = {
  links_to: "Renvoie vers",
  relates_to: "Se rapporte à",
  derived_from: "Dérivée de",
  supersedes: "Remplace",
};

export const VAULT_TREE_LIMIT = 50;

/**
 * Boutons Accepter/Refuser visibles seulement si le rôle le permet :
 * portée studio → admin ; portée projet → rôle d'écriture (`readonly`
 * exclu, le serveur revérifie l'appartenance au projet). Seule une note
 * `proposed` se tranche ici.
 */
export function canDecideVaultNote(
  scope: VaultNote["scope"],
  status: VaultNote["status"],
  role: AuthRole | null,
): boolean {
  if (status !== "proposed" || role === null) return false;
  if (scope === "studio") return role === "admin";
  return role === "admin" || role === "developer" || role === "agent";
}

export function vaultScopeLabel(scope: VaultNote["scope"]): string {
  return scope === "studio" ? "Studio" : "Projet";
}

function noteHref(noteId: string): string {
  return `#/vault/${encodeURIComponent(noteId)}`;
}

function statusBadge(status: VaultNoteStatus): string {
  return dsBadge(VAULT_STATUS_LABEL[status] ?? String(status), VAULT_STATUS_TONE[status] ?? "neutral");
}

function typeBadge(noteType: VaultNoteType): string {
  return dsBadge(VAULT_TYPE_LABEL[noteType] ?? String(noteType), "neutral");
}

export function vaultItemHtml(note: VaultNoteSummary): string {
  const title = note.title.trim() === "" ? note.slug : note.title;
  const readable = note.readable_id !== null && note.readable_id !== undefined
    ? `<span class="ds-list-sub"><code class="mono">${esc(note.readable_id)}</code></span>`
    : "";
  return `<li class="ds-list-item" data-id="${esc(note.id)}">` +
    `<span class="grow"><span class="ds-list-title"><a href="${esc(noteHref(note.id))}">${esc(title)}</a></span> ` +
    `${readable}<br />` +
    `<span class="ds-list-sub"><code class="mono">${esc(note.slug)}</code> · ${esc(vaultScopeLabel(note.scope))} · v${note.version}</span></span>` +
    `<span class="vault-badges">${typeBadge(note.note_type)}${statusBadge(note.status)}</span></li>`;
}

export function vaultListHtml(
  notes: VaultNoteSummary[],
  opts: { searching: boolean; truncated?: boolean; total?: number },
): string {
  if (notes.length === 0) {
    return dsEmptyState(
      opts.searching ? "Aucun résultat" : "Aucune note",
      opts.searching
        ? "Aucune note ne correspond à cette recherche et à ces filtres."
        : "Aucune note dans cette portée pour le moment.",
    );
  }
  const hint = opts.searching && opts.total !== undefined
    ? `<p class="ds-list-sub" role="status">${opts.total} résultat(s)${opts.truncated === true ? " — liste tronquée, affinez la recherche" : ""}</p>`
    : "";
  return `${hint}<ul class="ds-list vault-list" role="list">${notes.map(vaultItemHtml).join("")}</ul>`;
}

function vaultToolbarHtml(
  state: VaultListState,
  projects: Project[],
  counts: { shown: number; searching: boolean },
): string {
  const scopeStudio = state.scope === "studio";
  const projectOptions = projects
    .map((project) => `<option value="${esc(project.id)}"${state.projectId === project.id ? " selected" : ""}>${esc(project.name)}</option>`)
    .join("");
  const typeOptions = [`<option value="all"${state.noteType === "all" ? " selected" : ""}>Tous les types</option>`]
    .concat(
      (Object.keys(VAULT_TYPE_LABEL) as VaultNoteType[]).map(
        (type) => `<option value="${esc(type)}"${state.noteType === type ? " selected" : ""}>${esc(VAULT_TYPE_LABEL[type])}</option>`,
      ),
    )
    .join("");
  const statusOptions = [`<option value="all"${state.status === "all" ? " selected" : ""}>Tous les statuts</option>`]
    .concat(
      (Object.keys(VAULT_STATUS_LABEL) as VaultNoteStatus[]).map(
        (status) => `<option value="${esc(status)}"${state.status === status ? " selected" : ""}>${esc(VAULT_STATUS_LABEL[status])}</option>`,
      ),
    )
    .join("");
  return `<div class="vault-toolbar" role="search" aria-label="Filtrer le vault">` +
    `<div class="vault-scopes" role="group" aria-label="Portée">` +
    `<button class="${scopeStudio ? "ds-btn ds-btn--primary" : "ds-btn"}" type="button" data-vault-scope="studio" aria-pressed="${scopeStudio ? "true" : "false"}">Studio</button>` +
    `<button class="${scopeStudio ? "ds-btn" : "ds-btn ds-btn--primary"}" type="button" data-vault-scope="project" aria-pressed="${scopeStudio ? "false" : "true"}">Projet</button>` +
    `</div>` +
    (scopeStudio
      ? ""
      : `<label class="vault-filter"><span>Projet</span><select class="ds-select" id="vault-project">${projectOptions === "" ? `<option value="">Aucun projet accessible</option>` : projectOptions}</select></label>`) +
    `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span>` +
    `<label class="ds-sr-only" for="vault-query">Rechercher dans le vault</label>` +
    `<input class="ds-input" type="search" id="vault-query" value="${esc(state.query)}" placeholder="Rechercher (serveur)…" autocomplete="off" /></div>` +
    `<label class="vault-filter"><span>Type</span><select class="ds-select" id="vault-type">${typeOptions}</select></label>` +
    `<label class="vault-filter"><span>Statut</span><select class="ds-select" id="vault-status">${statusOptions}</select></label>` +
    `<button class="ds-btn ds-btn--sm" type="button" id="vault-reset">Réinitialiser</button>` +
    `<p class="ds-list-sub" role="status" aria-live="polite">${counts.shown} note(s) affichée(s)${counts.searching ? " — recherche serveur" : ""}.</p>` +
    `</div>`;
}

export function vaultPageHtml(
  state: VaultListState,
  projects: Project[],
  notes: VaultNoteSummary[],
  opts: { searching: boolean; truncated?: boolean; total?: number; error?: string },
): string {
  const header = dsPageHeader("Vault", "Connaissances validées du studio et des projets.");
  if (opts.error !== undefined) {
    return `${header}<div class="ds-notice ds-notice--danger" role="alert"><strong>Vault indisponible.</strong>${esc(opts.error)}</div>`;
  }
  return `${header}${vaultToolbarHtml(state, projects, { shown: notes.length, searching: opts.searching })}` +
    vaultListHtml(notes, { searching: opts.searching, truncated: opts.truncated, total: opts.total });
}

function vaultLinksHtml(note: VaultNote): string {
  const links = note.links ?? [];
  if (links.length === 0) return `<p class="ds-list-sub">Aucun lien déclaré.</p>`;
  const items = links
    .map(
      (link) =>
        `<li><a href="${esc(noteHref(link.target_note_id))}"><code class="mono">${esc(link.target_note_id)}</code></a> ` +
        `<span class="ds-list-sub">${esc(VAULT_LINK_LABEL[link.kind] ?? link.kind)}</span></li>`,
    )
    .join("");
  return `<ul class="ds-list">${items}</ul>`;
}

function vaultAnchorsHtml(note: VaultNote): string {
  const anchors = note.anchors ?? [];
  if (anchors.length === 0) return `<p class="ds-list-sub">Aucune ancre.</p>`;
  return `<ul class="vault-anchors">${anchors.map((anchor) => `<li><code class="mono">${esc(anchor)}</code></li>`).join("")}</ul>`;
}

/**
 * `message` est le texte d'erreur de la dernière écriture : il survit au
 * re-rendu (le 409 recharge la note et repeint, le message doit rester lisible).
 */
export function vaultDecisionActionsHtml(note: VaultNote, role: AuthRole | null, message?: string): string {
  if (!canDecideVaultNote(note.scope, note.status, role)) return "";
  return `<div class="vault-actions" role="group" aria-label="Trancher cette note">` +
    `<button class="ds-btn ds-btn--sm ds-btn--primary" type="button" data-vault-accept="${esc(note.id)}">Valider</button>` +
    `<button class="ds-btn ds-btn--sm" type="button" data-vault-reject="${esc(note.id)}">Refuser</button>` +
    `<div data-vault-msg class="ds-field-error" role="alert">${message === undefined ? "" : esc(message)}</div></div>`;
}

export function vaultDetailHtml(
  note: VaultNote,
  role: AuthRole | null,
  opts: { versionsError?: string; message?: string } = {},
): string {
  const title = note.title.trim() === "" ? note.slug : note.title;
  const readable = note.readable_id !== null && note.readable_id !== undefined
    ? ` · <code class="mono">${esc(note.readable_id)}</code>`
    : "";
  return `<p><a href="#/vault">← Retour au vault</a></p>` +
    `<p class="ds-hero-eyebrow">Vault / ${esc(vaultScopeLabel(note.scope))}</p>` +
    dsPageHeader(title, note.summary === "" ? "" : note.summary) +
    `<p class="vault-badges">${typeBadge(note.note_type)}${statusBadge(note.status)}` +
    `<span class="ds-list-sub"><code class="mono">${esc(note.slug)}</code>${readable} · v${note.version}</span></p>` +
    vaultDecisionActionsHtml(note, role, opts.message) +
    `<section class="ds-panel" aria-label="Contenu"><header><h2>Contenu</h2></header><div class="body vault-prose">${renderNoteMarkdown(note.body)}</div></section>` +
    `<section class="ds-panel" aria-label="Liens"><header><h2>Liens</h2></header><div class="body">${vaultLinksHtml(note)}</div></section>` +
    `<section class="ds-panel" aria-label="Ancres"><header><h2>Ancres</h2></header><div class="body">${vaultAnchorsHtml(note)}</div></section>` +
    `<section class="ds-panel" aria-label="Historique des versions"><header><h2>Historique des versions</h2></header><div class="body"><div data-vault-versions>` +
    (opts.versionsError !== undefined
      ? `<div class="ds-notice ds-notice--danger" role="alert"><strong>Historique indisponible.</strong>${esc(opts.versionsError)}</div>`
      : dsSkeleton(2)) +
    `</div></div></section>` +
    `<details class="vault-tech"><summary>Informations techniques</summary><dl class="vault-tech-list">` +
    `<div><dt>Identifiant</dt><dd><code class="mono">${esc(note.id)}</code></dd></div>` +
    `<div><dt>Portée</dt><dd>${esc(note.scope)}</dd></div>` +
    (note.project_id !== null && note.project_id !== undefined ? `<div><dt>Projet</dt><dd><code class="mono">${esc(note.project_id)}</code></dd></div>` : "") +
    `<div><dt>Version</dt><dd>v${note.version}</dd></div>` +
    `<div><dt>Mots-clés</dt><dd>${(note.tags ?? []).length === 0 ? "—" : esc((note.tags ?? []).join(", "))}</dd></div>` +
    `</dl></details>`;
}

/**
 * Historique : une ligne par version, du plus récent au plus ancien, corps
 * déplié seulement pour la version choisie (jamais tous les corps d'un coup).
 */
export function vaultVersionsHtml(versions: VaultNoteVersion[], selected: number | null): string {
  if (versions.length === 0) return dsEmptyState("Aucune version", "Aucune version enregistrée pour cette note.");
  const sorted = [...versions].sort((a, b) => b.version - a.version);
  const blocks = sorted
    .map((version) => {
      const open = selected !== null && version.version === selected;
      const headline = `v${version.version} · ${version.title} · ${VAULT_STATUS_LABEL[version.status] ?? version.status}${version.change_summary ? ` — ${version.change_summary}` : ""}`;
      return `<div class="vault-version" data-version="${version.version}">` +
        `<div class="vault-version-head">` +
        `<button class="vault-version-toggle" type="button" data-vault-show-version="${version.version}" aria-expanded="${open ? "true" : "false"}" aria-controls="vault-version-${version.version}">` +
        `${open ? "Masquer" : "Afficher"} v${version.version}</button>` +
        `<span class="vault-version-label">${esc(headline)}</span>` +
        `<span class="ds-list-sub">${fmtTime(version.created_at)}</span>` +
        `</div>` +
        `<div class="vault-version-body" id="vault-version-${version.version}"${open ? "" : " hidden"}>` +
        (open ? `<div class="vault-prose">${renderNoteMarkdown(version.body)}</div>` : "") +
        `</div></div>`;
    })
    .join("");
  return `<div class="vault-versions">${blocks}</div>`;
}

async function fetchProjects(client: StudioClient): Promise<Project[]> {
  const result = await client.GET("/api/v1/projects");
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export async function renderVault(root: HTMLElement, ctx: VaultContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = dsPageHeader("Vault", "Connaissances validées du studio et des projets.") +
      dsEmptyState("Connectez-vous", "Saisissez votre jeton machine pour charger le vault.");
    return;
  }
  root.innerHTML = dsPageHeader("Vault", "Connaissances validées du studio et des projets.") + dsSkeleton(4);
  let projects: Project[] = [];
  try {
    projects = await fetchProjects(ctx.client);
  } catch {
    projects = [];
  }
  const selected = uiState.selectedProjectId;
  const state: VaultListState = {
    scope: selected !== null ? "project" : "studio",
    projectId: selected ?? projects[0]?.id ?? null,
    query: "",
    noteType: "all",
    status: "all",
  };

  const paint = async (): Promise<void> => {
    const searching = state.query.trim() !== "";
    try {
      if (searching) {
        const result = await searchVault(ctx.client, {
          q: state.query.trim(),
          scope: state.scope,
          ...(state.scope === "project" && state.projectId !== null ? { projectId: state.projectId } : {}),
          ...(state.noteType !== "all" ? { noteTypes: [state.noteType] } : {}),
          ...(state.status !== "all" ? { statuses: [state.status] } : {}),
          limit: VAULT_TREE_LIMIT,
        });
        const notes = result.items.map((hit) => hit.note);
        root.innerHTML = vaultPageHtml(state, projects, notes, {
          searching: true,
          truncated: result.truncated,
          total: result.total,
        });
      } else {
        const page = await listVaultTree(ctx.client, {
          scope: state.scope,
          ...(state.scope === "project" && state.projectId !== null ? { projectId: state.projectId } : {}),
          ...(state.status !== "all"
            ? { status: state.status, ...(state.status === "archived" ? { includeArchived: true } : {}) }
            : {}),
          limit: VAULT_TREE_LIMIT,
        });
        const visible = state.noteType === "all"
          ? page.items
          : page.items.filter((note) => note.note_type === state.noteType);
        root.innerHTML = vaultPageHtml(state, projects, visible, { searching: false });
      }
    } catch (error) {
      root.innerHTML = vaultPageHtml(state, projects, [], { searching, error: describeError(error) });
    }
    bind();
  };

  let debounce: ReturnType<typeof setTimeout> | null = null;
  const bind = (): void => {
    root.querySelectorAll<HTMLButtonElement>("[data-vault-scope]").forEach((button) => {
      button.addEventListener("click", () => {
        const scope = button.dataset["vaultScope"];
        if (scope !== "studio" && scope !== "project") return;
        state.scope = scope;
        if (scope === "project" && state.projectId === null) {
          state.projectId = projects[0]?.id ?? null;
        }
        void paint();
      });
    });
    root.querySelector("#vault-project")?.addEventListener("change", (event) => {
      state.projectId = (event.target as HTMLSelectElement).value || null;
      void paint();
    });
    const query = root.querySelector<HTMLInputElement>("#vault-query");
    query?.addEventListener("input", () => {
      if (debounce !== null) clearTimeout(debounce);
      const value = query.value;
      debounce = setTimeout(() => {
        state.query = value;
        void paint();
      }, 250);
    });
    query?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (debounce !== null) clearTimeout(debounce);
        state.query = query.value;
        void paint();
      }
    });
    root.querySelector("#vault-type")?.addEventListener("change", (event) => {
      state.noteType = (event.target as HTMLSelectElement).value as VaultListState["noteType"];
      void paint();
    });
    root.querySelector("#vault-status")?.addEventListener("change", (event) => {
      state.status = (event.target as HTMLSelectElement).value as VaultListState["status"];
      void paint();
    });
    root.querySelector("#vault-reset")?.addEventListener("click", () => {
      state.query = "";
      state.noteType = "all";
      state.status = "all";
      void paint();
      root.querySelector<HTMLInputElement>("#vault-query")?.focus();
    });
  };

  await paint();
}

export async function renderVaultDetail(root: HTMLElement, ctx: VaultContext, noteId: string): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = dsPageHeader("Vault", "Connaissances validées du studio et des projets.") +
      dsEmptyState("Connectez-vous", "Saisissez votre jeton machine pour lire cette note.");
    return;
  }
  root.innerHTML = dsPageHeader("Vault", "") + dsSkeleton(4);
  let note: VaultNote;
  try {
    note = await getVaultNote(ctx.client, noteId);
  } catch (error) {
    root.innerHTML = dsPageHeader("Vault", "Connaissances validées du studio et des projets.") +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Note indisponible.</strong>${esc(describeError(error))}</div>`;
    return;
  }
  const role = (await fetchIdentity(ctx.client))?.role ?? null;

  // Le message d'une écriture refusée survit au re-rendu (409 → rechargement).
  let message: string | undefined;

  const paintDetail = (current: VaultNote): void => {
    root.innerHTML = vaultDetailHtml(current, role, message === undefined ? {} : { message });
    bindDetail(current);
    void loadVersions(current.id);
  };

  const loadVersions = async (id: string): Promise<void> => {
    const host = root.querySelector("[data-vault-versions]");
    if (host === null) return;
    try {
      const page = await listVaultVersions(ctx.client, id, { limit: 100 });
      let selected: number | null = null;
      const repaint = (): void => {
        host.innerHTML = vaultVersionsHtml(page.items, selected);
        host.querySelectorAll<HTMLButtonElement>("[data-vault-show-version]").forEach((button) => {
          button.addEventListener("click", () => {
            const wanted = Number(button.dataset["vaultShowVersion"]);
            selected = selected === wanted ? null : wanted;
            repaint();
            const again = host.querySelector<HTMLButtonElement>(`[data-vault-show-version="${wanted}"]`);
            again?.focus();
          });
        });
      };
      repaint();
    } catch (error) {
      host.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Historique indisponible.</strong>${esc(describeError(error))}</div>`;
    }
  };

  const bindDetail = (current: VaultNote): void => {
    const setMsg = (text: string): void => {
      message = text;
      const host = root.querySelector("[data-vault-msg]");
      if (host !== null) host.textContent = text;
    };
    const decide = (kind: "accept" | "reject"): void => {
      const buttons = [...root.querySelectorAll<HTMLButtonElement>("[data-vault-accept], [data-vault-reject]")];
      buttons.forEach((button) => {
        button.disabled = true;
      });
      const target: VaultNoteStatus = kind === "accept" ? "validated" : "archived";
      updateVaultNote(ctx.client, current.id, { expected_version: current.version, status: target })
        .then((updated) => {
          message = undefined;
          dsNotify(kind === "accept" ? "Note validée." : "Note refusée.", kind === "accept" ? "success" : "warning");
          paintDetail(updated);
        })
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 409) {
            setMsg("Cet élément a été modifié ailleurs. Rechargement de la dernière version…");
            getVaultNote(ctx.client, current.id)
              .then((fresh) => paintDetail(fresh))
              .catch((reloadError: unknown) => setMsg(describeError(reloadError)));
            return;
          }
          setMsg(describeError(error));
          buttons.forEach((button) => {
            button.disabled = false;
          });
        });
    };
    root.querySelector("[data-vault-accept]")?.addEventListener("click", () => decide("accept"));
    root.querySelector("[data-vault-reject]")?.addEventListener("click", () => decide("reject"));
  };

  paintDetail(note);
}
