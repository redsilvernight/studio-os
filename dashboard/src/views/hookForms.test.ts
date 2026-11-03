import { describe, expect, it } from "vitest";
import { buildContent, contentFieldsHtml, type FormReader } from "./libraryForms";

const fields = (overrides: Record<string, string | undefined> = {}): FormReader => {
  const values: Record<string, string | undefined> = {
    event: "pre_tool", mode: "advisory", timeout_seconds: "30", matcher: "Read", hook_description: "Vérifie les outils",
    hook_script_0_os: "windows", hook_script_0_shell: "pwsh", hook_script_0_body: "  Write-Output 'ok'\n",
    ...overrides,
  };
  return { text: (name) => values[name] ?? "", checked: () => false };
};

describe("formulaires Hooks", () => {
  it("produit le contenu canonique et préserve le corps des scripts", () => {
    expect(buildContent("hook", fields())).toEqual({ ok: true, value: {
      content_schema: "studio.library.hook/v1", event: "pre_tool", mode: "advisory", timeout_seconds: 30,
      matcher: "Read", description: "Vérifie les outils",
      scripts: [{ os: "windows", shell: "pwsh", body: "  Write-Output 'ok'\n" }],
    } });
  });

  it("offre des champs natifs de plateforme et de script", () => {
    const html = contentFieldsHtml("hook");
    expect(html).toContain('name="event"');
    expect(html).toContain('name="hook_script_0_os"');
    expect(html).toContain('name="hook_script_0_shell"');
    expect(html).toContain('name="hook_script_0_body"');
    expect(html).toContain("data-hook-add");
  });

  it.each(["session_start", "session_end", "user_prompt", "pre_tool", "post_tool", "stop", "subagent_stop", "notification", "pre_compact"])("accepte l'événement %s sans matcher", (event) => {
    expect(buildContent("hook", fields({ event, matcher: "" })).ok).toBe(true);
  });

  it.each([
    { event: "PreToolUse" }, { mode: "unknown" }, { timeout_seconds: "0" }, { timeout_seconds: "601" },
    { timeout_seconds: "1.5" }, { timeout_seconds: "NaN" }, { event: "session_start", matcher: "Read" },
    { event: "post_tool", mode: "blocking" }, { matcher: "x".repeat(201) }, { hook_description: "x".repeat(1001) },
    { hook_script_0_body: "" }, { hook_script_0_body: "x".repeat(65_537) },
    { hook_script_0_os: "android" }, { hook_script_0_shell: "cmd" },
    { hook_script_1_os: "windows", hook_script_1_shell: "pwsh", hook_script_1_body: "Write-Output 2" },
  ])("rejette une déclaration invalide %#", (overrides) => {
    const built = buildContent("hook", fields(overrides));
    expect(built.ok).toBe(false);
    if (!built.ok) expect(built.error.length).toBeGreaterThan(0);
  });

  it.each(["pre_tool", "user_prompt", "stop"])("autorise le mode bloquant sur %s", (event) => {
    expect(buildContent("hook", fields({ event, matcher: "", mode: "blocking" })).ok).toBe(true);
  });

  it("accepte plusieurs plateformes distinctes et les limites inclusives", () => {
    const built = buildContent("hook", fields({
      timeout_seconds: "600", hook_description: "x".repeat(1000), matcher: "x".repeat(200),
      hook_script_0_body: "x".repeat(65_536),
      hook_script_2_os: "linux", hook_script_2_shell: "bash", hook_script_2_body: "echo ok",
    }));
    expect(built.ok).toBe(true);
    if (built.ok) expect(built.value["scripts"]).toHaveLength(2);
  });
});
