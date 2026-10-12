/**
 * Indicateur permanent de synchronisation des skills (Desktop) : état courant
 * du démon (`skills.status`), notification à la fin d'une synchro qui a changé
 * quelque chose ou échoué, détail et actions (différences, réessayer).
 * Les messages affichés sont fixes : jamais le texte brut du démon.
 */
import { dsModalHtml, dsNotify, openDsDialog } from "./ds/ds";
import { esc } from "./ui";
import { harnessErrorMessage } from "./harnessApi";
import type { Platform } from "./platform";
import {
  applySkills,
  configureSkillsSync,
  getSkillsSyncStatus,
  previewSkills,
  SYNC_STATE_LABELS,
  SYNC_STATE_LEVELS,
  SYNC_STATE_MESSAGES,
  type SkillsSyncStatus,
  type SkillsPreviewResult,
  type SkillResolution,
} from "./skillsApi";

const NOTIFIED_KEY = "studio.skills-sync.notified";
const RUNNING_POLL_MS = 3000;
const IDLE_POLL_MS = 60000;
const DIALOG_ID = "skills-sync-dialog";

let timer: ReturnType<typeof setTimeout> | null = null;
let current: SkillsSyncStatus | null = null;
let unavailable = false;
let busy = false;
let preview: SkillsPreviewResult | null = null;
let previewLoading = false;
let previewIssue = "";
let operationNote = "";
let confirming = false;
let previewGeneration = 0;
const choices = new Map<string, "local" | "library">();

type PreviewEntry = NonNullable<SkillsPreviewResult["skills"]>[number];

function pendingSkills(plan: SkillsPreviewResult | null): PreviewEntry[] {
  return (plan?.skills ?? []).filter((skill) => skill.targets.some((target) => target.state !== "current"));
}

function diffHtml(diff: string): string {
  return diff.split("\n").map((line) => {
    const kind = line.startsWith("+") && !line.startsWith("+++") ? "added"
      : line.startsWith("-") && !line.startsWith("---") ? "removed" : "context";
    return `<span class="skills-sync-line skills-sync-line--${kind}">${esc(line)}\n</span>`;
  }).join("");
}

function skillRowHtml(skill: PreviewEntry): string {
  const key = skill.stable_key;
  const selected = choices.get(key) ?? "";
  const missing = skill.targets.every((target) => target.state === "missing");
  const local = skill.targets.some((target) => target.state === "locally_modified");
  const state = local ? "Modifié localement" : missing ? "Absent" : "Mise à jour disponible";
  return `<li class="skills-sync-row" data-skill="${esc(key)}">` +
    `<div class="skills-sync-identity"><strong>${esc(key)}</strong><span class="ds-badge ds-badge--${local ? "warning" : "neutral"}">${state}</span>` +
    `<code>.agents/skills/${esc(key)}/SKILL.md</code><small>Copies partagées et Claude Code</small></div>` +
    `<select class="ds-input" data-skills-choice="${esc(key)}" aria-label="Version à utiliser pour ${esc(key)}"${busy || !skill.preview_hash ? " disabled" : ""}>` +
    `<option value=""${selected === "" ? " selected" : ""}>Choisir une version…</option>` +
    `<option value="local"${selected === "local" ? " selected" : ""}${missing ? " disabled" : ""}>Garder ma version</option>` +
    `<option value="library"${selected === "library" ? " selected" : ""}>Utiliser la Library</option></select>` +
    `<details class="skills-sync-comparison"><summary>Comparer les versions de ${esc(key)}</summary>` +
    `<div class="skills-sync-legend"><span>− Ma version locale</span><span>+ Version Library · v${skill.version}</span></div>` +
    `<pre class="skills-sync-diff"><code>${diffHtml(skill.diff || "Aucune différence.")}</code></pre></details></li>`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "jamais";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "jamais" : date.toLocaleString("fr-FR");
}

function nameList(items: readonly string[] | undefined): string {
  const list = items ?? [];
  return list.length === 0 ? "" : `<ul>${list.map((name) => `<li>${esc(name)}</li>`).join("")}</ul>`;
}

export function skillsIndicatorHtml(status: SkillsSyncStatus | null, failed = false): string {
  const known = status !== null && !failed;
  const level = known ? SYNC_STATE_LEVELS[status.state] : "warn";
  const label = known ? SYNC_STATE_LABELS[status.state] : "Skills : état indisponible";
  const pending = known ? (status.conflicts ?? []).length || (status.updated ?? []).length + (status.added ?? []).length : 0;
  const suffix = known && pending > 0 && status.state !== "up_to_date" ? ` (${pending})` : "";
  return (
    `<button class="app-connection app-connection--${level} app-skills-sync" id="skills-sync" type="button" ` +
    `data-testid="skills-sync" data-state="${known ? status.state : "unavailable"}" ` +
    `aria-haspopup="dialog" aria-controls="${DIALOG_ID}" title="${esc(label + suffix)}">` +
    `<span class="app-connection-dot" aria-hidden="true"></span>` +
    `<span class="app-connection-label">${esc(label + suffix)}</span></button>`
  );
}

