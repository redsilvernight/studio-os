/**
 * Paramètres › Intégrations IA — action « Configurer ce poste ».
 *
 * Un aperçu par étape (harnais détectés, hooks, skills, adapters, MCP), puis
 * une application liée à cet aperçu après confirmation. Les fichiers, diffs et
 * sauvegardes appartiennent à l'assistant local : cette vue n'affiche comme
 * écrit que ce que le rapport de l'assistant confirme (relecture disque).
 */
import type { Platform } from "../platform";
import { dsBadge } from "../ds/ds";
import { type HarnessStatus } from "../harnessApi";
import {
  ADAPTERS_STATE_LABELS,
  ITEM_KIND_LABELS,
  ITEM_OUTCOME_LABELS,
  ITEM_OUTCOME_TONES,
  ITEM_STATE_LABELS,
  ITEM_STATE_TONES,
  SKILLS_OUTCOME_LABELS,
  SKILLS_UNAVAILABLE_LABELS,
  applySetup,
  hasPendingWork,
  previewSetup,
  setupErrorMessage,
  type SetupApplyResult,
  type SetupItemPlan,
  type SetupPlan,
} from "../setupApi";
import { esc } from "../ui";

export interface SetupView {
  /** Aperçu en attente de confirmation : rien n'est écrit avant. */
  plan?: SetupPlan;
  /** Rapport de la dernière application (l'aperçu n'est alors plus applicable). */
  result?: SetupApplyResult;
  error?: string;
  /** Cases cochées conservées entre deux rendus. */
  overwrite?: string[];
  syncSkills?: boolean;
}

type Rerender = (view: { setup: SetupView }) => Promise<void>;

const itemLabel = (item: SetupItemPlan): string => `${ITEM_KIND_LABELS[item.kind]} (${item.harness})`;

const plural = (count: number, one: string, many: string): string => `${count} ${count > 1 ? many : one}`;

/** Résumé du diff replié : lignes annoncées (additions + suppressions) ou lignes du diff. */
const diffSummary = (item: SetupItemPlan): string => {
  const counted = (item.lines_added ?? 0) + (item.lines_removed ?? 0);
  const lines = counted > 0 ? counted : (item.diff ?? "").split("\n").filter((line) => line.trim() !== "").length;
  return lines > 1 ? `Voir les ${lines} lignes modifiées` : "Voir la ligne modifiée";
};

function itemHtml(item: SetupItemPlan, checked: boolean): string {
  const registration = item.needs_registration
    ? `<p class="settings-intro" data-testid="needs-registration">À enregistrer dans les réglages de l'outil (étape manuelle).</p>`
    : "";
  const differs =
    item.state === "differs"
      ? `<p class="settings-intro">${item.managed ? "Copie gérée différente de la version actuelle (obsolète ou modifiée)" : "Fichier qui n'est pas géré par Studi'OS"} : +${item.lines_added ?? 0} / −${item.lines_removed ?? 0} ligne(s).</p>` +
        `<details class="setup-diff"><summary>${diffSummary(item)}</summary>` +
        `<pre class="mono" data-testid="setup-diff">${esc(item.diff ?? "")}</pre>` +
        (item.diff_truncated ? `<p class="settings-intro">Différence tronquée : seules les premières lignes sont affichées.</p>` : "") +
        `</details>` +
        `<label class="settings-check"><input type="checkbox" data-setup-overwrite="${esc(item.item_id)}"${checked ? " checked" : ""}> Remplacer ce fichier par la version gérée (une sauvegarde de votre version est créée avant)</label>` +
        `<p class="settings-intro">Case non cochée : le fichier garde son contenu actuel, sans aucune modification.</p>`
      : "";
  return (
    `<li data-setup-item="${esc(item.item_id)}" data-state="${item.state}">` +
    `${esc(itemLabel(item))} : ${dsBadge(ITEM_STATE_LABELS[item.state], ITEM_STATE_TONES[item.state])}` +
    registration +
    differs +
    `</li>`
  );
}

