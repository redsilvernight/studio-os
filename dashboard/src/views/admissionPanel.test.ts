// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import type { AdmissionBatchRequest, AdmissionBatchResult, AdmissionCandidate, AdmissionDryRun } from "../admissionApi";
import { pendingAdmissionBody, pendingAdmissionKey } from "../admissionApi";
import type { MachineEligibility } from "../taskLaunchesApi";
import { renderAdmissionPanelInto } from "./admissionPanel";

type Result<T> = { data?: T; error?: unknown; response: Response };
const ok = <T>(data: T, status = 200): Result<T> => ({ data, response: { ok: true, status } as Response });
const fail = (status: number, error: unknown): Result<undefined> => ({ error, response: { ok: false, status } as Response });

type Fake = { GET: ReturnType<typeof vi.fn>; POST: ReturnType<typeof vi.fn> };
const fakeClient = (impl: Partial<Fake> = {}): StudioClient =>
  ({ GET: vi.fn(), POST: vi.fn(), ...impl }) as unknown as StudioClient;

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

function machine(machineId: string, displayName: string, harnessIds: string[]): MachineEligibility {
  return {
    machine_id: machineId,
    display_name: displayName,
    status: "online",
    eligible: true,
    free_slots: 1,
    reasons: [],
    harnesses: harnessIds.map((harnessId) => ({ harness_id: harnessId, detected: true, configured: true })),
  } as MachineEligibility;
}

const candidate = (taskId: string, stepKey: string, title: string, machineIds: string[]): AdmissionCandidate => ({
  task_id: taskId,
  step_key: stepKey,
  title,
  machine_ids: machineIds,
});

function dryRun(launchable: AdmissionCandidate[], overrides: Partial<AdmissionDryRun> = {}): AdmissionDryRun {
  return {
    roadmap_id: "r1",
    project_id: "p1",
    roadmap_status: "active",
    roadmap_version: 1,
    harness_id: null,
    launchable,
    excluded: [],
    steps_without_tasks: [],
    machines: [machine("m1", "flo-laptop", ["claude-code"]), machine("m2", "mathieu-desktop", ["claude-code", "opencode"])],
    plan_digest: "abcdef0123456789aabb",
    evaluated_at: new Date().toISOString(),
    ...overrides,
  } as AdmissionDryRun;
}

function batchResult(launches: number): AdmissionBatchResult {
  return {
    roadmap_id: "r1",
    plan_digest: "abcdef0123456789aabb",
    launches: Array.from({ length: launches }, (_, index) => ({ id: `l${index + 1}` })),
    admitted_at: new Date().toISOString(),
  } as unknown as AdmissionBatchResult;
}

async function render(client: StudioClient, storage: Storage = memoryStorage()): Promise<{ root: HTMLElement; storage: Storage }> {
  const root = document.createElement("div");
  document.body.append(root);
  await renderAdmissionPanelInto(root, { client, roadmapId: "r1", storage });
  return { root, storage };
}

function click(root: HTMLElement, selector: string): void {
  const node = root.querySelector<HTMLElement>(selector);
  expect(node, selector).not.toBeNull();
  node?.click();
}

function option(root: HTMLElement, selector: string, value: string): void {
  const select = root.querySelector<HTMLSelectElement>(selector);
  expect(select, selector).not.toBeNull();
  if (select === null) return;
  select.value = value;
  select.dispatchEvent(new Event("change"));
}

async function preview(root: HTMLElement): Promise<void> {
  click(root, "[data-admission-preview]");
  await vi.waitFor(() => expect(root.querySelector("[data-admission-launchable], [data-admission-excluded]")).not.toBeNull());
}

async function chooseHarness(root: HTMLElement, harnessId: string): Promise<void> {
  option(root, "[data-admission-harness]", harnessId);
  await vi.waitFor(() => expect(root.querySelector<HTMLButtonElement>("[data-admission-confirm]")?.disabled).toBe(false));
}

