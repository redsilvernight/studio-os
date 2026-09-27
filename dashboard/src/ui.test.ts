import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { describeError, newUuid } from "./ui";

describe("newUuid", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("produit un UUID v4 même hors contexte sécurisé (HTTP, sans crypto.randomUUID)", () => {
    vi.stubGlobal("crypto", { getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto) });
    const id = newUuid();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(newUuid()).not.toBe(id);
  });
});

function apiError(status: number, errorCode: string | null, message = `HTTP ${status}`, serverVersion: number | null = null): ApiError {
  return new ApiError({ status, errorCode, message, serverVersion });
}

describe("describeError", () => {
  it("dit d'abord une phrase humaine, puis garde le code pour le débogage", () => {
    const text = describeError(apiError(409, "version_conflict", "version_conflict (HTTP 409)", 9));
    expect(text.startsWith("Cet élément a été modifié ailleurs.")).toBe(true);
    expect(text).toContain("(HTTP 409 · version_conflict · version serveur 9)");
    expect(text).not.toContain("expected_version");
  });

  it("distingue un refus d'accès projet (403 isolation) d'un droit manquant", () => {
    const project = new ApiError({
      status: 403,
      errorCode: "forbidden",
      message: "forbidden (HTTP 403)",
      serverVersion: null,
      details: { error_code: "forbidden", resource: "project", action: "read" },
    });
    expect(describeError(project)).toContain("pas accès à ce projet");
    expect(describeError(project)).toContain("HTTP 403 · forbidden");
    expect(describeError(apiError(403, "forbidden"))).toContain("droits nécessaires");
    expect(describeError(apiError(403, "forbidden"))).not.toContain("session");
  });

  it("traduit les codes métier connus sans masquer le code", () => {
    expect(describeError(apiError(409, "already_claimed"))).toContain("déjà prise en charge");
    expect(describeError(apiError(409, "already_claimed"))).toContain("already_claimed");
    expect(describeError(apiError(422, "invalid_content"))).toContain("n'est pas valide");
  });

  it("retombe sur le statut HTTP pour un code inconnu ou absent", () => {
    expect(describeError(apiError(403, null))).toContain("droits nécessaires");
    expect(describeError(apiError(404, null, "Task not found"))).toContain("Élément introuvable");
    // Le détail serveur brut reste disponible, mais après le message humain.
    expect(describeError(apiError(404, null, "Task not found"))).toContain("(HTTP 404 · Task not found)");
    expect(describeError(apiError(500, null))).toContain("Le serveur a rencontré une erreur");
    expect(describeError(apiError(418, "teapot"))).toContain("L'action n'a pas pu aboutir.");
    expect(describeError(apiError(418, "teapot"))).toContain("teapot");
  });

  it("ne confond pas une erreur réseau avec un bug de code", () => {
    expect(describeError(new TypeError("Failed to fetch"))).toContain("Impossible de joindre le serveur");
    expect(describeError(new TypeError("Cannot read properties of undefined"))).toBe("Cannot read properties of undefined");
    expect(describeError(new Error("boom"))).toBe("boom");
    expect(describeError("texte")).toBe("texte");
  });
});