function previewHtml(plan: SetupPlan, view: SetupView, harnesses: HarnessStatus[]): string {
  const chosen = new Set(view.overwrite ?? []);
  const detected = (plan.harnesses ?? []).filter((h) => h.detected);
  const skills = plan.skills;
  const skillsPending = skills.state === "checked" && ((skills.missing ?? 0) > 0 || (skills.outdated ?? 0) > 0);
  const skillsBody =
    skills.state === "unavailable"
      ? `${dsBadge("Indisponible", "warning")} ${esc(skills.reason ? SKILLS_UNAVAILABLE_LABELS[skills.reason] : "")} Rien ne sera écrit.`
      : `${skills.current ?? 0} à jour · ${skills.missing ?? 0} absentes · ${skills.outdated ?? 0} obsolètes · ${skills.locally_modified ?? 0} modifiées localement (jamais écrasées).` +
        (skillsPending
          ? `<label class="settings-check"><input type="checkbox" data-setup-skills${view.syncSkills === false ? "" : " checked"}> Synchroniser les skills absentes ou obsolètes</label>`
          : "");
  const adapters = plan.adapters;
  const adaptersBody =
    adapters.state === "checked"
      ? `${dsBadge(adapters.drifted ? "Dérive" : "Conformes", adapters.drifted ? "warning" : "success")} ${adapters.checked ?? 0} fichier(s) vérifié(s), ${adapters.drifted ?? 0} en dérive. Lecture seule : cet aperçu ne modifie aucun de ces fichiers.`
      : `${esc(ADAPTERS_STATE_LABELS[adapters.state])}.`;
  const mcp =
    harnesses.length === 0
      ? "Aucun outil IA chargé."
      : `${plural(harnesses.length, "outil IA chargé", "outils IA chargés")} : le raccordement de chacun se fait dans sa carte ci-dessous.`;
  const hooks = (plan.hooks ?? []).map((item) => itemHtml(item, chosen.has(item.item_id))).join("");
  const kept = (plan.hooks ?? []).filter((item) => item.state === "differs" && !chosen.has(item.item_id)).length;
  const keptSummary =
    kept === 0
      ? ""
      : `<p class="settings-intro setup-summary" data-testid="setup-summary">${plural(kept, "fichier restera inchangé", "fichiers resteront inchangés")} : cochez « Remplacer ce fichier » pour appliquer la version gérée.</p>`;
  const nothing = !hasPendingWork(plan);
  return (
    `<div class="integration-plan" data-testid="setup-plan" role="alertdialog" aria-label="Aperçu de la configuration du poste">` +
    `<h3>Aperçu — rien n'est écrit tant que vous ne confirmez pas</h3>` +
    `<h4>1. Harnais détectés</h4><p class="settings-intro" data-testid="setup-harnesses">${detected.length === 0 ? "Aucun harnais détecté." : detected.map((h) => `<code class="mono">${esc(h.harness)}</code>`).join(", ")}</p>` +
    `<h4>2. Fichiers utilisés par les outils IA</h4>` +
    `<p class="settings-intro">Un script ajouté au démarrage de chaque session, un script qui bloque les commits directs sur les branches protégées, et l'extension qui applique les mêmes règles dans OpenCode.</p>` +
    (hooks === "" ? `<p class="settings-intro">Aucun de ces fichiers à installer.</p>` : `<ul>${hooks}</ul>`) +
    `<h4>3. Skills de la bibliothèque</h4><p class="settings-intro" data-testid="setup-skills">${skillsBody}</p>` +
    `<h4>4. Adapters</h4><p class="settings-intro" data-testid="setup-adapters">${adaptersBody}</p>` +
    `<h4>5. Connexion MCP</h4><p class="settings-intro" data-testid="setup-mcp">${mcp} Chaque raccordement se fait avec sa propre confirmation : il n'est jamais déclaré configuré ici.</p>` +
    (nothing
      ? `<p class="settings-notice" role="status" data-testid="setup-nothing">Ce poste est déjà configuré : rien à écrire.</p>`
      : keptSummary + `<button class="ds-btn ds-btn--primary" type="button" data-action="confirm-setup">Confirmer et appliquer</button> `) +
    `<button class="ds-btn" type="button" data-action="cancel-setup">${nothing ? "Fermer" : "Annuler"}</button>` +
    `</div>`
  );
}

