import type { Platform } from "../platform";
import type { LocalWorkspaceConfig, WorkspaceListResult, WorkspaceStatus } from "../platform/generated/local-contracts.generated";
import { callWorkspace, type WorkspaceOutcome } from "../onboarding/workspaceApi";

export { confirmRoots, saveWorkspaceConfig, validateWorkspace, workspaceErrorMessage } from "../onboarding/workspaceApi";
export type { WorkspaceOutcome } from "../onboarding/workspaceApi";

export async function listWorkspaces(platform: Platform): Promise<WorkspaceOutcome<WorkspaceStatus[]>> {
  const result = await callWorkspace<WorkspaceListResult>(platform, "workspace.list", {});
  return result.ok ? { ok: true, value: result.value.items ?? [] } : result;
}

export function folderKey(path: string): string {
  return path.replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
}

export function findLinkedWorkspace(items: WorkspaceStatus[], projectId: string, root: string): WorkspaceStatus | undefined {
  const wanted = folderKey(root);
  return items.find((item) => item.config?.project_id === projectId && folderKey(item.config.roots.workspace_root) === wanted);
}

export async function findLinkedWorkspaceId(platform: Platform, projectId: string, root: string): Promise<string | undefined> {
  const listed = await listWorkspaces(platform);
  return listed.ok ? findLinkedWorkspace(listed.value, projectId, root)?.workspace_id : undefined;
}

export function getWorkspaceConfig(platform: Platform, workspaceId: string): Promise<WorkspaceOutcome<LocalWorkspaceConfig>> {
  return callWorkspace(platform, "workspace.get_config", { workspace_id: workspaceId });
}
