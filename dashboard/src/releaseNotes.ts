/**
 * « Quoi de neuf » — notes de version du Desktop (patch notes).
 *
 * Les notes sont embarquées dans l'application (module généré, aucun appel
 * réseau) et rédigées dans « desktop/release-notes/<version>.md ». Au démarrage,
 * on mémorise localement la dernière version vue : une version courante plus
 * récente ouvre la fenêtre une seule fois, avec les notes cumulées depuis
 * cette version. Une première installation n'affiche rien. L'historique reste
 * accessible depuis « Réglages › Application ».
 */
import { dsModalHtml, openDsDialog } from "./ds/ds";
import type { DesktopInfo, Platform } from "./platform/types";
import { RELEASE_NOTES } from "./releaseNotes.generated";
import { esc } from "./ui";

export const WHATS_NEW_STORAGE_KEY = "studio-os.whats-new.v1";
export const WHATS_NEW_SCHEMA = 1;
export const WHATS_NEW_HOST_ID = "whats-new-host";
export const WHATS_NEW_DIALOG_ID = "whats-new-dialog";

export interface ReleaseNoteEntry {
  version: string;
  markdown: string;
}

export interface WhatsNewDecision {
  /** Une mise à jour a eu lieu et des notes non vues existent. */
  show: boolean;
  /** Aucune version vue : première installation, jamais de fenêtre. */
  freshInstall: boolean;
  entries: ReleaseNoteEntry[];
}

/** La version de base `majeur.mineur.patch` : `0.1.0-dev.42` -> `0.1.0`. */
export function baseVersion(version: string): string {
  const match = /^(\d+\.\d+\.\d+)/.exec(version.trim());
  return match?.[1] ?? version.trim();
}

function parts(version: string): number[] {
  return baseVersion(version)
    .split(".")
    .map((part) => Number.parseInt(part, 10) || 0);
}

/** Compare deux versions de base : < 0, 0 ou > 0. */
export function compareVersions(a: string, b: string): number {
  const left = parts(a);
  const right = parts(b);
  for (let index = 0; index < 3; index += 1) {
    const delta = (left[index] ?? 0) - (right[index] ?? 0);
    if (delta !== 0) return delta > 0 ? 1 : -1;
  }
  return 0;
}

/** Notes des versions strictement postérieures à `seen` et ≤ `current`, ascendantes. */
export function notesSince(
  seen: string | null,
  current: string,
  notes: Record<string, string> = RELEASE_NOTES,
): ReleaseNoteEntry[] {
  return Object.keys(notes)
    .filter((version) => seen === null || compareVersions(version, seen) > 0)
    .filter((version) => compareVersions(version, current) <= 0)
    .sort(compareVersions)
    .map((version) => ({ version, markdown: notes[version] ?? "" }))
    .filter((entry) => entry.markdown !== "");
}

/** Toutes les notes connues, de la plus ancienne à la plus récente. */
export function allNotes(notes: Record<string, string> = RELEASE_NOTES): ReleaseNoteEntry[] {
  return notesSince(null, "9999.0.0", notes);
}

