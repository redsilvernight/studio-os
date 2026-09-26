import { describe, expect, it } from "vitest";
import { publicHashScreen, readAccountLink, scrubbedPath } from "./accountLink";

describe("readAccountLink", () => {
  it("reads the verification secret from the fragment", () => {
    expect(readAccountLink("/verify-email", "#token=abc123")).toEqual({ kind: "verify", token: "abc123" });
  });

  it("reads the reset secret under a sub-path", () => {
    expect(readAccountLink("/studio/reset-password/", "#token=xyz")).toEqual({ kind: "reset", token: "xyz" });
  });

  it("flags a link without secret", () => {
    expect(readAccountLink("/verify-email", "")).toEqual({ kind: "verify", token: null });
    expect(readAccountLink("/verify-email", "#token=")).toEqual({ kind: "verify", token: null });
  });

  it("ignores every other path", () => {
    expect(readAccountLink("/", "#token=abc")).toBeNull();
    expect(readAccountLink("/not-verify-email", "#token=abc")).toBeNull();
  });
});

describe("scrubbedPath", () => {
  it("returns the application root without the link segment", () => {
    expect(scrubbedPath("/verify-email")).toBe("/");
    expect(scrubbedPath("/studio/reset-password/")).toBe("/studio/");
  });
});

describe("publicHashScreen", () => {
  it("maps the shareable pre-login addresses", () => {
    expect(publicHashScreen("#/inscription")).toBe("register");
    expect(publicHashScreen("#/mot-de-passe-oublie")).toBe("forgot");
    expect(publicHashScreen("#/renvoyer-verification/")).toBe("resend");
    expect(publicHashScreen("#/projects")).toBeNull();
    expect(publicHashScreen("")).toBeNull();
  });
});
