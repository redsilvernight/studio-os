import {
  dsBadge,
  dsEmptyState,
  dsField,
  dsNotify,
  dsProgress,
  dsSectionHeader,
  dsSkeleton,
} from "../ds/ds";
import {
  parseRoadmapDocument,
  roadmapToDocument,
  serializeRoadmapDocument,
} from "../roadmapFormat";
import type {
  Roadmap,
  RoadmapDataSource,
  RoadmapDocument,
  RoadmapPhase,
  RoadmapStatus,
  RoadmapStep,
} from "../roadmapTypes";
import { describeError, esc } from "../ui";

export type RoadmapMode = "plan" | "execution";

export interface RoadmapViewContext {
  dataSource: RoadmapDataSource;
  projectId: string;
  projectName: string;
}

const STATUS_LABELS: Record<RoadmapStatus, string> = {
  draft: "Brouillon",
  proposed: "À examiner",
  active: "Active",
  completed: "Terminée",
  archived: "Archivée",
};

const STEP_LABELS: Record<string, string> = {
  not_started: "À venir",
  in_progress: "En cours",
  blocked: "Bloquée",
  done: "Terminée",
  skipped: "Ignorée",
};

function statusTone(status: RoadmapStatus): "neutral" | "info" | "warning" | "success" {
  if (status === "active") return "info";
  if (status === "completed") return "success";
  if (status === "proposed") return "warning";
  return "neutral";
}

function stepTone(state: string): "neutral" | "info" | "warning" | "success" {
  if (state === "done") return "success";
  if (state === "in_progress") return "info";
  if (state === "blocked") return "warning";
  return "neutral";
}

function percent(ratio: number | undefined): number {
  return Math.round(Math.max(0, Math.min(1, ratio ?? 0)) * 100);
}

function allSteps(roadmap: Roadmap): RoadmapStep[] {
  return (roadmap.phases ?? []).flatMap((phase) => phase.steps ?? []);
}

function phaseProgress(phase: RoadmapPhase): number {
  if (phase.progress?.ratio !== undefined) return percent(phase.progress.ratio);
  const steps = phase.steps ?? [];
  const counted = steps.filter((step) => step.state !== "skipped");
  if (counted.length === 0) return 0;
  return Math.round((counted.filter((step) => step.state === "done").length / counted.length) * 100);
}

function stepButtonHtml(step: RoadmapStep, selected: boolean): string {
  const state = step.state ?? "not_started";
  const current = selected ? ` aria-current="true"` : "";
  const available = step.available === true ? `<span class="roadmap-available">Disponible</span>` : "";
  return `<button class="roadmap-step${selected ? " is-selected" : ""}" type="button" data-step-key="${esc(step.key)}"${current}>` +
    `<span class="roadmap-step-main"><strong>${esc(step.title)}</strong><span class="roadmap-step-key">${esc(step.key)}</span></span>` +
    `<span class="roadmap-step-state">${available}${dsBadge(STEP_LABELS[state] ?? state, stepTone(state))}</span></button>`;
}

export function roadmapPlanHtml(roadmap: Roadmap, selectedKey: string | null): string {
  const phases = roadmap.phases ?? [];
  if (phases.length === 0) {
    return dsEmptyState("Le plan est vide", "Ajoutez une phase lorsque vous souhaitez structurer ce projet.");
  }
  return `<div class="roadmap-timeline" aria-label="Plan par phases">${phases
    .map((phase, index) => {
      const progress = phaseProgress(phase);
      const steps = phase.steps ?? [];
      return `<section class="roadmap-phase"><div class="roadmap-phase-marker" aria-hidden="true">${index + 1}</div>` +
        `<div class="roadmap-phase-body"><header><div><p class="roadmap-eyebrow">Phase ${index + 1}</p><h3>${esc(phase.title)}</h3>${phase.objective ? `<p>${esc(phase.objective)}</p>` : ""}</div>` +
        `<div class="roadmap-phase-progress">${dsProgress(progress, 100, `${progress} %`)}</div></header>` +
        (steps.length === 0
          ? `<p class="ds-list-sub">Aucune étape dans cette phase.</p>`
          : `<div class="roadmap-step-list">${steps.map((step) => stepButtonHtml(step, step.key === selectedKey)).join("")}</div>`) +
        `</div></section>`;
    })
    .join("")}</div>`;
}

