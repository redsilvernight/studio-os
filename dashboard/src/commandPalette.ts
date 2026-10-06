/**
 * Palette « Aller à… » (Ctrl K, UX V2 P03-shell).
 *
 * Une seule navigation : la palette liste exactement les destinations de la
 * barre latérale (quotidiennes + Administration), filtrées localement. Ce
 * n'est pas une recherche globale (aucun backend) : elle donne l'accès rapide
 * aux surfaces expertes sans seconde navigation concurrente.
 */
import type { Route } from "./router";
import { icon, shellNavGroups, type ShellNavItem } from "./shell";
import { esc } from "./ui";

export interface PaletteEntry {
  href: string;
  label: string;
  group: string;
  icon: string;
}

export function paletteEntries(route: Route, desktop = false): PaletteEntry[] {
  return shellNavGroups(route, desktop).flatMap((group) =>
    group.items.map((item: ShellNavItem) => ({ href: item.href, label: item.label, group: group.title, icon: item.icon })),
  );
}

/** Minuscules sans accents : « a valider » trouve « À valider ». */
function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim();
}

/** Filtre : chaque mot de la requête doit apparaître ; les débuts de libellé d'abord. */
export function filterPalette(entries: PaletteEntry[], query: string): PaletteEntry[] {
  const words = fold(query).split(/\s+/).filter((word) => word !== "");
  if (words.length === 0) return entries;
  const hits = entries.filter((entry) => {
    const hay = fold(`${entry.label} ${entry.group}`);
    return words.every((word) => hay.includes(word));
  });
  const first = words[0] as string;
  return [...hits.filter((e) => fold(e.label).startsWith(first)), ...hits.filter((e) => !fold(e.label).startsWith(first))];
}

export function paletteListHtml(entries: PaletteEntry[], activeIndex: number): string {
  if (entries.length === 0) return `<li class="app-palette-empty" role="presentation">Aucune page ne correspond.</li>`;
  return entries
    .map((entry, index) => {
      const selected = index === activeIndex;
      return (
        `<li class="app-palette-item${selected ? " active" : ""}" id="app-palette-opt-${index}" role="option" ` +
        `aria-selected="${selected ? "true" : "false"}" data-href="${esc(entry.href)}">` +
        `${icon(entry.icon)}<span class="app-palette-label">${esc(entry.label)}</span>` +
        `<span class="app-palette-group">${esc(entry.group)}</span></li>`
      );
    })
    .join("");
}

interface PaletteState {
  entries: PaletteEntry[];
  shown: PaletteEntry[];
  active: number;
  trigger: HTMLElement | null;
}

let state: PaletteState | null = null;
let keyListener = false;
let source: () => PaletteEntry[] = () => [];

function overlay(): HTMLElement | null {
  return document.getElementById("app-palette");
}

export function isPaletteOpen(): boolean {
  const node = overlay();
  return node !== null && !node.hidden;
}

function paint(): void {
  const list = document.getElementById("app-palette-list");
  const input = document.getElementById("app-palette-input") as HTMLInputElement | null;
  if (list === null || input === null || state === null) return;
  list.innerHTML = paletteListHtml(state.shown, state.active);
  if (state.shown.length > 0) {
    input.setAttribute("aria-activedescendant", `app-palette-opt-${state.active}`);
    document.getElementById(`app-palette-opt-${state.active}`)?.scrollIntoView({ block: "nearest" });
  } else {
    input.removeAttribute("aria-activedescendant");
  }
}

export function closePalette(restoreFocus = true): void {
  const node = overlay();
  if (node === null || node.hidden) return;
  node.hidden = true;
  const trigger = state?.trigger ?? null;
  state = null;
  if (restoreFocus && trigger !== null && document.contains(trigger)) trigger.focus();
}

function go(href: string): void {
  closePalette(false);
  if (location.hash === href) document.getElementById("view")?.focus();
  else location.hash = href;
}

export function openPalette(entries: PaletteEntry[], trigger: HTMLElement | null): void {
  const node = overlay();
  const input = document.getElementById("app-palette-input") as HTMLInputElement | null;
  if (node === null || input === null) return;
  state = { entries, shown: entries, active: 0, trigger };
  input.value = "";
  node.hidden = false;
  paint();
  input.focus();
}

/**
 * Câble la palette sur un shell fraîchement monté. `entries` est relu à
 * chaque ouverture (la route courante change l'état actif, pas la liste).
 */
export function mountPalette(entries: () => PaletteEntry[]): void {
  const node = overlay();
  const input = document.getElementById("app-palette-input") as HTMLInputElement | null;
  const list = document.getElementById("app-palette-list");
  const opener = document.getElementById("palette-open");
  if (node === null || input === null || list === null) return;
  source = entries;
  opener?.addEventListener("click", () => openPalette(source(), opener));
  node.addEventListener("click", (event) => {
    if (event.target === node) closePalette();
  });
  input.addEventListener("input", () => {
    if (state === null) return;
    state.shown = filterPalette(state.entries, input.value);
    state.active = 0;
    paint();
  });
  input.addEventListener("keydown", (event) => {
    if (state === null) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (state.shown.length === 0) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      state.active = (state.active + step + state.shown.length) % state.shown.length;
      paint();
    } else if (event.key === "Enter") {
      event.preventDefault();
      const entry = state.shown[state.active];
      if (entry !== undefined) go(entry.href);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closePalette();
    } else if (event.key === "Tab") {
      // Un seul champ dans le dialogue : le focus y reste (piège modal).
      event.preventDefault();
    }
  });
  list.addEventListener("click", (event) => {
    const item = (event.target as HTMLElement | null)?.closest<HTMLElement>("[data-href]");
    const href = item?.dataset["href"];
    if (href !== undefined) go(href);
  });
  if (!keyListener) {
    keyListener = true;
    document.addEventListener("keydown", (event) => {
      if (event.key.toLowerCase() !== "k" || !(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return;
      if (overlay() === null) return;
      event.preventDefault();
      if (isPaletteOpen()) {
        closePalette();
        return;
      }
      // Pas par-dessus un dialogue métier déjà ouvert.
      if (document.querySelector(".ds-overlay:not([hidden]):not(#app-palette)") !== null) return;
      const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      openPalette(source(), active);
    });
  }
}

/** Test seam. */
export function resetPaletteForTests(): void {
  state = null;
}
