/**
 * Studios (R2-coque, fiche E1) — GET /api/v1/studios.
 *
 * L'endpoint est en cours d'ajout côté API : le schéma OpenAPI généré ne le
 * connaît pas encore, d'où l'interface minimale `StudiosClient` (le client
 * réel est casté à l'appel, un seul endroit). Réponse attendue :
 * `[{ id, name, slug, plan, status, role }]` avec `status` ∈ active|suspended.
 * Rôles (hypothèse documentée, QUESTION posée sans réponse bloquante) :
 * `owner`|`admin`|`member`|`viewer` (+ alias `readonly` → `viewer`).
 *
 * Repli « studio unique » : un 404 (endpoint absent) ne bloque pas la coque,
 * on expose un studio local unique marqué `fallback: true` — le sélecteur
 * s'affiche alors sans flèche (E1, état « studio unique »).
 */
import { ApiError, parseErrorBody } from "./api";

export type StudioRole = "owner" | "admin" | "member" | "viewer";
export type StudioStatus = "active" | "suspended";

export interface Studio {
  id: string;
  name: string;
  slug: string;
  /** Formule, texte libre côté API (« Gratuit », « Pro »…) — affichée telle quelle. */
  plan: string;
  status: StudioStatus;
  role: StudioRole;
}

/** Client minimal : le schéma généré ne connaît pas encore /api/v1/studios. */
export interface StudiosClient {
  GET: (
    path: "/api/v1/studios",
    init?: unknown,
  ) => Promise<{ response: { ok: boolean; status: number }; data?: unknown; error?: unknown }>;
}

export const STUDIO_ROLE_LABELS: Record<StudioRole, string> = {
  owner: "Propriétaire",
  admin: "Administrateur",
  member: "Membre",
  viewer: "Lecture seule",
};

export function studioRoleLabel(role: StudioRole): string {
  return STUDIO_ROLE_LABELS[role];
}

/** Normalise un rôle brut ; inconnu → `viewer` (le plus restrictif : masque l'Abonnement). */
export function normalizeStudioRole(value: unknown): StudioRole {
  if (typeof value !== "string") return "viewer";
  const folded = value.trim().toLowerCase();
  if (folded === "owner" || folded === "proprietaire" || folded === "propriétaire") return "owner";
  if (folded === "admin" || folded === "administrator" || folded === "administrateur") return "admin";
  if (folded === "member" || folded === "membre") return "member";
  return "viewer";
}

function normalizeStudioStatus(value: unknown): StudioStatus {
  return value === "suspended" ? "suspended" : "active";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeStudio(value: unknown): Studio | null {
  if (!isRecord(value)) return null;
  const { id, name, slug, plan, status, role } = value;
  if (typeof id !== "string" || id === "" || typeof name !== "string" || name === "") return null;
  return {
    id,
    name,
    slug: typeof slug === "string" && slug !== "" ? slug : id,
    plan: typeof plan === "string" && plan !== "" ? plan : "Gratuit",
    status: normalizeStudioStatus(status),
    role: normalizeStudioRole(role),
  };
}

/** Studio local de repli (endpoint 404) : propriétaire, actif, formule gratuite. */
export const SINGLE_STUDIO_FALLBACK: Studio = {
  id: "unique",
  name: "Atelier",
  slug: "atelier",
  plan: "Gratuit",
  status: "active",
  role: "owner",
};

export interface StudiosResult {
  studios: Studio[];
  /** Vrai quand l'API a répondu 404 : liste locale, sélecteur sans menu. */
  fallback: boolean;
}

export async function listStudios(client: StudiosClient): Promise<StudiosResult> {
  const result = await client.GET("/api/v1/studios", {});
  if (result.response.status === 404) {
    return { studios: [{ ...SINGLE_STUDIO_FALLBACK }], fallback: true };
  }
  if (!result.response.ok) {
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  const data = Array.isArray(result.data) ? result.data : [];
  const studios = data.map(normalizeStudio).filter((studio): studio is Studio => studio !== null);
  if (studios.length === 0) return { studios: [{ ...SINGLE_STUDIO_FALLBACK }], fallback: true };
  return { studios, fallback: false };
}

/**
 * « Connecté » = état vrai (E1) : sonde /healthz, jamais un défaut.
 * `fetchFn` injectable pour les tests.
 */
export async function probeServer(
  baseUrl: string,
  fetchFn: typeof globalThis.fetch = globalThis.fetch,
  timeoutMs = 8000,
): Promise<boolean> {
  const clean = baseUrl.replace(/\/+$/, "");
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchFn(`${clean}/healthz`, { cache: "no-store", signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}