function executionList(title: string, steps: RoadmapStep[], empty: string, selectedKey: string | null): string {
  const body = steps.length === 0
    ? `<p class="ds-list-sub">${esc(empty)}</p>`
    : `<div class="roadmap-execution-list">${steps.map((step) => stepButtonHtml(step, step.key === selectedKey)).join("")}</div>`;
  return `<section class="roadmap-execution-section">${dsSectionHeader(`${title} (${steps.length})`)}${body}</section>`;
}

export function roadmapExecutionHtml(roadmap: Roadmap, selectedKey: string | null): string {
  const steps = allSteps(roadmap);
  const current = steps.filter((step) => step.key === roadmap.current_step_key || step.state === "in_progress");
  const available = steps.filter((step) => step.available === true && !current.includes(step));
  const blocked = steps.filter((step) => step.state === "blocked" || (step.waiting_on?.length ?? 0) > 0);
  return `<div class="roadmap-execution">` +
    executionList("Étape actuelle", current.slice(0, 1), "Aucune étape en cours.", selectedKey) +
    executionList("Disponible maintenant", available, "Rien de plus n'est disponible pour le moment.", selectedKey) +
    executionList("En attente", blocked, "Aucune étape bloquée.", selectedKey) +
    `</div>`;
}

function taskListHtml(step: RoadmapStep): string {
  const planned = step.tasks ?? [];
  const linked = step.linked_tasks ?? [];
  if (planned.length === 0 && linked.length === 0) return `<p class="ds-list-sub">Aucune tâche liée.</p>`;
  return `<ul class="roadmap-detail-list">` +
    planned.map((task) => `<li><strong>${esc(task.title)}</strong>${task.description ? `<span>${esc(task.description)}</span>` : ""}</li>`).join("") +
    linked.map((link) => `<li><a href="#/tasks/${esc(link.task_id)}">Tâche ${esc(link.task_id.slice(0, 8))}</a><span>${esc(link.hydration_key ?? "Liée manuellement")}</span></li>`).join("") +
    `</ul>`;
}

function criteriaHtml(step: RoadmapStep): string {
  const criteria = step.acceptance_criteria ?? [];
  if (criteria.length === 0) return `<p class="ds-list-sub">Aucun critère défini.</p>`;
  const checked = new Set(step.criteria_checked ?? []);
  return `<ul class="roadmap-criteria">${criteria.map((criterion, index) => `<li class="${checked.has(index) ? "is-checked" : ""}"><span aria-hidden="true">${checked.has(index) ? "✓" : "○"}</span><span>${esc(criterion)}</span></li>`).join("")}</ul>`;
}

export function roadmapStepDetailHtml(step: RoadmapStep | null, roadmap: Roadmap): string {
  if (step === null) {
    return `<aside class="roadmap-detail">${dsEmptyState("Choisissez une étape", "Son objectif, ses tâches et ses dépendances apparaîtront ici.")}</aside>`;
  }
  const state = step.state ?? "not_started";
  const dependencies = step.depends_on ?? [];
  const waiting = step.waiting_on ?? [];
  const completedTasks = step.task_progress?.completed ?? 0;
  const totalTasks = step.task_progress?.total ?? (step.linked_tasks?.length ?? 0);
  return `<aside class="roadmap-detail" aria-label="Détail de l'étape ${esc(step.title)}">` +
    `<header><div><p class="roadmap-eyebrow">${esc(step.key)}</p><h2>${esc(step.title)}</h2></div>${dsBadge(STEP_LABELS[state] ?? state, stepTone(state))}</header>` +
    `<section><h3>Objectif</h3><p>${esc(step.objective?.trim() || "Objectif non renseigné.")}</p>${step.context ? `<p class="roadmap-context">${esc(step.context)}</p>` : ""}</section>` +
    `<section><h3>Tâches</h3>${taskListHtml(step)}${totalTasks > 0 ? dsProgress(completedTasks, totalTasks, `${completedTasks} sur ${totalTasks} terminée(s)`) : ""}</section>` +
    `<section><h3>Critères d'acceptation</h3>${criteriaHtml(step)}</section>` +
    `<section><h3>Dépendances</h3>${dependencies.length === 0 ? `<p class="ds-list-sub">Aucune dépendance.</p>` : `<p>${dependencies.map(esc).join(", ")}</p>`}` +
    (waiting.length > 0 ? `<div class="ds-notice ds-notice--warning" role="status"><strong>En attente de :</strong> ${waiting.map(esc).join(", ")}</div>` : "") + `</section>` +
    `<details class="roadmap-technical"><summary>Informations techniques</summary><dl>` +
    `<div><dt>Clé</dt><dd><code class="mono">${esc(step.key)}</code></dd></div>` +
    `<div><dt>État dérivé</dt><dd>${esc(state)}</dd></div>` +
    `<div><dt>Disponible</dt><dd>${step.available === true ? "oui" : "non"}</dd></div>` +
    `<div><dt>Roadmap</dt><dd><code class="mono">${esc(roadmap.id ?? "fixture")}</code></dd></div>` +
    `</dl></details></aside>`;
}

