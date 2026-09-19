/**
 * UI-7 — Bibliothèque : trouver, comprendre, lire, gérer.
 *
 * Refonte de la Bibliothèque CRUD (P12) en bibliothèque de connaissances
 * lisible : page racine calme (5 catégories françaises), listes
 * documentaires aérées avec recherche locale dominante, page détail
 * d'abord LECTURE (contenu prioritaire, technique replié), versions en
 * divulgation progressive, création en modale DS.
 *
 * Capacités préservées (0 perte) : 5 kinds, index, liste par kind,
 * création (+ Idempotency-Key), détail, versions, nouvelle version, locks,
 * Activate / Deprecate (avec révision optimiste), shadowing (signalé, non
 * décidé), deep link Inspector (agent-definitions). Aucun nouveau kind,
 * aucun endpoint, aucun contrat modifié.
 *
 * Données honnêtes : GET /library ne retourne que des LibraryResource
 * (id, kind, stable_key, scope, status, active_version, …) — ni titre ni
 * description ni contenu au niveau liste. La recherche / les filtres
 * portent donc sur les champs réellement chargés (stable_key, portée,
 * état) et l'annoncent. Les titres / contenus vivent dans les versions.
 * La compatibilité réelle n'existe que dans l'Inspecteur (POST
 * /resolutions) : ici, seules les exigences déclarées sont affichées,
 * jamais un verdict inventé (unknown != compatible).
 */
import type { StudioClient } from "../api";
import type { components } from "../openapi-schema";
import {
  LIBRARY_KINDS,
  contentSchema,
  contentText,
  kindFromSlug,
  kindMeta,
  libraryKindHref,
  parseWorkflowContent,
  relationLabel,
  requirementEntries,
  statusTone,
  workflowEdges,
  type CapabilityRequirement,
  type LibraryKind,
  type LibraryKindSlug,
  type LibraryScope,
  type LibraryStatus,
  type WorkflowIODeclaration,
} from "../libraryFormat";
import {
  activateLibraryVersion,
  createLibraryLock,
  createLibraryResource,
  createLibraryVersion,
  deprecateLibraryResource,
  getLibraryResource,
  listLibraryLocks,
  listLibraryResources,
  listLibraryVersions,
  releaseLibraryLock,
  type LibraryLockCreate,
  type LibraryProjectLock,
  type LibraryResource,
  type LibraryResourceCreate,
  type LibraryVersion,
  type LibraryVersionCreate,
} from "../libraryApi";
import {
  buildContent,
  buildDependencies,
  buildWorkflowContent,
  contentFieldsHtml,
  dependencyRowHtml,
  formReader,
  ioRowHtml,
  participantRowHtml,
  readRows,
  asDependencyInputs,
  asIoInputs,
  asParticipantInputs,
} from "./libraryForms";
import {
  closeDsDialog,
  dsBadge,
  dsEmptyState,
  dsModalHtml,
  dsNotify,
  dsPageHeader,
  dsSkeleton,
  dsStatus,
  focusDsErrorBox,
  openDsDialog,
} from "../ds/ds";
import { newIdempotencyKey } from "../claimsApi";
import { describeError, esc, fmtTime, shortId } from "../ui";

export interface LibraryContext {
  client: StudioClient;
  authed: boolean;
}

/* ------------------------------------------------------------------ */
/* Vocabulaire français (présentation seule : URLs, kinds, contrats et */
/* JSON restent en anglais / inchangés).                               */
/* ------------------------------------------------------------------ */

export interface LibraryKindFr {
  slug: LibraryKindSlug;
  kind: LibraryKind;
  singular: string;
  plural: string;
  description: string;
}

export const LIBRARY_KIND_FR: readonly LibraryKindFr[] = [
  {
    slug: "rules",
    kind: "rule",
    singular: "Règle",
    plural: "Règles",
    description: "Textes réutilisables qui cadrent le travail : conventions, exigences, garde-fous.",
  },
  {
    slug: "skills",
    kind: "skill",
    singular: "Compétence",
    plural: "Compétences",
    description: "Savoir-faire réutilisables, mobilisables par les agents dans leur travail.",
  },
  {
    slug: "agent-definitions",
    kind: "agent_definition",
    singular: "Définition d'agent",
    plural: "Définitions d'agents",
    description: "Identités d'agents : rôle et configuration logique, sans exécution ici.",
  },
  {
    slug: "workflows",
    kind: "workflow",
    singular: "Flux de travail",
    plural: "Flux de travail",
    description: "Enchaînements déclaratifs d'étapes et de dépendances — décrits ici, jamais exécutés.",
  },
  {
    slug: "model-profiles",
    kind: "model_profile",
    singular: "Profil de modèle",
    plural: "Profils de modèles",
    description: "Besoins en capacités pour choisir un modèle : raisonnement, outils, contexte.",
  },
];

export function kindFrFromSlug(slug: LibraryKindSlug): LibraryKindFr {
  const found = LIBRARY_KIND_FR.find((entry) => entry.slug === slug);
  if (found !== undefined) return found;
  return { slug, kind: "rule", singular: slug, plural: slug, description: "" };
}

export function kindFr(kind: LibraryKind): LibraryKindFr {
  const found = LIBRARY_KIND_FR.find((entry) => entry.kind === kind);
  if (found !== undefined) return found;
  return { slug: "rules", kind, singular: String(kind), plural: String(kind), description: "" };
}

const SCOPE_FR: Record<LibraryScope, string> = {
  studio: "Studio",
  project: "Projet",
  user: "Utilisateur",
};

export function scopeLabelFr(scope: LibraryScope): string {
  return SCOPE_FR[scope] ?? String(scope);
}

const STATUS_FR: Record<LibraryStatus, string> = {
  draft: "Brouillon",
  active: "Actif",
  deprecated: "Déprécié",
};

export function statusLabelFr(status: LibraryStatus): string {
  return STATUS_FR[status] ?? String(status);
}

function statusBadge(status: LibraryStatus): string {
  const tone = statusTone(status);
  const dsState = tone === "ok" ? "success" : tone === "bad" ? "danger" : "warning";
  return dsStatus(dsState, statusLabelFr(status));
}

function scopeBadge(scope: LibraryScope): string {
  return dsBadge(scopeLabelFr(scope), "neutral");
}

/* ------------------------------------------------------------------ */
/* Navigation par kinds (français, liens stables).                     */
/* ------------------------------------------------------------------ */

