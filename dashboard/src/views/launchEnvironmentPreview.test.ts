// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Platform } from "../platform";
import type { HarnessLaunchPreview } from "../platform/generated/local-contracts.generated";
import { call } from "../harnessApi";
import { bindLaunchEnvironmentPreview, launchEnvironmentPreviewHtml } from "./launchEnvironmentPreview";

vi.mock("../harnessApi", () => ({ call: vi.fn() }));
const mockedCall = vi.mocked(call);
const platform = {} as Platform;
const preview: HarnessLaunchPreview = {
  adapter_id: "claude-code", isolation: "isolated", production_approval_required: false,
  settings_sources: ["Sources personnelles désactivées"],
  hooks: [{ name: "Identité Studio", state: "included", reason: "Fichier présent" }, { name: "Garde Git", state: "unavailable", reason: "Fichier absent" }],
  mcp_servers: [{ name: "studio-os", state: "included", reason: "Configuration stricte" }],
  exclusions: ["Autres MCP exclus"], limitations: ["Exécution non vérifiée"], access_modes: ["read_only", "workspace_write"],
};
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function mount() {
  const card = document.createElement("article");
  card.innerHTML = launchEnvironmentPreviewHtml();
  bindLaunchEnvironmentPreview(card, platform, "workspace", "claude-code");
  return { card, button: card.querySelector<HTMLButtonElement>("button")!, result: card.querySelector<HTMLElement>("[data-launch-environment]")! };
}

describe("aperçu local des lancements", () => {
  beforeEach(() => vi.resetAllMocks());

  it("consulte uniquement après clic et affiche les observations sans appliquer de configuration", async () => {
    mockedCall.mockResolvedValue({ ok: true, value: preview });
    const { button, result } = mount();
    expect(mockedCall).not.toHaveBeenCalled();
    button.click();
    expect(button.disabled).toBe(true);
    button.click();
    await flush();
    expect(mockedCall).toHaveBeenCalledExactlyOnceWith(platform, "harness.launch_preview", { workspace_id: "workspace", adapter_id: "claude-code" });
    expect(result.textContent).toContain("Identité Studio — Prévu");
    expect(result.textContent).toContain("Garde Git — Absent");
    expect(result.textContent).toContain("studio-os — Prévu");
    expect(result.textContent).toContain("Autres MCP exclus");
    expect(result.textContent).toContain("Lecture seule");
    expect(result.textContent).toContain("sur ce poste seulement");
    expect(button.disabled).toBe(false);
  });

  it("rend les limites d’un adaptateur non isolé sans les présenter comme un succès", async () => {
    mockedCall.mockResolvedValue({ ok: true, value: { ...preview, isolation: "unverified", production_approval_required: true, hooks: [], mcp_servers: [] } });
    const { button, result } = mount();
    button.click(); await flush();
    expect(result.textContent).toContain("Isolation non vérifiée");
    expect(result.textContent).toContain("refuse le lancement sans autorisation explicite");
  });

  it("échappe tout contenu affiché", async () => {
    mockedCall.mockResolvedValue({ ok: true, value: { ...preview, settings_sources: ["<img src=x onerror=alert(1)>"], hooks: [{ name: "<script>x</script>", state: "unverified", reason: "<svg onload=alert(1)>" }] } });
    const { button, result } = mount();
    button.click(); await flush();
    expect(result.querySelector("img,script,svg")).toBeNull();
    expect(result.textContent).toContain("<img");
  });

  it.each(["capability_missing", "not_supported", "read_only"])("rend %s indisponible sans bloquer la suite", async (code) => {
    mockedCall.mockResolvedValue({ ok: false, error: { code } } as never);
    const { button, result } = mount();
    button.click(); await flush();
    expect(result.textContent).toContain("Aperçu indisponible");
    expect(button.disabled).toBe(false);
  });

  it("refuse une réponse pour un autre outil", async () => {
    mockedCall.mockResolvedValue({ ok: true, value: { ...preview, adapter_id: "opencode" } });
    const { button, result } = mount();
    button.click(); await flush();
    expect(result.textContent).toContain("Aperçu indisponible");
    expect(result.querySelector("section")).toBeNull();
  });

  it("rend une exception réseau explicite et permet de réessayer", async () => {
    mockedCall.mockRejectedValue(new Error("offline"));
    const { button, result } = mount();
    button.click(); await flush();
    expect(result.textContent).toContain("la lecture locale a échoué");
    expect(button.disabled).toBe(false);
    mockedCall.mockResolvedValue({ ok: true, value: preview });
    button.click(); await flush();
    expect(result.textContent).toContain("Configuration isolée prévue");
  });
});
