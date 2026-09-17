/**
 * P12 — Library UI (five kinds, versions, lifecycle, locks, authoring).
 *
 * Everything is read from / written to the canonical P7 routes through
 * `libraryApi.ts`. The dashboard never ranks scopes, never picks an effective
 * version and never re-implements a resolver: shadowing and effective-version
 * selection stay server-side (P2/P5) and are surfaced by the Resolution
 * Inspector.
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
  scopeLabel,
  statusLabel,
  statusTone,
  workflowEdges,
  type CapabilityRequirement,
  type LibraryKind,
  type LibraryKindSlug,
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
  type LibraryVersionCreate,
  type LibraryProjectLock,
  type LibraryResource,
  type LibraryResourceCreate,
  type LibraryVersion,
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
import { describeError, esc, fmtTime, idCell, section, statusBlock } from "../ui";

export interface LibraryContext {
  client: StudioClient;
  authed: boolean;
}

export function libraryTabsHtml(active: LibraryKindSlug | null): string {
  const tabs = LIBRARY_KINDS.map(
    (meta) => `<a class="tab${meta.slug === active ? " active" : ""}" href="#/library/${meta.slug}">${esc(meta.plural)}</a>`,
  ).join("");
  return `<nav class="tabs">${tabs}</nav>`;
}

function statusBadge(status: LibraryStatus): string {
  return `<span class="status ${statusTone(status)}">${esc(statusLabel(status))}</span>`;
}

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
    `<div class="notice" role="note">${shadowed} stable key(s) exist in more than one scope. ` +
    `This list shows every stored resource; it does not decide which one is effective. ` +
    `Use the <a href="#/inspector">Resolution Inspector</a> to see the canonical winner.</div>`
  );
}

export function resourcesTableHtml(resources: LibraryResource[]): string {
  if (resources.length === 0) return statusBlock("empty", "No resources of this kind.");
  const rows = resources
    .map((resource) => {
      const project = resource.project_id !== null ? idCell(resource.project_id) : '<span class="meta">—</span>';
      const active = resource.active_version === 0 ? '<span class="meta">none</span>' : `v${resource.active_version}`;
      return (
        `<tr><td><a href="${esc(libraryKindHref(resource.kind, resource.id))}"><code class="mono">${esc(resource.stable_key)}</code></a></td>` +
        `<td>${esc(scopeLabel(resource.scope))}</td><td>${project}</td><td>${active}</td>` +
        `<td>${statusBadge(resource.status)}</td><td>${fmtTime(resource.updated_at)}</td>` +
        `<td class="actions"><a href="${esc(libraryKindHref(resource.kind, resource.id))}">Open</a></td></tr>`
      );
    })
    .join("");
  return `<table><thead><tr><th>Stable key</th><th>Scope</th><th>Project</th><th>Active</th><th>Status</th><th>Updated</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
}

export function versionsTableHtml(versions: LibraryVersion[], activeVersion: number): string {
  if (versions.length === 0) return statusBlock("empty", "No versions.");
  const rows = [...versions]
    .sort((a, b) => b.version - a.version)
    .map((version) => {
      const active = version.version === activeVersion ? '<span class="status ok">active</span>' : "";
      return (
        `<tr><td>v${version.version}</td><td>${esc(version.title)}</td><td>${active}</td>` +
        `<td>${idCell(version.created_by_user_id)}</td><td>${fmtTime(version.created_at)}</td></tr>`
      );
    })
    .join("");
  return `<table><thead><tr><th>Version</th><th>Title</th><th></th><th>Created by</th><th>Created</th></tr></thead><tbody>${rows}</tbody></table>`;
}

export function locksTableHtml(locks: LibraryProjectLock[]): string {
  if (locks.length === 0) return statusBlock("empty", "No project lock on this resource.");
  const rows = locks
    .map(
      (lock) =>
        `<tr><td data-lock-id="${esc(lock.id)}">${idCell(lock.project_id)}</td><td>v${lock.locked_version}</td>` +
        `<td>${idCell(lock.created_by_user_id)}</td><td>${fmtTime(lock.created_at)}</td>` +
        `<td class="actions"><button type="button" data-release-lock="${esc(lock.id)}">Release</button></td></tr>`,
    )
    .join("");
  return `<table><thead><tr><th>Project</th><th>Locked version</th><th>Created by</th><th>Created</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
}

export function dependenciesTableHtml(dependencies: LibraryVersion["dependencies"]): string {
  if (dependencies.length === 0) return `<span class="meta">No dependencies.</span>`;
  const rows = dependencies
    .map((pin) => {
      const relation = pin.relation !== null && pin.relation !== undefined ? esc(relationLabel(pin.relation)) : '<span class="meta">—</span>';
      return `<tr><td>${esc(kindMeta(pin.kind).singular)}</td><td><code class="mono">${esc(pin.stable_key)}</code></td><td>v${pin.version}</td><td>${relation}</td></tr>`;
    })
    .join("");
  return `<table><thead><tr><th>Kind</th><th>Stable key</th><th>Version</th><th>Relation</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function entriesTableHtml(entries: { label: string; value: string }[]): string {
  if (entries.length === 0) return `<span class="meta">No requirement declared.</span>`;
  const rows = entries.map((entry) => `<tr><td>${esc(entry.label)}</td><td><code class="mono">${esc(entry.value)}</code></td></tr>`).join("");
  return `<table><thead><tr><th>Dimension</th><th>Value</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function ioTableHtml(declarations: WorkflowIODeclaration[]): string {
  if (declarations.length === 0) return `<span class="meta">None declared.</span>`;
  const rows = declarations
    .map(
      (declaration) =>
        `<tr><td><code class="mono">${esc(declaration.name)}</code></td><td>${declaration.description !== null ? esc(declaration.description) : "<span class=\"meta\">—</span>"}</td>` +
        `<td>${declaration.required ? "required" : "optional"}</td><td>${declaration.type !== null ? esc(declaration.type) : "<span class=\"meta\">—</span>"}</td>` +
        `<td>${declaration.source !== null ? esc(declaration.source.participantId === null ? `workflow input ${declaration.source.name}` : `${declaration.source.participantId}.${declaration.source.name}`) : "<span class=\"meta\">—</span>"}</td></tr>`,
    )
    .join("");
  return `<table><thead><tr><th>Name</th><th>Description</th><th>Required</th><th>Type</th><th>Source</th></tr></thead><tbody>${rows}</tbody></table>`;
}

/** Human, per-kind rendering of one stored version content. */
export function versionContentHtml(kind: LibraryKind, version: LibraryVersion): string {
  const schema = contentSchema(version.content);
  const header = schema !== null ? `<div class="meta mono">content_schema: ${esc(schema)}</div>` : "";
  if (kind === "rule" || kind === "skill") {
    const text = contentText(version.content);
    return `${header}${text === null ? statusBlock("empty", "No text in this version.") : `<pre class="code">${esc(text)}</pre>`}`;
  }
  if (kind === "model_profile") {
    const requirements = version.content["requirements"] as CapabilityRequirement | undefined;
    return `${header}${entriesTableHtml(requirementEntries(requirements))}`;
  }
  if (kind === "agent_definition") {
    const summary = typeof version.content["summary"] === "string" ? version.content["summary"] : null;
    const intendedUse = typeof version.content["intended_use"] === "string" ? version.content["intended_use"] : null;
    return (
      `${header}` +
      `<div class="detail-grid"><div>Summary: ${summary !== null ? esc(summary) : '<span class="meta">—</span>'}</div>` +
      `<div>Intended use: ${intendedUse !== null ? esc(intendedUse) : '<span class="meta">—</span>'}</div></div>`
    );
  }
  const workflow = parseWorkflowContent(version.content);
  if (workflow === null) {
    return `${header}${statusBlock("empty", "Workflow content is not in the canonical studio.library.workflow/v1 shape.")}`;
  }
  const participants = workflow.participants
    .map(
      (participant) =>
        `<tr><td><code class="mono">${esc(participant.participantId)}</code></td><td><code class="mono">${esc(participant.agentStableKey)}</code></td>` +
        `<td>${participant.dependsOn.length === 0 ? '<span class="meta">—</span>' : esc(participant.dependsOn.join(", "))}</td>` +
        `<td>${participant.description !== null ? esc(participant.description) : '<span class="meta">—</span>'}</td></tr>`,
    )
    .join("");
  const edges = workflowEdges(workflow);
  const edgeList =
    edges.length === 0
      ? '<span class="meta">No dependency edges.</span>'
      : `<ul class="edges">${edges.map((edge) => `<li><code class="mono">${esc(edge.from)} → ${esc(edge.to)}</code></li>`).join("")}</ul>`;
  const summary = workflow.summary !== null ? `<div>Summary: ${esc(workflow.summary)}</div>` : "";
  return (
    `${header}${summary}` +
    `<h3>Participants</h3><table><thead><tr><th>Participant</th><th>Agent Definition</th><th>Depends on</th><th>Description</th></tr></thead><tbody>${participants}</tbody></table>` +
    `<h3>Flow (declared order)</h3>${edgeList}<div class="meta">Declarative dependency edges only — Studi'OS never executes this workflow.</div>` +
    `<h3>Workflow inputs</h3>${ioTableHtml(workflow.inputs)}<h3>Workflow outputs</h3>${ioTableHtml(workflow.outputs)}`
  );
}

