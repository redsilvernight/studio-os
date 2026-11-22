// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import {
  dsActorAvatar,
  dsEntitySelect,
  dsIcon,
  dsIllustratedEmpty,
  dsPagination,
  dsPersistentNotice,
  dsSegmented,
  initDsEntitySelect,
  initDsPersistentNotice,
} from "./lot1";
import { dsMarkdown } from "./markdown";

const OPTIONS = [
  { id: "a", label: "Atelier", meta: "Propriétaire" },
  { id: "b", label: "Nord" },
];

describe("lot 1 — rendu", () => {
  it("icônes décoratives, taille bornée", () => {
    expect(dsIcon("check")).toContain('aria-hidden="true"');
    expect(dsIcon("check", 9999)).toContain('width="16"');
  });

  it("avatar agent annonce « Agent … », humain affiche les initiales", () => {
    expect(dsActorAvatar("Relecteur", "agent")).toContain('aria-label="Agent Relecteur"');
    expect(dsActorAvatar("Amina Benali")).toContain(">AB<");
    expect(dsActorAvatar("<b>x</b>")).not.toContain("<b>");
  });

  it("état vide illustré : une action, texte échappé", () => {
    const html = dsIllustratedEmpty("inbox", "<i>T</i>", "m", { label: "Go", href: "#/x" });
    expect(html).toContain("ds-empty-art");
    expect(html).not.toContain("<i>T</i>");
    expect(html.match(/<a class="ds-btn /g)).toHaveLength(1);
  });

  it("notification : danger = alert, sinon status ; fermeture à la demande", () => {
    expect(dsPersistentNotice("n", "danger", "T", "m")).toContain('role="alert"');
    const warn = dsPersistentNotice("n", "warning", "T", "m", { dismissible: true });
    expect(warn).toContain('role="status"');
    expect(warn).toContain("data-ds-dismiss");
    expect(dsPersistentNotice("n", "info", "T", "m")).not.toContain("data-ds-dismiss");
  });

  it("pagination : page courante, bords désactivés, fenêtre avec trous", () => {
    const first = dsPagination(1, 10, (p) => `#${p}`);
    expect(first).toContain('aria-current="page"');
    expect(first).toContain('aria-disabled="true"');
    expect(first).toContain("ds-page-gap");
    expect(dsPagination(1, 1, (p) => `#${p}`).match(/aria-disabled/g)).toHaveLength(2);
    expect(dsPagination(99, 3, (p) => `#${p}`)).toContain('aria-label="Page 3" aria-current="page"');
  });

  it("bascule segmentée : un seul radio coché", () => {
    const html = dsSegmented("m", "Mode", [{ value: "s", label: "S" }, { value: "e", label: "E" }], "e");
    expect(html.match(/checked/g)).toHaveLength(1);
    expect(html).toContain("<legend");
  });
});

describe("sélecteur d'entité — clavier", () => {
  function mount(): { root: HTMLElement; onChange: ReturnType<typeof vi.fn>; trigger: HTMLButtonElement; list: HTMLElement } {
    const root = document.createElement("div");
    root.innerHTML = dsEntitySelect("sel", "Studio", OPTIONS, "a");
    document.body.append(root);
    const onChange = vi.fn();
    initDsEntitySelect(root, "sel", onChange);
    return { root, onChange, trigger: root.querySelector("button") as HTMLButtonElement, list: root.querySelector("ul") as HTMLElement };
  }
  const key = (el: Element, k: string): void => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
  };

  it("ouvre, navigue, choisit et rend le focus", () => {
    const { trigger, list, onChange, root } = mount();
    key(trigger, "ArrowDown");
    expect(list.hidden).toBe(false);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    key(list, "ArrowDown");
    key(list, "Enter");
    expect(onChange).toHaveBeenCalledWith("b");
    expect(list.hidden).toBe(true);
    expect(document.activeElement).toBe(trigger);
    expect(root.querySelector(".ds-entity-current")?.textContent).toBe("Nord");
    expect(root.querySelectorAll('[aria-selected="true"]')).toHaveLength(1);
  });

  it("Échap ferme sans changer la valeur", () => {
    const { trigger, list, onChange } = mount();
    trigger.click();
    key(list, "Escape");
    expect(list.hidden).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("notification persistante — fermeture", () => {
  it("retire le bandeau", () => {
    const root = document.createElement("div");
    root.innerHTML = dsPersistentNotice("n1", "warning", "T", "m", { dismissible: true });
    initDsPersistentNotice(root, "n1");
    (root.querySelector("[data-ds-dismiss]") as HTMLElement).click();
    expect(root.querySelector("#n1")).toBeNull();
  });
});

describe("dsMarkdown — sûreté", () => {
  const attacks = [
    "<script>alert(1)</script>",
    '<img src=x onerror="alert(1)">',
    "[clic](javascript:alert(1))",
    "[clic](JaVaScRiPt:alert(1))",
    "[clic](data:text/html;base64,PHNjcmlwdD4=)",
    "[clic](vbscript:msgbox(1))",
    "![x](https://evil.test/p.png)",
    "![x](javascript:alert(1))",
    '[a](https://ok.test/"onmouseover="alert(1))',
    "<a href=\"javascript:alert(1)\">x</a>",
    "`<script>`",
    "```\n<script>alert(1)</script>\n```",
  ];

  it.each(attacks)("neutralise %s", (attack) => {
    const host = document.createElement("div");
    host.innerHTML = dsMarkdown(attack);
    expect(host.querySelector("script, img, iframe, svg, object, embed")).toBeNull();
    for (const el of host.querySelectorAll("*")) {
      for (const attr of el.getAttributeNames()) {
        expect(attr.startsWith("on"), `${attr} sur <${el.tagName}>`).toBe(false);
      }
    }
    for (const a of host.querySelectorAll("a")) {
      expect(a.getAttribute("href")).toMatch(/^(https?:\/\/|mailto:)/i);
    }
    expect(host.querySelectorAll("[style]")).toHaveLength(0);
  });

  it("rend le formatage prévu et décale les titres sous h1", () => {
    const html = dsMarkdown("# T\n\n**g** *i* `c` [l](https://example.com)\n\n- a\n- b\n\n1. x");
    expect(html).toContain("<h3>T</h3>");
    expect(html).toContain("<strong>g</strong>");
    expect(html).toContain("<em>i</em>");
    expect(html).toContain("<code>c</code>");
    expect(html).toContain('<a href="https://example.com" rel="noopener noreferrer" target="_blank">l</a>');
    expect(html).toContain("<ul><li>a</li><li>b</li></ul>");
    expect(html).toContain("<ol><li>x</li></ol>");
  });

  it("ne garde que l'alternative d'une image", () => {
    expect(dsMarkdown("![logo](https://x.test/a.png)")).toContain("<p>logo</p>");
  });
});
