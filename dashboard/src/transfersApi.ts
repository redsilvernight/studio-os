/**
 * DASH-5 — transfer creation + direct-to-storage upload.
 *
 * Bytes NEVER pass through the API: `POST /transfers` declares metadata and
 * reserves quota, then the dashboard PUTs to the pre-signed URL(s) handed back
 * by `POST /transfers/{id}/upload/initiate`, exactly like the Python
 * `TransferClient` (`packages/studio-client/.../transfers.py`). The browser
 * cannot reuse that module (httpx/Path/SQLite), so the small state machine is
 * mirrored here:
 * - small file (≤ 128 MiB server-side): initiate without a checksum → the
 *   server answers `422 missing_content_md5` → retry with the base64 MD5 →
 *   single PUT with the matching `Content-MD5` header → complete;
 * - large file: initiate → multipart parts (64 MiB) PUT in bounded parallel →
 *   complete with each part's ETag.
 * Multipart part state is in-memory only: a resumable UI is out of scope, and
 * no token or upload state is ever persisted locally.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import { newIdempotencyKey } from "./claimsApi";
import { md5Base64 } from "./md5";
import type { components } from "./openapi-schema";

export type Transfer = components["schemas"]["Transfer"];
export type TransferCreate = components["schemas"]["TransferCreate"];
export type TransferConsumption = components["schemas"]["TransferConsumption"];
export type UploadInitiateResponse = components["schemas"]["UploadInitiateResponse"];
export type UploadCompleteRequest = components["schemas"]["UploadCompleteRequest"];

/** Server constants (`services/transfers.py`), mirrored for progress display. */
export const MULTIPART_THRESHOLD_BYTES = 128 * 1024 * 1024;
export const PART_SIZE_BYTES = 64 * 1024 * 1024;
export const PART_CONCURRENCY = 4;

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function createTransfer(
  client: StudioClient,
  input: TransferCreate,
  key: string = newIdempotencyKey(),
): Promise<Transfer> {
  return unwrap(
    client.POST("/api/v1/transfers", {
      params: { header: { "Idempotency-Key": key } },
      body: input,
    }),
  );
}

export function listTransfers(client: StudioClient, projectId?: string): Promise<Transfer[]> {
  return unwrap(
    client.GET("/api/v1/transfers", {
      params: { query: projectId !== undefined ? { project_id: projectId } : {} },
    }),
  );
}

export function getConsumption(client: StudioClient, projectId?: string): Promise<TransferConsumption> {
  return unwrap(
    client.GET("/api/v1/transfers/consumption", {
      params: { query: projectId !== undefined ? { project_id: projectId } : {} },
    }),
  );
}

export function initiateUpload(
  client: StudioClient,
  transferId: string,
  contentMd5?: string,
): Promise<UploadInitiateResponse> {
  return unwrap(
    client.POST("/api/v1/transfers/{transfer_id}/upload/initiate", {
      params: { path: { transfer_id: transferId } },
      body: contentMd5 === undefined ? {} : { content_md5: contentMd5 },
    }),
  );
}

export function completeUpload(
  client: StudioClient,
  transferId: string,
  body: UploadCompleteRequest,
): Promise<Transfer> {
  return unwrap(
    client.POST("/api/v1/transfers/{transfer_id}/upload/complete", {
      params: { path: { transfer_id: transferId } },
      body,
    }),
  );
}

export function downloadUrl(client: StudioClient, transferId: string): Promise<{ download_url: string }> {
  return unwrap(
    client.POST("/api/v1/transfers/{transfer_id}/download-url", {
      params: { path: { transfer_id: transferId } },
    }),
  );
}

