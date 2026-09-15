/** Minimal observable UI state (vanilla). Server data is never cached here
 *  beyond selection/pagination — views refetch explicitly after mutations. */
type Listener = () => void;

const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

export const uiState: {
  selectedProjectId: string | null;
  selectedTaskId: string | null;
} = {
  selectedProjectId: null,
  selectedTaskId: null,
};

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function selectProject(projectId: string | null): void {
  if (uiState.selectedProjectId !== projectId) {
    uiState.selectedProjectId = projectId;
    uiState.selectedTaskId = null;
    notify();
  }
}

export function selectTask(taskId: string | null): void {
  if (uiState.selectedTaskId !== taskId) {
    uiState.selectedTaskId = taskId;
    notify();
  }
}