export function libraryTabsHtml(active: LibraryKindSlug | null): string {
  const tabs = LIBRARY_KINDS.map((meta) => {
    const fr = kindFr(meta.kind);
    return `<a class="tab${meta.slug === active ? " active" : ""}" href="#/library/${meta.slug}"${meta.slug === active ? ' aria-current="page"' : ""}>${esc(fr.plural)}</a>`;
  }).join("");
  return `<nav class="tabs" aria-label="Catégories de la bibliothèque">${tabs}</nav>`;
}

/* ------------------------------------------------------------------ */
/* Shadowing : signalé quand présent, jamais décidé localement.        */
/* ------------------------------------------------------------------ */

export function shadowNoteHtml(resources: LibraryResource[]): string {
  const scopesByKey = new Map<string, Set<string>>();
  for (const resource of resources) {
    const scopes = scopesByKey.get(resource.stable_key) ?? new Set<string>();
    scopes.add(resource.scope);
    scopesByKey.set(resource.stable_key, scopes);
  }
  const shadowed = [...scopesByKey.values()].filter((scopes) => scopes.size > 1).length;
  if (shadowed === 0) return "";
  return (
    `<div class="ds-notice ds-notice--warning" role="note"><strong>Plusieurs portées pour ${shadowed} clé(s) stable(s).</strong>` +
    `Cette liste montre chaque ressource stockée ; elle ne choisit pas la version effective. ` +
    `Consultez l'<a href="#/inspector">Inspecteur de résolution</a> pour voir la version retenue.</div>`
  );
}

function shadowNoteForDetail(resource: LibraryResource, siblings: LibraryResource[]): string {
  const clash = siblings.some(
    (sibling) => sibling.stable_key === resource.stable_key && sibling.scope !== resource.scope && sibling.id !== resource.id,
  );
  if (!clash) return "";
  return (
    `<div class="ds-notice ds-notice--warning" role="note"><strong>Cette clé existe dans plusieurs portées.</strong>` +
    `Ce que vous lisez est la ressource ${esc(scopeLabelFr(resource.scope))} « ${esc(resource.stable_key)} ». ` +
    `L'<a href="#/inspector/${esc(encodeURIComponent(resource.stable_key))}">Inspecteur de résolution</a> montre la version effective.</div>`
  );
}

/* ------------------------------------------------------------------ */
/* Recherche + filtres : filtrage local honnête sur données chargées.  */
/* ------------------------------------------------------------------ */

export interface LibraryListState {
  query: string;
  scope: LibraryScope | "all";
  status: LibraryStatus | "all";
}

/** Filtre client honnête : sous-chaîne insensible à la casse sur stable_key + libellés chargés. */
export function filterLibraryResources(resources: LibraryResource[], state: LibraryListState): LibraryResource[] {
  const query = state.query.trim().toLowerCase();
  return resources.filter((resource) => {
    if (state.scope !== "all" && resource.scope !== state.scope) return false;
    if (state.status !== "all" && resource.status !== state.status) return false;
    if (query === "") return true;
    const haystack =
      `${resource.stable_key}\n${resource.scope}\n${scopeLabelFr(resource.scope)}\n${resource.status}\n${statusLabelFr(resource.status)}`.toLowerCase();
    return haystack.includes(query);
  });
}

/* ------------------------------------------------------------------ */
/* Listes documentaires (pas de table dense, pas de technique au       */
/* premier plan : stable_key, badges portée/état, version active).     */
/* ------------------------------------------------------------------ */

function resourceItemHtml(resource: LibraryResource): string {
  const active =
    resource.active_version === 0
      ? `<span class="ds-list-sub">Aucune version activée</span>`
      : `<span class="ds-list-sub">Version active : v${resource.active_version}</span>`;
  return (
    `<li class="ds-card library-item"><div class="library-item-top">` +
    `<h3 class="library-item-title"><a href="${esc(libraryKindHref(resource.kind, resource.id))}"><code class="mono">${esc(resource.stable_key)}</code></a></h3>` +
    `<span class="library-item-badges">${scopeBadge(resource.scope)}${statusBadge(resource.status)}</span></div>` +
    `${active}<p class="ds-list-sub">Mis à jour le ${fmtTime(resource.updated_at)}</p></li>`
  );
}

export function resourcesTableHtml(resources: LibraryResource[]): string {
  if (resources.length === 0) return dsEmptyState("Aucune ressource", "Aucune ressource de cette catégorie pour le moment.");
  return `<ul class="library-list">${resources.map(resourceItemHtml).join("")}</ul>`;
}

export function versionsTableHtml(versions: LibraryVersion[], activeVersion: number): string {
  if (versions.length === 0) return dsEmptyState("Aucune version", "Aucune version enregistrée pour cette ressource.");
  const items = [...versions]
    .sort((a, b) => b.version - a.version)
    .map((version) => {
      const badge =
        version.version === activeVersion
          ? dsBadge("Active", "success")
          : dsBadge(`v${version.version}`, "neutral");
      const author = version.created_by_user_id ? ` · par ${esc(shortId(version.created_by_user_id))}` : "";
      return `<li class="ds-list-item"><span class="grow"><span class="ds-list-title">v${version.version} · ${esc(version.title)}</span>` +
        `<br /><span class="ds-list-sub">${fmtTime(version.created_at)}${author}</span></span>${badge}</li>`;
    })
    .join("");
  return `<ul class="ds-list">${items}</ul>`;
}

