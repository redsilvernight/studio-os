/**
 * DASH-3 — refetch dispatch glue on top of `sse.ts`'s `openLiveProjectStream`.
 *
 * One live connection per tab, owned by `main.ts`, keyed on
 * `uiState.selectedProjectId`. Every parsed SSE message is JSON-parsed into
 * an `EventEnvelope` and, debounced, triggers the SAME `render()` the shell
 * already uses for hash/token changes — SSE is never a second source of
 * truth (store.ts), it only tells the app "go refetch". A `resource.conflict`
 * additionally surfaces a transient banner from the event's own payload
 * (no extra REST call), per dashboard/README.md's DASH-2 promise.
 */
import type { SseMessage } from "./sse";
import { openLiveProjectStream, type LiveStreamHandle } from "./sse";
import type { components } from "./openapi-schema";

type EventEnvelope = components["schemas"]["EventEnvelope"];

export interface RealtimeCallbacks {
  /** Called (debounced) after one or more live events land. */
  onRefetch: () => void;
  /** Called for each `resource.conflict` event, undebounced. */
  onConflict?: (event: EventEnvelope) => void;
  /** The stream was refused for good (401/403); live updates stopped. */
  onDenied?: (status: number) => void;
}

export interface RealtimeOptions {
  debounceMs?: number;
}

export function parseEventEnvelope(message: SseMessage): EventEnvelope | null {
  try {
    const parsed: unknown = JSON.parse(message.data);
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      "event_type" in parsed &&
      typeof (parsed as { event_type: unknown }).event_type === "string"
    ) {
      return parsed as EventEnvelope;
    }
    return null;
  } catch {
    return null;
  }
}

export interface RealtimeConnection {
  close: () => void;
}

export function startRealtimeConnection(
  baseUrl: string,
  token: string,
  projectId: string,
  callbacks: RealtimeCallbacks,
  options: RealtimeOptions = {},
): RealtimeConnection {
  const debounceMs = options.debounceMs ?? 300;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  const scheduleRefetch = (): void => {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      callbacks.onRefetch();
    }, debounceMs);
  };

  const handle: LiveStreamHandle = openLiveProjectStream(baseUrl, token, projectId, {
    onMessage: (message) => {
      const event = parseEventEnvelope(message);
      if (event === null) return;
      if (event.event_type === "resource.conflict") callbacks.onConflict?.(event);
      scheduleRefetch();
    },
    onDenied: (status) => {
      callbacks.onDenied?.(status);
    },
  });

  return {
    close() {
      if (debounceTimer !== null) {
        clearTimeout(debounceTimer);
        debounceTimer = null;
      }
      handle.close();
    },
  };
}
