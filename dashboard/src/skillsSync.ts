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
  getSkillsSyncStatus,
  previewSkills,
  SYNC_STATE_LABELS,
  SYNC_STATE_LEVELS,
  SYNC_STATE_MESSAGES,
  type SkillsSyncStatus,
} from "./skillsApi";

const NOTIFIED_KEY = "studio.skills-sync.notified";
const RUNNING_POLL_MS = 3000;
const IDLE_POLL_MS = 60000;
const DIALOG_ID = "skills-sync-dialog";

let timer: ReturnType<typeof setTimeout> | null = null;
let current: SkillsSyncStatus | null = null;
let unavailable = false;
let busy = false;

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
    `aria-haspopup="dialog" aria-controls="${DIALOG_ID}" title="${esc(label)}">` +
    `<span class="app-connection-dot" aria-hidden="true"></span>` +
    `<span class="app-connection-label">${esc(label + suffix)}</span></button>`
  );
}

export function skillsDetailHtml(status: SkillsSyncStatus | null, failed: boolean): string {
  if (status === null || failed) {
    return (
      `<p>${esc(SYNC_STATE_MESSAGES.not_synced)}</p>` +
      `<div class="ds-dialog-actions"><button class="ds-btn" type="button" data-skills-action="refresh">Réessayer</button></div>`
    );
  }
  const added = nameList(status.added);
  const updated = nameList(status.updated);
  const conflicts = nameList(status.conflicts);
  return (
    `<p>${esc(SYNC_STATE_MESSAGES[status.state])}</p>` +
    `<p>Dernière vérification : ${esc(formatDate(status.last_check))}<br>` +
    `Dernière synchro réussie : ${esc(formatDate(status.last_successful_sync))}</p>` +
    (added ? `<h3>Ajoutés</h3>${added}` : "") +
    (updated ? `<h3>Mis à jour</h3>${updated}` : "") +
    (conflicts ? `<h3>Conflits</h3>${conflicts}` : "") +
    `<pre class="skills-sync-diff" data-testid="skills-sync-diff" hidden></pre>` +
    `<div class="ds-dialog-actions">` +
    `<button class="ds-btn" type="button" data-skills-action="diff">Voir les différences</button>` +
    `<button class="ds-btn ds-btn--primary" type="button" data-skills-action="retry"${status.state === "in_progress" ? " disabled" : ""}>Réessayer</button>` +
    `</div>`
  );
}

function notifyIfChanged(status: SkillsSyncStatus): void {
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
}

function openDetail(platform: Platform, trigger: HTMLElement | null): void {
  const body = document.getElementById(`${DIALOG_ID}-body`);
  if (body !== null) body.innerHTML = skillsDetailHtml(current, unavailable);
  bindActions(platform);
  openDsDialog(document, DIALOG_ID, trigger);
}

function paint(platform: Platform): void {
  const existing = document.getElementById("skills-sync");
  const holder = document.createElement("template");
  holder.innerHTML = skillsIndicatorHtml(current, unavailable);
  const next = holder.content.firstElementChild;
  if (existing === null || next === null) return;
  existing.replaceWith(next);
  next.addEventListener("click", () => openDetail(platform, next as HTMLElement));
  const body = document.getElementById(`${DIALOG_ID}-body`);
  if (body !== null && !document.getElementById(DIALOG_ID)?.hasAttribute("hidden")) {
    body.innerHTML = skillsDetailHtml(current, unavailable);
    bindActions(platform);
  }
}

function bindActions(platform: Platform): void {
  const root = document.getElementById(`${DIALOG_ID}-body`);
  if (root === null) return;
  root.querySelector('[data-skills-action="refresh"]')?.addEventListener("click", () => void refresh(platform));
  root.querySelector('[data-skills-action="diff"]')?.addEventListener("click", () => {
    void previewSkills(platform).then((outcome) => {
      const box = root.querySelector<HTMLElement>(".skills-sync-diff");
      if (box === null) return;
      box.hidden = false;
      box.textContent = outcome.ok ? outcome.value.diff || "Aucune différence." : harnessErrorMessage(outcome.error);
    });
  });
  root.querySelector('[data-skills-action="retry"]')?.addEventListener("click", () => {
    if (busy) return;
    busy = true;
    void applySkills(platform).then(async (outcome) => {
      busy = false;
      if (!outcome.ok) dsNotify(harnessErrorMessage(outcome.error), "warning");
      await refresh(platform);
    });
  });
}

async function refresh(platform: Platform): Promise<void> {
  const outcome = await getSkillsSyncStatus(platform).catch(() => null);
  unavailable = outcome === null || !outcome.ok;
  if (outcome?.ok) {
    current = outcome.value;
    notifyIfChanged(outcome.value);
  }
  paint(platform);
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
      actions: [{ label: "Fermer" }],
    });
    document.body.append(...Array.from(dialog.content.childNodes));
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
}