export function decideWhatsNew(
  current: string,
  seen: string | null,
  notes: Record<string, string> = RELEASE_NOTES,
): WhatsNewDecision {
  if (seen === null) return { show: false, freshInstall: true, entries: [] };
  if (compareVersions(current, seen) <= 0) return { show: false, freshInstall: false, entries: [] };
  const entries = notesSince(seen, current, notes);
  return { show: entries.length > 0, freshInstall: false, entries };
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function storage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/** Dernière version vue, ou `null` (première installation / valeur illisible). */
export function loadSeenVersion(store: StorageLike | null = storage()): string | null {
  try {
    const raw = store?.getItem(WHATS_NEW_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { schema?: unknown; version?: unknown };
    if (parsed.schema !== WHATS_NEW_SCHEMA || typeof parsed.version !== "string") return null;
    return baseVersion(parsed.version);
  } catch {
    return null;
  }
}

export function saveSeenVersion(version: string, store: StorageLike | null = storage()): void {
  try {
    store?.setItem(WHATS_NEW_STORAGE_KEY, JSON.stringify({ schema: WHATS_NEW_SCHEMA, version: baseVersion(version) }));
  } catch {
    // Stockage indisponible : la note s'affichera au prochain lancement.
  }
}

function inline(text: string): string {
  return esc(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

/** Rendu Markdown minimal et sûr (titres, listes, gras) des notes. */
export function renderNoteMarkdown(markdown: string): string {
  const html: string[] = [];
  let list: string[] = [];
  const flush = (): void => {
    if (list.length > 0) {
      html.push(`<ul>${list.map((item) => `<li>${item}</li>`).join("")}</ul>`);
      list = [];
    }
  };
  for (const raw of markdown.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trim();
    if (line === "") {
      flush();
    } else if (line.startsWith("## ")) {
      flush();
      html.push(`<h3>${esc(line.slice(3))}</h3>`);
    } else if (line.startsWith("# ")) {
      flush();
      html.push(`<h2>${esc(line.slice(2))}</h2>`);
    } else if (line.startsWith("- ")) {
      list.push(inline(line.slice(2)));
    } else {
      flush();
      html.push(`<p>${inline(line)}</p>`);
    }
  }
  flush();
  return html.join("");
}

export function whatsNewModalHtml(entries: ReleaseNoteEntry[], title = "Quoi de neuf"): string {
  const body = entries
    .map(
      (entry) =>
        `<section class="whats-new-entry" data-version="${esc(entry.version)}">${renderNoteMarkdown(entry.markdown)}</section>`,
    )
    .join("");
  return dsModalHtml({
    id: WHATS_NEW_DIALOG_ID,
    title,
    body,
    actions: [{ label: "Fermer" }],
  });
}

/**
 * Ouvre la fenêtre « Quoi de neuf ». Les notes sont rendues comme données
 * citées ; la fenêtre se ferme au clavier (Échap) et au bouton Fermer, et le
 * focus revient au déclencheur.
 */
export function openWhatsNew(root: ParentNode, entries: ReleaseNoteEntry[], title = "Quoi de neuf"): HTMLElement | null {
  if (entries.length === 0) return null;
  const doc = (root instanceof Document ? root : root.ownerDocument) ?? document;
  let host = doc.getElementById(WHATS_NEW_HOST_ID);
  if (host === null) {
    host = doc.createElement("div");
    host.id = WHATS_NEW_HOST_ID;
    doc.body.appendChild(host);
  }
  host.innerHTML = whatsNewModalHtml(entries, title);
  openDsDialog(host, WHATS_NEW_DIALOG_ID);
  return host;
}

/** Section « Notes de version » des Réglages (Desktop uniquement). */
export function whatsNewSectionHtml(notes: Record<string, string> = RELEASE_NOTES): string {
  const entries = allNotes(notes);
  if (entries.length === 0) return "";
  const latest = entries[entries.length - 1] as ReleaseNoteEntry;
  const versions = entries
    .map((entry) => `<li><code class="mono">${esc(entry.version)}</code></li>`)
    .reverse()
    .join("");
  return (
    `<section class="settings-domain" data-testid="whats-new-section"><h2>Notes de version</h2>` +
    `<p class="settings-intro">Les nouveautés de chaque mise à jour, de la plus récente à la plus ancienne.</p>` +
    `<div class="settings-actions"><button class="ds-btn ds-btn--ghost" type="button" data-action="open-whats-new" ` +
    `data-testid="open-whats-new">Ouvrir « Quoi de neuf » (${esc(latest.version)})</button></div>` +
    `<ul class="settings-refs" data-testid="whats-new-versions">${versions}</ul>` +
    `</section>`
  );
}

/**
 * Au démarrage du Desktop : première installation = on mémorise la version sans
 * rien afficher ; version plus récente qu'à la dernière fois = fenêtre une
 * seule fois, avec les notes cumulées.
 */
export async function checkWhatsNewAtStart(
  platform: Pick<Platform, "mode" | "desktopInfo">,
  notes: Record<string, string> = RELEASE_NOTES,
): Promise<void> {
  if (platform.mode !== "desktop") return;
  let info: DesktopInfo | null = null;
  try {
    info = await platform.desktopInfo();
  } catch {
    return;
  }
  if (info === null) return;
  const current = info.desktop_version;
  const decision = decideWhatsNew(current, loadSeenVersion(), notes);
  if (decision.freshInstall) {
    saveSeenVersion(current);
    return;
  }
  if (!decision.show) return;
  openWhatsNew(document, decision.entries);
  saveSeenVersion(current);
}