export async function sha256Hex(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Half-open byte range of a multipart part, clamped to the payload. */
export function partRange(partNumber: number, partSize: number, totalBytes: number): [number, number] {
  const start = (partNumber - 1) * partSize;
  const end = Math.min(start + partSize, totalBytes);
  return [start, end];
}

async function putToSignedUrl(url: string, body: BodyInit, headers?: Record<string, string>): Promise<Response> {
  const response = await fetch(url, { method: "PUT", body, headers });
  if (!response.ok) throw new Error(`storage PUT failed: HTTP ${response.status}`);
  return response;
}

async function runBounded<T>(items: T[], limit: number, worker: (item: T) => Promise<void>): Promise<void> {
  let cursor = 0;
  const runner = async (): Promise<void> => {
    while (cursor < items.length) {
      const item = items[cursor];
      cursor += 1;
      if (item !== undefined) await worker(item);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, runner));
}

export interface UploadProgress {
  phase: "hashing" | "uploading" | "completing" | "done";
  uploadedBytes: number;
  totalBytes: number;
}

/**
 * Declares the bytes and uploads them straight to storage. `transfer` must be
 * `created` (not `ready`) and `file.size` must equal `transfer.size_bytes`
 * (server-enforced on completion anyway). Never sends bytes through the API.
 */
export async function uploadTransfer(
  client: StudioClient,
  transfer: Transfer,
  file: File,
  onProgress: (progress: UploadProgress) => void = () => {},
): Promise<Transfer> {
  if (file.size !== transfer.size_bytes) {
    throw new Error(
      `local file is ${file.size} bytes but transfer ${transfer.id} expects ${transfer.size_bytes}`,
    );
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  onProgress({ phase: "hashing", uploadedBytes: 0, totalBytes: file.size });

  const md5 = md5Base64(bytes);
  let init: UploadInitiateResponse;
  try {
    init = await initiateUpload(client, transfer.id);
  } catch (error) {
    if (error instanceof ApiError && error.errorCode === "missing_content_md5") {
      init = await initiateUpload(client, transfer.id, md5);
    } else {
      throw error;
    }
  }

  const sha256 = await sha256Hex(bytes);

  if (!init.multipart) {
    if (!init.upload_url) throw new Error("initiate did not return a single upload URL");
    onProgress({ phase: "uploading", uploadedBytes: 0, totalBytes: file.size });
    await putToSignedUrl(init.upload_url, bytes, {
      "Content-Type": transfer.content_type,
      "Content-MD5": md5,
    });
    onProgress({ phase: "completing", uploadedBytes: file.size, totalBytes: file.size });
    const done = await completeUpload(client, transfer.id, { size_bytes: file.size, sha256 });
    onProgress({ phase: "done", uploadedBytes: file.size, totalBytes: file.size });
    return done;
  }

  const uploadId = init.upload_id;
  if (!uploadId) throw new Error("initiate returned multipart without an upload_id");
  const partSize = init.part_size_bytes ?? PART_SIZE_BYTES;
  const partUrls = init.part_urls ?? {};
  const partNumbers = Object.keys(partUrls)
    .map((key) => Number.parseInt(key, 10))
    .filter((value) => Number.isInteger(value) && value > 0)
    .sort((a, b) => a - b);

  const parts: Record<number, string> = {};
  let uploaded = 0;
  onProgress({ phase: "uploading", uploadedBytes: 0, totalBytes: file.size });

  await runBounded(partNumbers, PART_CONCURRENCY, async (partNumber) => {
    const url = partUrls[String(partNumber)];
    if (url === undefined) return;
    const [start, end] = partRange(partNumber, partSize, file.size);
    const chunk = bytes.subarray(start, end);
    const response = await putToSignedUrl(url, chunk);
    const etag = response.headers.get("ETag");
    if (etag === null || etag === "") {
      throw new Error(
        `storage did not expose the ETag for part ${partNumber} (CORS must expose it); cannot complete multipart`,
      );
    }
    parts[partNumber] = etag.replace(/^"|"$/g, "");
    uploaded += chunk.byteLength;
    onProgress({ phase: "uploading", uploadedBytes: uploaded, totalBytes: file.size });
  });

  onProgress({ phase: "completing", uploadedBytes: file.size, totalBytes: file.size });
  const done = await completeUpload(client, transfer.id, {
    size_bytes: file.size,
    sha256,
    upload_id: uploadId,
    parts,
  });
  onProgress({ phase: "done", uploadedBytes: file.size, totalBytes: file.size });
  return done;
}

export function uploadPhaseLabel(progress: UploadProgress): string {
  const percent = progress.totalBytes === 0 ? 0 : Math.round((progress.uploadedBytes / progress.totalBytes) * 100);
  switch (progress.phase) {
    case "hashing":
      return "Hashing…";
    case "uploading":
      return `Uploading… ${percent}%`;
    case "completing":
      return "Finalising…";
    case "done":
      return "Done";
  }
}
