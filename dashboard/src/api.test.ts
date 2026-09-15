import { describe, expect, it } from "vitest";
import { ApiError, parseErrorBody, requireToken } from "./api";
import { clearToken, setToken } from "./auth";

describe("parseErrorBody", () => {
  it("maps string details", () => {
    expect(parseErrorBody(404, { detail: "project not found" })).toMatchObject({
      status: 404,
      errorCode: null,
      message: "project not found",
    });
  });

  it("maps machine-readable error_code envelopes", () => {
    expect(parseErrorBody(403, { detail: { error_code: "forbidden" } })).toMatchObject({
      status: 403,
      errorCode: "forbidden",
    });
  });

  it("maps version conflicts with their message", () => {
    const parsed = parseErrorBody(409, { detail: { error_code: "version_conflict" } });
    expect(parsed.status).toBe(409);
    expect(parsed.errorCode).toBe("version_conflict");
  });

  it("falls back to HTTP status on unknown bodies", () => {
    expect(parseErrorBody(500, null).message).toBe("HTTP 500");
  });
});

describe("ApiError", () => {
  it("flags 401/403 as auth errors", () => {
    const base = { errorCode: null as string | null, message: "x", serverVersion: null };
    expect(new ApiError({ status: 401, ...base }).isAuth).toBe(true);
    expect(new ApiError({ status: 403, errorCode: "forbidden", message: "x", serverVersion: null }).isAuth).toBe(true);
    expect(new ApiError({ status: 404, ...base }).isAuth).toBe(false);
  });

  it("carries server_version from version_conflict bodies", () => {
    const parsed = parseErrorBody(409, { detail: { error_code: "version_conflict", server_version: 7 } });
    const error = new ApiError(parsed);
    expect(error.errorCode).toBe("version_conflict");
    expect(error.serverVersion).toBe(7);
  });
});

describe("requireToken", () => {
  it("throws 401 when no token is set and returns it otherwise", () => {
    clearToken();
    expect(() => requireToken()).toThrowError(ApiError);
    setToken("tok");
    expect(requireToken()).toBe("tok");
    clearToken();
  });
});
