/**
 * MC P05 — admission batch d'une roadmap (DEC-0216, DEC-0218).
 *
 * Enveloppes minces : le serveur calcule seul l'éligibilité, l'ordre et les
 * raisons ; le dashboard affiche le dry-run tel quel et renvoie son
 * `plan_digest` à l'admission. Un `409 admission_plan_changed` porte le plan
 * frais, un `409 admission_refused` les refus par item ; rien n'est créé.
 *
 * La clé de rejeu d'un lot est conservée en `sessionStorage` par roadmap et
 * corps de requête : un rechargement pendant l'envoi rejoue la même clé (le
 * serveur rend la réponse d'origine), jamais un second lot.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import { newIdempotencyKey } from "./claimsApi";
import type { components } from "./openapi-schema";

export type AdmissionDryRun = components["schemas"]["AdmissionDryRun"];
export type AdmissionCandidate = components["schemas"]["AdmissionCandidate"];
export type AdmissionExclusion = components["schemas"]["AdmissionExclusion"];
export type AdmissionExclusionReason = components["schemas"]["AdmissionExclusionReason"];
export type AdmissionBatchItem = components["schemas"]["AdmissionBatchItem"];
export type AdmissionBatchRequest = components["schemas"]["AdmissionBatchRequest"];
export type AdmissionBatchResult = components["schemas"]["AdmissionBatchResult"];

export type AdmissionRefusalReason = "duplicate_item" | "not_launchable" | "machine_not_eligible" | "budget_refused";

export interface AdmissionRefusal {
  task_id: string;
  machine_id: string;
  reason: AdmissionRefusalReason;
  exclusion_reasons?: AdmissionExclusionReason[];
  budget?: Record<string, unknown> | null;
}

export interface AdmissionBatchRefused {
  error_code: "admission_plan_changed" | "admission_refused";
  plan?: AdmissionDryRun | null;
  refusals?: AdmissionRefusal[];
}

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function getAdmissionDryRun(
  client: StudioClient,
  roadmapId: string,
  harnessId: string | null,
): Promise<AdmissionDryRun> {
  return unwrap(
    client.GET("/api/v1/roadmaps/{roadmap_id}/admission/dry-run", {
      params: { path: { roadmap_id: roadmapId }, query: harnessId === null ? {} : { harness_id: harnessId } },
    }),
  );
}

export function admitRoadmapBatch(
  client: StudioClient,
  roadmapId: string,
  body: AdmissionBatchRequest,
  idempotencyKey: string,
): Promise<AdmissionBatchResult> {
  return unwrap(
    client.POST("/api/v1/roadmaps/{roadmap_id}/admission", {
      params: { path: { roadmap_id: roadmapId }, header: { "Idempotency-Key": idempotencyKey } },
      body,
    }),
  );
}

/** The typed `409` body of an admission, or `null` for any other error. */
export function admissionRefusal(error: unknown): AdmissionBatchRefused | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  if (error.errorCode !== "admission_plan_changed" && error.errorCode !== "admission_refused") return null;
  return error.details as AdmissionBatchRefused;
}

const KEY_PREFIX = "studio.admission.";

function storageKey(roadmapId: string): string {
  return `${KEY_PREFIX}${roadmapId}`;
}

function bodyFingerprint(body: AdmissionBatchRequest): string {
  return JSON.stringify(body);
}

/**
 * Replay key for this exact batch body: reused while the same body is pending
 * (reload, reconnect, double click), new for any other body.
 */
export function pendingAdmissionKey(roadmapId: string, body: AdmissionBatchRequest, storage: Storage = sessionStorage): string {
  const fingerprint = bodyFingerprint(body);
  try {
    const raw = storage.getItem(storageKey(roadmapId));
    if (raw !== null) {
      const stored = JSON.parse(raw) as { key?: unknown; body?: unknown };
      if (typeof stored.key === "string" && stored.body === fingerprint) return stored.key;
    }
  } catch {
    /* unreadable entry: replaced below */
  }
  const key = newIdempotencyKey();
  try {
    storage.setItem(storageKey(roadmapId), JSON.stringify({ key, body: fingerprint }));
  } catch {
    /* storage unavailable: the key still guards this page's retries */
  }
  return key;
}

/** The pending batch body left by a previous page, if any (to resume after a reload). */
export function pendingAdmissionBody(roadmapId: string, storage: Storage = sessionStorage): AdmissionBatchRequest | null {
  try {
    const raw = storage.getItem(storageKey(roadmapId));
    if (raw === null) return null;
    const stored = JSON.parse(raw) as { body?: unknown };
    return typeof stored.body === "string" ? (JSON.parse(stored.body) as AdmissionBatchRequest) : null;
  } catch {
    return null;
  }
}

/** Forget the pending batch once the server answered definitively (201 or 409). */
export function clearPendingAdmission(roadmapId: string, storage: Storage = sessionStorage): void {
  try {
    storage.removeItem(storageKey(roadmapId));
  } catch {
    /* nothing to clear */
  }
}