export function skillsDetailHtml(status: SkillsSyncStatus | null, failed: boolean): string {
  const pending = pendingSkills(preview);
  const count = choices.size;
  const replacements = pending.filter((skill) => choices.get(skill.stable_key) === "library");
  const compatible = pending.every((skill) => Boolean(skill.preview_hash));
  const message = status === null || failed ? SYNC_STATE_MESSAGES.not_synced : SYNC_STATE_MESSAGES[status.state];
  const subtitle = pending.length ? `${pending.length} skill${pending.length > 1 ? "s" : ""} à vérifier avant la mise à jour` : message;
  const confirmation = confirming
    ? `<section class="skills-sync-confirmation" aria-labelledby="skills-sync-confirm-title"><h3 id="skills-sync-confirm-title">Vérifier les choix</h3>` +
      `<p>${replacements.length ? "Les copies de ces skills seront remplacées par la Library, après sauvegarde :" : "Vos versions locales seront conservées pour cette synchronisation."}</p>` +
      (replacements.length ? `<ul>${replacements.map((skill) => `<li><strong>${esc(skill.stable_key)}</strong><code>${skill.targets.filter((target) => target.state !== "current").map((target) => `${target.harness === "agents" ? ".agents" : ".claude"}/skills/${esc(skill.stable_key)}/SKILL.md`).join("<br>")}</code></li>`).join("")}</ul>` : "") +
      `<p class="skills-sync-help">Les copies modifiées sont sauvegardées dans ~/.studio-os/backups/skills. Les skills sans choix restent en attente.</p></section>` : "";
  return `<div class="skills-sync-content"><p class="skills-sync-subtitle">${esc(subtitle)}</p>` +
    (pending.some((skill) => skill.targets.some((target) => target.state === "locally_modified")) || status?.state === "conflicts"
      ? `<p class="skills-sync-notice">Vos modifications locales ont été conservées.</p>` : "") +
    (previewLoading ? `<p role="status">Chargement des versions à comparer…</p>` : "") +
    (previewIssue ? `<p class="ds-error" role="alert">${esc(previewIssue)}</p>` : "") +
    (!compatible ? `<p class="ds-error" role="alert">Mettez à jour l'assistant local pour choisir une version par skill.</p>` : "") +
    (!confirming && pending.length ? `<h3 class="skills-sync-section-title">Choisissez la version à utiliser</h3><ul class="skills-sync-list">${pending.map(skillRowHtml).join("")}</ul>` : "") +
    confirmation +
    (operationNote ? `<p class="skills-sync-help" role="status">${esc(operationNote)}</p>` : "") +
    `<details class="skills-sync-technical"><summary>Détails de synchronisation</summary>` +
    `<p>Dernière vérification : ${esc(formatDate(status?.last_check))}<br>Dernière synchronisation réussie : ${esc(formatDate(status?.last_successful_sync))}</p>` +
    (status?.added?.length ? `<h3>Ajoutés</h3>${nameList(status.added)}` : "") +
    (status?.updated?.length ? `<h3>Mis à jour</h3>${nameList(status.updated)}` : "") +
    (status ? `<button class="ds-btn ds-btn--ghost" type="button" data-skills-action="toggle"${busy ? " disabled" : ""}>${status.auto_sync_enabled ? "Désactiver" : "Activer"} la synchronisation automatique</button>` : "") +
    `<button class="ds-btn ds-btn--ghost" type="button" data-skills-action="refresh"${busy || previewLoading ? " disabled" : ""}>Vérifier de nouveau</button></details></div>` +
    `<footer class="skills-sync-footer"><span class="skills-sync-progress" aria-live="polite">${count ? `${count} choix prêt${count > 1 ? "s" : ""} · ${pending.length - count} en attente` : "Les skills sans choix restent en attente."}</span>` +
    `<div class="skills-sync-actions">` +
    (confirming ? `<button class="ds-btn" type="button" data-skills-action="back"${busy ? " disabled" : ""}>Revenir aux choix</button>` : `<button class="ds-btn" type="button" data-ds-close>${pending.length ? "Plus tard" : "Fermer"}</button>`) +
    (pending.length && compatible ? `<button class="ds-btn ds-btn--${confirming && replacements.length ? "danger" : "primary"}" type="button" data-skills-action="${confirming ? "confirm" : "apply"}"${busy || count === 0 || previewLoading ? " disabled" : ""}>${busy ? "Application…" : confirming ? replacements.length ? "Confirmer le remplacement" : "Confirmer les choix" : `Appliquer ${count || "les"} choix`}</button>` : "") +
    (!pending.length && previewIssue ? `<button class="ds-btn ds-btn--primary" type="button" data-skills-action="refresh"${busy || previewLoading ? " disabled" : ""}>Réessayer</button>` : "") +
    `</div></footer>`;
}

