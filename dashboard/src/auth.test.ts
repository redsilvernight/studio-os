import { beforeEach, describe, expect, it } from "vitest";
import { clearToken, getToken, hasToken, setToken } from "./auth";

beforeEach(() => {
  clearToken();
});

describe("in-memory token store", () => {
  it("starts empty", () => {
    expect(hasToken()).toBe(false);
    expect(getToken()).toBeNull();
  });

  it("stores and clears a token", () => {
    setToken("secret-token");
    expect(hasToken()).toBe(true);
    expect(getToken()).toBe("secret-token");
    clearToken();
    expect(hasToken()).toBe(false);
    expect(getToken()).toBeNull();
  });

  it("treats blank input as clear", () => {
    setToken("  ");
    expect(hasToken()).toBe(false);
  });

  it("never touches web storage", () => {
    let touched = false;
    const trap = { get: () => touched, set: () => (touched = true) };
    Object.defineProperty(globalThis, "localStorage", { ...trap, configurable: true });
    Object.defineProperty(globalThis, "sessionStorage", { ...trap, configurable: true });
    Object.defineProperty(globalThis, "document", { ...trap, configurable: true });
    try {
      setToken("abc");
      getToken();
      hasToken();
      clearToken();
      expect(touched).toBe(false);
    } finally {
      // @ts-expect-error cleanup test globals
      delete globalThis.localStorage;
      // @ts-expect-error cleanup test globals
      delete globalThis.sessionStorage;
      // @ts-expect-error cleanup test globals
      delete globalThis.document;
    }
  });
});
