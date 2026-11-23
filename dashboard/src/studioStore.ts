/**
 * Studio actif (R2-coque, fiche E1) — sélection persistée, changement sans
 * rechargement de la page (un événement `studio-change` est émis, le shell
 * repeint la vue courante).
 */
import type { Studio } from "./studiosApi";

export const STUDIO_CHANGE_EVENT = "studio-change";
const STORAGE_KEY = "studios.selected";

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(id: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* stockage indisponible : la sélection vit en mémoire de session */
  }
}

let studios: Studio[] = [];
let activeId: string | null = readStored();
const listeners = new Set<(active: Studio | null) => void>();

export function setStudios(next: Studio[]): void {
  studios = [...next];
  if (activeId === null) activeId = readStored();
  if (activeId === null || !studios.some((studio) => studio.id === activeId)) {
    activeId = studios[0]?.id ?? null;
  }
}

export function getStudios(): Studio[] {
  return [...studios];
}

export function getActiveStudio(): Studio | null {
  return studios.find((studio) => studio.id === activeId) ?? studios[0] ?? null;
}

/** Change de studio sans recharger : persiste + notifie (le shell repeint). */
export function selectStudio(id: string): Studio | null {
  if (!studios.some((studio) => studio.id === id)) return null;
  activeId = id;
  writeStored(id);
  const active = getActiveStudio();
  for (const listener of [...listeners]) listener(active);
  window.dispatchEvent(new CustomEvent(STUDIO_CHANGE_EVENT, { detail: { id } }));
  return active;
}

export function subscribeStudios(listener: (active: Studio | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Remise à zéro pour les tests. */
export function resetStudioStoreForTests(): void {
  studios = [];
  activeId = null;
  listeners.clear();
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
