/** Minimal observable state (DASH-0). Only cross-section UI state lives here. */
type Listener = () => void;

const listeners = new Set<Listener>();

export const uiState: {
  selectedProjectId: string | null;
} = {
  selectedProjectId: null,
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
    for (const listener of listeners) listener();
  }
}
