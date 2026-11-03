import type { StudioClient } from "./api";
import { listLibraryResources, listLibraryVersions, type LibraryResource, type LibraryVersion } from "./libraryApi";

export interface HookVersionSummary {
  version: number;
  event: string;
  matcher: string | null;
  mode: string;
}

export interface HookListContent {
  summary: HookVersionSummary | null;
  error?: string;
}

export interface IncomingHookDependency {
  resource: LibraryResource;
  sourceVersion: number;
  hookVersion: number;
}

export function hookVersionSummary(version: LibraryVersion): HookVersionSummary | null {
  const content = version.content;
  const mode = content["mode"] ?? "advisory";
  if (content["content_schema"] !== "studio.library.hook/v1" || typeof content["event"] !== "string" || typeof mode !== "string") return null;
  return {
    version: version.version,
    event: content["event"],
    matcher: typeof content["matcher"] === "string" ? content["matcher"] : null,
    mode,
  };
}

async function readVersions<T>(
  client: StudioClient,
  resources: LibraryResource[],
  convert: (resource: LibraryResource, versions: LibraryVersion[]) => T,
): Promise<{ values: Map<string, T>; errors: Map<string, string> }> {
  const values = new Map<string, T>();
  const errors = new Map<string, string>();
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(4, resources.length) }, async () => {
    while (next < resources.length) {
      const resource = resources[next++]!;
      try {
        values.set(resource.id, convert(resource, await listLibraryVersions(client, resource.id)));
      } catch (error) {
        errors.set(resource.id, error instanceof Error ? error.message : String(error));
      }
    }
  }));
  return { values, errors };
}

export async function loadHookListContent(client: StudioClient, resources: LibraryResource[]): Promise<Map<string, HookListContent>> {
  const loaded = await readVersions(client, resources, (resource, versions) => {
    const selected = resource.active_version > 0
      ? versions.find((version) => version.version === resource.active_version)
      : [...versions].sort((a, b) => b.version - a.version)[0];
    return selected === undefined ? null : hookVersionSummary(selected);
  });
  return new Map(resources.map((resource) => [resource.id, {
    summary: loaded.values.get(resource.id) ?? null,
    ...(loaded.errors.has(resource.id) ? { error: loaded.errors.get(resource.id)! } : {}),
  }]));
}

export async function loadIncomingHookDependencies(
  client: StudioClient,
  hook: LibraryResource,
): Promise<{ dependencies: IncomingHookDependency[]; errors: string[] }> {
  const resources: LibraryResource[] = [];
  for (const kind of ["agent_definition", "workflow"] as const) {
    let offset = 0;
    while (true) {
      const page = await listLibraryResources(client, { kind, limit: 100, offset });
      resources.push(...page);
      if (page.length < 100) break;
      offset += page.length;
    }
  }
  const loaded = await readVersions(client, resources, (resource, versions) => versions.flatMap((version) =>
    version.dependencies.filter((pin) => pin.kind === "hook" && pin.stable_key === hook.stable_key && (pin.relation === "uses_hook" || pin.relation == null))
      .map((pin) => ({ resource, sourceVersion: version.version, hookVersion: pin.version })),
  ));
  return { dependencies: [...loaded.values.values()].flat(), errors: [...loaded.errors.values()] };
}
