/**
 * MC P05 — panneau « Lancer un lot » d'une roadmap active (DEC-0216, DEC-0218).
 *
 * Le frontend ne recalcule jamais l'éligibilité : l'ordre des tâches lançables
 * et les raisons d'exclusion sont ceux du dry-run serveur, affichés tels quels.
 * Aucun envoi n'a lieu sans une confirmation explicite, un seul appel est en
 * vol à la fois, et la clé de rejeu est conservée en storage par corps de
 * requête : un rechargement pendant l'envoi propose de rejouer la MÊME clé,
 * jamais un second lot.
 */
import { dsBadge, dsEmptyState, dsNotify, dsSectionHeader, dsSkeleton } from "../ds/ds";
import { describeError, esc, fmtTime } from "../ui";
import type { StudioClient } from "../api";
import type {
  AdmissionBatchItem,
  AdmissionBatchRequest,
  AdmissionCandidate,
  AdmissionDryRun,
  AdmissionExclusion,
  AdmissionExclusionReason,
  AdmissionRefusal,
} from "../admissionApi";
import {
  admissionRefusal,
  admitRoadmapBatch,
  clearPendingAdmission,
  getAdmissionDryRun,
  pendingAdmissionBody,
  pendingAdmissionKey,
} from "../admissionApi";

export interface AdmissionPanelContext {
  client: StudioClient;
  roadmapId: string;
  /** Injection de test : sessionStorage par défaut en navigateur. */
  storage?: Storage;
}

/**
 * Plafond du lot (ADMISSION_BATCH_MAX_ITEMS côté contrat). Ce n'est pas un
 * calcul d'éligibilité : c'est la limite du serveur, affichée pour éviter
 * d'envoyer un corps qu'il refuserait d'office.
 */
const MAX_BATCH_ITEMS = 50;

const EXCLUSION_REASON_FR: Record<AdmissionExclusionReason, string> = {
  roadmap_not_active: "la roadmap n'est plus active",
  dependency_pending: "une dépendance est en attente",
  task_data_missing: "des données de tâche manquent",
  task_completed: "la tâche est déjà terminée",
  task_blocked: "la tâche est bloquée",
  review_pending: "une relecture est en attente",
  launch_active: "un lancement est déjà actif",
  task_claimed_elsewhere: "la tâche est réservée ailleurs",
  claims_held_elsewhere: "des ressources sont réservées ailleurs",
  no_eligible_machine: "aucun poste éligible",
};

const REFUSAL_REASON_FR: Record<string, string> = {
  duplicate_item: "la tâche apparaît deux fois",
  not_launchable: "la tâche n'est plus lançable",
  machine_not_eligible: "le poste choisi n'est pas éligible",
  budget_refused: "le budget du projet refuse ce lancement",
};

export function exclusionReasonLabel(reason: AdmissionExclusionReason): string {
  return EXCLUSION_REASON_FR[reason] ?? reason;
}

export function refusalReasonLabel(reason: string): string {
  return REFUSAL_REASON_FR[reason] ?? reason;
}

/** Empreinte abrégée : on montre une identité, jamais un secret. */
function shortDigest(digest: string): string {
  return digest.slice(0, 12);
}

/** Repli sans navigateur (tests, rendu serveur) : la clé ne survit qu'à la page. */
function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length(): number {
      return map.size;
    },
    clear(): void {
      map.clear();
    },
    getItem(key: string): string | null {
      return map.get(key) ?? null;
    },
    key(index: number): string | null {
      return [...map.keys()][index] ?? null;
    },
    removeItem(key: string): void {
      map.delete(key);
    },
    setItem(key: string, value: string): void {
      map.set(key, String(value));
    },
  } as Storage;
}

function resolveStorage(injected: Storage | undefined): Storage {
  if (injected !== undefined) return injected;
  try {
    return sessionStorage;
  } catch {
    return memoryStorage();
  }
}