function resultHtml(plan: SetupPlan | undefined, result: SetupApplyResult): string {
  const names = new Map((plan?.hooks ?? []).map((item) => [item.item_id, itemLabel(item)]));
  const rows = (result.hooks ?? [])
    .map(
      (item) =>
        `<li data-setup-result="${esc(item.item_id)}" data-outcome="${item.outcome}">${esc(names.get(item.item_id) ?? item.item_id)} : ${dsBadge(ITEM_OUTCOME_LABELS[item.outcome], ITEM_OUTCOME_TONES[item.outcome])}${item.backed_up ? " · sauvegarde créée avant remplacement" : ""}</li>`,
    )
    .join("");
  const skills = result.skills;
  const skillsTone = skills.outcome === "failed" ? "danger" : skills.outcome === "synced" ? "success" : "neutral";
  const skillsLine =
    dsBadge(SKILLS_OUTCOME_LABELS[skills.outcome], skillsTone) +
    (skills.written ? ` ${skills.written} fichier(s) écrit(s).` : "") +
    (skills.left_modified ? ` ${skills.left_modified} modifiée(s) localement, laissée(s) telle(s) quelle(s).` : "");
  return (
    `<div class="integration-plan" data-testid="setup-result">` +
    `<h3>Rapport</h3>` +
    (rows === "" ? "" : `<ul>${rows}</ul>`) +
    `<p class="settings-intro" data-testid="setup-result-skills">Skills : ${skillsLine}</p>` +
    (result.backups_created ? `<p class="settings-intro">Les fichiers remplacés ont été sauvegardés sur ce poste.</p>` : "") +
    `<p class="settings-intro">« Écrit et relu » signifie que le fichier a été relu après écriture. Le raccordement MCP reste à faire harnais par harnais ci-dessous.</p>` +
    `</div>`
  );
}

export function setupSectionHtml(view: SetupView = {}, harnesses: HarnessStatus[] = []): string {
  const body =
    view.plan && !view.result
      ? previewHtml(view.plan, view, harnesses)
      : `<button class="ds-btn ds-btn--primary" type="button" data-action="preview-setup">Configurer ce poste…</button>`;
  return (
    `<section class="settings-domain settings-setup" data-testid="machine-setup">` +
    `<h2>Configurer ce poste</h2>` +
    `<p class="settings-intro">Repère les outils IA installés sur ce poste, prépare les fichiers qu'ils exécutent, synchronise les skills manquantes ou obsolètes et vérifie les fichiers d'adaptation, en une seule action. Un aperçu s'affiche d'abord ; aucun fichier existant n'est remplacé sans votre confirmation, fichier par fichier, et une sauvegarde est créée avant.</p>` +
    (view.error ? `<p class="ds-field-error" role="alert" data-testid="setup-error">${esc(view.error)}</p>` : "") +
    (view.result ? resultHtml(view.plan, view.result) : "") +
    body +
    `</section>`
  );
}

export function bindSetup(root: HTMLElement, platform: Platform, view: SetupView | undefined, again: Rerender): void {
  const section = root.querySelector("[data-testid=machine-setup]");
  if (!section) return;
  const plan = view?.plan;
  section.querySelector("[data-action=preview-setup]")?.addEventListener("click", () => {
    void previewSetup(platform).then((outcome) =>
      outcome.ok ? again({ setup: { plan: outcome.value } }) : again({ setup: { error: setupErrorMessage(outcome.error) } }),
    );
  });
  section.querySelector("[data-action=cancel-setup]")?.addEventListener("click", () => void again({ setup: {} }));
  section.querySelector("[data-action=confirm-setup]")?.addEventListener("click", () => {
    if (!plan) return;
    const overwrite = [...section.querySelectorAll<HTMLInputElement>("[data-setup-overwrite]")]
      .filter((box) => box.checked)
      .map((box) => box.dataset["setupOverwrite"] ?? "");
    const skillsBox = section.querySelector<HTMLInputElement>("[data-setup-skills]");
    const syncSkills = skillsBox ? skillsBox.checked : false;
    void applySetup(platform, plan, overwrite, syncSkills).then((outcome) =>
      outcome.ok
        ? again({ setup: { plan, result: outcome.value } })
        : again({ setup: { ...(outcome.error.code === "plan_expired" ? {} : { plan }), error: setupErrorMessage(outcome.error) } }),
    );
  });
}
