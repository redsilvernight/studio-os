/**
 * Cycle de vie des studios (atelier N1/N2/N5/N7) — client typé local.
 *
 * Le contrat serveur est en cours d'écriture par un autre lot : ce module
 * code directement contre le contrat convenu (types locaux ci-dessous),
 * sans régénérer openapi-schema. Même discipline que le client canonique
 * (api.ts) : fetch via observedFetch (signaux de connexion du shell),
 * jeton Bearer injecté depuis le store mémoire, erreurs HTTP mappées en
 * ApiError (status + error_code), aucune logique métier côté client.
 *
 * Contrat codé ici :
 * - GET  /studios                        -> StudioSummary[]
 * - POST /studios {name}                 -> StudioSummary (créateur = owner)
 * - GET  /studios/{id}                   -> Studio (+ deletion_scheduled_at)
 * - POST /studios/{id}/invitations {email,role}      -> StudioInvitation
 * - GET  /studios/{id}/invitations                   -> StudioInvitation[]
 * - DELETE /studios/{id}/invitations/{inv_id}        -> 204
 * - POST /invitations/preview {token}    -> InvitationPreview
 * - POST /invitations/accept {token}     -> InvitationAcceptance ; 410 avec
 *   error_code « invitation_expired » (expirée) ou « invitation_used » (déjà
 *   utilisée)
 * - GET  /studios/{id}/members           -> StudioMember[]
 * - PATCH  /studios/{id}/members/{user_id} {role}    -> 204
 * - DELETE /studios/{id}/members/{user_id}           -> 204
 * - POST /studios/{id}/transfer-ownership {user_id}  -> 204
 * - POST /studios/{id}/exports           -> StudioExportRef
 * - GET  /studios/{id}/exports/{export_id} -> StudioExportLink
 * - POST /studios/{id}/deletion {confirm_slug} -> StudioDeletion
 * - DELETE /studios/{id}/deletion        -> 204 (annule pendant le délai)
 */
import { ApiError, parseErrorBody } from "./api";
import { observedFetch } from "./apiEvents";
import { getToken } from "./auth";
import { clientNegotiationHeaders } from "./clientIdentity";

/** Préfixe canonique du serveur (comme openapi-schema : /api/v1/…). */
export const STUDIO_API_PREFIX = "/api/v1";

export type StudioPlan = "free" | "pro";
export type StudioStatus = "active" | "suspended";
/** Rôle porté par l'objet studio (le créateur est « owner »). */
export type StudioRole = "owner" | "admin" | "member" | "viewer";
/** Rôles modifiables d'un membre (PATCH /members/{user_id}). */
export type MemberRole = "admin" | "member" | "viewer";

/** Élément de GET /studios et réponse de POST /studios. */
export interface StudioSummary {
  id: string;
  slug: string;
  name: string;
  plan: StudioPlan;
  status: StudioStatus;
  role: StudioRole;
}

/** Réponse de GET /studios/{id} : le détail ajoute l'échéance de suppression. */
export interface Studio extends StudioSummary {
  deletion_scheduled_at: string | null;
}

export interface StudioInvitation {
  id: string;
  studio_id: string;
  email: string;
  role: StudioRole;
  expires_at: string;
  consumed_at: string | null;
  invited_by_user_id: string;
  created_at: string;
}

export interface StudioMember {
  studio_id: string;
  user_id: string;
  role: StudioRole;
  granted_by_user_id: string | null;
  created_at: string;
  user_display_name: string | null;
  user_email: string | null;
}

export interface InvitationAcceptance {
  status: "accepted";
  studio_id: string;
  role: StudioRole;
}

/**
 * POST /invitations/preview : état du lien d'invitation, avant acceptation.
 * `unknown` = jeton inconnu (champs null) ; les champs de présentation ne
 * sont renseignés que pour un jeton valide.
 */
export type InvitationPreviewState = "valid" | "expired" | "used" | "unknown";

export interface InvitationPreview {
  state: InvitationPreviewState;
  studio_name: string | null;
  role: StudioRole | null;
  inviter_display_name: string | null;
}

/** POST /studios/{id}/exports : l'export démarre, le lien arrive plus tard. */
export interface StudioExportRef {
  id: string;
}

/** GET /studios/{id}/exports/{export_id} : lien pré-signé de courte durée. */
export interface StudioExportLink {
  download_url: string;
  expires_at: string;
}

export interface StudioDeletion {
  deletion_scheduled_at: string;
}

