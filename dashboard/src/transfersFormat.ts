/**
 * UI-10 — Transferts : dérivation d'affichage pure (aucun DOM, aucun accès
 * réseau). Le contrat Transfer est la seule source : rien n'est inventé.
 *
 * Statuts backend réels (`studio_contracts.transfers.TransferStatus`) :
 * created, uploading, ready, downloaded, expired, deleted. Le service ne
 * pose jamais `expired` (la retention `expire_transfers` marque `deleted`) :
 * une expiration encore visible est donc DÉRIVÉE de `expires_at <= now`,
 * signalée comme telle — jamais confondue avec un statut serveur.
 *
 * Les octets ne sont jamais exposés : seuls taille, type MIME et références
 * techniques le sont. Aucune URL présignée, aucun token.
 */
import { ApiError } from "./api";
import type { Transfer, TransferCategory } from "./transfersApi";
import { describeError, shortId } from "./ui";

export type TransferStatusKey =
  | "created"
  | "uploading"
  | "ready"
  | "downloaded"
  | "expired"
  | "deleted";

export type TransferTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface StatusLabel {
  key: TransferStatusKey;
  label: string;
  tone: TransferTone;
  hint: string;
  /** Vrai quand l'expiration est déduite de `expires_at`, pas du statut serveur. */
  derivedExpiry: boolean;
}

const STATUS_LABELS: Record<TransferStatusKey, { label: string; tone: TransferTone; hint: string }> = {
  created: {
    label: "En attente d'envoi",
    tone: "info",
    hint: "Transfert déclaré : les octets n'ont pas encore été envoyés au stockage.",
  },
  uploading: {
    label: "Envoi en cours",
    tone: "info",
    hint: "Envoi des octets vers le stockage en cours.",
  },
  ready: {
    label: "Disponible",
    tone: "success",
    hint: "Le fichier est disponible au téléchargement.",
  },
  downloaded: {
    label: "Téléchargé",
    tone: "success",
    hint: "Au moins un téléchargement a été enregistré par le serveur.",
  },
  expired: {
    label: "Expiré",
    tone: "danger",
    hint: "La durée de conservation est dépassée : le serveur supprimera le fichier.",
  },
  deleted: {
    label: "Supprimé",
    tone: "neutral",
    hint: "Le transfert et ses octets ont été supprimés.",
  },
};

const CATEGORY_LABELS: Record<TransferCategory, string> = {
  temporary: "Temporaire",
  build: "Build",
  asset: "Ressource",
  raw_recording: "Enregistrement brut",
};

export function transferCategoryFr(category: string): string {
  return CATEGORY_LABELS[category as TransferCategory] ?? category;
}

/** `expires_at` dépassé, hors statut `deleted` (le serveur l'a déjà retiré). */
export function isExpired(
  transfer: Pick<Transfer, "expires_at" | "status">,
  now: number,
): boolean {
  if (transfer.status === "deleted") return false;
  if (transfer.expires_at === null || transfer.expires_at === undefined) return false;
  const time = new Date(transfer.expires_at).getTime();
  return !Number.isNaN(time) && time <= now;
}

export function normalizeStatus(status: string): TransferStatusKey {
  return status in STATUS_LABELS ? (status as TransferStatusKey) : "created";
}

/** Statut effectif (statut serveur, ou expiration dérivée), libellé FR + ton. */
export function effectiveStatus(
  transfer: Pick<Transfer, "expires_at" | "status">,
  now: number,
): StatusLabel {
  if (isExpired(transfer, now)) {
    return { key: "expired", ...STATUS_LABELS.expired, derivedExpiry: true };
  }
  const key = normalizeStatus(transfer.status);
  return { key, ...STATUS_LABELS[key], derivedExpiry: false };
}

/** Un objet ne se télécharge que s'il a été envoyé et n'est pas retiré/expiré. */
export function isDownloadable(
  transfer: Pick<Transfer, "expires_at" | "status">,
  now: number,
): boolean {
  if (isExpired(transfer, now)) return false;
  return transfer.status === "ready" || transfer.status === "downloaded";
}

/** Taille humaine : octets, Ko, Mo, Go (base 1024, décimales françaises). */
export function humanBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} ${bytes === 1 ? "octet" : "octets"}`;
  const units = ["Ko", "Mo", "Go", "To"] as const;
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = value >= 100 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} ${units[unit]}`;
}

/** Expiration absolue : date lisible, sans prétendre à une précision à la seconde. */
export function expiryLabelFr(expiresAt: string | null | undefined, now: number): string {
  if (expiresAt === null || expiresAt === undefined || expiresAt === "") {
    return "Aucune expiration programmée";
  }
  const time = new Date(expiresAt).getTime();
  if (Number.isNaN(time)) return "Date d'expiration illisible";
  const date = new Date(time).toLocaleString("fr-FR");
  return time <= now ? `Expiré depuis le ${date}` : `Expire le ${date}`;
}

export function senderLabelFr(transfer: Pick<Transfer, "sender_user_id">): string {
  return `Utilisateur ${shortId(transfer.sender_user_id)}`;
}

