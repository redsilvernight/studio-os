/** Tiny HTML helpers — no framework, escaped by default. French user-facing strings (DEC-0078). */

import { ApiError } from "./api";

export function esc(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function fmtTime(iso: string | null | undefined): string {
  if (iso === null || iso === undefined || iso === "") return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return esc(iso);
  return esc(date.toLocaleString("fr-FR"));
}

/**
 * UUID v4. `crypto.randomUUID` n'existe qu'en contexte sécurisé (HTTPS/localhost) :
 * le dashboard est servi en HTTP sur une IP (Tailscale), d'où le repli sur
 * `getRandomValues`, disponible partout.
 */
export function newUuid(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

export function idCell(id: string | null | undefined): string {
  if (!id) return "—";
  return `<code class="mono" title="${esc(id)}">${esc(shortId(id))}</code>`;
}

export type SectionStatus = "loading" | "error" | "empty" | "ready";

export function statusBlock(status: SectionStatus, message = ""): string {
  if (status === "loading")
    return `<div class="state loading" role="status" aria-busy="true">Chargement…</div>`;
  if (status === "error") return `<div class="state error" role="alert">Erreur : ${esc(message)}</div>`;
  if (status === "empty")
    return `<div class="state empty">${esc(message === "" ? "Rien à afficher." : message)}</div>`;
  return "";
}

export function section(title: string, meta: string, body: string): string {
  return `<section class="panel"><header><h2>${esc(title)}</h2><span class="meta">${meta}</span></header><div class="body">${body}</div></section>`;
}

/** Confirmation partagée (Bibliothèque et Paramètres) : même geste, même phrase. */
export const CONFIRM_RELEASE_LOCK = "Libérer ce verrou ? La version ne sera plus figée pour ce projet.";

/**
 * Messages humains par code métier renvoyé par l'API. Les surfaces qui
 * traitent un code de façon spécifique (409 tâche, 401/403 inspecteur,
 * transferts…) gardent leur propre message ; ceci n'est que le repli commun.
 */
const CODE_MESSAGES: Record<string, string> = {
  version_conflict: "Cet élément a été modifié ailleurs. Rechargez pour voir la dernière version, puis réappliquez votre changement.",
  already_claimed: "Cette tâche est déjà prise en charge par une autre machine.",
  already_locked: "Cette ressource est déjà verrouillée pour ce projet.",
  already_bound: "Cette règle d'affectation existe déjà.",
  duplicate_stable_key: "Une ressource porte déjà cette clé stable.",
  idempotency_key_in_progress: "Cette demande est déjà en cours de traitement. Patientez un instant.",
  idempotency_key_payload_mismatch: "Cette demande a déjà été envoyée avec un contenu différent. Rechargez la page, puis recommencez.",
  invalid_status_transition: "Ce changement de statut n'est pas autorisé depuis l'état actuel.",
  invalid_state: "Cette action n'est pas possible dans l'état actuel. Rechargez pour voir le statut à jour.",
  active_roadmap_exists: "Une autre roadmap est déjà active dans ce projet. Clôturez-la ou archivez-la d'abord.",
  runtime_incompatible: "Le runtime retenu ne satisfait pas les exigences demandées.",
  runtime_not_found: "Runtime introuvable.",
  definition_not_found: "Définition introuvable.",
  invalid_resolution_input: "La demande de résolution n'est pas valide. Vérifiez la clé stable et le projet.",
  invalid_binding: "Cette liaison n'est pas valide.",
  invalid_runtime_binding: "Cette règle d'affectation n'est pas valide.",
  invalid_content: "Le contenu saisi n'est pas valide pour ce type de ressource.",
  invalid_workflow: "Le flux de travail saisi n'est pas valide.",
  invalid_scope_context: "La portée choisie ne correspond pas au projet indiqué.",
  project_not_found: "Projet introuvable.",
  task_not_found: "Tâche introuvable.",
  forbidden: "Vous n'avez pas les droits nécessaires pour cette action.",
};

const STATUS_MESSAGES: Record<number, string> = {
  400: "La demande n'est pas valide.",
  401: "Votre session n'est plus valide. Reconnectez-vous, puis réessayez.",
  403: "Vous n'avez pas les droits nécessaires pour cette action.",
  404: "Élément introuvable : il a peut-être été supprimé ou n'est pas visible avec ce compte.",
  409: "Cette action entre en conflit avec l'état actuel des données. Rechargez, puis réessayez.",
  413: "Le contenu envoyé est trop volumineux.",
  422: "Les informations saisies ne sont pas valides. Vérifiez les champs, puis réessayez.",
  429: "Trop de demandes. Patientez un instant, puis réessayez.",
};

function humanMessage(error: ApiError): string {
  if (error.errorCode !== null && CODE_MESSAGES[error.errorCode] !== undefined) return CODE_MESSAGES[error.errorCode] ?? "";
  if (STATUS_MESSAGES[error.status] !== undefined) return STATUS_MESSAGES[error.status] ?? "";
  if (error.status >= 500) return "Le serveur a rencontré une erreur. Réessayez dans un instant.";
  return "L'action n'a pas pu aboutir.";
}

/**
 * Erreur de mutation lisible : un message humain d'abord, puis les détails
 * utiles au débogage entre parenthèses (statut, code métier, version serveur).
 * N'invente jamais un changement d'état.
 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const technical = [`HTTP ${error.status}`];
    if (error.errorCode !== null) technical.push(error.errorCode);
    else if (error.message !== "" && error.message !== `HTTP ${error.status}`) technical.push(error.message);
    if (error.errorCode === "version_conflict" && error.serverVersion !== null) {
      technical.push(`version serveur ${error.serverVersion}`);
    }
    return `${humanMessage(error)} (${technical.join(" · ")})`;
  }
  if (error instanceof TypeError && /fetch|network|load failed/i.test(error.message)) {
    return `Impossible de joindre le serveur. Vérifiez votre connexion, puis réessayez. (${error.message})`;
  }
  return error instanceof Error ? error.message : String(error);
}
