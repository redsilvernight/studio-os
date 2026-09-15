import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import {
  createTransfer,
  partRange,
  sha256Hex,
  uploadPhaseLabel,
  uploadTransfer,
} from "./transfersApi";

type Fake = Record<"POST", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});

const created = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 201 } as Response,
});

const fail = (status: number, error: unknown): { data?: undefined; error: unknown; response: Response } => ({
  error,
  response: { ok: false, status } as Response,
});

describe("createTransfer", () => {
  it("sends the Idempotency-Key and metadata, never bytes", async () => {
    const POST = vi.fn().mockResolvedValue(created({ id: "tr1" }));
    await createTransfer(
      fakeClient({ POST }),
      {
        recipient_user_id: null,
        project_id: "p1",
        task_id: null,
        category: "temporary",
        filename: "a.bin",
        content_type: "application/octet-stream",
        size_bytes: 10,
      },
      "key-1",
    );
    expect(POST).toHaveBeenCalledWith("/api/v1/transfers", {
      params: { header: { "Idempotency-Key": "key-1" } },
      body: expect.objectContaining({ filename: "a.bin", size_bytes: 10 }),
    });
  });
});

describe("partRange", () => {
  it("clamps the last part to the payload size", () => {
    expect(partRange(1, 10, 25)).toEqual([0, 10]);
    expect(partRange(3, 10, 25)).toEqual([20, 25]);
  });
});

describe("sha256Hex", () => {
  it("matches the known SHA-256 vector", async () => {
    const bytes = new TextEncoder().encode("abc");
    await expect(sha256Hex(bytes)).resolves.toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });
});

describe("uploadPhaseLabel", () => {
  it("renders progress and terminal phases", () => {
    expect(uploadPhaseLabel({ phase: "hashing", uploadedBytes: 0, totalBytes: 10 })).toBe("Hashing…");
    expect(uploadPhaseLabel({ phase: "uploading", uploadedBytes: 5, totalBytes: 10 })).toBe("Uploading… 50%");
    expect(uploadPhaseLabel({ phase: "done", uploadedBytes: 10, totalBytes: 10 })).toBe("Done");
  });
});

function transfer(size: number) {
  return { id: "tr1", size_bytes: size, content_type: "application/octet-stream" } as never;
}

async function fileOf(size: number): Promise<File> {
  return new File([new Uint8Array(size).fill(7)], "a.bin", { type: "application/octet-stream" });
}

describe("uploadTransfer", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("falls back to content_md5 and PUTs the bytes straight to storage", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, headers: new Headers() });
    vi.stubGlobal("fetch", fetchMock);
    const POST = vi
      .fn()
      .mockResolvedValueOnce(fail(422, { detail: { error_code: "missing_content_md5" } }))
      .mockResolvedValueOnce(ok({ transfer_id: "tr1", multipart: false, upload_url: "https://storage/put" }))
      .mockResolvedValueOnce(ok({ id: "tr1", status: "ready" }));
    const file = await fileOf(3);
    const states: string[] = [];
    const result = await uploadTransfer(fakeClient({ POST }), transfer(3), file, (state) => states.push(state.phase));

    expect(result).toMatchObject({ status: "ready" });
    const put = fetchMock.mock.calls[0] ?? [];
    expect(put[0]).toBe("https://storage/put");
    expect((put[1] as RequestInit).method).toBe("PUT");
    expect((put[1] as { headers: Record<string, string> }).headers["Content-MD5"]).toBeTruthy();
    expect(states).toContain("completing");
    expect(POST).toHaveBeenCalledTimes(3);
  });

  it("uploads each multipart part and completes with its ETag", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      headers: new Headers({ ETag: url.endsWith("/1") ? '"etag-1"' : '"etag-2"' }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const POST = vi
      .fn()
      .mockResolvedValueOnce(
        ok({
          transfer_id: "tr1",
          multipart: true,
          upload_id: "up-1",
          part_urls: { "1": "https://storage/part/1", "2": "https://storage/part/2" },
          part_size_bytes: 4,
        }),
      )
      .mockResolvedValueOnce(ok({ id: "tr1", status: "ready" }));
    const file = await fileOf(6);
    await uploadTransfer(fakeClient({ POST }), transfer(6), file);

    const completeCall = POST.mock.calls[1] ?? [];
    expect(completeCall[0]).toBe("/api/v1/transfers/{transfer_id}/upload/complete");
    expect((completeCall[1] as { body: unknown }).body).toMatchObject({
      size_bytes: 6,
      upload_id: "up-1",
      parts: { 1: "etag-1", 2: "etag-2" },
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("refuses a local file whose size disagrees with the declared transfer", async () => {
    const file = await fileOf(3);
    await expect(uploadTransfer(fakeClient({ POST: vi.fn() }), transfer(5), file)).rejects.toThrow(/expects 5/);
  });
});
