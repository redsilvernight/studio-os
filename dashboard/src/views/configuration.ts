/**
 * P12 — Configuration UI (runtimes, bindings, project resources/locks/overrides).
 *
 * All writes go through the canonical P7 routes; after each mutation the view
 * refetches the canonical state. The UI never computes a precedence winner: it
 * lists stored levels and points at the Resolution Inspector for the canonical
 * result.
 */
import type { StudioClient } from "../api";
import {
  capabilityEntries,
  bindingLevelLabel,
  kindMeta,
  libraryKindHref,
  runtimeStatusLabel,
  runtimeTargetEntries,
  scopeLabel,
  type RuntimeCapabilities,
  type RuntimeTarget,
} from "../libraryFormat";
import {
  getRuntime,
  listRuntimes,
  registerRuntime,
  revokeRuntime,
  updateRuntime,
  type RuntimeRegistration,
} from "../runtimesApi";
import {
  createRuntimeBinding,
  deleteRuntimeBinding,
  listRuntimeBindings,
  type RuntimeBinding,
} from "../bindingsApi";
import { createLibraryLock, listLibraryLocks, listLibraryResources, releaseLibraryLock, type LibraryProjectLock, type LibraryResource } from "../libraryApi";
import { buildBindingCreate, buildRuntimeCreate, buildRuntimeUpdate, capabilityFieldsHtml } from "./configForms";
import { formReader } from "./libraryForms";
import { uiState } from "../store";
import { describeError, esc, fmtTime, idCell, section, statusBlock } from "../ui";

export interface ConfigurationContext {
  client: StudioClient;
  authed: boolean;
}

export type ConfigTab = "runtimes" | "bindings" | "project";

export function configTabsHtml(active: ConfigTab): string {
  const tab = (name: ConfigTab, label: string, href: string): string =>
    `<a class="tab${active === name ? " active" : ""}" href="${href}">${esc(label)}</a>`;
  return `<nav class="tabs">${tab("runtimes", "Runtimes", "#/configuration/runtimes")}${tab(
    "bindings",
    "Bindings",
    "#/configuration/bindings",
  )}${tab("project", "Project", "#/configuration/project")}</nav>`;
}

export function runtimeTargetSummary(target: RuntimeTarget): string {
  const entries = runtimeTargetEntries(target);
  if (entries.length === 0) return '<span class="meta">—</span>';
  return entries.map((entry) => `${esc(entry.label)}: <code class="mono">${esc(entry.value)}</code>`).join(" · ");
}

export function capabilitySummary(capabilities: RuntimeCapabilities): string {
  const entries = capabilityEntries(capabilities);
  if (entries.length === 0) return '<span class="meta">none declared</span>';
  return entries.map((entry) => `<span class="tag">${esc(entry.label)}=${esc(entry.value)}</span>`).join(" ");
}

let includeRevoked = false;

export async function renderRuntimes(root: HTMLElement, ctx: ConfigurationContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML =
      configTabsHtml("runtimes") + section("Runtimes", "GET /runtimes", statusBlock("empty", "Set a machine token to read your runtimes."));
    return;
  }
  root.innerHTML = configTabsHtml("runtimes") + section("Runtimes", "GET /runtimes", statusBlock("loading"));
  let runtimes: RuntimeRegistration[];
  try {
    runtimes = await listRuntimes(ctx.client, { includeRevoked });
  } catch (error) {
    root.innerHTML = configTabsHtml("runtimes") + section("Runtimes", "GET /runtimes", statusBlock("error", describeError(error)));
    return;
  }
  const rows =
    runtimes.length === 0
      ? ""
      : runtimes
          .map(
            (runtime) =>
              `<tr><td><a href="#/configuration/runtimes/${esc(runtime.id)}"><code class="mono">${esc(runtime.id)}</code></a></td>` +
              `<td>${esc(runtime.harness_ref ?? "—")}</td><td>${esc(runtime.provider_ref ?? "—")}</td><td>${esc(runtime.model_ref ?? "—")}</td>` +
              `<td>${capabilitySummary(runtime.capabilities)}</td>` +
              `<td>${runtime.machine_id !== null ? idCell(runtime.machine_id) : '<span class="meta">remote</span>'}</td>` +
              `<td>${esc(runtimeStatusLabel(runtime.status))}</td><td>v${runtime.version}</td></tr>`,
          )
          .join("");
  const table =
    rows === "" ? statusBlock("empty", includeRevoked ? "No runtimes." : "No active runtimes.") : `<table><thead><tr><th>Runtime</th><th>Harness</th><th>Provider</th><th>Model</th><th>Capabilities</th><th>Machine</th><th>Status</th><th>Version</th></tr></thead><tbody>${rows}</tbody></table>`;
  root.innerHTML =
    configTabsHtml("runtimes") +
    section(
      "Runtimes",
      `GET /runtimes${includeRevoked ? "?include_revoked=true" : ""} · ${runtimes.length} shown`,
      `<div class="row"><label class="check">Include revoked <input type="checkbox" data-include-revoked${includeRevoked ? " checked" : ""} /></label></div>` +
        table +
        createRuntimeFormHtml() +
        `<p class="meta">A runtime is private to its owner. Refs are open strings — no vendor catalog.</p>`,
    );
  bindRuntimes(root, ctx);
}

