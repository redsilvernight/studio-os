// @vitest-environment happy-dom
/**
 * Réactivité des boutons de l'assistant : verrou anti double clic, erreur
 * affichée, reprise après redémarrage de l'app. P3 : le parcours ne couvre
 * que le poste (bienvenue, connexion, vérification, final, termine) ; la
 * mémoire, l'environnement et le harnais vivent dans `workspaceFolderSetup`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BridgeAnswer } from "../platform/contracts";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import { clearToken, setToken } from "../auth";
import { resetIdentityCache } from "../identityApi";
import { ONBOARDING_STORAGE_KEY } from "./state";
import { emptySession, renderOnboarding, revalidate } from "./view";

const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  createProject: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, createApiClient: () => ({ GET: api.GET, POST: api.POST }) };
});

const PROJECT = "22222222-2222-4222-8222-222222222222";
const MACHINE = "33333333-3333-4333-8333-333333333333";

const ok = (payload: unknown): BridgeAnswer => ({ ok: true, response: { payload } }) as unknown as BridgeAnswer;
const refused = (code: string): BridgeAnswer =>
  ({ ok: false, error: { code, component: "workspace", message: "x", retryable: false, correlation_id: null, details: {} } }) as unknown as BridgeAnswer;

const tick = (ms = 0): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function mount(): HTMLElement {
  const root = document.createElement("main");
  document.body.append(root);
  return root;
}

beforeEach(() => {
  document.body.innerHTML = "";
  globalThis.localStorage.removeItem(ONBOARDING_STORAGE_KEY);
  api.GET.mockReset();
  api.POST.mockReset();
  api.createProject.mockReset();
  resetIdentityCache();
  setToken("session-token");
});

afterEach(() => {
  setToken("");
});

describe("step « Connexion »", () => {
  it("saves the server address once on a double submit", async () => {
    let calls = 0;
    const gate = deferred<void>();
    const platform = fakeDesktop({
      setServerOrigin: async () => {
        calls += 1;
        await gate.promise;
        return { ok: true as const, state: { configured: "https://new.example", applied: "https://new.example", restart_required: false } };
      },
    });
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    const root = mount();
    await renderOnboarding(root, platform, emptySession({ schema: 1, status: "in_progress", current: "connexion" }));
    const form = root.querySelector<HTMLFormElement>("[data-testid=server-origin-form]")!;
    root.querySelector<HTMLInputElement>("#server-origin-input")!.value = "https://new.example";
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    expect(form.querySelector<HTMLButtonElement>("button[type=submit]")!.disabled).toBe(true);
    gate.resolve();
    await tick(20);
    expect(calls).toBe(1);
    expect(root.querySelector("[data-testid=onboarding-notice]")?.textContent).toContain("Adresse enregistrée");
    fetchSpy.mockRestore();
  });
});

describe("resume after an app restart", () => {
  it("keeps the persisted step: revalidation never diverts the workstation journey", async () => {
    const platform = fakeDesktop({ request: (async () => refused("daemon_unavailable")) as never });
    const session = emptySession({ schema: 1, status: "in_progress", current: "final" });
    await revalidate(session, platform);
    expect(session.state.current).toBe("final");
    expect(session.error).toBeNull();
  });

  it("reopens a legacy persisted step on the ready screen, without error", async () => {
    globalThis.localStorage.setItem(
      ONBOARDING_STORAGE_KEY,
      JSON.stringify({ schema: 1, status: "in_progress", current: "memoire" }),
    );
    const platform = fakeDesktop({
      request: (async (command: string) => {
        if (command === "identity.get_view") {
          return ok({ profile: { profile_id: "main", server_origin: "https://studio.example" }, secrets: [{ status: "present" }] });
        }
        return refused("not_supported");
      }) as never,
    });
    const root = mount();
    await renderOnboarding(root, platform);
    expect(root.querySelector("[data-testid=onboarding-step]")?.getAttribute("data-step")).toBe("final");
    expect(root.querySelector("[data-testid=onboarding-error]")).toBeNull();
    expect(root.textContent).toContain("Dossiers du projet");
  });
});

describe("A5 — compte auto-inscrit dans l'assistant", () => {
  it("« Connexion » : créer un compte sur le serveur configuré puis revenir à la connexion", async () => {
    clearToken();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    api.POST.mockResolvedValue({ response: new Response(null, { status: 202 }) });
    const root = mount();
    await renderOnboarding(root, fakeDesktop(), emptySession({ schema: 1, status: "in_progress", current: "connexion" }));
    const host = root.querySelector<HTMLElement>("[data-testid=onboarding-login]")!;
    host.querySelector<HTMLAnchorElement>("a[data-account-action=register]")!.click();
    expect(host.querySelector("[data-screen=register]")).not.toBeNull();
    // L'adresse serveur reste celle de l'étape : aucune seconde saisie.
    expect(host.querySelector("#server-origin-input, #login-server-input")).toBeNull();

    host.querySelector<HTMLInputElement>("input[name=email]")!.value = "ada@example.com";
    host.querySelector<HTMLFormElement>("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await tick(10);
    expect(api.POST.mock.calls[0]![0]).toBe("/api/v1/auth/register");
    expect(host.querySelector("[data-screen=sent]")).not.toBeNull();
    expect(host.querySelector("[data-testid=onboarding-verify-hint]")).not.toBeNull();

    host.querySelector<HTMLAnchorElement>("a[data-action=login]")!.click();
    expect(host.querySelector("#login-form")).not.toBeNull();
    expect(host.querySelector("[data-testid=login-account-links]")).not.toBeNull();
    fetchSpy.mockRestore();
  });

  it("« Connexion » : inscriptions fermées = écran explicite dans l'assistant", async () => {
    clearToken();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    api.POST.mockResolvedValue({
      response: new Response(null, { status: 404 }),
      error: { detail: { error_code: "registration_unavailable" } },
    });
    const root = mount();
    await renderOnboarding(root, fakeDesktop(), emptySession({ schema: 1, status: "in_progress", current: "connexion" }));
    const host = root.querySelector<HTMLElement>("[data-testid=onboarding-login]")!;
    host.querySelector<HTMLAnchorElement>("a[data-account-action=register]")!.click();
    host.querySelector<HTMLInputElement>("input[name=email]")!.value = "ada@example.com";
    host.querySelector<HTMLFormElement>("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await tick(10);
    expect(host.querySelector("[data-screen=failure-registration_unavailable]")?.textContent).toContain("Inscriptions fermées");
    fetchSpy.mockRestore();
  });
});

describe("A5 — enregistrement du poste sans admin (DEC-0130)", () => {
  const PROFILE = { profile_id: "main", server_origin: "https://studio.example" };
  const view = (status: string) => ok({ profile: PROFILE, secrets: [{ status }] });

  function enrollingDesktop(answers: {
    status: () => string;
    enroll?: (payload: Record<string, unknown>) => BridgeAnswer;
    granted?: string[];
  }) {
    const calls: Array<{ command: string; payload: Record<string, unknown> }> = [];
    const granted = answers.granted ?? ["daemon.control", "identity.view", "identity.enroll"];
    const platform = fakeDesktop({
      request: (async (command: string, payload: Record<string, unknown>) => {
        calls.push({ command, payload });
        if (command === "runtime.handshake") return ok({ outcome: "compatible", granted_capabilities: granted });
        if (command === "identity.get_view") return view(answers.status());
        if (command === "identity.enroll" && answers.enroll) return answers.enroll(payload);
        return refused("not_supported");
      }) as never,
    });
    return { platform, calls };
  }

  const verification = () => emptySession({ schema: 1, status: "in_progress", current: "verification" });

  it("enregistre le poste avec la session de l'étape « Connexion », une seule fois", async () => {
    let status = "absent";
    const { platform, calls } = enrollingDesktop({
      status: () => status,
      enroll: () => {
        status = "present";
        return ok({ outcome: "enrolled", machine_id: PROJECT, view: { profile: PROFILE, secrets: [] } });
      },
    });
    const root = mount();
    await renderOnboarding(root, platform, verification());
    expect(root.querySelector<HTMLButtonElement>("[data-action=next]")!.disabled).toBe(true);
    const enroll = root.querySelector<HTMLButtonElement>("[data-action=enroll]")!;
    enroll.click();
    enroll.click();
    await tick(20);

    const enrolls = calls.filter((c) => c.command === "identity.enroll");
    expect(enrolls).toHaveLength(1);
    expect(enrolls[0]!.payload).toMatchObject({ profile: PROFILE, human_session: "session-token", replace_existing: false });
    expect(String(enrolls[0]!.payload["machine_name"])).toContain("Studi'OS Desktop");
    expect(root.querySelector("[data-testid=onboarding-notice]")?.textContent).toContain("Poste enregistré.");
    expect(root.querySelector<HTMLButtonElement>("[data-action=next]")!.disabled).toBe(false);
    expect(root.innerHTML).not.toContain("session-token");
  });

  it("propose les machines non révoquées et transmet adopt_machine_id en reprise", async () => {
    api.GET.mockImplementation(async (path: string) =>
      path === "/api/v1/machines"
        ? { response: { ok: true }, data: [{ id: MACHINE, display_name: "Atelier", owner_user_id: PROJECT, status: "offline" }] }
        : { response: { ok: true }, data: [] },
    );
    const { platform, calls } = enrollingDesktop({
      status: () => "absent",
      enroll: () => ok({ outcome: "enrolled", machine_id: MACHINE, view: { profile: PROFILE, secrets: [] } }),
    });
    const root = mount();
    await renderOnboarding(root, platform, verification());
    expect(root.querySelector("[data-testid=enroll-machine-choice]")).not.toBeNull();
    expect(root.textContent).toContain("Reprendre la machine « Atelier »");

    root.querySelector<HTMLInputElement>(`input[name=enroll-mode][value="${MACHINE}"]`)!.checked = true;
    root.querySelector<HTMLButtonElement>("[data-action=enroll]")!.click();
    await tick(20);
    const payload = calls.find((c) => c.command === "identity.enroll")!.payload;
    expect(payload["adopt_machine_id"]).toBe(MACHINE);
  });

  it("par défaut, crée une nouvelle machine sans adopt_machine_id", async () => {
    api.GET.mockImplementation(async (path: string) =>
      path === "/api/v1/machines"
        ? { response: { ok: true }, data: [{ id: MACHINE, display_name: "Atelier", owner_user_id: PROJECT, status: "offline" }] }
        : { response: { ok: true }, data: [] },
    );
    const { platform, calls } = enrollingDesktop({
      status: () => "absent",
      enroll: () => ok({ outcome: "enrolled", machine_id: PROJECT, view: { profile: PROFILE, secrets: [] } }),
    });
    const root = mount();
    await renderOnboarding(root, platform, verification());
    expect(root.querySelector<HTMLInputElement>("input[name=enroll-mode][value=new]")!.checked).toBe(true);
    root.querySelector<HTMLButtonElement>("[data-action=enroll]")!.click();
    await tick(20);
    const payload = calls.find((c) => c.command === "identity.enroll")!.payload;
    expect("adopt_machine_id" in payload).toBe(false);
  });

  it("sans machine connue, l'enrôlement garde son unique geste", async () => {
    api.GET.mockResolvedValue({ response: { ok: true }, data: [] });
    const { platform } = enrollingDesktop({ status: () => "absent" });
    const root = mount();
    await renderOnboarding(root, platform, verification());
    expect(root.querySelector("[data-testid=enroll-machine-choice]")).toBeNull();
    expect(root.querySelector("[data-action=enroll]")).not.toBeNull();
  });

  it("un credential révoqué est remplacé explicitement", async () => {
    const { platform, calls } = enrollingDesktop({
      status: () => "revoked",
      enroll: () => ok({ outcome: "enrolled", machine_id: PROJECT, view: { profile: PROFILE, secrets: [] } }),
    });
    const root = mount();
    await renderOnboarding(root, platform, verification());
    root.querySelector<HTMLButtonElement>("[data-action=enroll]")!.click();
    await tick(20);
    expect(calls.find((c) => c.command === "identity.enroll")?.payload["replace_existing"]).toBe(true);
  });

  it("ancien démon sans la capacité : message de mise à jour, la session n'est jamais envoyée", async () => {
    const { platform, calls } = enrollingDesktop({ status: () => "absent", granted: ["daemon.control", "identity.view"] });
    const root = mount();
    await renderOnboarding(root, platform, verification());
    expect(root.querySelector("[data-action=enroll]")).toBeNull();
    expect(root.querySelector("[data-testid=enroll-unavailable]")?.textContent).toContain("Mettez l'application à jour");
    expect(calls.some((c) => c.command === "identity.enroll")).toBe(false);
    expect(JSON.stringify(calls)).not.toContain("session-token");
  });

  it("capacité perdue entre l'affichage et le clic (démon redémarré) : rien n'est envoyé", async () => {
    let granted = ["daemon.control", "identity.view", "identity.enroll"];
    const calls: string[] = [];
    const platform = fakeDesktop({
      request: (async (command: string) => {
        calls.push(command);
        if (command === "runtime.handshake") return ok({ outcome: "compatible", granted_capabilities: granted });
        if (command === "identity.get_view") return view("absent");
        return refused("not_supported");
      }) as never,
    });
    const root = mount();
    await renderOnboarding(root, platform, verification());
    granted = ["daemon.control", "identity.view"];
    root.querySelector<HTMLButtonElement>("[data-action=enroll]")!.click();
    await tick(20);
    expect(calls).not.toContain("identity.enroll");
    expect(root.querySelector("[data-testid=onboarding-error]")?.textContent).toContain("Mettez l'application à jour");
  });

  it("sans session : invite à se connecter, aucun appel", async () => {
    clearToken();
    const { platform, calls } = enrollingDesktop({ status: () => "absent" });
    const root = mount();
    await renderOnboarding(root, platform, verification());
    expect(root.querySelector("[data-testid=enroll-needs-login]")).not.toBeNull();
    expect(root.querySelector("[data-action=enroll]")).toBeNull();
    expect(calls.some((c) => c.command === "identity.enroll")).toBe(false);
  });

  it.each([
    [{ code: "permission_denied", details: { reason: "session_expired" } }, "Votre session a expiré"],
    [{ code: "permission_denied", details: { reason: "forbidden" } }, "ne peut pas enregistrer de poste"],
    [{ code: "internal_error", details: { reason: "server_unreachable" } }, "Serveur injoignable"],
    [{ code: "keyring_unavailable", details: { reason: "credential_not_stored" } }, "révoquez-le depuis « Postes »"],
    [{ code: "wrong_profile", details: {} }, "vise un autre serveur"],
    [{ code: "capability_missing", details: {} }, "ne sait pas enregistrer le poste"],
  ])("refus %o : message fixe", async (error, expected) => {
    const { platform } = enrollingDesktop({
      status: () => "absent",
      enroll: () =>
        ({ ok: false, error: { component: "daemon", message: "server text", retryable: false, correlation_id: null, ...error } }) as unknown as BridgeAnswer,
    });
    const root = mount();
    await renderOnboarding(root, platform, verification());
    root.querySelector<HTMLButtonElement>("[data-action=enroll]")!.click();
    await tick(20);
    const shown = root.querySelector("[data-testid=onboarding-error]")?.textContent ?? "";
    expect(shown).toContain(expected);
    expect(shown).not.toContain("server text");
  });
});
