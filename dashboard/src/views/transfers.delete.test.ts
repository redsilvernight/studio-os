// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import { clearToken, setToken } from "../auth";
import { resetIdentityCache, type AuthIdentity } from "../identityApi";
import type { Transfer } from "../transfersApi";
import { canDeleteTransfer, renderTransfers } from "./transfers";

const sender: AuthIdentity = { user_id: "sender", display_name: "Expéditeur", email: "sender@example.test", role: "developer", machine_id: "machine" };
const transfer: Transfer = {
  id: "transfer-1", transfer_code: "TRF-1", sender_user_id: sender.user_id, category: "temporary",
  filename: "archive du studio.zip", object_key: "studio/transfer-1/archive.zip", content_type: "application/zip", size_bytes: 12,
  status: "ready", created_at: "2026-10-20T12:00:00Z", deleted_at: null,
};

beforeEach(() => {
  resetIdentityCache();
  setToken("test-transfer-delete");
  document.body.innerHTML = '<div id="ds-toast-region"></div><main id="root"></main>';
});
afterEach(() => { clearToken(); resetIdentityCache(); vi.restoreAllMocks(); });

async function mount(status = 204) {
  const DELETE = vi.fn(async () => ({ response: new Response(null, { status }), error: status === 204 ? undefined : { detail: { error_code: status === 403 ? "forbidden" : "storage_unavailable" } } }));
  const GET = vi.fn(async (path: string) => ({
    response: new Response(null, { status: 200 }),
    data: path === "/api/v1/auth/me" ? sender : path === "/api/v1/transfers" ? [transfer]
      : path === "/api/v1/transfers/{transfer_id}" ? { ...transfer, status: "deleted", deleted_at: "2026-10-20T12:10:00Z" }
        : path === "/api/v1/transfers/consumption" ? { consumed_bytes: 12, quota_bytes: 100, remaining_bytes: 88 } : [],
  }));
  const root = document.getElementById("root")!;
  await renderTransfers(root, { client: { GET, DELETE } as unknown as StudioClient, authed: true });
  root.querySelector<HTMLButtonElement>("[data-transfer-details]")!.click();
  return { root, DELETE };
}

describe("suppression de transfert", () => {
  it("ne propose l'action qu'à l'expéditeur ou un administrateur, jamais après suppression", () => {
    expect(canDeleteTransfer(transfer, sender)).toBe(true);
    expect(canDeleteTransfer(transfer, { ...sender, user_id: "admin", role: "admin" })).toBe(true);
    expect(canDeleteTransfer(transfer, { ...sender, user_id: "recipient" })).toBe(false);
    expect(canDeleteTransfer(transfer, { ...sender, role: "readonly" })).toBe(false);
    expect(canDeleteTransfer(transfer, null)).toBe(false);
    expect(canDeleteTransfer({ ...transfer, status: "deleted" }, sender)).toBe(false);
  });

  it("nomme le fichier et attend la confirmation ; annuler ne fait aucune requête", async () => {
    const { root, DELETE } = await mount();
    root.querySelector<HTMLButtonElement>("[data-transfer-delete]")!.click();
    const confirmation = root.querySelector<HTMLElement>("[data-transfer-delete-confirm]")!;
    expect(confirmation.hidden).toBe(false);
    expect(confirmation.textContent).toContain(transfer.filename);
    expect(DELETE).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>("[data-transfer-delete-cancel]")!.click();
    expect(confirmation.hidden).toBe(true);
    expect(DELETE).not.toHaveBeenCalled();
  });

  it("supprime après confirmation et conserve une fiche historique sans bouton de suppression", async () => {
    const { root, DELETE } = await mount();
    root.querySelector<HTMLButtonElement>("[data-transfer-delete]")!.click();
    const submit = root.querySelector<HTMLButtonElement>("[data-transfer-delete-submit]")!;
    submit.click();
    submit.click();
    await vi.waitFor(() => expect(root.querySelector("[data-transfer-delete]")).toBeNull());
    expect(DELETE).toHaveBeenCalledTimes(1);
    expect(root.querySelector("#transfer-drawer-body")?.textContent).toContain("Supprimé");
    expect(document.getElementById("ds-toast-region")?.textContent).toContain("supprimé");
  });

  it.each([403, 503])("affiche l'échec %s sans état ni notification de succès", async (status) => {
    const { root, DELETE } = await mount(status);
    root.querySelector<HTMLButtonElement>("[data-transfer-delete]")!.click();
    root.querySelector<HTMLButtonElement>("[data-transfer-delete-submit]")!.click();
    await vi.waitFor(() => expect(root.querySelector("[data-transfer-delete-error]")?.textContent).toContain(status === 403 ? "refusée" : "stockage est indisponible"));
    expect(DELETE).toHaveBeenCalledTimes(1);
    expect(root.querySelector<HTMLButtonElement>("[data-transfer-delete-submit]")!.disabled).toBe(false);
    expect(document.getElementById("ds-toast-region")?.textContent ?? "").not.toContain("supprimé");
  });
});