/** `recipient_user_id` absent = diffusion à tous les destinataires autorisés. */
export function recipientLabelFr(
  transfer: Pick<Transfer, "recipient_user_id">,
): string {
  if (transfer.recipient_user_id === null || transfer.recipient_user_id === undefined) {
    return "Diffusion (destinataires autorisés)";
  }
  return `Utilisateur ${shortId(transfer.recipient_user_id)}`;
}

/**
 * Erreurs actionnables : `413 transfer_too_large` affiche la taille maximale,
 * `507 quota_exceeded` le restant du bucket — jamais un échec générique.
 */
export function transferErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const details =
      error.details !== null && typeof error.details === "object"
        ? (error.details as Record<string, unknown>)
        : null;
    if (error.errorCode === "transfer_too_large") {
      const max = details?.["max_size_bytes"];
      return typeof max === "number"
        ? `Fichier trop volumineux : la taille maximale d'un transfert est ${humanBytes(max)}.`
        : "Fichier trop volumineux pour un transfert.";
    }
    if (error.errorCode === "quota_exceeded") {
      const quota = details?.["quota_bytes"];
      const consumed = details?.["consumed_bytes"];
      if (typeof quota === "number" && typeof consumed === "number") {
        return `Quota de transfert dépassé : ${humanBytes(Math.max(quota - consumed, 0))} restants sur ${humanBytes(quota)}.`;
      }
      return "Quota de transfert dépassé pour ce bucket.";
    }
    if (error.errorCode === "missing_content_md5") {
      return "Le stockage exige l'empreinte MD5 du fichier (nouvel essai automatique).";
    }
  }
  return describeError(error);
}

/* ------------------------------------------------------------------ */
/* Recherche, filtres et tri locaux (données déjà chargées).           */
/* ------------------------------------------------------------------ */

export type TransferStatusFilter = "all" | TransferStatusKey;
export type TransferCategoryFilter = "all" | TransferCategory;

export interface TransfersFilterState {
  query: string;
  status: TransferStatusFilter;
  category: TransferCategoryFilter;
  /** `""` = tous les projets ; sinon `project_id` chargé. */
  projectId: string;
}

export function initialTransfersFilterState(): TransfersFilterState {
  return { query: "", status: "all", category: "all", projectId: "" };
}

export function isTransfersDefaultState(state: TransfersFilterState): boolean {
  return (
    state.query.trim() === "" &&
    state.status === "all" &&
    state.category === "all" &&
    state.projectId === ""
  );
}

export interface TransfersFilterContext {
  now: number;
  /** Noms de projets résolus (GET /projects) pour la recherche. */
  projectNameById?: ReadonlyMap<string, string>;
  /** Titres de tâches résolus (GET /tasks) pour la recherche. */
  taskTitleById?: ReadonlyMap<string, string>;
}

function haystack(transfer: Transfer, ctx: TransfersFilterContext): string {
  const parts = [
    transfer.filename,
    transfer.transfer_code,
    transferCategoryFr(transfer.category),
    effectiveStatus(transfer, ctx.now).label,
    transfer.sender_user_id,
    transfer.recipient_user_id ?? "diffusion",
    transfer.project_id !== null && transfer.project_id !== undefined
      ? (ctx.projectNameById?.get(transfer.project_id) ?? "")
      : "",
    transfer.task_id !== null && transfer.task_id !== undefined
      ? (ctx.taskTitleById?.get(transfer.task_id) ?? "")
      : "",
  ];
  return parts.join("\n").toLowerCase();
}

export function filterTransfers(
  transfers: Transfer[],
  state: TransfersFilterState,
  ctx: TransfersFilterContext,
): Transfer[] {
  const query = state.query.trim().toLowerCase();
  return transfers.filter((transfer) => {
    if (state.status !== "all" && effectiveStatus(transfer, ctx.now).key !== state.status) {
      return false;
    }
    if (state.category !== "all" && transfer.category !== state.category) return false;
    if (state.projectId !== "" && transfer.project_id !== state.projectId) return false;
    if (query === "") return true;
    return haystack(transfer, ctx).includes(query);
  });
}

/**
 * L'API `GET /transfers` ne fixe aucun ordre : tri client déterministe
 * (créé décroissant, puis identifiant, puis code) — jamais présenté comme un
 * ordre serveur.
 */
export function sortTransfers(transfers: Transfer[]): Transfer[] {
  return [...transfers].sort((a, b) => {
    const delta = new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    if (delta !== 0 && !Number.isNaN(delta)) return delta;
    return (
      a.id.localeCompare(b.id) || a.transfer_code.localeCompare(b.transfer_code)
    );
  });
}

export function visibleTransfers(
  transfers: Transfer[],
  state: TransfersFilterState,
  ctx: TransfersFilterContext,
): Transfer[] {
  return filterTransfers(sortTransfers(transfers), state, ctx);
}

/** Projets distincts présents dans les transferts chargés (pour le filtre). */
export function transferProjectIds(transfers: Transfer[]): string[] {
  const ids = new Set<string>();
  for (const transfer of transfers) {
    if (transfer.project_id !== null && transfer.project_id !== undefined && transfer.project_id !== "") {
      ids.add(transfer.project_id);
    }
  }
  return [...ids];
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_RE.test(value.trim());
}