function proposalHtml(roadmap: Roadmap): string {
  if (roadmap.status !== "proposed") return "";
  const steps = allSteps(roadmap);
  const taskCount = steps.reduce((total, step) => total + (step.tasks?.length ?? 0), 0);
  const dependencyCount = steps.reduce((total, step) => total + (step.depends_on?.length ?? 0), 0);
  return `<section class="roadmap-proposal" aria-labelledby="roadmap-proposal-title">` +
    `<div><p class="roadmap-eyebrow">Proposition à examiner</p><h2 id="roadmap-proposal-title">${esc(roadmap.title)}</h2><p>${esc(roadmap.objective?.trim() || "Aucun objectif résumé.")}</p></div>` +
    `<dl class="roadmap-proposal-summary"><div><dt>Phases</dt><dd>${roadmap.phases?.length ?? 0}</dd></div><div><dt>Étapes</dt><dd>${steps.length}</dd></div><div><dt>Tâches prévues</dt><dd>${taskCount}</dd></div><div><dt>Dépendances</dt><dd>${dependencyCount}</dd></div></dl>` +
    `<div class="roadmap-proposal-change"><strong>Modifications proposées</strong><p>Créer ce plan et ses liens de dépendance. Les tâches restent des unités de travail séparées.</p></div>` +
    `<div class="roadmap-actions"><button class="ds-btn ds-btn--primary" type="button" data-review="approve">Approuver</button>` +
    `<button class="ds-btn" type="button" data-review="request_changes">Demander des changements</button>` +
    `<button class="ds-btn ds-btn--danger" type="button" data-review="reject">Rejeter</button></div></section>`;
}

export function roadmapPrintHtml(roadmap: Roadmap): string {
  const roadmapProgress = percent(roadmap.progress?.ratio);
  const phases = roadmap.phases ?? [];
  const phaseSections = phases.map((phase, phaseIndex) => {
    const steps = phase.steps ?? [];
    const stepSections = steps.map((step, stepIndex) => {
      const state = step.state ?? "not_started";
      const plannedTasks = step.tasks ?? [];
      const linkedCount = step.linked_tasks?.length ?? 0;
      const tasks = plannedTasks.length === 0 && linkedCount === 0
        ? `<p>Aucune tâche liée.</p>`
        : `<ul>${plannedTasks.map((task) => `<li>${esc(task.title)}</li>`).join("")}${linkedCount > 0 ? `<li>${linkedCount} tâche(s) liée(s)</li>` : ""}</ul>`;
      const dependencies = (step.depends_on ?? []).length === 0 ? "Aucune" : (step.depends_on ?? []).map(esc).join(", ");
      const criteria = (step.acceptance_criteria ?? []).length === 0
        ? `<p>Aucun critère défini.</p>`
        : `<ul>${(step.acceptance_criteria ?? []).map((criterion) => `<li>${esc(criterion)}</li>`).join("")}</ul>`;
      return `<article class="roadmap-print-step"><header><h3>${phaseIndex + 1}.${stepIndex + 1} ${esc(step.title)}</h3><span>${esc(STEP_LABELS[state] ?? state)}</span></header>` +
        `<p><strong>Objectif :</strong> ${esc(step.objective?.trim() || "Non renseigné")}</p>` +
        `<div><strong>Tâches</strong>${tasks}</div><p><strong>Dépendances :</strong> ${dependencies}</p>` +
        `<div><strong>Critères d'acceptation</strong>${criteria}</div></article>`;
    }).join("");
    return `<section class="roadmap-print-phase"><header><p>Phase ${phaseIndex + 1}</p><h2>${esc(phase.title)}</h2><p>${esc(phase.objective?.trim() || "Objectif non renseigné")}</p><p><strong>Progression :</strong> ${phaseProgress(phase)} %</p></header>${stepSections || `<p>Aucune étape.</p>`}</section>`;
  }).join("");
  return `<section class="roadmap-print-document" aria-label="Roadmap exportable"><header><p>Studi'OS · Roadmap</p><h1>${esc(roadmap.title)}</h1><p>${esc(roadmap.objective?.trim() || "Plan du projet")}</p>${roadmap.context ? `<p>${esc(roadmap.context)}</p>` : ""}` +
    `<dl><div><dt>Statut</dt><dd>${esc(STATUS_LABELS[roadmap.status])}</dd></div><div><dt>Progression</dt><dd>${roadmapProgress} %</dd></div><div><dt>Phases</dt><dd>${phases.length}</dd></div></dl></header>${phaseSections || `<p>Aucune phase.</p>`}</section>`;
}

