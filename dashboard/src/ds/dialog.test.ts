// @vitest-environment happy-dom
/**
 * UI-14 — primitive dialogue/onglets/toast : focus trap, Échap persistant,
 * retour focus, câblage unique entre réouvertures, Début/Fin des onglets.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  closeDsDialog,
  dsModalHtml,
  dsNotify,
  dsTabsHtml,
  focusDsErrorBox,
  initDsTabs,
  openDsDialog,
} from "./ds";

function keydown(target: Element, key: string, shift = false): void {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, shiftKey: shift });
  target.dispatchEvent(event);
}

describe("openDsDialog / closeDsDialog", () => {
  beforeEach(() => {
    document.body.innerHTML =
      `<button id="trigger" type="button">Ouvrir</button>` +
      dsModalHtml({
        id: "dlg",
        title: "Titre",
        body: `<input id="field" type="text" /><button id="stay" type="button">Rester</button>`,
        actions: [{ label: "Fermer", variant: "primary" }],
      });
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("ouvre, focalise le titre et rend le focus au déclencheur à la fermeture", () => {
    const trigger = document.getElementById("trigger") as HTMLButtonElement;
    trigger.focus();
    openDsDialog(document, "dlg", trigger);
    const overlay = document.getElementById("dlg") as HTMLElement;
    expect(overlay.hasAttribute("hidden")).toBe(false);
    expect(document.activeElement?.textContent).toContain("Titre");
    closeDsDialog(document, "dlg");
    expect(overlay.hasAttribute("hidden")).toBe(true);
    expect(document.activeElement).toBe(trigger);
  });

  it("piège Tab et Shift+Tab dans le dialogue", () => {
    const trigger = document.getElementById("trigger") as HTMLButtonElement;
    openDsDialog(document, "dlg", trigger);
    const field = document.getElementById("field") as HTMLInputElement;
    const stay = document.getElementById("stay") as HTMLButtonElement;
    const close = document.querySelector<HTMLElement>("#dlg [data-ds-close]") as HTMLElement;

    close.focus();
    keydown(close, "Tab");
    expect(document.activeElement).toBe(field);

    field.focus();
    keydown(field, "Tab", true);
    expect(document.activeElement).toBe(close);

    stay.focus();
    keydown(stay, "Tab");
    expect(document.activeElement).toBe(stay);
  });

  it("Échap ferme sur chaque ouverture, sans recâblage", () => {
    const trigger = document.getElementById("trigger") as HTMLButtonElement;
    for (let i = 0; i < 3; i += 1) {
      openDsDialog(document, "dlg", trigger);
      expect(document.getElementById("dlg")?.hasAttribute("hidden")).toBe(false);
      keydown(document.getElementById("dlg") as HTMLElement, "Escape");
      expect(document.getElementById("dlg")?.hasAttribute("hidden")).toBe(true);
    }
    expect(document.activeElement).toBe(trigger);
  });

  it("oublie un déclencheur disparu : la fermeture suivante ne refocalise pas un nœud mort", () => {
    const trigger = document.getElementById("trigger") as HTMLButtonElement;
    openDsDialog(document, "dlg", trigger);
    trigger.remove();
    closeDsDialog(document, "dlg");
    const trigger2 = document.createElement("button");
    trigger2.id = "trigger2";
    trigger2.type = "button";
    trigger2.textContent = "Second";
    document.body.prepend(trigger2);
    openDsDialog(document, "dlg", trigger2);
    keydown(document.getElementById("dlg") as HTMLElement, "Escape");
    expect(document.activeElement).toBe(trigger2);
  });
});

describe("focusDsErrorBox", () => {
  it("rend le bloc atteignable et le focalise", () => {
    document.body.innerHTML = `<div id="err" role="alert" hidden>Erreur</div>`;
    const box = document.getElementById("err") as HTMLElement;
    focusDsErrorBox(box);
    expect(box.getAttribute("tabindex")).toBe("-1");
    expect(document.activeElement).toBe(box);
    document.body.innerHTML = "";
  });
});

describe("initDsTabs", () => {
  beforeEach(() => {
    document.body.innerHTML = dsTabsHtml(
      "demo",
      [
        { id: "a", label: "Premier", panel: "<p>A</p>" },
        { id: "b", label: "Deuxième", panel: "<p>B</p>" },
        { id: "c", label: "Troisième", panel: "<p>C</p>" },
      ],
      "a",
      "Démonstration",
    );
    initDsTabs(document, "demo");
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("Début et Fin déplacent le focus et la sélection", () => {
    const tabs = [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
    tabs[0]?.focus();
    keydown(tabs[0] as HTMLElement, "End");
    expect(document.activeElement).toBe(tabs[2]);
    expect(tabs[2]?.getAttribute("aria-selected")).toBe("true");
    keydown(tabs[2] as HTMLElement, "Home");
    expect(document.activeElement).toBe(tabs[0]);
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("true");
  });
});

describe("dsNotify", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="ds-toast-region" role="status" aria-live="polite"></div>`;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("annonce une erreur en alerte et la conserve plus longtemps", () => {
    dsNotify("Échec critique.", "danger");
    const toast = document.querySelector(".ds-toast--danger");
    expect(toast?.getAttribute("role")).toBe("alert");
    vi.advanceTimersByTime(6000);
    expect(document.querySelector(".ds-toast--danger")).not.toBeNull();
    vi.advanceTimersByTime(6000);
    expect(document.querySelector(".ds-toast--danger")).toBeNull();
  });

  it("retire une info après le délai standard", () => {
    dsNotify("Note.", "info");
    expect(document.querySelector(".ds-toast--info")).not.toBeNull();
    vi.advanceTimersByTime(6000);
    expect(document.querySelector(".ds-toast--info")).toBeNull();
  });
});