describe("admissionPanel", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="ds-toast-region"></div>`;
  });

  it("respecte l'ordre serveur des tâches lançables et affiche l'empreinte", async () => {
    const GET = vi.fn().mockResolvedValue(
      ok(dryRun([candidate("t2", "S2", "Deuxième", ["m1"]), candidate("t1", "S1", "Première", ["m1", "m2"])])),
    );
    const { root } = await render(fakeClient({ GET }));
    await preview(root);

    const ids = [...root.querySelectorAll("[data-admission-launchable] li[data-task-id]")].map((li) =>
      li.getAttribute("data-task-id"),
    );
    expect(ids).toEqual(["t2", "t1"]);
    expect(root.querySelector("[data-admission-digest]")?.textContent).toContain("abcdef012345");
    expect(root.querySelector("[data-admission-pick]")).toBeInstanceOf(HTMLInputElement);
    expect(root.querySelector<HTMLInputElement>("[data-admission-pick]")?.checked).toBe(true);
    const machineLabel = root.querySelector<HTMLSelectElement>("[data-admission-machine] option")?.textContent;
    expect(machineLabel).toContain("flo-laptop");
  });

  it("affiche les raisons d'exclusion en français avec leur code", async () => {
    const GET = vi.fn().mockResolvedValue(
      ok(
        dryRun([], {
          excluded: [
            { task_id: "t3", step_key: "S3", title: "Troisième", reasons: ["dependency_pending", "task_blocked"] },
          ],
        }),
      ),
    );
    const { root } = await render(fakeClient({ GET }));
    await preview(root);

    const reasons = [...root.querySelectorAll("[data-admission-excluded] li[data-admission-reason]")];
    expect(reasons.map((node) => node.getAttribute("data-admission-reason"))).toEqual(["dependency_pending", "task_blocked"]);
    expect(reasons[0]?.textContent).toContain("dépendance");
    expect(reasons[1]?.textContent).toContain("bloquée");
  });

  it("n'envoie rien sans une confirmation explicite, puis envoie le corps attendu", async () => {
    const GET = vi.fn().mockResolvedValue(ok(dryRun([candidate("t1", "S1", "Première", ["m1", "m2"])])));
    const POST = vi.fn().mockResolvedValue(ok(batchResult(1), 201));
    const { root } = await render(fakeClient({ GET, POST }));
    await preview(root);

    const confirm = (): HTMLButtonElement => root.querySelector<HTMLButtonElement>("[data-admission-confirm]") as HTMLButtonElement;
    expect(confirm().disabled).toBe(true);
    expect(POST).not.toHaveBeenCalled();

    await chooseHarness(root, "claude-code");
    expect(confirm().textContent).toContain("Lancer 1 tâche");
    expect(POST).not.toHaveBeenCalled();

    confirm().click();
    const dialog = root.querySelector("[data-admission-confirmation]");
    expect(dialog?.getAttribute("role")).toBe("alertdialog");
    expect(dialog?.textContent).toContain("claude-code");
    expect(dialog?.textContent).toContain("flo-laptop");
    expect(POST).not.toHaveBeenCalled();

    click(root, "[data-admission-cancel]");
    expect(root.querySelector("[data-admission-confirmation]")).toBeNull();
    expect(POST).not.toHaveBeenCalled();

    confirm().click();
    click(root, "[data-admission-submit]");
    await vi.waitFor(() => expect(POST).toHaveBeenCalledTimes(1));
    const sent = (POST.mock.calls[0]?.[1] as { params: { header: Record<string, string> } }).params;
    const body = (POST.mock.calls[0]?.[1] as { body: AdmissionBatchRequest }).body;
    expect(sent.header["Idempotency-Key"]).toBeTruthy();
    expect(body).toEqual({
      plan_digest: "abcdef0123456789aabb",
      harness_id: "claude-code",
      items: [{ task_id: "t1", machine_id: "m1" }],
      expires_in_seconds: 7200,
    });
    await vi.waitFor(() => expect(root.querySelector("[data-admission-result]")?.textContent).toContain("1 lancement"));
  });

  it("désactive submit et n'envoie qu'un seul appel sur double clic", async () => {
    const GET = vi.fn().mockResolvedValue(ok(dryRun([candidate("t1", "S1", "Première", ["m1"])])));
    let resolvePost: (value: Result<AdmissionBatchResult>) => void = () => undefined;
    const POST = vi.fn().mockImplementation(() => new Promise<Result<AdmissionBatchResult>>((resolve) => { resolvePost = resolve; }));
    const { root } = await render(fakeClient({ GET, POST }));
    await preview(root);
    await chooseHarness(root, "claude-code");
    click(root, "[data-admission-confirm]");

    const submit = root.querySelector<HTMLButtonElement>("[data-admission-submit]") as HTMLButtonElement;
    submit.click();
    submit.click();
    submit.click();
    expect(POST).toHaveBeenCalledTimes(1);
    expect(root.querySelector<HTMLButtonElement>("[data-admission-submit]")?.disabled).toBe(true);

    resolvePost(ok(batchResult(1), 201));
    await vi.waitFor(() => expect(root.querySelector("[data-admission-result]")).not.toBeNull());
  });

  it("sur 409 plan_changed, remplace le plan, vide la clé et exige une nouvelle confirmation", async () => {
    const first = dryRun([candidate("t1", "S1", "Première", ["m1"])], { plan_digest: "digest-old00000" });
    const fresh = dryRun([candidate("t1", "S1", "Première", ["m1"])], { plan_digest: "digest-new11111" });
    const GET = vi.fn().mockResolvedValue(ok(first));
    const POST = vi.fn().mockResolvedValue(fail(409, { detail: { error_code: "admission_plan_changed", plan: fresh } }));
    const { root, storage } = await render(fakeClient({ GET, POST }));
    await preview(root);
    await chooseHarness(root, "claude-code");
    click(root, "[data-admission-confirm]");
    click(root, "[data-admission-submit]");

    await vi.waitFor(() => expect(root.querySelector("[data-admission-stale]")).not.toBeNull());
    expect(pendingAdmissionBody("r1", storage)).toBeNull();
    expect(root.querySelector("[data-admission-confirmation]")).toBeNull();
    expect(root.querySelector("[data-admission-digest]")?.textContent).toContain("digest-new11");
  });

  it("sur 409 refused, liste chaque refus avec sa raison", async () => {
    const GET = vi.fn().mockResolvedValue(ok(dryRun([candidate("t1", "S1", "Première", ["m1"])])));
    const POST = vi.fn().mockResolvedValue(
      fail(409, {
        detail: {
          error_code: "admission_refused",
          refusals: [
            { task_id: "t1", machine_id: "m1", reason: "machine_not_eligible", exclusion_reasons: ["no_eligible_machine"] },
          ],
        },
      }),
    );
    const { root, storage } = await render(fakeClient({ GET, POST }));
    await preview(root);
    await chooseHarness(root, "claude-code");
    click(root, "[data-admission-confirm]");
    click(root, "[data-admission-submit]");

    await vi.waitFor(() => expect(root.querySelector("[data-admission-refusals]")).not.toBeNull());
    const items = [...root.querySelectorAll("[data-admission-refusals] li[data-admission-refusal]")];
    expect(items.map((node) => node.getAttribute("data-admission-refusal"))).toEqual(["machine_not_eligible"]);
    expect(items[0]?.textContent).toContain("poste");
    expect(pendingAdmissionBody("r1", storage)).toBeNull();
  });

  it("sur erreur réseau, garde la clé et réessaie le même corps", async () => {
    const GET = vi.fn().mockResolvedValue(ok(dryRun([candidate("t1", "S1", "Première", ["m1"])])));
    const POST = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValueOnce(ok(batchResult(1), 201));
    const { root, storage } = await render(fakeClient({ GET, POST }));
    await preview(root);
    await chooseHarness(root, "claude-code");
    click(root, "[data-admission-confirm]");
    click(root, "[data-admission-submit]");

    await vi.waitFor(() => expect(root.querySelector("[data-admission-retry]")).not.toBeNull());
    const firstKey = (POST.mock.calls[0]?.[1] as { params: { header: Record<string, string> } }).params.header["Idempotency-Key"];
    const firstBody = (POST.mock.calls[0]?.[1] as { body: AdmissionBatchRequest }).body;
    expect(pendingAdmissionBody("r1", storage)).toEqual(firstBody);

    click(root, "[data-admission-retry]");
    await vi.waitFor(() => expect(POST).toHaveBeenCalledTimes(2));
    const secondKey = (POST.mock.calls[1]?.[1] as { params: { header: Record<string, string> } }).params.header["Idempotency-Key"];
    const secondBody = (POST.mock.calls[1]?.[1] as { body: AdmissionBatchRequest }).body;
    expect(secondKey).toBe(firstKey);
    expect(secondBody).toEqual(firstBody);
  });

  it("démarre sans harnais choisi et ne confirme qu'après un choix explicite", async () => {
    const GET = vi.fn().mockResolvedValue(ok(dryRun([candidate("t1", "S1", "Première", ["m1"])])));
    const { root } = await render(fakeClient({ GET }));
    const harness = root.querySelector<HTMLSelectElement>("[data-admission-harness]") as HTMLSelectElement;
    expect(harness.value).toBe("");
    expect(harness.querySelector("option[value='']")?.textContent).toBe("Choisir un harnais");

    await preview(root);
    expect((GET.mock.calls[0]?.[1] as { params: { query: Record<string, string> } }).params.query).toEqual({});
    expect(root.querySelector<HTMLButtonElement>("[data-admission-confirm]")?.disabled).toBe(true);

    option(root, "[data-admission-harness]", "claude-code");
    await vi.waitFor(() =>
      expect((GET.mock.calls.at(-1)?.[1] as { params: { query: Record<string, string> } }).params.query).toEqual({ harness_id: "claude-code" }),
    );
    await vi.waitFor(() => expect(root.querySelector<HTMLButtonElement>("[data-admission-confirm]")?.disabled).toBe(false));
  });

  it("décocher la dernière tâche désactive le lancement", async () => {
    const GET = vi.fn().mockResolvedValue(
      ok(dryRun([candidate("t1", "S1", "Première", ["m1"]), candidate("t2", "S2", "Deuxième", ["m2"])])),
    );
    const POST = vi.fn();
    const { root } = await render(fakeClient({ GET, POST }));
    await preview(root);
    await chooseHarness(root, "claude-code");
    expect(root.querySelector("[data-admission-confirm]")?.textContent).toContain("Lancer 2 tâches");

    const boxes = root.querySelectorAll<HTMLInputElement>("[data-admission-pick]");
    boxes[0]!.checked = false;
    boxes[0]!.dispatchEvent(new Event("change"));
    expect(root.querySelector("[data-admission-confirm]")?.textContent).toContain("Lancer 1 tâche");

    const remaining = root.querySelectorAll<HTMLInputElement>("[data-admission-pick]");
    remaining[1]!.checked = false;
    remaining[1]!.dispatchEvent(new Event("change"));
    expect(root.querySelector<HTMLButtonElement>("[data-admission-confirm]")?.disabled).toBe(true);
    expect(POST).not.toHaveBeenCalled();
  });

  it("refuse un lot au-delà du plafond serveur plutôt que d'envoyer un corps refusé", async () => {
    const many = Array.from({ length: 51 }, (_, index) => candidate(`t${index + 1}`, `S${index + 1}`, `Tâche ${index + 1}`, ["m1"]));
    const GET = vi.fn().mockResolvedValue(ok(dryRun(many)));
    const POST = vi.fn();
    const { root } = await render(fakeClient({ GET, POST }));
    await preview(root);
    option(root, "[data-admission-harness]", "claude-code");
    await vi.waitFor(() => expect(root.querySelectorAll("[data-admission-launchable] li").length).toBe(51));

    expect(root.querySelector("[data-admission-overflow]")?.textContent).toContain("50");
    expect(root.querySelector<HTMLButtonElement>("[data-admission-confirm]")?.disabled).toBe(true);
    expect(POST).not.toHaveBeenCalled();
  });

it("propose de reprendre un envoi en attente sans envoi automatique", async () => {
    const storage = memoryStorage();
    const body: AdmissionBatchRequest = {
      plan_digest: "pending-digest",
      harness_id: "claude-code",
      items: [{ task_id: "t1", machine_id: "m1" }],
      expires_in_seconds: 7200,
    };
    const key = pendingAdmissionKey("r1", body, storage);
    const GET = vi.fn().mockResolvedValue(ok(dryRun([])));
    const POST = vi.fn().mockResolvedValue(ok(batchResult(1), 201));
    const { root } = await render(fakeClient({ GET, POST }), storage);

    expect(root.querySelector("[data-admission-resume]")).not.toBeNull();
    expect(POST).not.toHaveBeenCalled();

    click(root, "[data-admission-resume-send]");
    await vi.waitFor(() => expect(POST).toHaveBeenCalledTimes(1));
    const sentOptions = POST.mock.calls[0]?.[1] as { params: { header: Record<string, string> }; body: AdmissionBatchRequest };
    expect(sentOptions.params.header["Idempotency-Key"]).toBe(key);
    expect(sentOptions.body).toEqual(body);
  });

  it("conserve le harnais choisi après un nouveau dry-run même s'il n'est plus annoncé", async () => {
    const announced = dryRun([candidate("t1", "S1", "Première", ["m1"])]);
    const later = dryRun([candidate("t1", "S1", "Première", ["m1"])], {
      machines: [machine("m2", "mathieu-desktop", ["opencode"])],
    });
    const GET = vi.fn().mockImplementation((_path: string, options: { params?: { query?: Record<string, string> } }) =>
      Promise.resolve(ok(options?.params?.query?.harness_id === "claude-code" ? later : announced)),
    );
    const { root } = await render(fakeClient({ GET }));
    await preview(root);
    await chooseHarness(root, "claude-code");

    const harness = root.querySelector<HTMLSelectElement>("[data-admission-harness]") as HTMLSelectElement;
    expect(harness.value).toBe("claude-code");
    expect(harness.querySelector("option[value='claude-code']")).not.toBeNull();

    click(root, "[data-admission-preview]");
    await vi.waitFor(() =>
      expect((GET.mock.calls.at(-1)?.[1] as { params: { query: Record<string, string> } }).params.query).toEqual({
        harness_id: "claude-code",
      }),
    );

    const after = root.querySelector<HTMLSelectElement>("[data-admission-harness]") as HTMLSelectElement;
    expect(after.value).toBe("claude-code");
    expect(after.querySelector("option[value='claude-code']")).not.toBeNull();
  });

  it("ne propose que les harnais configurés, jamais ceux seulement détectés", async () => {
    const plan = dryRun([candidate("t1", "S1", "Première", ["m1"])], {
      machines: [
        {
          machine_id: "m1",
          display_name: "flo-laptop",
          status: "online",
          eligible: true,
          free_slots: 1,
          reasons: [],
          harnesses: [
            { harness_id: "claude-code", detected: true, configured: true },
            { harness_id: "opencode", detected: true, configured: false },
          ],
        } as MachineEligibility,
      ],
    });
    const GET = vi.fn().mockResolvedValue(ok(plan));
    const { root } = await render(fakeClient({ GET }));
    await preview(root);

    const values = [...root.querySelectorAll<HTMLOptionElement>("[data-admission-harness] option")].map((o) => o.value);
    expect(values).toEqual(["", "claude-code"]);
  });
});