const SCOPE_VALUES = ["studio", "project", "user"] as const;

function rowContainerHtml(rowKind: string, addLabel: string, seed: string): string {
  return `<div class="repeat" data-rows="${esc(rowKind)}">${seed}</div><button type="button" data-add-row="${esc(rowKind)}">${esc(addLabel)}</button>`;
}

function contentEditorsHtml(kind: LibraryKind): string {
  if (kind !== "workflow") return contentFieldsHtml(kind);
  return (
    contentFieldsHtml(kind) +
    `<h3>Participants</h3>${rowContainerHtml("participant", "Add participant", participantRowHtml())}` +
    `<h3>Workflow inputs</h3>${rowContainerHtml("io-input", "Add input", ioRowHtml("input"))}` +
    `<h3>Workflow outputs</h3>${rowContainerHtml("io-output", "Add output", ioRowHtml("output"))}`
  );
}

function createFormHtml(kind: LibraryKind, authed: boolean): string {
  const disabled = authed ? "" : "disabled";
  return (
    `<details class="editor"><summary>New ${esc(kindMeta(kind).singular)}</summary>` +
    `<form class="stack-form" data-create>` +
    `<label class="stack">Stable key <input name="stable_key" required ${disabled} /></label>` +
    `<label class="stack">Scope <select name="scope" ${disabled}>${SCOPE_VALUES.map((scope) => `<option value="${scope}">${esc(scopeLabel(scope))}</option>`).join("")}</select></label>` +
    `<label class="stack">Project ID (required for project scope) <input name="project_id" placeholder="uuid" ${disabled} /></label>` +
    `<label class="stack">Title <input name="title" required ${disabled} /></label>` +
    `<label class="stack">Description <input name="description" ${disabled} /></label>` +
    contentEditorsHtml(kind) +
    `<h3>Dependencies (version pins)</h3>${rowContainerHtml("dependency", "Add dependency", dependencyRowHtml())}` +
    `<button type="submit" ${disabled}>Create</button>` +
    `<span class="meta">POST /library · Idempotency-Key per attempt · version 1 is created as a draft</span>` +
    `<div data-msg class="meta"></div></form></details>`
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
  // Property assignment (not addEventListener) so re-renders replace the
  // handler instead of stacking one per render on the persistent #view node.
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
  if (stableKey === "") return { error: "stable key is required" };
  const title = read.text("title").trim();
  if (title === "") return { error: "title is required" };
  const scope = read.text("scope");
  if (scope !== "studio" && scope !== "project" && scope !== "user") return { error: "unknown scope" };
  const projectId = read.text("project_id").trim();
  if (scope === "project" && projectId === "") return { error: "project scope requires a project ID" };

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

function bindCreate(root: HTMLElement, ctx: LibraryContext, kind: LibraryKind): void {
  const form = root.querySelector<HTMLFormElement>("[data-create]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = form.querySelector("[data-msg]");
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    const built = buildResourcePayload(form, kind);
    if ("error" in built) {
      if (msg !== null) msg.textContent = built.error;
      return;
    }
    if (submit !== null) submit.disabled = true;
    createLibraryResource(ctx.client, built.payload)
      .then(() => {
        void renderLibrary(root, ctx, kindMeta(kind).slug);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
}

const KIND_DESCRIPTIONS: Record<LibraryKindSlug, string> = {
  rules: "Reusable textual rules (studio.library.rule/v1).",
  skills: "Reusable textual skills (studio.library.skill/v1).",
  "agent-definitions": "Logical agent definitions: no runtime, no provider (studio.library.agent_definition/v1).",
  workflows: "Declarative workflows: participants, DAG and I/O — never executed here (studio.library.workflow/v1).",
  "model-profiles": "Vendor-neutral capability requirements (studio.library.model_profile/v1).",
};

function kindIndexHtml(): string {
  return `<div class="cards">${LIBRARY_KINDS.map(
    (meta) =>
      `<a class="card link" href="#/library/${meta.slug}"><span class="title">${esc(meta.plural)}</span>` +
      `<span class="sub">${esc(KIND_DESCRIPTIONS[meta.slug])}</span></a>`,
  ).join("")}</div>`;
}

export async function renderLibrary(root: HTMLElement, ctx: LibraryContext, kindSlug: LibraryKindSlug | null): Promise<void> {
  const meta = kindSlug === null ? null : kindFromSlug(kindSlug);
  if (kindSlug !== null && meta === null) {
    root.innerHTML = libraryTabsHtml(null) + section("Library", "", statusBlock("error", "Unknown library kind."));
    return;
  }
  if (meta === null) {
    root.innerHTML =
      libraryTabsHtml(null) +
      section(
        "Library",
        "GET /api/v1/library · five canonical kinds",
        `<p class="meta">Read definitions, versions and lifecycle from the canonical HTTP API. Nothing here is resolved locally.</p>${kindIndexHtml()}`,
      );
    return;
  }
  if (!ctx.authed) {
    root.innerHTML =
      libraryTabsHtml(meta.slug) +
      section(meta.plural, `GET /library?kind=${meta.kind}`, statusBlock("empty", "Set a machine token to read the Library."));
    return;
  }
  root.innerHTML = libraryTabsHtml(meta.slug) + section(meta.plural, `GET /library?kind=${meta.kind}`, statusBlock("loading"));
  let resources: LibraryResource[];
  try {
    resources = await listLibraryResources(ctx.client, { kind: meta.kind });
  } catch (error) {
    root.innerHTML = libraryTabsHtml(meta.slug) + section(meta.plural, `GET /library?kind=${meta.kind}`, statusBlock("error", describeError(error)));
    return;
  }
  root.innerHTML =
    libraryTabsHtml(meta.slug) +
    section(
      meta.plural,
      `GET /library?kind=${meta.kind} · ${resources.length} shown`,
      `${shadowNoteHtml(resources)}${resourcesTableHtml(resources)}${createFormHtml(meta.kind, ctx.authed)}`,
    );
  bindRepeatable(root);
  bindCreate(root, ctx, meta.kind);
}

function identityHtml(kind: LibraryKind, resource: LibraryResource): string {
  const active = resource.active_version === 0 ? '<span class="meta">none</span>' : `v${resource.active_version}`;
  return (
    `<div class="detail-grid">` +
    `<div>Kind: ${esc(kindMeta(kind).singular)} · scope: <strong>${esc(scopeLabel(resource.scope))}</strong></div>` +
    `<div>Stable key: <code class="mono">${esc(resource.stable_key)}</code></div>` +
    `<div>Active version: ${active} · resource revision: v${resource.version}</div>` +
    `<div>Status: ${statusBadge(resource.status)}</div>` +
    `<div>Project: ${resource.project_id !== null ? idCell(resource.project_id) : '<span class="meta">—</span>'} · owner: ${idCell(resource.owner_user_id)}</div>` +
    `<div class="meta">id ${esc(resource.id)}</div></div>`
  );
}

function lifecycleFormsHtml(kind: LibraryKind, resource: LibraryResource, authed: boolean): string {
  const disabled = authed ? "" : "disabled";
  const activeVersion = resource.active_version === 0 ? "" : String(resource.active_version);
  return (
    `<form class="inline-form" data-activate>` +
    `<h3>Activate a version</h3>` +
    `<label>Version to activate <input name="version" type="number" min="1" value="${esc(activeVersion)}" required ${disabled} /></label>` +
    `<span class="meta">expected resource revision v${resource.version}</span>` +
    `<button type="submit" ${disabled}>Activate</button>` +
    `<span class="meta">POST /library/{id}/activate · 409 on stale revision</span></form>` +
    `<form class="inline-form" data-deprecate>` +
    `<h3>Deprecate</h3><span class="meta">Keeps history and the active pointer; replaces deletion.</span>` +
    `<button type="submit" ${disabled}>Deprecate</button></form>` +
    `<details class="editor"><summary>New version</summary>` +
    `<form class="stack-form" data-version>` +
    `<label class="stack">Title <input name="version_title" required ${disabled} /></label>` +
    `<label class="stack">Description <input name="version_description" ${disabled} /></label>` +
    contentEditorsHtml(kind) +
    `<h3>Dependencies (version pins)</h3>${rowContainerHtml("dependency", "Add dependency", dependencyRowHtml())}` +
    `<button type="submit" ${disabled}>Create draft version</button>` +
    `<span class="meta">POST /library/{id}/versions · never moves the active pointer · Idempotency-Key per attempt</span>` +
    `<div data-msg class="meta"></div></form></details>`
  );
}

function buildVersionPayload(form: HTMLFormElement, kind: LibraryKind): { value: LibraryVersionCreate } | { error: string } {
  const read = formReader(form);
  const title = read.text("version_title").trim();
  if (title === "") return { error: "title is required" };
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

export async function renderLibraryDetail(
  root: HTMLElement,
  ctx: LibraryContext,
  kindSlug: LibraryKindSlug,
  resourceId: string,
): Promise<void> {
  const meta = kindFromSlug(kindSlug);
  if (meta === null) {
    root.innerHTML = libraryTabsHtml(null) + section("Library", "", statusBlock("error", "Unknown library kind."));
    return;
  }
  if (!ctx.authed) {
    root.innerHTML = libraryTabsHtml(meta.slug) + section(meta.plural, `GET /library/{id}`, statusBlock("empty", "Set a machine token to read this resource."));
    return;
  }
  root.innerHTML = libraryTabsHtml(meta.slug) + section(`${meta.singular}`, "GET /library/{id} + /versions", statusBlock("loading"));
  let resource: LibraryResource;
  let versions: LibraryVersion[];
  let locks: LibraryProjectLock[];
  try {
    [resource, versions, locks] = await Promise.all([
      getLibraryResource(ctx.client, resourceId),
      listLibraryVersions(ctx.client, resourceId),
      listLibraryLocks(ctx.client),
    ]);
  } catch (error) {
    root.innerHTML = libraryTabsHtml(meta.slug) + section(meta.singular, "GET /library/{id}", statusBlock("error", describeError(error)));
    return;
  }
  const relevantLocks = locks.filter((lock) => lock.resource_id === resource.id);
  const versionBlocks = [...versions]
    .sort((a, b) => b.version - a.version)
    .map((version) => {
      const isActive = version.version === resource.active_version;
      return (
        `<details class="version"${isActive ? " open" : ""}><summary>v${version.version} · ${esc(version.title)}${isActive ? " · active" : ""}</summary>` +
        versionContentHtml(resource.kind, version) +
        `<h3>Dependencies</h3>${dependenciesTableHtml(version.dependencies)}</details>`
      );
    })
    .join("");
  const inspect =
    resource.kind === "agent_definition"
      ? `<p><a href="#/inspector/${encodeURIComponent(resource.stable_key)}">Inspect resolution of ${esc(resource.stable_key)}</a></p>`
      : "";
  root.innerHTML =
    libraryTabsHtml(meta.slug) +
    section(
      `${meta.singular} · ${resource.stable_key}`,
      `GET /library/{id} + /versions · GET /library-locks`,
      `${identityHtml(resource.kind, resource)}${inspect}` +
        `${lifecycleFormsHtml(resource.kind, resource, ctx.authed)}` +
        section("Versions", `${versions.length} version(s) · immutable snapshots`, versionBlocks === "" ? statusBlock("empty", "No versions.") : versionBlocks) +
        section("Project locks", "GET /library-locks (filtered to this resource)", locksTableHtml(relevantLocks)) +
        `<form class="inline-form" data-lock>` +
        `<h3>Lock this resource for a project</h3>` +
        `<label>Project ID <input name="lock_project_id" placeholder="uuid" required ${ctx.authed ? "" : "disabled"} /></label>` +
        `<label>Version <input name="lock_version" type="number" min="1" required ${ctx.authed ? "" : "disabled"} /></label>` +
        `<button type="submit" ${ctx.authed ? "" : "disabled"}>Set lock</button>` +
        `<span class="meta">POST /library-locks · canonical resource UUID, never stable_key alone</span>` +
        `<div data-msg class="meta"></div></form>`,
    );
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
    if (!Number.isInteger(version) || version < 1) return;
    activateLibraryVersion(ctx.client, resource.id, { version, expected_resource_version: resource.version })
      .then(refresh)
      .catch((error: unknown) => {
        const msg = activateForm.querySelector("[data-msg]");
        if (msg !== null) msg.textContent = describeError(error);
      });
  });
  const deprecateForm = root.querySelector<HTMLFormElement>("[data-deprecate]");
  deprecateForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!window.confirm("Deprecate this resource? History and the active pointer are kept.")) return;
    deprecateLibraryResource(ctx.client, resource.id, { expected_resource_version: resource.version })
      .then(refresh)
      .catch((error: unknown) => {
        const msg = deprecateForm.querySelector("[data-msg]");
        if (msg !== null) msg.textContent = describeError(error);
      });
  });
  const versionForm = root.querySelector<HTMLFormElement>("[data-version]");
  versionForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = versionForm.querySelector("[data-msg]");
    const submit = versionForm.querySelector<HTMLButtonElement>("button[type=submit]");
    const built = buildVersionPayload(versionForm, resource.kind);
    if ("error" in built) {
      if (msg !== null) msg.textContent = built.error;
      return;
    }
    if (submit !== null) submit.disabled = true;
    createLibraryVersion(ctx.client, resource.id, built.value)
      .then(refresh)
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
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
      if (msg !== null) msg.textContent = "project ID and a version ≥ 1 are required";
      return;
    }
    const input: LibraryLockCreate = { project_id: projectId, resource_id: resource.id, locked_version: version };
    createLibraryLock(ctx.client, input)
      .then(refresh)
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
      });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-release-lock]").forEach((button) => {
    button.addEventListener("click", () => {
      const lockId = button.dataset["releaseLock"];
      if (lockId === undefined) return;
      if (!window.confirm("Release this project lock?")) return;
      releaseLibraryLock(ctx.client, lockId)
        .then(refresh)
        .catch((error: unknown) => {
          window.alert(describeError(error));
        });
    });
  });
}