function notifyIfChanged(status: SkillsSyncStatus): void {
  if (!document.getElementById(DIALOG_ID)?.hidden) return;
  if (status.state === "in_progress" || status.state === "up_to_date" || status.state === "disabled") return;
  const key = `${status.state}|${status.last_check}`;
  try {
    if (localStorage.getItem(NOTIFIED_KEY) === key) return;
    localStorage.setItem(NOTIFIED_KEY, key);
  } catch {
    // Best effort: a missing storage only means the toast may repeat.
  }
  if (status.state === "updated") {
    const count = (status.added ?? []).length + (status.updated ?? []).length;
    dsNotify(`Skills synchronisés : ${count} ajouté(s) ou mis à jour.`, "success");
  } else if (status.state === "conflicts") {
    dsNotify(`Skills : ${(status.conflicts ?? []).length} conflit(s) à résoudre.`, "warning");
  } else {
    dsNotify("Skills non synchronisés (hors ligne, non connecté ou erreur).", "warning");
  }
  document.getElementById("ds-toast-region")?.lastElementChild?.setAttribute("data-skills-notice", "");
}

function openDetail(platform: Platform, trigger: HTMLElement | null): void {
  if (busy) return;
  document.querySelectorAll("[data-skills-notice]").forEach((notice) => notice.remove());
  choices.clear();
  preview = null;
  confirming = false;
  operationNote = "";
  previewIssue = "";
  previewLoading = true;
  renderDetail(platform);
  openDsDialog(document, DIALOG_ID, trigger);
  void loadPreview(platform);
}

function renderDetail(platform: Platform, focusAction?: string): void {
  const body = document.getElementById(`${DIALOG_ID}-body`);
  if (body === null) return;
  body.innerHTML = skillsDetailHtml(current, unavailable);
  bindActions(platform);
  if (focusAction && !document.getElementById(DIALOG_ID)?.hidden) {
    body.querySelector<HTMLElement>(`[data-skills-action="${focusAction}"]`)?.focus();
  }
}

async function loadPreview(platform: Platform): Promise<void> {
  const generation = ++previewGeneration;
  previewLoading = true;
  previewIssue = "";
  const outcome = await previewSkills(platform).catch(() => null);
  if (generation !== previewGeneration) return;
  previewLoading = false;
  if (outcome?.ok) {
    const previous = new Map((preview?.skills ?? []).map((skill) => [skill.stable_key, skill.preview_hash]));
    preview = outcome.value;
    for (const key of choices.keys()) {
      const skill = pendingSkills(preview).find((entry) => entry.stable_key === key);
      if (!skill || previous.get(key) !== skill.preview_hash) choices.delete(key);
    }
  } else {
    preview = null;
    choices.clear();
    previewIssue = outcome ? harnessErrorMessage(outcome.error) : "Impossible de charger les versions. Vérifiez la connexion puis réessayez.";
  }
  confirming = false;
  renderDetail(platform);
}

function paint(): void {
  const existing = document.getElementById("skills-sync");
  const holder = document.createElement("template");
  holder.innerHTML = skillsIndicatorHtml(current, unavailable);
  const next = holder.content.firstElementChild;
  if (existing === null || next === null) return;
  existing.innerHTML = next.innerHTML;
  existing.dataset["state"] = (next as HTMLElement).dataset["state"];
  existing.className = next.className;
  existing.title = (next as HTMLElement).title;
}

