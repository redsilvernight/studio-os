/** Hash routes (DOM-free so they stay unit-testable). */
import { isLibraryKindSlug, type LibraryKindSlug } from "./libraryFormat";
import type { ProjectTab } from "./views/projectDetail";

export type ProjectConfigTab = "resources" | "locks" | "overrides";

export type Route =
  | { name: "dashboard" }
  | { name: "projects" }
  | { name: "project"; id: string; tab: ProjectTab; roadmapId?: string }
  | { name: "tasks" }
  | { name: "task"; id: string }
  | { name: "agents" }
  | { name: "agent"; id: string }
  | { name: "machines" }
  | { name: "decisions" }
  | { name: "transfers" }
  | { name: "library"; kind: LibraryKindSlug | null }
  | { name: "libraryDetail"; kind: LibraryKindSlug; id: string }
  | { name: "configRuntimes" }
  | { name: "configRuntime"; id: string }
  | { name: "configBindings" }
  | { name: "configProject"; tab: ProjectConfigTab }
  | { name: "inspector"; stableKey: string | null }
  | { name: "designSystem" }
  | { name: "notFound"; hash: string };

function decode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/** Hash inconnu → route 404 explicite (UI-2 : plus de repli silencieux). */
function notFound(hash: string): Route {
  return { name: "notFound", hash };
}

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter((p) => p !== "");
  if (parts.length === 0) return { name: "dashboard" };
  if (parts[0] === "projects" && parts.length === 1) return { name: "projects" };
  if (parts[0] === "projects" && parts[1] !== undefined) {
    const tab: ProjectTab =
      parts[2] === "roadmap" ||
      parts[2] === "tasks" ||
      parts[2] === "claims" ||
      parts[2] === "activity" ||
      parts[2] === "decisions"
        ? parts[2]
        : "overview";
    const roadmapId = tab === "roadmap" && parts.length === 4 && parts[3] !== undefined ? decode(parts[3]) : undefined;
    if (tab === "roadmap" && parts.length > 4) return notFound(hash);
    return roadmapId === undefined ? { name: "project", id: parts[1], tab } : { name: "project", id: parts[1], tab, roadmapId };
  }
  if (parts[0] === "tasks" && parts.length === 1) return { name: "tasks" };
  if (parts[0] === "tasks" && parts[1] !== undefined) return { name: "task", id: parts[1] };
  if (parts[0] === "agents" && parts.length === 1) return { name: "agents" };
  if (parts[0] === "agents" && parts.length === 2 && parts[1] !== undefined) {
    return { name: "agent", id: decode(parts[1]) };
  }
  if (parts[0] === "agents") return notFound(hash);
  if (parts[0] === "machines" && parts.length === 1) return { name: "machines" };
  if (parts[0] === "decisions" && parts.length === 1) return { name: "decisions" };
  if (parts[0] === "transfers" && parts.length === 1) return { name: "transfers" };
  if (parts[0] === "library") {
    if (parts.length === 1) return { name: "library", kind: null };
    const kind = parts[1];
    if (kind !== undefined && isLibraryKindSlug(kind)) {
      if (parts.length === 2) return { name: "library", kind };
      if (parts.length === 3 && parts[2] !== undefined) {
        return { name: "libraryDetail", kind, id: decode(parts[2]) };
      }
    }
    return notFound(hash);
  }
  if (parts[0] === "configuration") {
    if (parts.length === 1) return { name: "configRuntimes" };
    if (parts[1] === "runtimes" && parts.length === 2) return { name: "configRuntimes" };
    if (parts[1] === "runtimes" && parts.length === 3 && parts[2] !== undefined) {
      return { name: "configRuntime", id: decode(parts[2]) };
    }
    if (parts[1] === "bindings" && parts.length === 2) return { name: "configBindings" };
    if (parts[1] === "project" && parts.length <= 3) {
      const tab: ProjectConfigTab =
        parts[2] === "locks" || parts[2] === "overrides" ? parts[2] : "resources";
      return { name: "configProject", tab };
    }
    return notFound(hash);
  }
  if (parts[0] === "inspector") {
    if (parts.length === 1) return { name: "inspector", stableKey: null };
    if (parts.length === 2 && parts[1] !== undefined) {
      return { name: "inspector", stableKey: decode(parts[1]) };
    }
    return notFound(hash);
  }
  if (parts[0] === "design-system" && parts.length === 1) return { name: "designSystem" };
  return notFound(hash);
}