function ageLabel(iso: string): string {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "âge inconnu";
  const seconds = Math.max(0, Math.round((Date.now() - at) / 1000));
  if (seconds < 60) return `évalué il y a ${seconds} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `évalué il y a ${minutes} min`;
  return `évalué le ${fmtTime(iso)}`;
}

function machineDisplayName(plan: AdmissionDryRun, machineId: string): string {
  return (plan.machines ?? []).find((machine) => machine.machine_id === machineId)?.display_name ?? machineId;
}

function configuredHarnessIds(plan: AdmissionDryRun): string[] {
  const ids: string[] = [];
  for (const machine of plan.machines ?? []) {
    for (const harness of machine.harnesses ?? []) {
      if (harness.configured && !ids.includes(harness.harness_id)) ids.push(harness.harness_id);
    }
  }
  return ids;
}

interface Pick {
  checked: boolean;
  machineId: string;
}

interface PanelState {
  plan: AdmissionDryRun | null;
  harnessId: string;
  picks: Map<string, Pick>;
  loading: boolean;
  error: string;
  stale: boolean;
  refusals: AdmissionRefusal[];
  launches: number | null;
  confirmation: boolean;
  confirmBody: AdmissionBatchRequest | null;
  submitting: boolean;
  retryBody: AdmissionBatchRequest | null;
  resumeBody: AdmissionBatchRequest | null;
}

function defaultPicks(plan: AdmissionDryRun): Map<string, Pick> {
  const picks = new Map<string, Pick>();
  for (const candidate of plan.launchable ?? []) {
    picks.set(candidate.task_id, { checked: candidate.machine_ids.length > 0, machineId: candidate.machine_ids[0] ?? "" });
  }
  return picks;
}

function checkedCount(state: PanelState): number {
  let count = 0;
  for (const pick of state.picks.values()) if (pick.checked) count += 1;
  return count;
}

function buildItems(plan: AdmissionDryRun, state: PanelState): AdmissionBatchItem[] {
  const items: AdmissionBatchItem[] = [];
  for (const candidate of plan.launchable ?? []) {
    const pick = state.picks.get(candidate.task_id);
    if (pick?.checked === true) items.push({ task_id: candidate.task_id, machine_id: pick.machineId });
  }
  return items;
}

function buildBody(state: PanelState): AdmissionBatchRequest | null {
  const plan = state.plan;
  if (plan === null || state.harnessId === "") return null;
  const items = buildItems(plan, state);
  if (items.length === 0 || items.length > MAX_BATCH_ITEMS || items.some((item) => item.machine_id === "")) return null;
  return { plan_digest: plan.plan_digest, harness_id: state.harnessId, items, expires_in_seconds: 900 };
}

function harnessOptionsHtml(plan: AdmissionDryRun, selected: string): string {
  const ids = configuredHarnessIds(plan);
  if (selected !== "" && !ids.includes(selected)) ids.push(selected);
  const options = ids
    .map((id) => `<option value="${esc(id)}"${id === selected ? " selected" : ""}>${esc(id)}</option>`)
    .join("");
  return `<option value="">Choisir un harnais</option>${options}`;
}

/** Un candidat sans poste reste cochable visuellement mais ne produit aucun poste. */
function candidateItemHtml(plan: AdmissionDryRun, state: PanelState, candidate: AdmissionCandidate): string {
  const pick = state.picks.get(candidate.task_id) ?? { checked: candidate.machine_ids.length > 0, machineId: candidate.machine_ids[0] ?? "" };
  const options = candidate.machine_ids
    .map((id) => {
      const selected = id === pick.machineId ? " selected" : "";
      return `<option value="${esc(id)}"${selected}>${esc(machineDisplayName(plan, id))}</option>`;
    })
    .join("");
  const machine =
    candidate.machine_ids.length === 0
      ? `<span class="ds-list-sub">Aucun poste disponible</span>`
      : `<select data-admission-machine aria-label="Poste pour ${esc(candidate.title)}">${options}</select>`;
  return `<li data-task-id="${esc(candidate.task_id)}">` +
    `<label><input type="checkbox" data-admission-pick${pick.checked ? " checked" : ""}${pick.machineId === "" ? " disabled" : ""}> <strong>${esc(candidate.title)}</strong> <code class="mono">${esc(candidate.step_key)}</code></label>` +
    machine + `</li>`;
}

function excludedItemHtml(exclusion: AdmissionExclusion): string {
  const title = exclusion.title != null && exclusion.title.trim() !== "" ? exclusion.title : exclusion.step_key;
  const reasons = (exclusion.reasons ?? [])
    .map((reason) => `<li data-admission-reason="${esc(reason)}">${dsBadge(exclusionReasonLabel(reason))}</li>`)
    .join("");
  const waiting = (exclusion.waiting_on ?? []).map((key) => `<code class="mono">${esc(key)}</code>`).join(", ");
  const blocking = waiting === "" ? "" : `<p class="ds-list-sub">En attente de ${waiting}</p>`;
  return `<li data-task-id="${esc(exclusion.task_id)}"><div><strong>${esc(title)}</strong> <code class="mono">${esc(exclusion.step_key)}</code></div>` +
    `<ul class="admission-reasons">${reasons}</ul>${blocking}</li>`;
}

function refusalItemHtml(refusal: AdmissionRefusal): string {
  const reasons = (refusal.exclusion_reasons ?? []).map((reason) => exclusionReasonLabel(reason)).join(", ");
  const suffix = reasons === "" ? "" : ` (${esc(reasons)})`;
  return `<li data-admission-refusal="${esc(refusal.reason)}">${esc(refusalReasonLabel(refusal.reason))}${suffix}</li>`;
}

function confirmationHtml(state: PanelState, uid: string): string {
  const body = state.confirmBody;
  const plan = state.plan;
  if (body === null || plan === null) return "";
  const rows = body.items
    .map((item) => {
      const candidate = (plan.launchable ?? []).find((entry) => entry.task_id === item.task_id);
      const title = candidate?.title ?? item.task_id;
      return `<li>${esc(title)} ${dsBadge(machineDisplayName(plan, item.machine_id))}</li>`;
    })
    .join("");
  const count = body.items.length;
  const submit = state.submitting
    ? `<button class="ds-btn ds-btn--primary" type="button" data-admission-submit disabled>Envoi…</button>`
    : `<button class="ds-btn ds-btn--primary" type="button" data-admission-submit>Lancer ${count} tâche${count > 1 ? "s" : ""}</button>`;
  return `<div class="ds-overlay" data-admission-confirmation role="alertdialog" aria-modal="true" aria-labelledby="admission-confirmation-${uid}">` +
    `<div class="ds-modal"><h3 id="admission-confirmation-${uid}">Confirmer le lancement</h3>` +
    `<p>${count} tâche${count > 1 ? "s" : ""} sur le harnais <code class="mono">${esc(body.harness_id)}</code> · empreinte du plan <code class="mono">${esc(shortDigest(body.plan_digest))}</code></p>` +
    `<ul class="admission-confirmation-tasks">${rows}</ul>` +
    `<div class="ds-dialog-actions"><button class="ds-btn" type="button" data-admission-cancel>Annuler</button>${submit}</div>` +
    `</div></div>`;
}

function planBodyHtml(state: PanelState): string {
  if (state.loading) return dsSkeleton(3);
  const plan = state.plan;
  if (plan === null) {
    return dsEmptyState(
      "Aucune prévisualisation",
      "Prévisualisez les tâches disponibles : les tâches lançables, leur ordre et les raisons d'exclusion viennent du serveur.",
    );
  }
  const stale = state.stale
    ? `<div class="ds-notice ds-notice--warning" role="status" data-admission-stale><strong>Le plan a changé depuis la prévisualisation.</strong> Vérifiez les tâches ci-dessous, puis confirmez à nouveau.</div>`
    : "";
  const retry = state.retryBody === null ? "" : ` <button class="ds-btn" type="button" data-admission-retry>Réessayer</button>`;
  const error = state.error === ""
    ? ""
    : `<div class="ds-notice ds-notice--danger" role="alert" data-admission-error><strong>Lancement impossible.</strong> ${esc(state.error)}${retry}</div>`;
  const result = state.launches === null
    ? ""
    : `<div class="ds-notice ds-notice--success" role="status" data-admission-result><strong>${state.launches} lancement${state.launches > 1 ? "s" : ""} créé${state.launches > 1 ? "s" : ""}.</strong></div>`;
  const refusals = state.refusals.length === 0
    ? ""
    : `<div class="ds-notice ds-notice--danger" role="alert"><strong>Lot refusé, rien n'a été créé.</strong><ul data-admission-refusals>${state.refusals.map(refusalItemHtml).join("")}</ul></div>`;

  const launchable = plan.launchable ?? [];
  const launchableHtml = launchable.length === 0
    ? `<p class="ds-list-sub">Aucune tâche lançable pour ce harnais.</p>`
    : `<ul class="admission-launchable-list" data-admission-launchable>${launchable.map((candidate) => candidateItemHtml(plan, state, candidate)).join("")}</ul>`;

  const excluded = plan.excluded ?? [];
  const excludedHtml = excluded.length === 0
    ? ""
    : `<details class="admission-excluded" open><summary>Tâches exclues (${excluded.length})</summary><ul data-admission-excluded>${excluded.map(excludedItemHtml).join("")}</ul></details>`;

  const checked = checkedCount(state);
  const tooMany = checked > MAX_BATCH_ITEMS;
  const canConfirm = checked > 0 && checked <= MAX_BATCH_ITEMS && state.harnessId !== "";
  const overflow = tooMany
    ? `<div class="ds-notice ds-notice--warning" role="status" data-admission-overflow><strong>Lot trop grand.</strong> Le serveur accepte ${MAX_BATCH_ITEMS} tâches par lot : décochez-en ${checked - MAX_BATCH_ITEMS} pour continuer.</div>`
    : "";
  const confirm = `<div class="admission-actions"><button class="ds-btn ds-btn--primary" type="button" data-admission-confirm${canConfirm ? "" : " disabled"}>Lancer ${checked} tâche${checked > 1 ? "s" : ""}</button></div>`;

  return stale + error + result + refusals + overflow +
    `<p class="ds-list-sub" data-admission-digest>Empreinte du plan <code class="mono">${esc(shortDigest(plan.plan_digest))}</code> · ${esc(ageLabel(plan.evaluated_at))}</p>` +
    launchableHtml + excludedHtml + confirm;
}

