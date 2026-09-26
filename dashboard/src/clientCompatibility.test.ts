import { describe, expect, it } from "vitest";
import {
  advisoryLatest,
  advisoryText,
  CLIENT_VERSION,
  parseUpgradeRequired,
  upgradeRequiredText,
} from "./clientCompatibility";

describe("parseUpgradeRequired", () => {
  const detail = {
    error_code: "client_upgrade_required",
    client: "daemon",
    client_version: "0.0.1",
    minimum_supported: "0.1.0",
    latest: "0.2.0",
    message: "Trop ancien.",
  };

  it("reads the structured 426 detail", () => {
    const info = parseUpgradeRequired("client_upgrade_required", detail);
    expect(info).toEqual({
      client: "daemon",
      clientVersion: "0.0.1",
      minimumSupported: "0.1.0",
      latest: "0.2.0",
      message: "Trop ancien.",
    });
  });

  it("ignores any other error code", () => {
    expect(parseUpgradeRequired("version_conflict", detail)).toBeNull();
    expect(parseUpgradeRequired(null, detail)).toBeNull();
  });

  it("ignores a malformed detail", () => {
    expect(parseUpgradeRequired("client_upgrade_required", null)).toBeNull();
    expect(parseUpgradeRequired("client_upgrade_required", "boom")).toBeNull();
    expect(parseUpgradeRequired("client_upgrade_required", {})).toBeNull();
  });

  it("tolerates missing optional fields but requires a client", () => {
    const info = parseUpgradeRequired("client_upgrade_required", { client: "dashboard" });
    expect(info).not.toBeNull();
    expect(info?.latest).toBeNull();
    expect(info?.minimumSupported).toBeNull();
    expect(info?.message).toContain("plus prise en charge");
  });
});

describe("advisoryLatest", () => {
  it("returns the latest version only when recommended", () => {
    expect(
      advisoryLatest(new Headers({ "x-studio-client-update": "recommended", "x-studio-client-latest": "0.2.0" })),
    ).toBe("0.2.0");
    expect(advisoryLatest(new Headers({ "x-studio-client-update": "current" }))).toBeNull();
    expect(advisoryLatest(new Headers())).toBeNull();
    expect(advisoryLatest(new Headers({ "x-studio-client-update": "recommended" }))).toBeNull();
  });

  it("mentions the target version in the banner copy", () => {
    expect(advisoryText("0.2.0")).toContain("0.2.0");
    expect(advisoryText(null)).toBeNull();
  });
});

describe("upgradeRequiredText", () => {
  it("never claims a signature and includes the constraints", () => {
    const text = upgradeRequiredText({
      client: "daemon",
      clientVersion: "0.0.1",
      minimumSupported: "0.1.0",
      latest: "0.2.0",
      message: "Mise à jour requise.",
    });
    expect(text).toContain("Mise à jour requise.");
    expect(text).toContain("0.2.0");
    expect(text).toContain("0.1.0");
    expect(text.toLowerCase()).not.toContain("signé");
  });
});

describe("CLIENT_VERSION", () => {
  it("is injected from the build", () => {
    expect(CLIENT_VERSION).toBe("0.1.0");
  });
});
