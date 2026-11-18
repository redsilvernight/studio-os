/**
 * P3 — configuration d'un dossier par « Espaces de travail ».
 *
 * Réunit au même endroit ce que l'assistant de premier lancement ne fait
 * plus : la mémoire du dossier, l'environnement local (Git, analyse du
 * code) et la connexion de l'assistant IA (harnais). Le code est repris de
 * l'ancien parcours par étapes, sans le contraindre à un ordre imposé.
 */
import type { Platform } from "../platform";
import type {
  KnowledgeStatus,
  LocalError,
} from "../platform/generated/local-contracts.generated";
import { esc } from "../ui";
import { dsBadge } from "../ds/ds";
import {
  applyHarness,
  CHANGE_LABELS,
  detectHarnesses,
  harnessErrorMessage,
  previewHarness,
  STATE_LABELS,
  STATE_TONES,
  type HarnessPlan,
  type HarnessStatus,
} from "../harnessApi";
import {
  confirmRoots,
  gitStatusMessage,
  saveWorkspaceConfig,
  workspaceErrorMessage,
  workspaceGitStatus,
} from "../onboarding/workspaceApi";

export interface FolderSetupView {
  error: string | null;
  notice: string | null;
  knowledgeText: string | null;
  gitText: string | null;
  codeText: string | null;
  codeDisabled: boolean;
  harnesses: HarnessStatus[] | null;
  harnessError: string | null;
  plan: HarnessPlan | null;
}

function emptyView(): FolderSetupView {
  return {
    error: null,
    notice: null,
    knowledgeText: null,
    gitText: null,
    codeText: null,
    codeDisabled: false,
    harnesses: null,
    harnessError: null,
    plan: null,
  };
}