async function request<T>(
  baseUrl: string,
  path: string,
  method: "GET" | "POST" | "PATCH" | "DELETE",
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...clientNegotiationHeaders() };
  const token = getToken();
  if (token !== null) headers["Authorization"] = `Bearer ${token}`;
  const init: RequestInit = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await observedFetch(`${baseUrl}${STUDIO_API_PREFIX}${path}`, init);
  const payload: unknown = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(parseErrorBody(response.status, payload));
  return payload as T;
}

const studioPath = (studioId: string): string => `/studios/${encodeURIComponent(studioId)}`;

export function listStudios(baseUrl: string): Promise<StudioSummary[]> {
  return request<StudioSummary[]>(baseUrl, "/studios", "GET");
}

export function createStudio(baseUrl: string, name: string): Promise<StudioSummary> {
  return request<StudioSummary>(baseUrl, "/studios", "POST", { name });
}

export function getStudio(baseUrl: string, studioId: string): Promise<Studio> {
  return request<Studio>(baseUrl, studioPath(studioId), "GET");
}

export function listStudioInvitations(baseUrl: string, studioId: string): Promise<StudioInvitation[]> {
  return request<StudioInvitation[]>(baseUrl, `${studioPath(studioId)}/invitations`, "GET");
}

export function createStudioInvitation(
  baseUrl: string,
  studioId: string,
  email: string,
  role: MemberRole,
): Promise<StudioInvitation> {
  return request<StudioInvitation>(baseUrl, `${studioPath(studioId)}/invitations`, "POST", { email, role });
}

export function revokeStudioInvitation(baseUrl: string, studioId: string, invitationId: string): Promise<void> {
  return request<void>(baseUrl, `${studioPath(studioId)}/invitations/${encodeURIComponent(invitationId)}`, "DELETE");
}

/**
 * Lecture de l'état d'un lien d'invitation, sans l'accepter : sert à
 * distinguer « valide », « expirée », « déjà utilisée » et « inconnue ».
 */
export function previewInvitation(baseUrl: string, token: string): Promise<InvitationPreview> {
  return request<InvitationPreview>(baseUrl, "/invitations/preview", "POST", { token });
}

/** 410 = invitation expirée ou déjà utilisée (voir error_code dans ApiError). */
export function acceptInvitation(baseUrl: string, token: string): Promise<InvitationAcceptance> {
  return request<InvitationAcceptance>(baseUrl, "/invitations/accept", "POST", { token });
}

export function listStudioMembers(baseUrl: string, studioId: string): Promise<StudioMember[]> {
  return request<StudioMember[]>(baseUrl, `${studioPath(studioId)}/members`, "GET");
}

export function updateStudioMemberRole(
  baseUrl: string,
  studioId: string,
  userId: string,
  role: MemberRole,
): Promise<void> {
  return request<void>(
    baseUrl,
    `${studioPath(studioId)}/members/${encodeURIComponent(userId)}`,
    "PATCH",
    { role },
  );
}

export function removeStudioMember(baseUrl: string, studioId: string, userId: string): Promise<void> {
  return request<void>(baseUrl, `${studioPath(studioId)}/members/${encodeURIComponent(userId)}`, "DELETE");
}

export function transferStudioOwnership(baseUrl: string, studioId: string, userId: string): Promise<void> {
  return request<void>(baseUrl, `${studioPath(studioId)}/transfer-ownership`, "POST", { user_id: userId });
}

export function createStudioExport(baseUrl: string, studioId: string): Promise<StudioExportRef> {
  return request<StudioExportRef>(baseUrl, `${studioPath(studioId)}/exports`, "POST");
}

export function getStudioExport(baseUrl: string, studioId: string, exportId: string): Promise<StudioExportLink> {
  return request<StudioExportLink>(
    baseUrl,
    `${studioPath(studioId)}/exports/${encodeURIComponent(exportId)}`,
    "GET",
  );
}

/** `confirmSlug` = slug du studio, retapé dans le dialogue de conséquences. */
export function scheduleStudioDeletion(baseUrl: string, studioId: string, confirmSlug: string): Promise<StudioDeletion> {
  return request<StudioDeletion>(baseUrl, `${studioPath(studioId)}/deletion`, "POST", { confirm_slug: confirmSlug });
}

/** Annule la suppression programmée pendant le délai de grâce. */
export function cancelStudioDeletion(baseUrl: string, studioId: string): Promise<void> {
  return request<void>(baseUrl, `${studioPath(studioId)}/deletion`, "DELETE");
}