function createRuntimeFormHtml(): string {
  return (
    `<details class="editor"><summary>Register a runtime</summary><form class="stack-form" data-runtime-create>` +
    `<label class="stack">Machine ID (optional) <input name="machine_id" placeholder="uuid" /></label>` +
    `<label class="stack">Harness ref <input name="harness_ref" placeholder="open string (optional)" /></label>` +
    `<label class="stack">Provider ref <input name="provider_ref" placeholder="open string (optional)" /></label>` +
    `<label class="stack">Model ref <input name="model_ref" placeholder="open string (optional)" /></label>` +
    capabilityFieldsHtml() +
    `<label class="stack">Metadata (key=value per line) <textarea name="metadata" rows="2" placeholder="optional, secrets are refused by the server"></textarea></label>` +
    `<button type="submit">Register</button>` +
    `<span class="meta">POST /runtimes · Idempotency-Key per attempt · at least one anchor required</span>` +
    `<div data-msg class="meta"></div></form></details>`
  );
}

function bindRuntimes(root: HTMLElement, ctx: ConfigurationContext): void {
  const toggle = root.querySelector<HTMLInputElement>("[data-include-revoked]");
  toggle?.addEventListener("change", () => {
    includeRevoked = toggle.checked;
    void renderRuntimes(root, ctx);
  });
  const form = root.querySelector<HTMLFormElement>("[data-runtime-create]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = form.querySelector("[data-msg]");
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    const built = buildRuntimeCreate(formReader(form));
    if (!built.ok) {
      if (msg !== null) msg.textContent = built.error;
      return;
    }
    if (submit !== null) submit.disabled = true;
    registerRuntime(ctx.client, built.value)
      .then(() => {
        void renderRuntimes(root, ctx);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
}

export async function renderRuntimeDetail(root: HTMLElement, ctx: ConfigurationContext, runtimeId: string): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = configTabsHtml("runtimes") + section("Runtime", "", statusBlock("empty", "Set a machine token."));
    return;
  }
  root.innerHTML = configTabsHtml("runtimes") + section("Runtime", "GET /runtimes/{id}", statusBlock("loading"));
  let runtime: RuntimeRegistration;
  try {
    runtime = await getRuntime(ctx.client, runtimeId);
  } catch (error) {
    root.innerHTML = configTabsHtml("runtimes") + section("Runtime", "GET /runtimes/{id}", statusBlock("error", describeError(error)));
    return;
  }
  const refsHtml =
    [
      runtime.harness_ref !== null && runtime.harness_ref !== undefined ? `Harness=<code class="mono">${esc(runtime.harness_ref)}</code>` : null,
      runtime.provider_ref !== null && runtime.provider_ref !== undefined ? `Provider=<code class="mono">${esc(runtime.provider_ref)}</code>` : null,
      runtime.model_ref !== null && runtime.model_ref !== undefined ? `Model=<code class="mono">${esc(runtime.model_ref)}</code>` : null,
    ]
      .filter((part): part is string => part !== null)
      .join(" · ") || '<span class="meta">—</span>';
  root.innerHTML =
    configTabsHtml("runtimes") +
    section(
      `Runtime · ${runtime.id}`,
      "GET /runtimes/{id} · PATCH /runtimes/{id} · POST /runtimes/{id}/revoke",
      `<div class="detail-grid">` +
        `<div>Owner: ${idCell(runtime.owner_user_id)} · machine: ${runtime.machine_id !== null ? idCell(runtime.machine_id) : '<span class="meta">remote</span>'}</div>` +
        `<div>Status: ${esc(runtimeStatusLabel(runtime.status))} · revision: v${runtime.version} · capability source: ${esc(runtime.capability_source)}</div>` +
        `<div>Refs: ${refsHtml}</div>` +
        `<div>Capabilities: ${capabilitySummary(runtime.capabilities)}</div>` +
        `<div class="meta">created ${fmtTime(runtime.created_at)}${runtime.updated_at !== null ? ` · updated ${fmtTime(runtime.updated_at)}` : ""}</div>` +
        `<div>Metadata: <code class="mono">${esc(JSON.stringify(runtime.runtime_metadata))}</code></div></div>` +
        updateRuntimeFormHtml(runtime) +
        `<form class="inline-form" data-revoke><h3>Revoke</h3>` +
        `<span class="meta">Logical revocation: the row stays readable and bindings toward it fall through.</span>` +
        `<button type="submit"${runtime.status === "revoked" ? " disabled" : ""}>Revoke</button>` +
        `<div data-msg class="meta"></div></form>`,
    );
  bindRuntimeDetail(root, ctx, runtime);
}

function updateRuntimeFormHtml(runtime: RuntimeRegistration): string {
  const disabled = runtime.status === "revoked" ? "disabled" : "";
  return (
    `<form class="stack-form" data-runtime-update>` +
    `<label class="stack">Harness ref (blank = unchanged) <input name="harness_ref" placeholder="${esc(runtime.harness_ref ?? "unchanged")}" ${disabled} /></label>` +
    `<label class="stack">Provider ref (blank = unchanged) <input name="provider_ref" placeholder="${esc(runtime.provider_ref ?? "unchanged")}" ${disabled} /></label>` +
    `<label class="stack">Model ref (blank = unchanged) <input name="model_ref" placeholder="${esc(runtime.model_ref ?? "unchanged")}" ${disabled} /></label>` +
    `<label class="stack">Machine ID (blank = unchanged) <input name="machine_id" placeholder="uuid" ${disabled} /></label>` +
    `<label class="check">Detach machine <input name="detach_machine" type="checkbox" ${disabled} /></label>` +
    `<label class="check">Replace capabilities <input name="update_capabilities" type="checkbox" ${disabled} /></label>` +
    capabilityFieldsHtml(runtime.status === "revoked") +
    `<label class="stack">Metadata (key=value per line, blank = unchanged) <textarea name="metadata" rows="2" ${disabled}></textarea></label>` +
    `<label class="stack">Expected version <input name="expected_version" type="number" min="1" value="${runtime.version}" required ${disabled} /></label>` +
    `<button type="submit" ${disabled}>Update</button>` +
    `<span class="meta">PATCH /runtimes/{id} · stale expected_version → 409</span>` +
    `<div data-msg class="meta"></div></form>`
  );
}

function bindRuntimeDetail(root: HTMLElement, ctx: ConfigurationContext, runtime: RuntimeRegistration): void {
  const updateForm = root.querySelector<HTMLFormElement>("[data-runtime-update]");
  updateForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = updateForm.querySelector("[data-msg]");
    const submit = updateForm.querySelector<HTMLButtonElement>("button[type=submit]");
    const built = buildRuntimeUpdate(formReader(updateForm));
    if (!built.ok) {
      if (msg !== null) msg.textContent = built.error;
      return;
    }
    if (submit !== null) submit.disabled = true;
    updateRuntime(ctx.client, runtime.id, built.value)
      .then(() => {
        void renderRuntimeDetail(root, ctx, runtime.id);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
  const revokeForm = root.querySelector<HTMLFormElement>("[data-revoke]");
  revokeForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!window.confirm("Revoke this runtime? The row stays readable but resolves as non-live.")) return;
    revokeRuntime(ctx.client, runtime.id)
      .then(() => {
        void renderRuntimeDetail(root, ctx, runtime.id);
      })
      .catch((error: unknown) => {
        const msg = revokeForm.querySelector("[data-msg]");
        if (msg !== null) msg.textContent = describeError(error);
      });
  });
}