function utcNow(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function lockButton(button: HTMLButtonElement | null | undefined, label: string): boolean {
  if (!button) return true;
  if (button.disabled) return false;
  button.disabled = true;
  button.textContent = label;
  button.setAttribute("aria-busy", "true");
  return true;
}

function errorHtml(message: string | null): string {
  return message ? `<p class="ds-field-error" role="alert" data-testid="folder-setup-error">${esc(message)}</p>` : "";
}

function noticeHtml(message: string | null): string {
  return message ? `<p class="settings-notice" role="status" data-testid="folder-setup-notice">${esc(message)}</p>` : "";
}

function knowledgeMessage(status: KnowledgeStatus | null, error: LocalError | null): string {
  if (error) {
    if (error.code === "workspace_config_missing") return "Aucun dossier associé : la mémoire sera proposée après l'association.";
    return "Mémoire indisponible pour l'instant.";
  }
  if (!status) return "État de la mémoire inconnu.";
  const index = status.index?.state;
  switch (status.state) {
    case "ready":
      if (index === "ready") return "Mémoire prête.";
      if (index === "absent") return "Mémoire vide : aucun document indexé pour l'instant.";
      if (index === "indexing") return "Mémoire en cours d'indexation…";
      if (index === "corrupt") return "Index illisible : relancez l'indexation depuis les graphes.";
      return "Mémoire prête.";
    case "disabled":
      return "Mémoire désactivée pour ce dossier.";
    case "indexing":
      return "Mémoire en cours d'indexation…";
    case "unavailable":
      return "Mémoire indisponible : vérifiez le dossier de la mémoire.";
    default:
      return "Mémoire indisponible pour l'instant.";
  }
}

async function readKnowledge(platform: Platform, workspaceId: string): Promise<{ text: string }> {
  const answer = await platform.request("knowledge.status", { workspace_id: workspaceId });
  if (!answer.ok) return { text: knowledgeMessage(null, answer.error) };
  return { text: knowledgeMessage(answer.response.payload as unknown as KnowledgeStatus, null) };
}

async function readCodeGraphStatus(platform: Platform, workspaceId: string): Promise<{ text: string; disabled: boolean }> {
  const answer = await platform.request("code_graph.status", { workspace_id: workspaceId });
  if (!answer.ok) {
    if (answer.error.code === "not_supported" || answer.error.code === "capability_missing") {
      return { text: "Analyse avancée du code indisponible.", disabled: false };
    }
    return { text: "Analyse du code indisponible pour l'instant.", disabled: false };
  }
  const raw = answer.response.payload as { state?: string };
  if (raw.state === "ready") return { text: "Analyse du code prête.", disabled: false };
  if (raw.state === "not_installed") {
    return { text: "Analyse avancée du code indisponible (composant non installé).", disabled: false };
  }
  if (raw.state === "indexing") return { text: "Analyse du code en cours d'indexation…", disabled: false };
  if (raw.state === "disabled") return { text: "Analyse du code désactivée pour ce dossier.", disabled: true };
  return { text: "Analyse du code indisponible pour l'instant.", disabled: false };
}

const DEFAULT_MEMORY_FOLDER = "vault";
const CODE_GRAPH_REPO_NAME = "main";

async function enableKnowledge(
  platform: Platform,
  workspaceId: string,
  view: FolderSetupView,
  again: () => Promise<void>,
): Promise<void> {
  const answer = await platform.request("workspace.get_config", { workspace_id: workspaceId });
  if (!answer.ok) {
    view.error = workspaceErrorMessage(answer.error);
    return again();
  }
  const stored = answer.response.payload as Record<string, unknown>;
  const storedRoots = stored.roots as Record<string, unknown>;
  const storedKnowledge = (stored.knowledge as Record<string, unknown> | undefined) ?? {};
  const contentRoot =
    typeof storedKnowledge.content_root === "string" && storedKnowledge.content_root.trim()
      ? storedKnowledge.content_root
      : DEFAULT_MEMORY_FOLDER;
  const config = {
    ...(stored as object),
    features: { ...((stored.features as Record<string, unknown>) ?? {}), knowledge: true },
    knowledge: {
      provider_id: "markdown-files",
      content_root: contentRoot,
      index: { scope: "workspace_cache", directory_name: "knowledge-index" },
    },
    updated_at: utcNow(),
  };
  const saved = await saveWorkspaceConfig(platform, {
    config,
    current_roots: storedRoots,
    ...(typeof stored.updated_at === "string" ? { expected_updated_at: stored.updated_at } : {}),
  });
  if (!saved.ok) {
    view.error = workspaceErrorMessage(saved.error);
    return again();
  }
  const initialized = await platform.request("knowledge.init_vault", {
    workspace_id: workspaceId,
    confirmed: true,
  });
  if (!initialized.ok) {
    view.error = workspaceErrorMessage(initialized.error);
    return again();
  }
  const indexed = await platform.request("knowledge.reindex", {
    workspace_id: workspaceId,
    mode: "full_rebuild",
  });
  if (!indexed.ok) {
    view.error = workspaceErrorMessage(indexed.error);
    return again();
  }
  const { text } = await readKnowledge(platform, workspaceId);
  view.knowledgeText = text;
  view.notice = "Mémoire activée et préparée dans le dossier du projet.";
  view.error = null;
  return again();
}

async function enableCodeGraph(
  platform: Platform,
  workspaceId: string,
  view: FolderSetupView,
  again: () => Promise<void>,
): Promise<void> {
  const answer = await platform.request("workspace.get_config", { workspace_id: workspaceId });
  if (!answer.ok) {
    view.error = workspaceErrorMessage(answer.error);
    return again();
  }
  const stored = answer.response.payload as Record<string, unknown>;
  const storedRoots = stored.roots as { workspace_root: string; repo_roots?: { name: string; path: string }[] };
  const repoRoots = storedRoots.repo_roots ?? [];
  const roots = repoRoots.length
    ? { workspace_root: storedRoots.workspace_root, repo_roots: repoRoots }
    : { workspace_root: storedRoots.workspace_root, repo_roots: [{ name: CODE_GRAPH_REPO_NAME, path: storedRoots.workspace_root }] };
  let rootConfirmationId: string | undefined;
  if (!repoRoots.length) {
    const confirmed = await confirmRoots(platform, roots);
    if (!confirmed.ok) {
      view.error = workspaceErrorMessage(confirmed.error);
      return again();
    }
    rootConfirmationId = confirmed.value.root_confirmation_id;
  }
  const config = {
    ...(stored as object),
    roots,
    features: { ...((stored.features as Record<string, unknown>) ?? {}), code_graph: true },
    code_graph: {
      provider_id: "graphify",
      index: { scope: "workspace_cache", directory_name: "code-graph-index" },
    },
    updated_at: utcNow(),
  };
  const saved = await saveWorkspaceConfig(platform, {
    config,
    current_roots: storedRoots,
    ...(rootConfirmationId ? { root_confirmation_id: rootConfirmationId } : {}),
    ...(typeof stored.updated_at === "string" ? { expected_updated_at: stored.updated_at } : {}),
  });
  if (!saved.ok) {
    view.error = workspaceErrorMessage(saved.error);
    return again();
  }
  const indexed = await platform.request("code_graph.reindex", { workspace_id: workspaceId, mode: "full_rebuild" });
  const status = await readCodeGraphStatus(platform, workspaceId);
  view.codeText = status.text;
  view.error = null;
  view.notice =
    indexed.ok && (indexed.response.payload as { accepted?: boolean }).accepted
      ? "Analyse du code activée : l'indexation se poursuit en arrière-plan."
      : "Analyse du code activée. L'indexation démarrera dès que le composant d'analyse sera disponible.";
  return again();
}

function harnessCard(harness: HarnessStatus, plan: HarnessPlan | null): string {
  const configured = harness.state === "configured";
  const installed = configured || harness.state === "detected";
  const shown = plan && plan.adapter_id === harness.adapter_id ? planHtml(plan) : "";
  const actions = installed
    ? `<div class="integration-actions">` +
      `<button class="ds-btn ds-btn--primary" type="button" data-action="preview" data-harness="${esc(harness.adapter_id)}">${configured ? "Reconfigurer" : "Connecter à Studi'OS"}</button></div>`
    : "";
  return (
    `<article class="ds-card integration" data-harness="${esc(harness.adapter_id)}" data-state="${esc(harness.state)}">` +
    `<header class="integration-head"><h3>${esc(harness.display_name)}</h3>${dsBadge(STATE_LABELS[harness.state], STATE_TONES[harness.state])}</header>` +
    `<dl class="settings-rows"><div class="settings-row"><dt>Version</dt><dd>${esc(harness.detected_version ?? "—")}</dd></div>` +
    `<div class="settings-row"><dt>MCP Studi'OS</dt><dd>${configured ? "Configuré" : installed ? "Non configuré" : "—"}</dd></div></dl>` +
    actions +
    shown +
    `</article>`
  );
}

function planHtml(plan: HarnessPlan): string {
  const rows = (plan.changes ?? [])
    .map(
      (change) =>
        `<li><strong>${esc(CHANGE_LABELS[change.kind] ?? change.kind)}</strong> · <code class="mono">${esc(change.target)}</code></li>`,
    )
    .join("");
  if ((plan.changes ?? []).length === 0) {
    return `<div class="integration-plan" role="status"><p>Déjà à jour : aucune modification à appliquer.</p>` +
      `<button class="ds-btn" type="button" data-action="cancel-plan">Fermer</button></div>`;
  }
  return (
    `<div class="integration-plan" role="region" aria-label="Aperçu des modifications">` +
    `<h4>Aperçu — rien n'est écrit tant que vous n'appliquez pas</h4><ul>${rows}</ul>` +
    `<p class="settings-intro">Une sauvegarde locale est créée avant toute écriture.</p>` +
    `<button class="ds-btn ds-btn--primary" type="button" data-action="apply-plan">Appliquer</button> ` +
    `<button class="ds-btn" type="button" data-action="cancel-plan">Annuler</button></div>`
  );
}

function bindHarnessCards(
  root: HTMLElement,
  platform: Platform,
  workspaceId: string,
  view: FolderSetupView,
  again: () => Promise<void>,
): void {
  for (const card of root.querySelectorAll<HTMLElement>("[data-harness]")) {
    const adapterId = card.dataset["harness"] ?? "";
    const failed = (): Promise<void> => {
      view.error = harnessErrorMessage(null);
      return again();
    };
    card.querySelector<HTMLButtonElement>("[data-action=preview]")?.addEventListener("click", (event) => {
      if (!lockButton(event.currentTarget as HTMLButtonElement, "Préparation…")) return;
      void previewHarness(platform, workspaceId, adapterId).then((outcome) => {
        if (!outcome.ok) {
          view.error = harnessErrorMessage(outcome.error);
          return again();
        }
        view.plan = outcome.value;
        view.error = null;
        return again();
      }, failed);
    });
    card.querySelector("[data-action=cancel-plan]")?.addEventListener("click", () => {
      view.plan = null;
      void again();
    });
    card.querySelector<HTMLButtonElement>("[data-action=apply-plan]")?.addEventListener("click", (event) => {
      const plan = view.plan;
      if (!plan || plan.adapter_id !== adapterId) return;
      if (!lockButton(event.currentTarget as HTMLButtonElement, "Application…")) return;
      void applyHarness(platform, plan).then((outcome) => {
        if (!outcome.ok) {
          view.error = harnessErrorMessage(outcome.error);
          return again();
        }
        if (outcome.value.error || outcome.value.state !== "configured") {
          view.error = harnessErrorMessage(outcome.value.error);
          return again();
        }
        view.plan = null;
        view.notice = "Configuration appliquée. Une sauvegarde locale permet de la restaurer.";
        view.error = null;
        return again();
      }, failed);
    });
  }
}

/**
 * Configure la mémoire, l'environnement et l'assistant IA d'un dossier.
 * Monté par « Espaces de travail » (« Configurer le dossier »), jamais par
 * l'assistant de premier lancement.
 */
export async function renderFolderSetup(
  root: HTMLElement,
  platform: Platform,
  workspaceId: string,
  view: FolderSetupView | null = null,
): Promise<void> {
  const state: FolderSetupView = view ?? emptyView();
  const again = (): Promise<void> => renderFolderSetup(root, platform, workspaceId, state);
  const { text: knowledge } = await readKnowledge(platform, workspaceId);
  state.knowledgeText = knowledge;
  const probed = await workspaceGitStatus(platform, workspaceId);
  state.gitText = probed.ok ? gitStatusMessage(probed.value) : workspaceErrorMessage(probed.error);
  const codeStatus = await readCodeGraphStatus(platform, workspaceId);
  state.codeText = codeStatus.text;
  state.codeDisabled = codeStatus.disabled;
  const detected = await detectHarnesses(platform, workspaceId);
  state.harnesses = detected.ok ? (detected.value.harnesses ?? []) : [];
  state.harnessError = detected.ok ? null : harnessErrorMessage(detected.error);
  const cards =
    (state.harnesses ?? []).length === 0
      ? `<p class="settings-intro">Aucun assistant détecté. Studi'OS fonctionne sans assistant IA.</p>`
      : (state.harnesses ?? []).map((harness) => harnessCard(harness, state.plan)).join("");
  root.innerHTML =
    `<div data-testid="folder-setup">` +
    errorHtml(state.error ?? state.harnessError) +
    noticeHtml(state.notice) +
    `<section class="settings-domain" data-testid="folder-setup-memory"><h3>Mémoire du dossier</h3>` +
    `<dl class="settings-rows"><div class="settings-row"><dt>Mémoire</dt><dd>${esc(state.knowledgeText ?? "Non configurée.")}</dd></div></dl>` +
    `<p class="settings-intro">La mémoire est rangée dans le dossier, sans rien à choisir. Vous pourrez l'ouvrir dans Obsidian ou tout autre éditeur Markdown : Obsidian n'est jamais requis.</p>` +
    `<form class="settings-server-form" data-testid="memory-folder-form">` +
    `<div class="settings-actions"><button class="ds-btn ds-btn--primary" type="submit">Activer la mémoire</button></div></form></section>` +
    `<section class="settings-domain" data-testid="folder-setup-environment"><h3>Environnement local</h3>` +
    `<dl class="settings-rows">` +
    `<div class="settings-row"><dt>Git</dt><dd>${esc(state.gitText ?? "—")}</dd></div>` +
    `<div class="settings-row"><dt>Analyse du code</dt><dd>${esc(state.codeText ?? "—")}</dd></div></dl>` +
    (state.codeDisabled
      ? `<div class="settings-actions"><button class="ds-btn ds-btn--primary" type="button" data-action="enable-code">Activer l'analyse du code</button></div>`
      : "") +
    `</section>` +
    `<section class="settings-domain" data-testid="folder-setup-harness"><h3>Assistant IA</h3>` +
    `<p class="settings-intro">Le jeton Studi'OS n'est jamais écrit dans les fichiers, seulement référencé. Lancez ensuite votre assistant depuis Studi'OS pour activer la connexion.</p>` +
    `<div class="integrations-list">${cards}</div></section>` +
    `</div>`;
  state.notice = null;
  root.querySelector<HTMLFormElement>("[data-testid=memory-folder-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit?.disabled) return;
    if (submit) {
      submit.disabled = true;
      submit.textContent = "Activation en cours…";
    }
    form.setAttribute("aria-busy", "true");
    void enableKnowledge(platform, workspaceId, state, again).catch(() => {
      state.error = "L'activation de la mémoire a échoué. Réessayez.";
      void again();
    });
  });
  root.querySelector<HTMLButtonElement>("[data-action=enable-code]")?.addEventListener("click", (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = "Activation en cours…";
    void enableCodeGraph(platform, workspaceId, state, again).catch(() => {
      state.error = "L'activation de l'analyse du code a échoué. Réessayez.";
      void again();
    });
  });
  bindHarnessCards(root, platform, workspaceId, state, again);
}