export function roadmapShellHtml(roadmap: Roadmap, mode: RoadmapMode, selectedKey: string | null, demo = false): string {
  const progress = percent(roadmap.progress?.ratio);
  const plan = mode === "plan" ? roadmapPlanHtml(roadmap, selectedKey) : roadmapExecutionHtml(roadmap, selectedKey);
  const selected = allSteps(roadmap).find((step) => step.key === selectedKey) ?? null;
  const demoNote = demo
    ? `<div class="ds-notice ds-notice--info roadmap-fixture-note" role="note"><strong>Données de démonstration.</strong> Source locale de la session : les modifications restent ici, sans toucher l'API.</div>`
    : "";
  return `<div class="roadmap-view">${roadmapPrintHtml(roadmap)}` +
    demoNote +
    proposalHtml(roadmap) +
    `<header class="roadmap-header"><div><div class="roadmap-title-line"><h2>${esc(roadmap.title)}</h2>${dsBadge(STATUS_LABELS[roadmap.status], statusTone(roadmap.status))}</div>` +
    `<p>${esc(roadmap.objective?.trim() || "Plan du projet")}</p>${dsProgress(progress, 100, `${progress} % du plan terminé`)}</div>` +
    `<div class="roadmap-actions roadmap-no-print"><button class="ds-btn" type="button" data-edit-roadmap>Modifier</button><button class="ds-btn" type="button" data-import-json>Importer JSON</button><button class="ds-btn" type="button" data-export-json>Exporter JSON</button><button class="ds-btn ds-btn--primary" type="button" data-export-pdf>Exporter PDF</button></div></header>` +
    `<input class="ds-sr-only" type="file" accept="application/json,.json" aria-label="Choisir un fichier Roadmap JSON" data-import-file>` +
    `<div class="roadmap-reading-tabs roadmap-no-print" role="tablist" aria-label="Lecture de la roadmap"><button class="ds-tab" type="button" role="tab" aria-selected="${mode === "plan"}" data-mode="plan">Plan</button><button class="ds-tab" type="button" role="tab" aria-selected="${mode === "execution"}" data-mode="execution">Exécution</button></div>` +
    `<div class="roadmap-layout"><main class="roadmap-reading" data-roadmap-reading>${plan}</main>${roadmapStepDetailHtml(selected, roadmap)}</div>` +
    `<p class="roadmap-print-help roadmap-no-print">L'export PDF ouvre la vue d'impression du navigateur. Choisissez « Enregistrer au format PDF ».</p>` +
    `</div>`;
}

