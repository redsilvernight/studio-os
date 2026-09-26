/**
 * Noms lisibles des machines et agents, résolus côté client.
 *
 * - Sources : GET /api/v1/machines (`display_name` = libellé donné) et
 *   GET /api/v1/agents (`display_name` = nom enregistré), lisibles par toute
 *   machine authentifiée.
 * - Cache module partagé par toutes les vues, rafraîchi au plus toutes les
 *   REFRESH_MS ; chargement best-effort : un échec garde le cache précédent.
 * - Affichage : le nom, avec l'identifiant complet en infobulle ; repli sur
 *   l'identifiant court quand le nom est inconnu (machine révoquée, agent
 *   supprimé, chargement échoué).
 */
import type { StudioClient } from "./api";
import { esc, shortId } from "./ui";

const REFRESH_MS = 60_000;

const machineNames = new Map<string, string>();
const agentNames = new Map<string, string>();
let loadedAt = 0;
let pending: Promise<void> | null = null;

interface Named {
  id: string;
  display_name?: string | null;
}

function fill(target: Map<string, string>, rows: readonly Named[]): void {
  target.clear();
  for (const row of rows) {
    const name = (row.display_name ?? "").trim();
    if (name !== "") target.set(row.id, name);
  }
}

export function setActorNames(machines: readonly Named[] | null, agents: readonly Named[] | null): void {
  if (machines !== null) fill(machineNames, machines);
  if (agents !== null) fill(agentNames, agents);
}

export function resetActorNames(): void {
  machineNames.clear();
  agentNames.clear();
  loadedAt = 0;
  pending = null;
}

async function read(client: StudioClient, path: "/api/v1/machines" | "/api/v1/agents"): Promise<Named[] | null> {
  try {
    const result = await client.GET(path);
    return result.response.ok && Array.isArray(result.data) ? (result.data as Named[]) : null;
  } catch {
    return null;
  }
}

/** Charge (ou rafraîchit) le cache ; ne rejette jamais. */
export function loadActorNames(client: StudioClient, force = false): Promise<void> {
  if (pending !== null) return pending;
  if (!force && loadedAt !== 0 && Date.now() - loadedAt < REFRESH_MS) return Promise.resolve();
  pending = Promise.all([read(client, "/api/v1/machines"), read(client, "/api/v1/agents")])
    .then(([machines, agents]) => {
      setActorNames(machines, agents);
      loadedAt = Date.now();
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}

export function machineName(id: string | null | undefined): string | undefined {
  return id ? machineNames.get(id) : undefined;
}

export function agentName(id: string | null | undefined): string | undefined {
  return id ? agentNames.get(id) : undefined;
}

/** Texte brut : nom, sinon identifiant court. */
export function machineLabel(id: string | null | undefined): string {
  return machineName(id) ?? shortId(id);
}

export function agentLabel(id: string | null | undefined): string {
  return agentName(id) ?? shortId(id);
}

function ref(id: string | null | undefined, name: string | undefined): string {
  if (!id) return "—";
  return name !== undefined
    ? `<span class="actor-name" title="${esc(id)}">${esc(name)}</span>`
    : `<code class="mono" title="${esc(id)}">${esc(shortId(id))}</code>`;
}

/** HTML : nom avec l'identifiant complet en infobulle. */
export function machineRef(id: string | null | undefined): string {
  return ref(id, machineName(id));
}

export function agentRef(id: string | null | undefined): string {
  return ref(id, agentName(id));
}
