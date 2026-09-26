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
  it("flags only 401 as an auth error; 403 is a refused right", () => {
    const base = { errorCode: null as string | null, message: "x", serverVersion: null };
    expect(new ApiError({ status: 401, ...base }).isAuth).toBe(true);
    const forbidden = new ApiError({ status: 403, errorCode: "forbidden", message: "x", serverVersion: null });
    expect(forbidden.isAuth).toBe(false);
    expect(forbidden.isForbidden).toBe(true);
    expect(new ApiError({ status: 404, ...base }).isAuth).toBe(false);
  });

  it("recognises a project-isolation 403 from its structured detail", () => {
    const denied = new ApiError(
      parseErrorBody(403, { detail: { error_code: "forbidden", resource: "project", action: "read" } }),
    );
    expect(denied.isProjectAccessDenied).toBe(true);
    expect(denied.isAuth).toBe(false);
    const role = new ApiError(parseErrorBody(403, { detail: { error_code: "forbidden", resource: "user", action: "update" } }));
    expect(role.isProjectAccessDenied).toBe(false);
    expect(new ApiError(parseErrorBody(403, { detail: "insufficient role" })).isProjectAccessDenied).toBe(false);
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