function documentEditorHtml(document: RoadmapDocument): string {
  const phases = document.phases.map((phase, phaseIndex) => `<fieldset class="roadmap-editor-phase" data-editor-phase="${phaseIndex}"><legend>Phase ${phaseIndex + 1}</legend>` +
    dsField(`phase-${phaseIndex}-key`, "Clé", `<input id="FIELD" name="phase.${phaseIndex}.key" value="${esc(phase.key)}" required pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}">`) +
    dsField(`phase-${phaseIndex}-title`, "Titre", `<input id="FIELD" name="phase.${phaseIndex}.title" value="${esc(phase.title)}" required>`) +
    dsField(`phase-${phaseIndex}-objective`, "Objectif", `<textarea id="FIELD" name="phase.${phaseIndex}.objective">${esc(phase.objective ?? "")}</textarea>`) +
    `<div class="roadmap-editor-steps">${phase.steps.map((step, stepIndex) => `<fieldset class="roadmap-editor-step" data-editor-step="${stepIndex}"><legend>Étape ${stepIndex + 1}</legend>` +
      dsField(`step-${phaseIndex}-${stepIndex}-key`, "Clé", `<input id="FIELD" name="step.${phaseIndex}.${stepIndex}.key" value="${esc(step.key)}" required pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}">`) +
      dsField(`step-${phaseIndex}-${stepIndex}-title`, "Titre", `<input id="FIELD" name="step.${phaseIndex}.${stepIndex}.title" value="${esc(step.title)}" required>`) +
      dsField(`step-${phaseIndex}-${stepIndex}-objective`, "Objectif", `<textarea id="FIELD" name="step.${phaseIndex}.${stepIndex}.objective">${esc(step.objective ?? "")}</textarea>`) +
      dsField(`step-${phaseIndex}-${stepIndex}-depends`, "Dépend de", `<input id="FIELD" name="step.${phaseIndex}.${stepIndex}.depends" value="${esc(step.depends_on.join(", "))}">`, "Clés séparées par des virgules.") +
      dsField(`step-${phaseIndex}-${stepIndex}-criteria`, "Critères d'acceptation", `<textarea id="FIELD" name="step.${phaseIndex}.${stepIndex}.criteria">${esc(step.acceptance_criteria.join("\n"))}</textarea>`, "Un critère par ligne.") +
      `<button class="ds-btn ds-btn--ghost" type="button" data-remove-step="${phaseIndex}:${stepIndex}">Retirer l'étape</button></fieldset>`).join("")}</div>` +
    `<div class="roadmap-editor-row"><button class="ds-btn" type="button" data-add-step="${phaseIndex}">Ajouter une étape</button><button class="ds-btn ds-btn--ghost" type="button" data-remove-phase="${phaseIndex}">Retirer la phase</button></div></fieldset>`).join("");
  return `<div class="roadmap-editor"><div class="ds-notice ds-notice--info" role="note"><strong>Édition locale.</strong> Rien n'est envoyé au serveur dans cette version.</div>` +
    `<form data-roadmap-editor>` +
    dsField("roadmap-title", "Titre", `<input id="FIELD" name="title" value="${esc(document.title)}" required maxlength="200">`) +
    dsField("roadmap-objective", "Objectif", `<textarea id="FIELD" name="objective" maxlength="2000">${esc(document.objective ?? "")}</textarea>`) +
    dsField("roadmap-context", "Contexte", `<textarea id="FIELD" name="context" maxlength="4000">${esc(document.context ?? "")}</textarea>`) +
    `<div data-editor-phases>${phases}</div><button class="ds-btn" type="button" data-add-phase>Ajouter une phase</button>` +
    `<div data-editor-error></div><div class="ds-dialog-actions"><button class="ds-btn" type="button" data-editor-cancel>Annuler</button><button class="ds-btn ds-btn--primary" type="submit">Enregistrer</button></div></form></div>`;
}

