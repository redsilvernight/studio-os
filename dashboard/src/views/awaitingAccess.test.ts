// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import { clearToken, setToken } from "../auth";
import { resetIdentityCache } from "../identityApi";
import { probeProjectAccess, renderAwaitingAccess } from "./awaitingAccess";

function client(role: string | null, projects: unknown[] | "error"): StudioClient {
  const GET = vi.fn(async (path: string) => {
    if (path === "/api/v1/auth/me") {
      return role === null
        ? { response: new Response(null, { status: 401 }) }
        : { response: new Response(null, { status: 200 }), data: { role } };
    }
    return projects === "error"
      ? { response: new Response(null, { status: 500 }) }
      : { response: new Response(null, { status: 200 }), data: projects };
  });
  return { GET } as unknown as StudioClient;
}

beforeEach(() => {
  resetIdentityCache();
  clearToken();
  setToken("jwt-test");
});

describe("probeProjectAccess", () => {
  it("is none for a member-less readonly account", async () => {
    await expect(probeProjectAccess(client("readonly", []))).resolves.toBe("none");
  });

  it("is granted as soon as one project is visible", async () => {
    await expect(probeProjectAccess(client("readonly", [{ id: "p" }]))).resolves.toBe("granted");
  });

  it("is granted for an admin without project", async () => {
    await expect(probeProjectAccess(client("admin", []))).resolves.toBe("granted");
  });

  it("is unknown when identity or projects cannot be read (never blocks)", async () => {
    await expect(probeProjectAccess(client(null, []))).resolves.toBe("unknown");
    resetIdentityCache();
    await expect(probeProjectAccess(client("readonly", "error"))).resolves.toBe("unknown");
  });
});

describe("renderAwaitingAccess", () => {
  it("explains the wait and re-checks on demand", () => {
    const view = document.createElement("main");
    const onRecheck = vi.fn();
    renderAwaitingAccess(view, onRecheck);
    expect(view.querySelector("h1")?.textContent).toContain("En attente d'accès");
    const button = view.querySelector<HTMLButtonElement>("[data-testid=awaiting-access-recheck]")!;
    button.click();
    expect(onRecheck).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
  });
});
