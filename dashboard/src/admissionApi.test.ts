import { describe, expect, it } from "vitest";
import type { AdmissionBatchRequest } from "./admissionApi";
import { clearPendingAdmission, pendingAdmissionBody, pendingAdmissionKey } from "./admissionApi";

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
      return map.has(key) ? (map.get(key) as string) : null;
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

const body = (overrides: Partial<AdmissionBatchRequest> = {}): AdmissionBatchRequest => ({
  plan_digest: "digest-1",
  harness_id: "claude-code",
  items: [{ task_id: "t1", machine_id: "m1" }],
  expires_in_seconds: 900,
  ...overrides,
});

describe("pendingAdmissionKey", () => {
  it("reuse la même clé pour le même corps", () => {
    const storage = memoryStorage();
    const first = pendingAdmissionKey("r1", body(), storage);
    const again = pendingAdmissionKey("r1", body(), storage);
    expect(again).toBe(first);
  });

  it("génère une nouvelle clé pour un autre corps", () => {
    const storage = memoryStorage();
    const first = pendingAdmissionKey("r1", body(), storage);
    const other = pendingAdmissionKey("r1", body({ plan_digest: "digest-2" }), storage);
    expect(other).not.toBe(first);
  });

  it("isole les roadmaps", () => {
    const storage = memoryStorage();
    const first = pendingAdmissionKey("r1", body(), storage);
    const other = pendingAdmissionKey("r2", body(), storage);
    expect(other).not.toBe(first);
  });

  it("clear oublie le corps et la clé", () => {
    const storage = memoryStorage();
    pendingAdmissionKey("r1", body(), storage);
    expect(pendingAdmissionBody("r1", storage)).toEqual(body());
    clearPendingAdmission("r1", storage);
    expect(pendingAdmissionBody("r1", storage)).toBeNull();
    // Une nouvelle clé est émise après nettoyage.
    const afterClear = pendingAdmissionKey("r1", body(), storage);
    expect(afterClear).toBeTruthy();
  });
});
