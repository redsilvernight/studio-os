import { describe, expect, it } from "vitest";
import { applicationPageHtml } from "./application";

describe("applicationPageHtml", () => {
  it("shows identity, version, mode and protocol in desktop mode", () => {
    const html = applicationPageHtml("desktop", {
      product: "Studi'OS Desktop",
      desktop_version: "0.1.0",
      mode: "desktop",
      protocol: "studio.local/v1",
      sidecar: { state: "not_started" },
    });
    expect(html).toContain("Studi'OS Desktop");
    expect(html).toContain("0.1.0");
    expect(html).toContain("Desktop");
    expect(html).toContain("studio.local/v1");
    expect(html).toContain('aria-current="page"');
  });

  it("does not claim Desktop availability in web mode", () => {
    const html = applicationPageHtml("web", null);
    expect(html).toContain("Web");
    expect(html).toContain("Application Desktop non utilisée");
    expect(html).not.toContain("studio.local");
    expect(html).not.toContain("Version Desktop");
  });

  it("shows a visible error when the desktop identity cannot be read", () => {
    const html = applicationPageHtml("desktop", null, "protocole incompatible");
    expect(html).toContain('role="alert"');
    expect(html).toContain("protocole incompatible");
  });

  it("carries no diagnostics (P3) such as daemon state or secrets", () => {
    const html = applicationPageHtml("desktop", {
      product: "Studi'OS Desktop",
      desktop_version: "0.1.0",
      mode: "desktop",
      protocol: "studio.local/v1",
      sidecar: { state: "running", pid: 42 },
    });
    expect(html).not.toMatch(/pid|daemon|keyring|token/i);
  });
});
