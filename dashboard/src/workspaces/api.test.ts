import { describe, expect, it, vi } from "vitest";
import type { Platform } from "../platform";
import type { StudioClient } from "../api";
import type { WorkspaceStatus } from "../platform/generated/local-contracts.generated";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import {
  detectedFolderName,
  findLinkedWorkspace,
  linkDetectedRepository,
  listDetectedRepositories,
} from "./api";

const item = (workspace_id: string, project_id: string, workspace_root: string): WorkspaceStatus =>
  ({ workspace_id, health: "valid", config: { workspace_id, project_id, roots: { workspace_root, repo_roots: [] } } }) as unknown as WorkspaceStatus;

describe("findLinkedWorkspace", () => {
  const items = [item("a", "p1", "C:\\Projets\\Demo"), item("b", "p2", "C:\\Autre")];

  it("retrouve l'association du même dossier pour le même projet, quelle que soit la casse ou le séparateur", () => {
    expect(findLinkedWorkspace(items, "p1", "c:/projets/demo/")?.workspace_id).toBe("a");
  });

  it("ignore un autre projet ou un autre dossier", () => {
    expect(findLinkedWorkspace(items, "p2", "C:\\Projets\\Demo")).toBeUndefined();
    expect(findLinkedWorkspace(items, "p1", "C:\\Projets\\Demo2")).toBeUndefined();
  });
});

describe("detectedFolderName", () => {
  it("ne montre que le dernier segment, jamais le chemin brut", () => {
    expect(detectedFolderName("C:/Projects/untracked-game")).toBe("untracked-game");
    expect(detectedFolderName("C:\\Projects\\untracked-game\\")).toBe("untracked-game");
  });
});

describe("listDetectedRepositories", () => {
  it("renvoie les dépôts unresolved du pont local", async () => {
    const base = fakeDesktop();
    const payload = { items: [{ root: "C:/Projects/a", remotes: ["github.com/org/a"], reason: "not_found", last_seen_at: "2026-11-10T09:00:00+00:00" }] };
    const platform = {
      ...base,
      request: vi.fn(async () => ({ ok: true, response: { payload } })),
    } as unknown as Platform;
    const result = await listDetectedRepositories(platform);
    expect(result).toEqual({ ok: true, value: payload.items });
  });

  it("traduit un refus du pont sans le relayer brut", async () => {
    const base = fakeDesktop();
    const platform = {
      ...base,
      request: vi.fn(async () => ({ ok: false, error: { code: "not_supported" } })),
    } as unknown as Platform;
    const result = await listDetectedRepositories(platform);
    expect(result.ok).toBe(false);
  });
});

describe("linkDetectedRepository", () => {
  const PROFILE = { profile_id: "default", server_origin: "https://studio.example.test" };
  const baseRequest = { root: "C:/Projects/a", remote: "github.com/org/a", projectId: "p1", projectSlug: "demo", profile: PROFILE } as const;

  function rig(postStatus: number) {
    const calls: string[] = [];
    const base = fakeDesktop();
    const platform = {
      ...base,
      request: vi.fn(async (command: string, payload: Record<string, unknown>) => {
        calls.push(command);
        if (command === "workspace.confirm_roots") return { ok: true, response: { payload: { root_confirmation_id: "rc-1", expires_in_s: 600 } } };
        if (command === "workspace.save_config") return { ok: true, response: { payload: (payload as { config: unknown }).config } };
        throw new Error(`unexpected ${command}`);
      }),
    } as unknown as Platform;
    const POST = vi.fn(async (_path: string, _options: { params: { path: { project_id: string } }; body: { url: string } }) => ({ data: {}, response: { ok: postStatus < 300, status: postStatus } }));
    const client = { POST } as unknown as StudioClient;
    return { platform, client, calls, POST };
  }

  it("ajoute le remote au projet puis suit le dossier", async () => {
    const { platform, client, calls, POST } = rig(201);
    const result = await linkDetectedRepository(client, platform, { ...baseRequest });
    expect(result).toEqual({ ok: true });
    expect(POST).toHaveBeenCalledTimes(1);
    const [, options] = POST.mock.calls[0] as [{}, { params: { path: { project_id: string } }; body: { url: string } }];
    expect(options.params.path.project_id).toBe("p1");
    expect(options.body).toEqual({ url: "github.com/org/a" });
    expect(calls).toEqual(["workspace.confirm_roots", "workspace.save_config"]);
  });

  it("sans remote, suit le dossier sans toucher aux repositories", async () => {
    const { platform, client, POST } = rig(201);
    const result = await linkDetectedRepository(client, platform, { ...baseRequest, remote: null });
    expect(result).toEqual({ ok: true });
    expect(POST).not.toHaveBeenCalled();
  });

  it("un remote déjà lié ailleurs échoue sans suivre le dossier", async () => {
    const { platform, client } = rig(409);
    const result = await linkDetectedRepository(client, platform, { ...baseRequest });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.message).toContain("déjà rattaché");
  });

  it("un refus d'autorisation reste une phrase fixe", async () => {
    const { platform, client } = rig(403);
    const result = await linkDetectedRepository(client, platform, { ...baseRequest });
    expect(result).toEqual({ ok: false, message: "Accès refusé : seul un admin ou un developer peut rattacher un dépôt." });
  });
});