export function locksTableHtml(locks: LibraryProjectLock[]): string {
  if (locks.length === 0)
    return `<p class="ds-list-sub">Aucun verrou projet sur cette ressource. Un verrou fige une version précise pour un projet donné.</p>`;
  const rows = locks
    .map(
      (lock) =>
        `<tr><td data-lock-id="${esc(lock.id)}"><code class="mono" title="${esc(lock.project_id)}">${esc(shortId(lock.project_id))}</code></td><td>v${lock.locked_version}</td>` +
        `<td>${lock.created_by_user_id ? `<code class="mono" title="${esc(lock.created_by_user_id)}">${esc(shortId(lock.created_by_user_id))}</code>` : '<span class="ds-list-sub">—</span>'}</td><td>${fmtTime(lock.created_at)}</td>` +
        `<td class="actions"><button class="ds-btn ds-btn--sm" type="button" data-release-lock="${esc(lock.id)}" aria-label="Libérer le verrou du projet ${esc(shortId(lock.project_id))}">Libérer</button></td></tr>`,
    )
    .join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><caption>Verrous projet — une version figée par projet</caption><thead><tr><th scope="col">Projet</th><th scope="col">Version figée</th><th scope="col">Créé par</th><th scope="col">Créé le</th><th scope="col"><span class="ds-sr-only">Actions</span></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

export function dependenciesTableHtml(dependencies: LibraryVersion["dependencies"]): string {
  if (dependencies.length === 0) return `<p class="ds-list-sub">Aucune dépendance déclarée.</p>`;
  const rows = dependencies
    .map((pin) => {
      const relation =
        pin.relation !== null && pin.relation !== undefined ? esc(relationLabel(pin.relation)) : '<span class="ds-list-sub">—</span>';
      return `<tr><td>${esc(kindFr(pin.kind).singular)}</td><td><code class="mono">${esc(pin.stable_key)}</code></td><td>v${pin.version}</td><td>${relation}</td></tr>`;
    })
    .join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">Dépendances déclarées</caption><thead><tr><th scope="col">Type</th><th scope="col">Clé stable</th><th scope="col">Version</th><th scope="col">Relation</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function entriesTableHtml(entries: { label: string; value: string }[]): string {
  if (entries.length === 0) return `<p class="ds-list-sub">Aucune exigence déclarée.</p>`;
  const rows = entries.map((entry) => `<tr><td>${esc(entry.label)}</td><td><code class="mono">${esc(entry.value)}</code></td></tr>`).join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">Exigences déclarées</caption><thead><tr><th scope="col">Dimension</th><th scope="col">Valeur</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function ioTableHtml(declarations: WorkflowIODeclaration[], caption: string): string {
  if (declarations.length === 0) return `<p class="ds-list-sub">Aucune entrée déclarée.</p>`;
  const rows = declarations
    .map(
      (declaration) =>
        `<tr><td><code class="mono">${esc(declaration.name)}</code></td><td>${declaration.description !== null ? esc(declaration.description) : '<span class="ds-list-sub">—</span>'}</td>` +
        `<td>${declaration.required ? "requise" : "facultative"}</td><td>${declaration.type !== null ? esc(declaration.type) : '<span class="ds-list-sub">—</span>'}</td>` +
        `<td>${declaration.source !== null ? esc(declaration.source.participantId === null ? `entrée ${declaration.source.name}` : `${declaration.source.participantId}.${declaration.source.name}`) : '<span class="ds-list-sub">—</span>'}</td></tr>`,
    )
    .join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">${esc(caption)}</caption><thead><tr><th scope="col">Nom</th><th scope="col">Description</th><th scope="col">Requise</th><th scope="col">Type</th><th scope="col">Source</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

/** Rendu de lecture d'un contenu versionné, par kind (cohérence sans uniformisation abusive). */
export function versionContentHtml(kind: LibraryKind, version: LibraryVersion): string {
  if (kind === "rule" || kind === "skill") {
    const text = contentText(version.content);
    return text === null
      ? dsEmptyState("Sans texte", "Cette version ne contient aucun texte lisible.")
      : `<div class="library-prose">${esc(text)}</div>`;
  }
  if (kind === "model_profile") {
    const requirements = version.content["requirements"] as CapabilityRequirement | undefined;
    const description = typeof version.content["description"] === "string" ? version.content["description"] : null;
    return (
      (description !== null && description.trim() !== "" ? `<p class="library-prose">${esc(description)}</p>` : "") +
      `<h4>Exigences déclarées</h4>${entriesTableHtml(requirementEntries(requirements))}` +
      `<p class="ds-list-sub">La compatibilité réelle est évaluée dans l'Inspecteur — ici, seules les exigences déclarées sont affichées.</p>`
    );
  }
  if (kind === "agent_definition") {
    const summary = typeof version.content["summary"] === "string" ? version.content["summary"] : null;
    const intendedUse = typeof version.content["intended_use"] === "string" ? version.content["intended_use"] : null;
    return (
      `<dl class="library-kv">` +
      `<div><dt>Résumé</dt><dd>${summary !== null && summary.trim() !== "" ? esc(summary) : '<span class="ds-list-sub">—</span>'}</dd></div>` +
      `<div><dt>Usage prévu</dt><dd>${intendedUse !== null && intendedUse.trim() !== "" ? esc(intendedUse) : '<span class="ds-list-sub">—</span>'}</dd></div></dl>`
    );
  }
  const workflow = parseWorkflowContent(version.content);
  if (workflow === null) {
    return dsEmptyState(
      "Contenu non canonique",
      "Le contenu de cette version ne suit pas la forme canonique studio.library.workflow/v1.",
    );
  }
  const participants = workflow.participants
    .map(
      (participant) =>
        `<tr><td><code class="mono">${esc(participant.participantId)}</code></td><td><code class="mono">${esc(participant.agentStableKey)}</code></td>` +
        `<td>${participant.dependsOn.length === 0 ? '<span class="ds-list-sub">—</span>' : esc(participant.dependsOn.join(", "))}</td>` +
        `<td>${participant.description !== null ? esc(participant.description) : '<span class="ds-list-sub">—</span>'}</td></tr>`,
    )
    .join("");
  const edges = workflowEdges(workflow);
  const edgeList =
    edges.length === 0
      ? '<p class="ds-list-sub">Aucune dépendance entre étapes.</p>'
      : `<ul class="library-edges">${edges.map((edge) => `<li><code class="mono">${esc(edge.from)} → ${esc(edge.to)}</code></li>`).join("")}</ul>`;
  const summary = workflow.summary !== null ? `<p class="library-prose">${esc(workflow.summary)}</p>` : "";
  return (
    `${summary}` +
    `<h4>Participants</h4><div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">Participants du flux</caption><thead><tr><th scope="col">Participant</th><th scope="col">Définition d'agent</th><th scope="col">Dépend de</th><th scope="col">Description</th></tr></thead><tbody>${participants}</tbody></table></div>` +
    `<h4>Enchaînement (ordre déclaré)</h4>${edgeList}<p class="ds-list-sub">Dépendances déclaratives uniquement — Studi'OS n'exécute jamais ce flux ici.</p>` +
    `<h4>Entrées du flux</h4>${ioTableHtml(workflow.inputs, "Entrées du flux")}<h4>Sorties du flux</h4>${ioTableHtml(workflow.outputs, "Sorties du flux")}`
  );
}

/* ------------------------------------------------------------------ */
/* Page racine : cinq catégories calmes, noms français.                */
/* ------------------------------------------------------------------ */

export function libraryRootHtml(): string {
  const cards = LIBRARY_KIND_FR.map(
    (entry) =>
      `<li class="ds-card library-cat"><h2>${esc(entry.plural)}</h2><p>${esc(entry.description)}</p>` +
      `<p><a class="ds-btn" href="#/library/${esc(entry.slug)}">Ouvrir les ${esc(entry.plural.toLowerCase())}</a></p></li>`,
  ).join("");
  return (
    `${dsPageHeader("Bibliothèque", "Cinq catégories de connaissances et de configurations réutilisables. Ouvrez une catégorie pour trouver une ressource, la lire et gérer ses versions.")}` +
    `<ul class="library-cats">${cards}</ul>`
  );
}

/* ------------------------------------------------------------------ */
/* Formulaires : champs préservés (contrat), regroupés en principal /  */
/* avancé. Noms d'attributs inchangés pour compatibilité E2E.          */
/* ------------------------------------------------------------------ */

const SCOPE_VALUES = ["studio", "project", "user"] as const;

function rowContainerHtml(rowKind: string, addLabel: string, seed: string): string {
  return `<div class="repeat" data-rows="${esc(rowKind)}">${seed}</div><button class="ds-btn ds-btn--sm" type="button" data-add-row="${esc(rowKind)}">${esc(addLabel)}</button>`;
}

function contentEditorsHtml(kind: LibraryKind): string {
  if (kind !== "workflow") return contentFieldsHtml(kind);
  return (
    contentFieldsHtml(kind) +
    `<h3>Participants</h3>${rowContainerHtml("participant", "Ajouter un participant", participantRowHtml())}` +
    `<h3>Entrées du flux</h3>${rowContainerHtml("io-input", "Ajouter une entrée", ioRowHtml("input"))}` +
    `<h3>Sorties du flux</h3>${rowContainerHtml("io-output", "Ajouter une sortie", ioRowHtml("output"))}`
  );
}

/** Corps du formulaire de création — mêmes `name=` que P12 (contrat + E2E). */
export function createFormFieldsHtml(kind: LibraryKind): string {
  return (
    `<fieldset class="library-fieldset"><legend>Informations principales</legend>` +
    `<label class="stack">Clé stable <input name="stable_key" required autocomplete="off" placeholder="ma-ressource" /></label>` +
    `<label class="stack">Portée <select name="scope">${SCOPE_VALUES.map((scope) => `<option value="${scope}">${esc(scopeLabelFr(scope))}</option>`).join("")}</select></label>` +
    `<label class="stack">ID projet (exigé pour la portée Projet) <input name="project_id" placeholder="uuid" autocomplete="off" /></label>` +
    `<label class="stack">Titre <input name="title" required autocomplete="off" placeholder="Titre lisible de la version 1" /></label>` +
    `<label class="stack">Description <input name="description" autocomplete="off" placeholder="À quoi sert cette ressource (facultatif)" /></label>` +
    contentEditorsHtml(kind) +
    `</fieldset>` +
    `<details class="library-advanced"><summary>Paramètres avancés / techniques</summary>` +
    `<h3>Dépendances (épingles de version)</h3>${rowContainerHtml("dependency", "Ajouter une dépendance", dependencyRowHtml())}` +
    `<p class="ds-list-sub">POST /library · clé d'idempotence générée par tentative · la version 1 est créée en brouillon.</p>` +
    `</details>` +
    `<div data-msg class="ds-field-error" role="alert"></div>`
  );
}

function versionFormFieldsHtml(kind: LibraryKind): string {
  return (
    `<fieldset class="library-fieldset"><legend>Informations principales</legend>` +
    `<label class="stack">Titre <input name="version_title" required autocomplete="off" placeholder="Titre lisible de cette version" /></label>` +
    `<label class="stack">Description <input name="version_description" autocomplete="off" placeholder="Ce qui change (facultatif)" /></label>` +
    contentEditorsHtml(kind) +
    `</fieldset>` +
    `<details class="library-advanced"><summary>Paramètres avancés / techniques</summary>` +
    `<h3>Dépendances (épingles de version)</h3>${rowContainerHtml("dependency", "Ajouter une dépendance", dependencyRowHtml())}` +
    `<p class="ds-list-sub">POST /library/{id}/versions · ne déplace jamais le pointeur actif · clé d'idempotence par tentative.</p>` +
    `</details>` +
    `<div data-msg class="ds-field-error" role="alert"></div>`
  );
}

function appendRow(root: HTMLElement, rowKind: string): void {
  const container = root.querySelector(`[data-rows="${rowKind}"]`);
  if (container === null) return;
  if (rowKind === "dependency") container.insertAdjacentHTML("beforeend", dependencyRowHtml());
  else if (rowKind === "participant") container.insertAdjacentHTML("beforeend", participantRowHtml());
  else if (rowKind === "io-input") container.insertAdjacentHTML("beforeend", ioRowHtml("input"));
  else if (rowKind === "io-output") container.insertAdjacentHTML("beforeend", ioRowHtml("output"));
}

function bindRepeatable(root: HTMLElement): void {
  // Assignation de propriété (pas addEventListener) pour que les re-rendus
  // remplacent le gestionnaire au lieu de l'empiler sur le nœud #view.
  root.onclick = (event) => {
    const target = event.target as HTMLElement | null;
    if (target === null) return;
    const remove = target.closest("[data-remove-row]");
    if (remove !== null) {
      remove.closest(".repeat-row")?.remove();
      return;
    }
    const add = target.closest("[data-add-row]");
    if (add !== null) {
      const rowKind = (add as HTMLElement).dataset["addRow"];
      if (rowKind !== undefined) appendRow(root, rowKind);
    }
  };
}

export function buildResourcePayload(form: HTMLFormElement, kind: LibraryKind): { payload: LibraryResourceCreate } | { error: string } {
  const read = formReader(form);
  const stableKey = read.text("stable_key").trim();
  if (stableKey === "") return { error: "La clé stable est obligatoire." };
  const title = read.text("title").trim();
  if (title === "") return { error: "Le titre est obligatoire." };
  const scope = read.text("scope");
  if (scope !== "studio" && scope !== "project" && scope !== "user") return { error: "Portée inconnue." };
  const projectId = read.text("project_id").trim();
  if (scope === "project" && projectId === "") return { error: "La portée Projet exige un ID projet." };

  let content: Record<string, unknown>;
  if (kind === "workflow") {
    const built = buildWorkflowContent({
      summary: read.text("summary"),
      participants: asParticipantInputs(readRows(form, "participant")),
      inputs: asIoInputs(readRows(form, "io-input")),
      outputs: asIoInputs(readRows(form, "io-output")),
    });
    if (!built.ok) return { error: built.error };
    content = built.value;
  } else {
    const built = buildContent(kind, read);
    if (!built.ok) return { error: built.error };
    content = built.value;
  }
  const dependencies = buildDependencies(asDependencyInputs(readRows(form, "dependency")));
  if (!dependencies.ok) return { error: dependencies.error };

  const description = read.text("description").trim();
  const payload: LibraryResourceCreate = {
    kind,
    stable_key: stableKey,
    scope,
    project_id: scope === "project" ? projectId : null,
    title,
    description: description === "" ? null : description,
    content,
    dependencies: dependencies.value.map((pin) => ({
      kind: pin.kind,
      stable_key: pin.stable_key,
      version: pin.version,
      relation: (pin.relation ?? null) as components["schemas"]["DependencyPin"]["relation"],
    })),
  };
  return { payload };
}

/* ------------------------------------------------------------------ */
/* Liste d'un kind : recherche dominante + filtres honnêtes.           */
/* ------------------------------------------------------------------ */

function listToolbarHtml(meta: LibraryKindFr, state: LibraryListState, shown: number, total: number): string {
  const scopeSelected = (value: string): string => (state.scope === value ? " selected" : "");
  const statusSelected = (value: string): string => (state.status === value ? " selected" : "");
  return `<div class="library-toolbar" role="search" aria-label="Filtrer les ${esc(meta.plural.toLowerCase())} chargés">` +
    `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span><label class="ds-sr-only" for="library-filter">Rechercher parmi les éléments chargés</label>` +
    `<input class="ds-input" type="search" id="library-filter" name="q" value="${esc(state.query)}" placeholder="Rechercher par clé stable…" autocomplete="off" /></div>` +
    `<label class="library-filter"><span>Portée</span><select class="ds-select" id="library-scope">` +
    `<option value="all"${scopeSelected("all")}>Toutes</option>` +
    `<option value="studio"${scopeSelected("studio")}>Studio</option>` +
    `<option value="project"${scopeSelected("project")}>Projet</option>` +
    `<option value="user"${scopeSelected("user")}>Utilisateur</option>` +
    `</select></label>` +
    `<label class="library-filter"><span>État</span><select class="ds-select" id="library-status">` +
    `<option value="all"${statusSelected("all")}>Tous</option>` +
    `<option value="draft"${statusSelected("draft")}>Brouillon</option>` +
    `<option value="active"${statusSelected("active")}>Actif</option>` +
    `<option value="deprecated"${statusSelected("deprecated")}>Déprécié</option>` +
    `</select></label>` +
    `<button class="ds-btn ds-btn--sm" type="button" id="library-reset">Réinitialiser</button>` +
    `<p class="ds-list-sub" role="status" aria-live="polite">${shown} élément(s) affiché(s) sur ${total} chargé(s) — recherche et filtres locaux.</p>` +
    `</div>`;
}

export function libraryLoadingHtml(title: string): string {
  return `${dsPageHeader(title, "")}${dsSkeleton(4)}`;
}

/** Corps de la page liste d'un kind en HTML pur (DOM-free, testable). */
export function libraryKindPageHtml(kind: LibraryKind, resources: LibraryResource[], state: LibraryListState): string {
  const fr = kindFr(kind);
  const visible = filterLibraryResources(resources, state);
  const header = dsPageHeader(fr.plural, fr.description, [{ label: "+ Nouvelle ressource", id: "library-new", variant: "primary" }]);
  let body: string;
  if (resources.length === 0) {
    body = dsEmptyState(
      `Aucune ${fr.singular.toLowerCase()}`,
      `Aucune ressource de cette catégorie pour le moment. Créez la première pour commencer.`,
    );
  } else if (visible.length === 0) {
    body = dsEmptyState(
      "Aucun résultat pour cette recherche",
      "Modifiez ou réinitialisez la recherche et les filtres pour retrouver vos éléments déjà chargés.",
    );
  } else {
    body = resourcesTableHtml(visible);
  }
  return (
    `${libraryTabsHtml(fr.slug)}${header}` +
    `<p><a href="#/library">← Retour à la bibliothèque</a></p>` +
    `${listToolbarHtml(fr, state, visible.length, resources.length)}` +
    `${shadowNoteHtml(resources)}${body}`
  );
}

export async function renderLibrary(root: HTMLElement, ctx: LibraryContext, kindSlug: LibraryKindSlug | null): Promise<void> {
  const meta = kindSlug === null ? null : kindFromSlug(kindSlug);
  if (kindSlug !== null && meta === null) {
    root.innerHTML = libraryTabsHtml(null) + dsPageHeader("Bibliothèque", "") +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Catégorie inconnue.</strong>Revenez à la bibliothèque.</div>`;
    return;
  }
  if (meta === null) {
    root.innerHTML = `<div class="library">${libraryTabsHtml(null)}${libraryRootHtml()}</div>`;
    return;
  }
  const fr = kindFr(meta.kind);
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="library">${libraryTabsHtml(meta.slug)}` +
      `${dsPageHeader(fr.plural, fr.description)}` +
      dsEmptyState("Connectez-vous pour voir la bibliothèque", "Saisissez votre jeton machine pour charger les ressources.") +
      `</div>`;
    return;
  }
  root.innerHTML =
    `<div class="library">${libraryTabsHtml(meta.slug)}${libraryLoadingHtml(fr.plural)}</div>`;
  let resources: LibraryResource[];
  try {
    resources = await listLibraryResources(ctx.client, { kind: meta.kind });
  } catch (error) {
    root.innerHTML =
      `<div class="library">${libraryTabsHtml(meta.slug)}` +
      `${dsPageHeader(fr.plural, fr.description)}` +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>${esc(fr.plural)} indisponibles.</strong>${esc(describeError(error))}</div>` +
      `</div>`;
    return;
  }

  const state: LibraryListState = { query: "", scope: "all", status: "all" };

  const paint = (): void => {
    root.innerHTML =
      `<div class="library">${libraryKindPageHtml(meta.kind, resources, state)}` +
      dsModalHtml({
        id: "library-create-dialog",
        title: `Nouvelle ${fr.singular.toLowerCase()}`,
        body: `<form data-create id="library-create-form" novalidate>${createFormFieldsHtml(meta.kind)}` +
          `<div class="ds-dialog-actions"><button class="ds-btn" type="button" data-ds-close>Annuler</button>` +
          `<button class="ds-btn ds-btn--primary" type="submit" id="library-create-submit">Créer</button></div></form>`,
      }) +
      `</div>`;
    bind();
  };

  const refresh = async (): Promise<void> => {
    try {
      resources = await listLibraryResources(ctx.client, { kind: meta.kind });
    } catch {
      return;
    }
    paint();
  };

  const setCreateError = (message: string): void => {
    const node = root.querySelector("[data-create] [data-msg]");
    if (node === null) return;
    node.textContent = message;
    if (message !== "" && node instanceof HTMLElement) focusDsErrorBox(node);
  };

  const bind = (): void => {
    bindRepeatable(root);
    const filter = root.querySelector<HTMLInputElement>("#library-filter");
    filter?.addEventListener("input", () => {
      state.query = filter.value;
      paint();
      const next = root.querySelector<HTMLInputElement>("#library-filter");
      if (next !== null) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    });
    root.querySelector<HTMLSelectElement>("#library-scope")?.addEventListener("change", (event) => {
      state.scope = (event.target as HTMLSelectElement).value as LibraryListState["scope"];
      paint();
      root.querySelector<HTMLSelectElement>("#library-scope")?.focus();
    });
    root.querySelector<HTMLSelectElement>("#library-status")?.addEventListener("change", (event) => {
      state.status = (event.target as HTMLSelectElement).value as LibraryListState["status"];
      paint();
      root.querySelector<HTMLSelectElement>("#library-status")?.focus();
    });
    root.querySelector("#library-reset")?.addEventListener("click", () => {
      state.query = "";
      state.scope = "all";
      state.status = "all";
      paint();
      root.querySelector<HTMLInputElement>("#library-filter")?.focus();
    });
    const dialogId = "library-create-dialog";
    const openButton = root.querySelector<HTMLElement>("#library-new");
    openButton?.addEventListener("click", () => {
      setCreateError("");
      openDsDialog(root, dialogId, openButton);
      root.querySelector<HTMLElement>("form[data-create] input[name=stable_key]")?.focus();
    });
    const form = root.querySelector<HTMLFormElement>("form[data-create]");
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      const submit = root.querySelector<HTMLButtonElement>("#library-create-submit");
      const built = buildResourcePayload(form, meta.kind);
      if ("error" in built) {
        setCreateError(built.error);
        return;
      }
      if (submit !== null) {
        submit.disabled = true;
        submit.textContent = "Création en cours…";
      }
      setCreateError("");
      // Clé fraîche par tentative logique : la double soumission est
      // empêchée par le bouton désactivé, une nouvelle tentative après
      // erreur rejoue un corps identique sous une clé neuve.
      createLibraryResource(ctx.client, built.payload, newIdempotencyKey())
        .then((created) => {
          closeDsDialog(root, dialogId);
          dsNotify(`« ${created.stable_key} » créé en brouillon.`, "success");
          void refresh();
        })
        .catch((error: unknown) => {
          setCreateError(describeError(error));
          if (submit !== null) {
            submit.disabled = false;
            submit.textContent = "Créer";
          }
        });
    });
  };

  paint();
}

/* ------------------------------------------------------------------ */
/* Détail : d'abord LECTURE (contenu prioritaire), technique repliée.  */
/* ------------------------------------------------------------------ */

/** Deep link Inspector (agent-definitions uniquement) en langage utilisateur. */
export function inspectorLinkHtml(resource: LibraryResource): string {
  if (resource.kind !== "agent_definition") return "";
  return `<p><a class="ds-btn" href="#/inspector/${encodeURIComponent(resource.stable_key)}">Inspecter la résolution</a></p>`;
}

function identityTechHtml(resource: LibraryResource, schema: string | null): string {
  return (
    `<dl class="library-tech-list">` +
    `<div><dt>Identifiant</dt><dd><code class="mono">${esc(resource.id)}</code></dd></div>` +
    `<div><dt>Clé stable</dt><dd><code class="mono">${esc(resource.stable_key)}</code></dd></div>` +
    `<div><dt>content_schema</dt><dd>${schema !== null ? `<code class="mono">${esc(schema)}</code>` : '<span class="ds-list-sub">—</span>'}</dd></div>` +
    `<div><dt>Révision ressource</dt><dd>v${resource.version}</dd></div>` +
    `<div><dt>Version active</dt><dd>${resource.active_version === 0 ? "aucune" : `v${resource.active_version}`}</dd></div>` +
    `<div><dt>Créée le</dt><dd>${fmtTime(resource.created_at)}</dd></div>` +
    `<div><dt>Mise à jour le</dt><dd>${fmtTime(resource.updated_at)}</dd></div>` +
    `</dl>`
  );
}

function lifecycleFormsHtml(resource: LibraryResource): string {
  const activeVersion = resource.active_version === 0 ? "" : String(resource.active_version);
  return (
    `<div class="library-actions">` +
    `<form class="library-action" data-activate>` +
    `<h3>Activer une version</h3>` +
    `<p class="ds-list-sub">Déplace le pointeur actif. Révision attendue : v${resource.version} (conflit 409 si périmée).</p>` +
    `<label class="library-inline-field">Version à activer <input class="ds-input" name="version" type="number" min="1" value="${esc(activeVersion)}" required /></label>` +
    `<button class="ds-btn ds-btn--primary ds-btn--sm" type="submit">Activer</button>` +
    `<div data-msg class="ds-field-error" role="alert"></div></form>` +
    `<form class="library-action library-action--danger" data-deprecate>` +
    `<h3>Déprécier</h3><p class="ds-list-sub">Garde l'historique et le pointeur actif ; remplace la suppression.</p>` +
    `<button class="ds-btn ds-btn--danger ds-btn--sm" type="submit">Déprécier</button>` +
    `<div data-msg class="ds-field-error" role="alert"></div></form>` +
    `</div>`
  );
}

function buildVersionPayload(form: HTMLFormElement, kind: LibraryKind): { value: LibraryVersionCreate } | { error: string } {
  const read = formReader(form);
  const title = read.text("version_title").trim();
  if (title === "") return { error: "Le titre est obligatoire." };
  let content: Record<string, unknown>;
  if (kind === "workflow") {
    const built = buildWorkflowContent({
      summary: read.text("summary"),
      participants: asParticipantInputs(readRows(form, "participant")),
      inputs: asIoInputs(readRows(form, "io-input")),
      outputs: asIoInputs(readRows(form, "io-output")),
    });
    if (!built.ok) return { error: built.error };
    content = built.value;
  } else {
    const built = buildContent(kind, read);
    if (!built.ok) return { error: built.error };
    content = built.value;
  }
  const dependencies = buildDependencies(asDependencyInputs(readRows(form, "dependency")));
  if (!dependencies.ok) return { error: dependencies.error };
  const description = read.text("version_description").trim();
  return {
    value: {
      title,
      description: description === "" ? null : description,
      content,
      dependencies: dependencies.value.map((pin) => ({
        kind: pin.kind,
        stable_key: pin.stable_key,
        version: pin.version,
        relation: (pin.relation ?? null) as components["schemas"]["DependencyPin"]["relation"],
      })),
    },
  };
}

/** Page détail complète en HTML pur (DOM-free, testable) : lecture d'abord, technique repliée. */
export function libraryDetailHtml(
  resource: LibraryResource,
  versions: LibraryVersion[],
  locks: LibraryProjectLock[],
  siblings: LibraryResource[] = [],
): string {
  const fr = kindFr(resource.kind);
  const relevantLocks = locks.filter((lock) => lock.resource_id === resource.id);
  const sorted = [...versions].sort((a, b) => b.version - a.version);
  const activeVersion = versions.find((version) => version.version === resource.active_version) ?? null;
  const activeTitle =
    activeVersion?.title?.trim() !== undefined && (activeVersion?.title?.trim() ?? "") !== ""
      ? (activeVersion?.title as string)
      : resource.stable_key;
  const activeDescription =
    activeVersion?.description?.trim() !== undefined && ((activeVersion?.description?.trim() ?? "") !== "")
      ? (activeVersion?.description as string)
      : fr.description;
  const activeSchema = activeVersion !== null ? contentSchema(activeVersion.content) : null;

  const versionBlocks = sorted
    .map((version) => {
      const isActive = version.version === resource.active_version;
      return (
        `<details class="library-version"${isActive ? " open" : ""}><summary>v${version.version} · ${esc(version.title)}${isActive ? " · version activée" : ""}</summary>` +
        `<div class="library-version-body"><p class="ds-list-sub">${fmtTime(version.created_at)}${version.created_by_user_id ? ` · par ${esc(shortId(version.created_by_user_id))}` : ""}</p>` +
        (version.description ? `<p>${esc(version.description)}</p>` : "") +
        versionContentHtml(resource.kind, version) +
        `<h4>Dépendances</h4>${dependenciesTableHtml(version.dependencies)}</div></details>`
      );
    })
    .join("");

  return (
    `<div class="library library-detail">${libraryTabsHtml(kindFr(resource.kind).slug)}` +
    `<p><a href="${esc(libraryKindHref(resource.kind))}">← Retour aux ${esc(fr.plural.toLowerCase())}</a></p>` +
    `${dsPageHeader(activeTitle, activeDescription)}` +
    `<p class="library-badges">${scopeBadge(resource.scope)}${statusBadge(resource.status)}` +
    (resource.active_version === 0
      ? dsBadge("Aucune version activée", "warning")
      : dsBadge(`Version active : v${resource.active_version}`, "info")) +
    `<span class="ds-list-sub"><code class="mono">${esc(resource.stable_key)}</code></span></p>` +
    `${shadowNoteForDetail(resource, siblings)}` +
    `<section class="ds-panel library-reading" aria-label="Contenu actuel"><header><h2>Contenu actuel${activeVersion !== null ? ` — v${activeVersion.version}` : ""}</h2></header><div class="body">` +
    (activeVersion !== null
      ? `${versionContentHtml(resource.kind, activeVersion)}<h4>Dépendances de la version active</h4>${dependenciesTableHtml(activeVersion.dependencies)}`
      : dsEmptyState("Aucune version activée", "Créez une version puis activez-la pour donner un contenu lisible à cette ressource.")) +
    `</div></section>` +
    `${inspectorLinkHtml(resource)}` +
    `<section class="ds-panel" aria-label="Cycle de vie"><header><h2>Cycle de vie</h2></header><div class="body">` +
    `${lifecycleFormsHtml(resource)}` +
    `<p><button class="ds-btn" type="button" id="library-version-new">+ Nouvelle version</button></p>` +
    dsModalHtml({
      id: "library-version-dialog",
      title: "Nouvelle version",
      body: `<form data-version id="library-version-form" novalidate>${versionFormFieldsHtml(resource.kind)}` +
        `<div class="ds-dialog-actions"><button class="ds-btn" type="button" data-ds-close>Annuler</button>` +
        `<button class="ds-btn ds-btn--primary" type="submit" id="library-version-submit">Créer la version</button></div></form>`,
    }) +
    `</div></section>` +
    `<section class="ds-panel" aria-label="Historique des versions"><header><h2>Historique des versions</h2><span class="ds-list-sub">${versions.length} version(s) · instantanés immuables</span></header><div class="body">` +
    (versionBlocks === "" ? dsEmptyState("Aucune version", "Aucune version enregistrée.") : `<div class="library-versions">${versionBlocks}</div>`) +
    `</div></section>` +
    `<section class="ds-panel" aria-label="Verrous projet"><header><h2>Verrous projet</h2></header><div class="body">` +
    `<p>Un verrou fige une version précise pour un projet donné. Il n'empêche jamais un commit Git : il signale l'écart.</p>` +
    `${locksTableHtml(relevantLocks)}` +
    `<form class="library-action" data-lock>` +
    `<h3>Figer une version pour un projet</h3>` +
    `<label class="library-inline-field">ID projet <input class="ds-input" name="lock_project_id" placeholder="uuid" required autocomplete="off" /></label>` +
    `<label class="library-inline-field">Version <input class="ds-input" name="lock_version" type="number" min="1" required /></label>` +
    `<button class="ds-btn ds-btn--sm" type="submit">Figer la version</button>` +
    `<p class="ds-list-sub">POST /library-locks · identifiant canonique de ressource, jamais la clé stable seule.</p>` +
    `<div data-msg class="ds-field-error" role="alert"></div></form>` +
    `</div></section>` +
    `<details class="library-tech"><summary>Détails techniques</summary>${identityTechHtml(resource, activeSchema)}</details>` +
    `</div>`
  );
}

export async function renderLibraryDetail(
  root: HTMLElement,
  ctx: LibraryContext,
  kindSlug: LibraryKindSlug,
  resourceId: string,
): Promise<void> {
  const meta = kindFromSlug(kindSlug);
  if (meta === null) {
    root.innerHTML = libraryTabsHtml(null) + dsPageHeader("Bibliothèque", "") +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Catégorie inconnue.</strong></div>`;
    return;
  }
  const fr = kindFr(meta.kind);
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="library">${libraryTabsHtml(meta.slug)}` +
      dsEmptyState("Connectez-vous pour lire cette ressource", "Saisissez votre jeton machine pour charger son contenu.") +
      `</div>`;
    return;
  }
  root.innerHTML = `<div class="library">${libraryTabsHtml(meta.slug)}${libraryLoadingHtml(fr.singular)}</div>`;
  let resource: LibraryResource;
  let versions: LibraryVersion[];
  try {
    [resource, versions] = await Promise.all([
      getLibraryResource(ctx.client, resourceId),
      listLibraryVersions(ctx.client, resourceId),
    ]);
  } catch (error) {
    root.innerHTML =
      `<div class="library">${libraryTabsHtml(meta.slug)}` +
      `${dsPageHeader(fr.singular, "")}` +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Ressource indisponible.</strong>${esc(describeError(error))}</div>` +
      `</div>`;
    return;
  }
  let locks: LibraryProjectLock[] = [];
  let locksError: string | undefined;
  try {
    locks = await listLibraryLocks(ctx.client);
  } catch (error) {
    locksError = describeError(error);
  }
  let siblings: LibraryResource[] = [];
  try {
    siblings = await listLibraryResources(ctx.client, { kind: resource.kind });
  } catch {
    siblings = [];
  }
  const relevantLocks = locks.filter((lock) => lock.resource_id === resource.id);
  void relevantLocks;
  const locksWarning =
    locksError === undefined
      ? ""
      : `<div class="ds-notice ds-notice--warning" role="alert"><strong>Verrous indisponibles.</strong> ${esc(locksError)}</div>`;
  root.innerHTML = libraryDetailHtml(resource, versions, locks, siblings) + locksWarning;
  bindRepeatable(root);
  bindDetail(root, ctx, meta.slug, resource);
}

function bindDetail(
  root: HTMLElement,
  ctx: LibraryContext,
  kindSlug: LibraryKindSlug,
  resource: LibraryResource,
): void {
  const refresh = (): void => {
    void renderLibraryDetail(root, ctx, kindSlug, resource.id);
  };
  const activateForm = root.querySelector<HTMLFormElement>("[data-activate]");
  activateForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const version = Number(formReader(activateForm).text("version"));
    const msg = activateForm.querySelector("[data-msg]");
    if (!Number.isInteger(version) || version < 1) {
      if (msg !== null) {
        msg.textContent = "Indiquez une version ≥ 1.";
        if (msg instanceof HTMLElement) focusDsErrorBox(msg);
      }
      return;
    }
    const submit = activateForm.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit !== null) submit.disabled = true;
    activateLibraryVersion(ctx.client, resource.id, { version, expected_resource_version: resource.version }, newIdempotencyKey())
      .then((updated) => {
        dsNotify(`Version v${updated.active_version} activée.`, "success");
        refresh();
      })
      .catch((error: unknown) => {
        if (msg !== null) {
          msg.textContent = describeError(error);
          if (msg instanceof HTMLElement) focusDsErrorBox(msg);
        }
        if (submit !== null) submit.disabled = false;
      });
  });
  const deprecateForm = root.querySelector<HTMLFormElement>("[data-deprecate]");
  deprecateForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!window.confirm("Déprécier cette ressource ? L'historique et le pointeur actif sont conservés.")) return;
    const msg = deprecateForm.querySelector("[data-msg]");
    const submit = deprecateForm.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit !== null) submit.disabled = true;
    deprecateLibraryResource(ctx.client, resource.id, { expected_resource_version: resource.version }, newIdempotencyKey())
      .then(() => {
        dsNotify("Ressource dépréciée.", "warning");
        refresh();
      })
      .catch((error: unknown) => {
        if (msg !== null) {
          msg.textContent = describeError(error);
          if (msg instanceof HTMLElement) focusDsErrorBox(msg);
        }
        if (submit !== null) submit.disabled = false;
      });
  });
  const versionDialogId = "library-version-dialog";
  const versionOpen = root.querySelector<HTMLElement>("#library-version-new");
  versionOpen?.addEventListener("click", () => {
    const msg = root.querySelector("[data-version] [data-msg]");
    if (msg !== null) msg.textContent = "";
    openDsDialog(root, versionDialogId, versionOpen);
    root.querySelector<HTMLElement>("[data-version] input[name=version_title]")?.focus();
  });
  const versionForm = root.querySelector<HTMLFormElement>("[data-version]");
  versionForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = versionForm.querySelector("[data-msg]");
    const submit = versionForm.querySelector<HTMLButtonElement>("button[type=submit]");
    const built = buildVersionPayload(versionForm, resource.kind);
    if ("error" in built) {
      if (msg !== null) {
        msg.textContent = built.error;
        if (msg instanceof HTMLElement) focusDsErrorBox(msg);
      }
      return;
    }
    if (submit !== null) {
      submit.disabled = true;
      submit.textContent = "Création en cours…";
    }
    createLibraryVersion(ctx.client, resource.id, built.value, newIdempotencyKey())
      .then((created) => {
        closeDsDialog(root, versionDialogId);
        dsNotify(`Version v${created.version} créée en brouillon.`, "success");
        refresh();
      })
      .catch((error: unknown) => {
        if (msg !== null) {
          msg.textContent = describeError(error);
          if (msg instanceof HTMLElement) focusDsErrorBox(msg);
        }
        if (submit !== null) {
          submit.disabled = false;
          submit.textContent = "Créer la version";
        }
      });
  });
  const lockForm = root.querySelector<HTMLFormElement>("[data-lock]");
  lockForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const read = formReader(lockForm);
    const projectId = read.text("lock_project_id").trim();
    const version = Number(read.text("lock_version"));
    const msg = lockForm.querySelector("[data-msg]");
    if (projectId === "" || !Number.isInteger(version) || version < 1) {
      if (msg !== null) {
        msg.textContent = "L'ID projet et une version ≥ 1 sont obligatoires.";
        if (msg instanceof HTMLElement) focusDsErrorBox(msg);
      }
      return;
    }
    const submit = lockForm.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit !== null) submit.disabled = true;
    const input: LibraryLockCreate = { project_id: projectId, resource_id: resource.id, locked_version: version };
    createLibraryLock(ctx.client, input, newIdempotencyKey())
      .then(() => {
        dsNotify("Version figée pour ce projet.", "success");
        refresh();
      })
      .catch((error: unknown) => {
        if (msg !== null) {
          msg.textContent = describeError(error);
          if (msg instanceof HTMLElement) focusDsErrorBox(msg);
        }
        if (submit !== null) submit.disabled = false;
      });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-release-lock]").forEach((button) => {
    button.addEventListener("click", () => {
      const lockId = button.dataset["releaseLock"];
      if (lockId === undefined) return;
      if (!window.confirm("Libérer ce verrou projet ?")) return;
      button.disabled = true;
      releaseLibraryLock(ctx.client, lockId)
        .then(() => {
          dsNotify("Verrou libéré.", "info");
          refresh();
        })
        .catch((error: unknown) => {
          button.disabled = false;
          dsNotify(`Libération impossible. ${describeError(error)}`, "danger");
        });
    });
  });
}
