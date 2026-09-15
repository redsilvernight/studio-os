/** Hash routes (DOM-free so they stay unit-testable). */
import type { ProjectTab } from "./views/projectDetail";

export type Route =
  | { name: "dashboard" }
  | { name: "projects" }
  | { name: "project"; id: string; tab: ProjectTab }
  | { name: "tasks" }
  | { name: "task"; id: string };

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter((p) => p !== "");
  if (parts.length === 0) return { name: "dashboard" };
  if (parts[0] === "projects" && parts.length === 1) return { name: "projects" };
  if (parts[0] === "projects" && parts[1] !== undefined) {
    const tab: ProjectTab = parts[2] === "tasks" || parts[2] === "claims" ? parts[2] : "overview";
    return { name: "project", id: parts[1], tab };
  }
  if (parts[0] === "tasks" && parts.length === 1) return { name: "tasks" };
  if (parts[0] === "tasks" && parts[1] !== undefined) return { name: "task", id: parts[1] };
  return { name: "dashboard" };
}