function bindActions(platform: Platform): void {
  const root = document.getElementById(`${DIALOG_ID}-body`);
  if (root === null) return;
  root.querySelectorAll('[data-skills-action="refresh"]').forEach((button) => button.addEventListener("click", () => {
    if (busy || previewLoading) return;
    confirming = false;
    previewLoading = true;
    renderDetail(platform);
    void refresh(platform, false).then(() => loadPreview(platform));
  }));
  root.querySelectorAll<HTMLSelectElement>("[data-skills-choice]").forEach((select) => select.addEventListener("change", () => {
    const key = select.dataset["skillsChoice"];
    if (!key) return;
    if (select.value === "local" || select.value === "library") choices.set(key, select.value);
    else choices.delete(key);
    const count = choices.size;
    const apply = root.querySelector<HTMLButtonElement>('[data-skills-action="apply"]');
    if (apply) { apply.disabled = count === 0; apply.textContent = `Appliquer ${count || "les"} choix`; }
    const progress = root.querySelector<HTMLElement>(".skills-sync-progress");
    if (progress) progress.textContent = `${count} choix prêt${count > 1 ? "s" : ""} · ${pendingSkills(preview).length - count} en attente`;
  }));
  root.querySelector('[data-skills-action="apply"]')?.addEventListener("click", () => {
    if (busy || choices.size === 0) return;
    confirming = true;
    renderDetail(platform, "confirm");
  });
  root.querySelector('[data-skills-action="back"]')?.addEventListener("click", () => {
    if (busy) return;
    confirming = false;
    renderDetail(platform, "apply");
  });
  root.querySelector('[data-skills-action="confirm"]')?.addEventListener("click", () => {
    if (busy) return;
    const selection: SkillResolution[] = pendingSkills(preview).flatMap((skill) => {
      const choice = choices.get(skill.stable_key);
      return choice && skill.preview_hash ? [{ stable_key: skill.stable_key, choice, preview_hash: skill.preview_hash }] : [];
    });
    if (!confirming || selection.length === 0) return;
    busy = true;
    renderDetail(platform);
    document.getElementById(`${DIALOG_ID}-title`)?.focus();
    void (async () => {
      try {
        const outcome = await applySkills(platform, selection);
        if (!outcome.ok) operationNote = harnessErrorMessage(outcome.error);
        else {
          const kept = selection.filter((item) => item.choice === "local").length;
          operationNote = kept ? "Choix appliqués. Les versions locales conservées restent personnalisées et seront signalées aux prochaines vérifications." : "Choix appliqués. Les autres skills restent en attente.";
          if (document.getElementById(DIALOG_ID)?.hidden) {
            dsNotify("Vos choix de synchronisation ont été appliqués.", "success");
          }
        }
      } catch {
        operationNote = "Impossible d'appliquer les choix. Vérifiez la connexion puis réessayez.";
      } finally {
        busy = false;
        choices.clear();
        await refresh(platform, false);
        await loadPreview(platform);
        if (!document.getElementById(DIALOG_ID)?.hidden) document.getElementById(`${DIALOG_ID}-title`)?.focus();
      }
    })();
  });
  root.querySelector('[data-skills-action="toggle"]')?.addEventListener("click", () => {
    if (busy) return;
    busy = true;
    renderDetail(platform);
    document.getElementById(`${DIALOG_ID}-title`)?.focus();
    void (async () => {
      try {
        const outcome = await configureSkillsSync(platform, current?.auto_sync_enabled !== true);
        if (!outcome.ok) dsNotify(harnessErrorMessage(outcome.error), "warning");
      } catch { dsNotify("Impossible de modifier la synchronisation automatique.", "warning"); }
      finally { busy = false; await refresh(platform, false); renderDetail(platform); }
    })();
  });
}

async function refresh(platform: Platform, notify = true): Promise<void> {
  const outcome = await getSkillsSyncStatus(platform).catch(() => null);
  unavailable = outcome === null || !outcome.ok;
  if (outcome?.ok) {
    current = outcome.value;
    if (notify) notifyIfChanged(outcome.value);
  }
  paint();
  if (timer !== null) clearTimeout(timer);
  timer = setTimeout(() => void refresh(platform), current?.state === "in_progress" ? RUNNING_POLL_MS : IDLE_POLL_MS);
}

/** Monte l'indicateur sous la pastille de connexion (Desktop uniquement). */
export function mountSkillsSync(platform: Platform): void {
  if (platform.mode !== "desktop") return;
  const anchor = document.getElementById("connection-status");
  if (anchor === null || document.getElementById("skills-sync") !== null) return;
  const holder = document.createElement("template");
  holder.innerHTML = skillsIndicatorHtml(current, unavailable);
  anchor.after(...Array.from(holder.content.childNodes));
  document.getElementById("skills-sync")?.addEventListener("click", (event) =>
    openDetail(platform, event.currentTarget as HTMLElement),
  );
  if (document.getElementById(DIALOG_ID) === null) {
    const dialog = document.createElement("template");
    dialog.innerHTML = dsModalHtml({
      id: DIALOG_ID,
      title: "Synchronisation des skills",
      body: `<div id="${DIALOG_ID}-body"></div>`,
      actions: [],
    });
    document.body.append(...Array.from(dialog.content.childNodes));
    document.querySelector(`#${DIALOG_ID} .ds-modal > .ds-dialog-actions`)?.remove();
  }
  void refresh(platform);
}

/** Test seam: forget the module state. */
export function resetSkillsSyncForTests(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
  current = null;
  unavailable = false;
  busy = false;
  preview = null;
  previewLoading = false;
  previewIssue = "";
  operationNote = "";
  confirming = false;
  previewGeneration += 1;
  choices.clear();
}
