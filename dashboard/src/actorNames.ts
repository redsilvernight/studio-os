/**
 * Noms lisibles des machines et agents, résolus côté client.
 *
 * - Sources : GET /api/v1/machines (`display_name` = libellé donné) et
 *   GET /api/v1/agents (`display_name` = nom enregistré), lisibles par toute
 *   machine authentifiée.
 * - Cache module partagé par toutes les vues, rafraîchi au plus toutes les
 *   REFRESH_MS ; chargement best-effort : un échec garde le cache précédent.
 * - Affichage : le nom ; repli sur un libellé générique (« Agent sans nom »)
 *   quand le nom est inconnu (machine révoquée, agent supprimé, chargement
 *   échoué). Jamais d'identifiant, même court (UX V2, cible C2).
 */
import type { StudioClient } from "./api";
import { FALLBACK_LABEL } from "./language";
import { esc } from "./ui";

const REFRESH_MS = 60_000;

const machineNames = new Map<string, string>();
const agentNames = new Map<string, string>();
const projectNames = new Map<string, string>();
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

export function setActorNames(
  machines: readonly Named[] | null,
  agents: readonly Named[] | null,
  projects: readonly { id: string; name?: string | null }[] | null = null,
): void {
  if (machines !== null) fill(machineNames, machines);
  if (agents !== null) fill(agentNames, agents);
  if (projects !== null) fill(projectNames, projects.map((p) => ({ id: p.id, display_name: p.name })));
}

export function resetActorNames(): void {
  machineNames.clear();
  agentNames.clear();
  projectNames.clear();
  loadedAt = 0;
  pending = null;
}

async function read(client: StudioClient, path: "/api/v1/machines" | "/api/v1/agents" | "/api/v1/projects"): Promise<Named[] | null> {
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
  pending = Promise.all([read(client, "/api/v1/machines"), read(client, "/api/v1/agents"), read(client, "/api/v1/projects")])
    .then(([machines, agents, projects]) => {
      setActorNames(machines, agents, projects as { id: string; name?: string | null }[] | null);
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

export function projectName(id: string | null | undefined): string | undefined {
  return id ? projectNames.get(id) : undefined;
}

/** Texte brut : nom, sinon libellé générique (jamais d'identifiant). */
export function machineLabel(id: string | null | undefined): string {
  return machineName(id) ?? FALLBACK_LABEL.machine;
}

export function agentLabel(id: string | null | undefined): string {
  return agentName(id) ?? FALLBACK_LABEL.agent;
}

export function projectLabel(id: string | null | undefined): string {
  return projectName(id) ?? FALLBACK_LABEL.project;
}

function ref(id: string | null | undefined, name: string | undefined, fallback: string): string {
  if (!id) return "—";
  return name !== undefined
    ? `<span class="actor-name">${esc(name)}</span>`
    : `<span class="actor-name actor-name--unknown">${esc(fallback)}</span>`;
}

/** HTML : nom, sinon libellé générique ; aucun identifiant (ni texte ni infobulle). */
export function machineRef(id: string | null | undefined): string {
  return ref(id, machineName(id), FALLBACK_LABEL.machine);
}

export function agentRef(id: string | null | undefined): string {
  return ref(id, agentName(id), FALLBACK_LABEL.agent);
}
