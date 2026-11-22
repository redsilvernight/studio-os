// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from "vitest";
import { confirmDs } from "./confirm";
import { answerConfirm } from "./confirmTest";

afterEach(() => { document.body.innerHTML = ""; });

describe("confirmDs", () => {
  it("résout true au clic sur Confirmer et retire le dialogue", async () => {
    const trigger = document.createElement("button");
    document.body.append(trigger);
    trigger.focus();
    const result = confirmDs("Supprimer ?", { confirmLabel: "Supprimer", danger: true });
    expect(document.querySelector("[role=dialog]")).not.toBeNull();
    expect(document.querySelector("[data-ds-confirm=ok]")?.textContent).toBe("Supprimer");
    expect(document.querySelector("[data-ds-confirm=ok]")?.className).toContain("ds-btn--danger");
    expect(await answerConfirm(true)).toBe("Supprimer ?");
    expect(await result).toBe(true);
    expect(document.querySelector("[role=dialog]")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("résout false sur Annuler et sur Échap", async () => {
    const cancelled = confirmDs("Continuer ?");
    await answerConfirm(false);
    expect(await cancelled).toBe(false);
    const escaped = confirmDs("Continuer ?");
    document.querySelector("[role=dialog]")?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(await escaped).toBe(false);
  });

  it("rend le message en texte brut", async () => {
    const result = confirmDs("<img src=x onerror=alert(1)>");
    expect(document.querySelector("[data-ds-confirm-message] img")).toBeNull();
    await answerConfirm(false);
    await result;
  });
});