function resumeNoticeHtml(state: PanelState): string {
  if (state.resumeBody === null) return "";
  return `<div class="ds-notice ds-notice--info" role="status" data-admission-resume><strong>Lancement interrompu.</strong> Un lot attendait la réponse du serveur. ` +
    `<button class="ds-btn" type="button" data-admission-resume-send>Reprendre l'envoi</button></div>`;
}

let panelCount = 0;

export async function renderAdmissionPanelInto(root: HTMLElement, ctx: AdmissionPanelContext): Promise<void> {
  const { client, roadmapId } = ctx;
  const store = resolveStorage(ctx.storage);
  const uid = `admission-${(panelCount += 1)}`;
  const state: PanelState = {
    plan: null,
    harnessId: "",
    picks: new Map<string, Pick>(),
    loading: false,
    error: "",
    stale: false,
    refusals: [],
    launches: null,
    confirmation: false,
    confirmBody: null,
    submitting: false,
    retryBody: null,
    resumeBody: null,
  };
  state.resumeBody = pendingAdmissionBody(roadmapId, store);

  function paint(): void {
    root.innerHTML = panelHtml(state);
    bind();
  }

  function bind(): void {
    root.querySelector("[data-admission-preview]")?.addEventListener("click", onPreview);
    const harnessSelect = root.querySelector<HTMLSelectElement>("[data-admission-harness]");
    if (harnessSelect !== null) {
      harnessSelect.value = state.harnessId;
      harnessSelect.addEventListener("change", onHarness);
    }
    root.querySelector("[data-admission-confirm]")?.addEventListener("click", onConfirm);
    root.querySelector("[data-admission-submit]")?.addEventListener("click", onSubmit);
    root.querySelector("[data-admission-cancel]")?.addEventListener("click", onCancel);
    root.querySelector("[data-admission-retry]")?.addEventListener("click", onRetry);
    root.querySelector("[data-admission-resume-send]")?.addEventListener("click", onResume);
    root.querySelectorAll<HTMLInputElement>("[data-admission-pick]").forEach((box) => box.addEventListener("change", onPick));
    root.querySelectorAll<HTMLSelectElement>("[data-admission-machine]").forEach((select) => select.addEventListener("change", onMachine));
    root.querySelector<HTMLElement>("[data-admission-confirmation]")?.addEventListener("keydown", (event) => {
      if (event.key === "Escape") onCancel();
    });
  }

  async function refresh(harness: string | null): Promise<void> {
    state.loading = true;
    state.error = "";
    state.retryBody = null;
    state.confirmation = false;
    state.confirmBody = null;
    paint();
    try {
      const plan = await getAdmissionDryRun(client, roadmapId, harness);
      state.plan = plan;
      state.stale = false;
      state.refusals = [];
      state.picks = defaultPicks(plan);
      if (harness !== null) state.harnessId = harness;
    } catch (error) {
      state.error = describeError(error);
    } finally {
      state.loading = false;
      paint();
    }
  }

  async function submit(body: AdmissionBatchRequest | null): Promise<void> {
    if (body === null || state.submitting) return;
    state.submitting = true;
    state.error = "";
    paint();
    const key = pendingAdmissionKey(roadmapId, body, store);
    try {
      const result = await admitRoadmapBatch(client, roadmapId, body, key);
      clearPendingAdmission(roadmapId, store);
      state.submitting = false;
      state.confirmation = false;
      state.confirmBody = null;
      state.retryBody = null;
      state.resumeBody = null;
      state.stale = false;
      state.refusals = [];
      state.launches = result.launches?.length ?? 0;
      dsNotify(`${state.launches} lancement${state.launches > 1 ? "s" : ""} demandé${state.launches > 1 ? "s" : ""}.`, "success");
      await refresh(state.harnessId === "" ? null : state.harnessId);
    } catch (error) {
      state.submitting = false;
      const refusal = admissionRefusal(error);
      if (refusal?.error_code === "admission_plan_changed") {
        clearPendingAdmission(roadmapId, store);
        state.retryBody = null;
        state.resumeBody = null;
        state.confirmation = false;
        state.confirmBody = null;
        if (refusal.plan !== undefined && refusal.plan !== null) {
          state.plan = refusal.plan;
          state.picks = defaultPicks(refusal.plan);
        }
        state.stale = true;
        paint();
        return;
      }
      if (refusal?.error_code === "admission_refused") {
        clearPendingAdmission(roadmapId, store);
        state.retryBody = null;
        state.resumeBody = null;
        state.confirmation = false;
        state.confirmBody = null;
        state.refusals = refusal.refusals ?? [];
        paint();
        return;
      }
      state.error = describeError(error);
      state.retryBody = body;
      paint();
    }
  }

  function onPreview(): void {
    void refresh(state.harnessId === "" ? null : state.harnessId);
  }

  function onHarness(event: Event): void {
    const value = (event.currentTarget as HTMLSelectElement).value;
    state.harnessId = value;
    void refresh(value === "" ? null : value);
  }

  function onConfirm(): void {
    const body = buildBody(state);
    if (body === null) return;
    state.confirmBody = body;
    state.confirmation = true;
    paint();
    const dialog = root.querySelector<HTMLElement>("[data-admission-confirmation]");
    const target = dialog?.querySelector<HTMLElement>("[data-admission-submit]") ?? dialog;
    target?.focus();
  }

  function onSubmit(): void {
    void submit(state.confirmBody);
  }

  function onCancel(): void {
    state.confirmation = false;
    state.confirmBody = null;
    paint();
  }

  function onRetry(): void {
    void submit(state.retryBody);
  }

  function onResume(): void {
    void submit(state.resumeBody);
  }

  function onPick(event: Event): void {
    const box = event.currentTarget as HTMLInputElement;
    const taskId = box.closest<HTMLElement>("[data-task-id]")?.dataset["taskId"];
    if (taskId === undefined) return;
    const pick = state.picks.get(taskId);
    if (pick !== undefined) pick.checked = box.checked;
    state.confirmation = false;
    state.confirmBody = null;
    paint();
  }

  function onMachine(event: Event): void {
    const select = event.currentTarget as HTMLSelectElement;
    const taskId = select.closest<HTMLElement>("[data-task-id]")?.dataset["taskId"];
    if (taskId === undefined) return;
    const pick = state.picks.get(taskId);
    if (pick !== undefined) pick.machineId = select.value;
    if (!state.confirmation) return;
    state.confirmation = false;
    state.confirmBody = null;
    paint();
  }

  function panelHtml(current: PanelState): string {
    const harnessOptions = current.plan === null
      ? `<option value="">Choisir un harnais</option>`
      : harnessOptionsHtml(current.plan, current.harnessId);
    return `<section class="admission-panel" data-admission-panel aria-label="Lancer un lot">` +
      dsSectionHeader("Lancer un lot") +
      `<p class="ds-list-sub">Le serveur calcule seul l'éligibilité et l'ordre ; ce panneau affiche son dry-run et lui renvoie son empreinte après confirmation.</p>` +
      resumeNoticeHtml(current) +
      `<div class="admission-toolbar"><label>Harnais <select data-admission-harness>${harnessOptions}</select></label>` +
      `<button class="ds-btn" type="button" data-admission-preview>Prévisualiser les tâches disponibles</button></div>` +
      planBodyHtml(current) +
      (current.confirmation && current.confirmBody !== null ? confirmationHtml(current, uid) : "") +
      `</section>`;
  }

  // Le dry-run est une lecture seule : l'aperçu se charge à l'ouverture,
  // seul le clic sur « Envoyer » de la confirmation écrit.
  await refresh(null);
}