export async function renderBindings(root: HTMLElement, ctx: ConfigurationContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML =
      configTabsHtml("bindings") + section("Bindings", "GET /runtime-bindings", statusBlock("empty", "Set a machine token to read your bindings."));
    return;
  }
  root.innerHTML = configTabsHtml("bindings") + section("Bindings", "GET /runtime-bindings", statusBlock("loading"));
  let bindings: RuntimeBinding[];
  try {
    bindings = await listRuntimeBindings(ctx.client);
  } catch (error) {
    root.innerHTML = configTabsHtml("bindings") + section("Bindings", "GET /runtime-bindings", statusBlock("error", describeError(error)));
    return;
  }
  const rows = bindings
    .map(
      (binding) =>
        `<tr><td>${esc(kindMeta(binding.target_kind).singular)}</td><td><code class="mono">${esc(binding.target_stable_key)}</code></td>` +
        `<td>${esc(bindingLevelLabel(binding.level))}</td><td>${binding.project_id !== null ? idCell(binding.project_id) : '<span class="meta">—</span>'}</td>` +
        `<td>${runtimeTargetSummary(binding.target)}</td><td>${idCell(binding.owner_user_id)}</td><td>${fmtTime(binding.created_at)}</td>` +
        `<td class="actions"><button type="button" data-delete-binding="${esc(binding.id)}">Delete</button></td></tr>`,
    )
    .join("");
  const table =
    bindings.length === 0
      ? statusBlock("empty", "No stored runtime binding.")
      : `<table><thead><tr><th>Target kind</th><th>Stable key</th><th>Level</th><th>Project</th><th>Runtime target</th><th>Owner</th><th>Created</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
  root.innerHTML =
    configTabsHtml("bindings") +
    section(
      "Bindings",
      `GET /runtime-bindings · ${bindings.length} shown`,
      `${table}${createBindingFormHtml()}` +
        `<p class="meta">A binding says "for this logical key, use this runtime". Levels are stored choices; the winning level is decided by the server at resolution time.</p>`,
    );
  bindBindings(root, ctx);
}

function createBindingFormHtml(): string {
  return (
    `<details class="editor"><summary>New binding</summary><form class="stack-form" data-binding-create>` +
    `<label class="stack">Level <select name="level"><option value="user">user</option><option value="project_override">project_override</option><option value="project_default">project_default</option><option value="studio_default">studio_default</option></select></label>` +
    `<label class="stack">Project ID (project levels only) <input name="project_id" placeholder="uuid" /></label>` +
    `<label class="stack">Target kind <select name="target_kind"><option value="agent_definition">Agent Definition</option><option value="model_profile">Model Profile</option></select></label>` +
    `<label class="stack">Target stable key <input name="target_stable_key" required /></label>` +
    `<label class="stack">Runtime registry id <input name="runtime_id" placeholder="uuid (exclusive of inline anchors)" /></label>` +
    `<div class="meta">or inline anchors:</div>` +
    `<label class="stack">Machine ID <input name="machine_id" placeholder="uuid" /></label>` +
    `<label class="stack">Harness ref <input name="harness_ref" /></label>` +
    `<label class="stack">Provider ref <input name="provider_ref" /></label>` +
    `<label class="stack">Model ref <input name="model_ref" /></label>` +
    capabilityFieldsHtml() +
    `<button type="submit">Create</button>` +
    `<span class="meta">POST /runtime-bindings · Idempotency-Key per attempt · session level is ephemeral and never stored here</span>` +
    `<div data-msg class="meta"></div></form></details>`
  );
}

function bindBindings(root: HTMLElement, ctx: ConfigurationContext): void {
  const form = root.querySelector<HTMLFormElement>("[data-binding-create]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = form.querySelector("[data-msg]");
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    const built = buildBindingCreate(formReader(form));
    if (!built.ok) {
      if (msg !== null) msg.textContent = built.error;
      return;
    }
    if (submit !== null) submit.disabled = true;
    createRuntimeBinding(ctx.client, built.value)
      .then(() => {
        void renderBindings(root, ctx);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-delete-binding]").forEach((button) => {
    button.addEventListener("click", () => {
      const bindingId = button.dataset["deleteBinding"];
      if (bindingId === undefined) return;
      if (!window.confirm("Delete this binding? The server snapshot is returned.")) return;
      deleteRuntimeBinding(ctx.client, bindingId)
        .then(() => {
          void renderBindings(root, ctx);
        })
        .catch((error: unknown) => {
          window.alert(describeError(error));
        });
    });
  });
}

let projectConfigOverride: string | null = null;

export function setProjectConfigProject(projectId: string | null): void {
  projectConfigOverride = projectId === null || projectId.trim() === "" ? null : projectId.trim();
}

function effectiveProjectId(): string | null {
  return projectConfigOverride ?? uiState.selectedProjectId;
}

export async function renderProjectConfig(root: HTMLElement, ctx: ConfigurationContext, tab: "resources" | "locks" | "overrides"): Promise<void> {
  const tabs = projectTabsHtml(tab);
  if (!ctx.authed) {
    root.innerHTML = configTabsHtml("project") + tabs + section("Project", "", statusBlock("empty", "Set a machine token to read project configuration."));
    return;
  }
  const projectId = effectiveProjectId();
  let body: string;
  try {
    body =
      projectId === null
        ? statusBlock("empty", "Enter a project ID to view its resources, locks and overrides.")
        : await projectTabBody(ctx, projectId, tab);
  } catch (error) {
    body = statusBlock("error", describeError(error));
  }
  root.innerHTML =
    configTabsHtml("project") +
    tabs +
    section("Project configuration", projectId === null ? "no project selected" : `project ${esc(projectId)}`, `${projectSelectorHtml(projectId)}${body}`);
  bindProjectTab(root, ctx, tab, projectId);
}

function projectSelectorHtml(projectId: string | null): string {
  return (
    `<form class="inline-form" data-project-select>` +
    `<label>Project ID <input name="project_id" value="${esc(projectId ?? "")}" placeholder="uuid" /></label>` +
    `<button type="submit">Load</button>` +
    `<span class="meta">${projectId === null ? "select one here or in Overview" : "active project context"}</span></form>`
  );
}

function projectTabsHtml(active: "resources" | "locks" | "overrides"): string {
  return `<nav class="tabs">${(["resources", "locks", "overrides"] as const)
    .map((name) => `<a class="tab${name === active ? " active" : ""}" href="#/configuration/project/${name}">${esc(name[0]?.toUpperCase() + name.slice(1))}</a>`)
    .join("")}</nav>`;
}

async function projectTabBody(ctx: ConfigurationContext, projectId: string, tab: "resources" | "locks" | "overrides"): Promise<string> {
  if (tab === "resources") return projectResourcesHtml(ctx, projectId);
  if (tab === "locks") return projectLocksHtml(ctx, projectId);
  return projectOverridesHtml(ctx, projectId);
}

function bindProjectTab(root: HTMLElement, ctx: ConfigurationContext, tab: "resources" | "locks" | "overrides", projectId: string | null): void {
  const selector = root.querySelector<HTMLFormElement>("[data-project-select]");
  selector?.addEventListener("submit", (event) => {
    event.preventDefault();
    setProjectConfigProject(formReader(selector).text("project_id"));
    void renderProjectConfig(root, ctx, tab);
  });
  if (tab !== "locks" || projectId === null) return;
  const lockForm = root.querySelector<HTMLFormElement>("[data-lock]");
  lockForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const read = formReader(lockForm);
    const resourceId = read.text("resource_id").trim();
    const version = Number(read.text("lock_version"));
    const msg = lockForm.querySelector("[data-msg]");
    if (resourceId === "" || !Number.isInteger(version) || version < 1) {
      if (msg !== null) msg.textContent = "resource ID and a version ≥ 1 are required";
      return;
    }
    createLibraryLock(ctx.client, { project_id: projectId, resource_id: resourceId, locked_version: version })
      .then(() => {
        void renderProjectConfig(root, ctx, "locks");
      })
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
        .then(() => {
          void renderProjectConfig(root, ctx, "locks");
        })
        .catch((error: unknown) => {
          window.alert(describeError(error));
        });
    });
  });
}

async function projectResourcesHtml(ctx: ConfigurationContext, projectId: string): Promise<string> {
  const resources: LibraryResource[] = await listLibraryResources(ctx.client, { projectId });
  const rows = resources
    .map(
      (resource) =>
        `<tr><td><a href="${esc(libraryKindHref(resource.kind, resource.id))}"><code class="mono">${esc(resource.stable_key)}</code></a></td>` +
        `<td>${esc(kindMeta(resource.kind).singular)}</td><td>${esc(scopeLabel(resource.scope))}</td>` +
        `<td>${resource.active_version === 0 ? '<span class="meta">none</span>' : `v${resource.active_version}`}</td><td>${esc(resource.status)}</td></tr>`,
    )
    .join("");
  const table =
    resources.length === 0
      ? statusBlock("empty", "No project-scoped library resource for this project.")
      : `<table><thead><tr><th>Stable key</th><th>Kind</th><th>Scope</th><th>Active</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`;
  return `<h3>Resources</h3><p class="meta">GET /library?project_id=&hellip; — project-scoped definitions. Studio/User resources are not project membership.</p>${table}`;
}

async function projectLocksHtml(ctx: ConfigurationContext, projectId: string): Promise<string> {
  const locks: LibraryProjectLock[] = await listLibraryLocks(ctx.client, projectId);
  const rows = locks
    .map(
      (lock) =>
        `<tr><td><code class="mono">${esc(lock.resource_id)}</code></td><td>v${lock.locked_version}</td>` +
        `<td>${idCell(lock.created_by_user_id)}</td><td>${fmtTime(lock.created_at)}</td>` +
        `<td class="actions"><button type="button" data-release-lock="${esc(lock.id)}">Release</button></td></tr>`,
    )
    .join("");
  const table =
    locks.length === 0
      ? statusBlock("empty", "No lock for this project.")
      : `<table><thead><tr><th>Resource</th><th>Locked version</th><th>Created by</th><th>Created</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
  return (
    `<h3>Locks</h3><p class="meta">RESOURCE | LOCKED VERSION — the lock pins a version for this project; the effective version is only decided by the server (see Resolution Inspector).</p>${table}` +
    `<form class="inline-form" data-lock>` +
    `<label>Resource ID <input name="resource_id" placeholder="uuid" required /></label>` +
    `<label>Version <input name="lock_version" type="number" min="1" required /></label>` +
    `<button type="submit">Set lock</button>` +
    `<span class="meta">POST /library-locks</span><div data-msg class="meta"></div></form>`
  );
}

