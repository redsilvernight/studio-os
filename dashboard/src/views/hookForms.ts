import { esc } from "../ui";

export interface HookFormReader {
  text(name: string): string;
}

const EVENTS = ["session_start", "session_end", "user_prompt", "pre_tool", "post_tool", "stop", "subagent_stop", "notification", "pre_compact"] as const;
const MODES = ["advisory", "blocking"] as const;
const PLATFORMS = ["any", "windows", "linux", "macos"] as const;
const SHELLS = ["pwsh", "bash", "sh", "python", "node"] as const;

function options(values: readonly string[], selected: string): string {
  return values.map((value) => `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(value)}</option>`).join("");
}

function scriptRowHtml(index: number): string {
  return `<fieldset data-hook-script-index="${index}"><legend>Script ${index + 1}</legend>` +
    `<label class="stack">Système <select name="hook_script_${index}_os">${options(PLATFORMS, "any")}</select></label>` +
    `<label class="stack">Interpréteur <select name="hook_script_${index}_shell">${options(SHELLS, "pwsh")}</select></label>` +
    `<label class="stack">Corps du script <textarea class="mono" name="hook_script_${index}_body" rows="6" required></textarea></label>` +
    `<button class="ds-btn ds-btn--sm" type="button" data-hook-remove aria-label="Retirer le script ${index + 1}">Retirer ce script</button></fieldset>`;
}

export function hookFieldsHtml(): string {
  return `<div data-hook-fields><label class="stack">Événement <select name="event">${options(EVENTS, "pre_tool")}</select></label>` +
    `<label class="stack">Mode <select name="mode">${options(MODES, "advisory")}</select></label>` +
    `<label class="stack">Matcher <input name="matcher" maxlength="200" placeholder="Filtre facultatif, pour pre_tool et post_tool" /></label>` +
    `<label class="stack">Délai maximal en secondes <input name="timeout_seconds" type="number" min="1" max="600" step="1" value="30" required /></label>` +
    `<label class="stack">Description du hook <textarea name="hook_description" rows="3" maxlength="1000"></textarea></label>` +
    `<p class="ds-list-sub">Un script par couple système / interpréteur, jusqu'à huit variantes. Les scripts seront exécutés localement après consentement sur chaque machine.</p>` +
    `<div data-hook-scripts>${scriptRowHtml(0)}</div><button class="ds-btn ds-btn--sm" type="button" data-hook-add>Ajouter un script</button></div>`;
}

export function bindHookScriptFields(root: HTMLElement): void {
  for (const fields of root.querySelectorAll<HTMLElement>("[data-hook-fields]")) {
    if (fields.dataset["hookBound"] === "true") continue;
    const container = fields.querySelector<HTMLElement>("[data-hook-scripts]");
    const add = fields.querySelector<HTMLButtonElement>("[data-hook-add]");
    if (container === null || add === null) continue;
    fields.dataset["hookBound"] = "true";
    const update = (): void => { add.disabled = container.children.length >= 8; };
    add.addEventListener("click", () => {
      const used = new Set(Array.from(container.children, (row) => Number((row as HTMLElement).dataset["hookScriptIndex"])));
      const index = Array.from({ length: 8 }, (_, i) => i).find((i) => !used.has(i));
      if (index === undefined) return;
      container.insertAdjacentHTML("beforeend", scriptRowHtml(index));
      update();
      container.querySelector<HTMLTextAreaElement>(`textarea[name="hook_script_${index}_body"]`)?.focus();
    });
    container.addEventListener("click", (event) => {
      if (!(event.target instanceof Element)) return;
      const remove = event.target.closest("[data-hook-remove]");
      if (remove === null) return;
      remove.closest("[data-hook-script-index]")?.remove();
      update();
      add.focus();
    });
    update();
  }
}

export function buildHookContent(read: HookFormReader): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const event = read.text("event");
  const mode = read.text("mode");
  const timeoutText = read.text("timeout_seconds").trim();
  const timeout = Number(timeoutText);
  const matcher = read.text("matcher").trim();
  const description = read.text("hook_description").trim();
  if (!(EVENTS as readonly string[]).includes(event)) return { ok: false, error: "Choisissez un événement de hook valide." };
  if (!(MODES as readonly string[]).includes(mode)) return { ok: false, error: "Choisissez un mode valide." };
  if (timeoutText === "" || !Number.isInteger(timeout) || timeout < 1 || timeout > 600) return { ok: false, error: "Le délai doit être un entier de 1 à 600 secondes." };
  if (Array.from(matcher).length > 200 || (matcher !== "" && event !== "pre_tool" && event !== "post_tool")) return { ok: false, error: "Le matcher est limité à 200 caractères et aux événements pre_tool et post_tool." };
  if (mode === "blocking" && !["pre_tool", "user_prompt", "stop"].includes(event)) return { ok: false, error: "Le mode bloquant est disponible pour pre_tool, user_prompt et stop." };
  if (Array.from(description).length > 1000) return { ok: false, error: "La description du hook est limitée à 1 000 caractères." };
  const scripts: { os: string; shell: string; body: string }[] = [];
  const targets = new Set<string>();
  for (let index = 0; index < 8; index++) {
    const os = read.text(`hook_script_${index}_os`);
    const shell = read.text(`hook_script_${index}_shell`);
    const body = read.text(`hook_script_${index}_body`);
    if (os === "" && shell === "" && body === "") continue;
    if (!(PLATFORMS as readonly string[]).includes(os) || !(SHELLS as readonly string[]).includes(shell)) return { ok: false, error: `Choisissez un système et un interpréteur valides pour le script ${index + 1}.` };
    if (body.trim() === "" || Array.from(body).length > 65_536) return { ok: false, error: `Le script ${index + 1} doit contenir de 1 à 65 536 caractères.` };
    const target = `${os}:${shell}`;
    if (targets.has(target)) return { ok: false, error: "Chaque couple système / interpréteur doit être unique." };
    targets.add(target);
    scripts.push({ os, shell, body });
  }
  if (scripts.length === 0) return { ok: false, error: "Ajoutez au moins un script." };
  return { ok: true, value: {
    content_schema: "studio.library.hook/v1", event, mode, timeout_seconds: timeout, scripts,
    ...(matcher === "" ? {} : { matcher }), ...(description === "" ? {} : { description }),
  } };
}