function readEditor(form: HTMLFormElement, baseline: RoadmapDocument): RoadmapDocument {
  const data = new FormData(form);
  const phaseNodes = [...form.querySelectorAll<HTMLElement>("[data-editor-phase]")];
  const phases = phaseNodes.map((phaseNode, phaseIndex) => {
    const original = baseline.phases[phaseIndex];
    const steps = [...phaseNode.querySelectorAll<HTMLElement>("[data-editor-step]")].map((_, stepIndex) => {
      const source = original?.steps[stepIndex];
      const value = (name: string): string => String(data.get(name) ?? "").trim();
      return {
        key: value(`step.${phaseIndex}.${stepIndex}.key`),
        title: value(`step.${phaseIndex}.${stepIndex}.title`),
        objective: value(`step.${phaseIndex}.${stepIndex}.objective`) || null,
        context: source?.context ?? null,
        instructions: source?.instructions ?? null,
        acceptance_criteria: value(`step.${phaseIndex}.${stepIndex}.criteria`).split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
        notes: source?.notes ?? null,
        metadata: source?.metadata ?? {},
        depends_on: value(`step.${phaseIndex}.${stepIndex}.depends`).split(",").map((item) => item.trim()).filter(Boolean),
        tasks: source?.tasks ?? [],
      };
    });
    return {
      key: String(data.get(`phase.${phaseIndex}.key`) ?? "").trim(),
      title: String(data.get(`phase.${phaseIndex}.title`) ?? "").trim(),
      objective: String(data.get(`phase.${phaseIndex}.objective`) ?? "").trim() || null,
      steps,
    };
  });
  return {
    format: "studio.roadmap/v1",
    title: String(data.get("title") ?? "").trim(),
    objective: String(data.get("objective") ?? "").trim() || null,
    context: String(data.get("context") ?? "").trim() || null,
    metadata: baseline.metadata,
    phases,
    exported_at: null,
    revision_no: baseline.revision_no,
  };
}