function bindingsTableHtml(bindings: RuntimeBinding[], emptyMessage: string): string {
  if (bindings.length === 0) return statusBlock("empty", emptyMessage);
  const rows = bindings
    .map(
      (binding) =>
        `<tr><td>${esc(kindMeta(binding.target_kind).singular)}</td><td><code class="mono">${esc(binding.target_stable_key)}</code></td>` +
        `<td>${esc(bindingLevelLabel(binding.level))}</td><td>${runtimeTargetSummary(binding.target)}</td></tr>`,
    )
    .join("");
  return `<table><thead><tr><th>Target kind</th><th>Stable key</th><th>Level</th><th>Runtime target</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function projectOverridesHtml(ctx: ConfigurationContext, projectId: string): Promise<string> {
  const [overrides, defaults, studioDefaults] = await Promise.all([
    listRuntimeBindings(ctx.client, { projectId, level: "project_override" }),
    listRuntimeBindings(ctx.client, { projectId, level: "project_default" }),
    listRuntimeBindings(ctx.client, { level: "studio_default" }),
  ]);
  return (
    `<h3>Project overrides</h3><p class="meta">GET /runtime-bindings?project_id=&hellip;&amp;level=project_override — explicit project pinning.</p>${bindingsTableHtml(overrides, "No project override.")}` +
    `<h3>Project defaults</h3><p class="meta">level=project_default — a fallback for this project, distinct from an override.</p>${bindingsTableHtml(defaults, "No project default.")}` +
    `<h3>Studio defaults</h3><p class="meta">level=studio_default — shown only if the server returns them for this token.</p>${bindingsTableHtml(studioDefaults, "No studio default visible.")}` +
    `<p><a href="#/inspector">Open the Resolution Inspector</a> to see which level actually wins for a given AgentDefinition.</p>`
  );
}
