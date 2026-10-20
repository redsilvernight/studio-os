import type { Platform } from "../platform";
import type { LocalWorkspaceConfig, WorkspaceListResult, WorkspaceStatus } from "../platform/generated/local-contracts.generated";
import { callWorkspace, type WorkspaceOutcome } from "../onboarding/workspaceApi";

export { confirmRoots, saveWorkspaceConfig, validateWorkspace, workspaceErrorMessage } from "../onboarding/workspaceApi";
export type { WorkspaceOutcome } from "../onboarding/workspaceApi";

export async function listWorkspaces(platform: Platform): Promise<WorkspaceOutcome<WorkspaceStatus[]>> {
  const result = await callWorkspace<WorkspaceListResult>(platform, "workspace.list", {});
  return result.ok ? { ok: true, value: result.value.items ?? [] } : result;
}

export function getWorkspaceConfig(platform: Platform, workspaceId: string): Promise<WorkspaceOutcome<LocalWorkspaceConfig>> {
  return callWorkspace(platform, "workspace.get_config", { workspace_id: workspaceId });
}