function downloadText(filename: string, contents: string): void {
  const url = URL.createObjectURL(new Blob([contents], { type: "application/json;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function emptyDocument(projectName: string): RoadmapDocument {
  return { format: "studio.roadmap/v1", title: `Plan de ${projectName}`, objective: null, context: null, metadata: {}, phases: [], exported_at: null, revision_no: null };
}

export async function renderRoadmapInto(root: HTMLElement, ctx: RoadmapViewContext): Promise<void> {
  root.innerHTML = dsSkeleton(5);
  let roadmap: Roadmap | null;
  try {
    roadmap = await ctx.dataSource.load(ctx.projectId);
  } catch (error) {
    root.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Roadmap indisponible.</strong> ${esc(describeError(error))}</div>`;
    return;
  }
  let mode: RoadmapMode = "plan";
  let selectedKey: string | null = roadmap?.current_step_key ?? (roadmap === null ? null : allSteps(roadmap)[0]?.key) ?? null;

  const paint = (): void => {
    if (roadmap === null) {
      root.innerHTML = `<div class="roadmap-optional">${dsEmptyState("Ce projet fonctionne sans roadmap", "Ajoutez-en une uniquement si un plan par étapes vous aide.")}` +
        `<button class="ds-btn ds-btn--primary" type="button" data-create-roadmap>Créer une roadmap</button></div>`;
      bind();
      return;
    }
    root.innerHTML = roadmapShellHtml(roadmap, mode, selectedKey, ctx.dataSource.demo === true);
    bind();
  };

  const openEditor = (document: RoadmapDocument): void => {
    root.insertAdjacentHTML("beforeend", `<div class="ds-overlay roadmap-editor-overlay" data-roadmap-editor-overlay><div class="ds-modal roadmap-editor-modal" role="dialog" aria-modal="true" aria-labelledby="roadmap-editor-title"><h2 id="roadmap-editor-title">Modifier la roadmap</h2>${documentEditorHtml(document)}</div></div>`);
    const overlay = root.querySelector<HTMLElement>("[data-roadmap-editor-overlay]");
    if (overlay === null) return;
    const form = overlay.querySelector<HTMLFormElement>("[data-roadmap-editor]");
    if (form === null) return;
    let draft = document;
    const close = (): void => overlay.remove();
    overlay.querySelector("[data-editor-cancel]")?.addEventListener("click", close);
    overlay.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
    overlay.querySelector("[data-add-phase]")?.addEventListener("click", () => {
      try { draft = readEditor(form, draft); } catch { /* native validation handles incomplete fields */ }
      draft.phases.push({ key: `phase-${draft.phases.length + 1}`, title: "Nouvelle phase", objective: null, steps: [] });
      close(); openEditor(draft);
    });
    overlay.querySelectorAll<HTMLElement>("[data-add-step]").forEach((button) => button.addEventListener("click", () => {
      try { draft = readEditor(form, draft); } catch { /* keep current draft */ }
      const phaseIndex = Number(button.dataset.addStep);
      draft.phases[phaseIndex]?.steps.push({ key: `step-${phaseIndex + 1}-${(draft.phases[phaseIndex]?.steps.length ?? 0) + 1}`, title: "Nouvelle étape", objective: null, context: null, instructions: null, acceptance_criteria: [], notes: null, metadata: {}, depends_on: [], tasks: [] });
      close(); openEditor(draft);
    }));
    overlay.querySelectorAll<HTMLElement>("[data-remove-phase]").forEach((button) => button.addEventListener("click", () => {
      draft = readEditor(form, draft); draft.phases.splice(Number(button.dataset.removePhase), 1); close(); openEditor(draft);
    }));
    overlay.querySelectorAll<HTMLElement>("[data-remove-step]").forEach((button) => button.addEventListener("click", () => {
      draft = readEditor(form, draft);
      const coordinates = (button.dataset.removeStep ?? "").split(":").map(Number);
      const phaseIndex = coordinates[0];
      const stepIndex = coordinates[1];
      if (phaseIndex !== undefined && stepIndex !== undefined) draft.phases[phaseIndex]?.steps.splice(stepIndex, 1);
      close(); openEditor(draft);
    }));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const errorBox = form.querySelector<HTMLElement>("[data-editor-error]");
      try {
        const validated = parseRoadmapDocument(JSON.stringify(readEditor(form, draft)));
        roadmap = await ctx.dataSource.replaceDocument(ctx.projectId, validated);
        close();
        selectedKey = allSteps(roadmap)[0]?.key ?? null;
        paint();
        dsNotify("Roadmap enregistrée.", "success");
      } catch (error) {
        if (errorBox !== null) errorBox.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Plan invalide.</strong> ${esc(describeError(error))}</div>`;
      }
    });
    overlay.querySelector<HTMLInputElement>("input")?.focus();
  };

  const bind = (): void => {
    root.querySelector<HTMLButtonElement>("[data-create-roadmap]")?.addEventListener("click", () => openEditor(emptyDocument(ctx.projectName)));
    if (roadmap === null) return;
    root.querySelectorAll<HTMLButtonElement>("[data-mode]").forEach((button) => button.addEventListener("click", () => {
      mode = button.dataset.mode === "execution" ? "execution" : "plan";
      paint();
    }));
    root.querySelectorAll<HTMLButtonElement>("[data-step-key]").forEach((button) => button.addEventListener("click", () => {
      selectedKey = button.dataset.stepKey ?? null;
      paint();
    }));
    root.querySelector<HTMLButtonElement>("[data-edit-roadmap]")?.addEventListener("click", () => { if (roadmap !== null) openEditor(roadmapToDocument(roadmap)); });
    const fileInput = root.querySelector<HTMLInputElement>("[data-import-file]");
    root.querySelector<HTMLButtonElement>("[data-import-json]")?.addEventListener("click", () => fileInput?.click());
    fileInput?.addEventListener("change", async () => {
      const file = fileInput.files?.[0];
      if (file === undefined) return;
      try {
        const document = parseRoadmapDocument(await file.text());
        roadmap = await ctx.dataSource.replaceDocument(ctx.projectId, document);
        selectedKey = allSteps(roadmap)[0]?.key ?? null;
        paint();
        dsNotify("Roadmap importée.", "success");
      } catch (error) {
        root.insertAdjacentHTML("afterbegin", `<div class="ds-notice ds-notice--danger" role="alert"><strong>Import impossible.</strong> ${esc(describeError(error))}</div>`);
      }
    });
    root.querySelector<HTMLButtonElement>("[data-export-json]")?.addEventListener("click", () => {
      if (roadmap === null) return;
      downloadText("studio-roadmap.json", serializeRoadmapDocument(roadmapToDocument(roadmap)));
    });
    root.querySelector<HTMLButtonElement>("[data-export-pdf]")?.addEventListener("click", () => window.print());
    root.querySelectorAll<HTMLButtonElement>("[data-review]").forEach((button) => button.addEventListener("click", async () => {
      if (roadmap === null) return;
      const decision = button.dataset.review;
      if (decision !== "approve" && decision !== "request_changes" && decision !== "reject") return;
      roadmap = await ctx.dataSource.reviewProposal(ctx.projectId, decision, decision === "request_changes" ? "Modifications demandées depuis l'aperçu." : undefined);
      paint();
      dsNotify("Décision enregistrée.", "success");
    }));
  };

  paint();
}
