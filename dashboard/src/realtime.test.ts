import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseEventEnvelope, startRealtimeConnection } from "./realtime";
import * as sseModule from "./sse";
import type { LiveStreamCallbacks, LiveStreamHandle } from "./sse";

describe("parseEventEnvelope", () => {
  it("parses a well-formed EventEnvelope payload", () => {
    const message = { seq: 1, data: '{"event_type":"task.created","project_id":"p1"}' };
    const envelope = parseEventEnvelope(message);
    expect(envelope?.event_type).toBe("task.created");
  });

  it("returns null on malformed JSON without throwing", () => {
    expect(parseEventEnvelope({ seq: null, data: "{not json" })).toBeNull();
  });

  it("returns null when event_type is missing", () => {
    expect(parseEventEnvelope({ seq: null, data: '{"project_id":"p1"}' })).toBeNull();
  });

  it("returns null for a non-object JSON value", () => {
    expect(parseEventEnvelope({ seq: null, data: "42" })).toBeNull();
  });
});

describe("startRealtimeConnection", () => {
  let capturedCallbacks: LiveStreamCallbacks | null = null;
  let closed = false;

  beforeEach(() => {
    vi.useFakeTimers();
    closed = false;
    capturedCallbacks = null;
    vi.spyOn(sseModule, "openLiveProjectStream").mockImplementation((_baseUrl, _token, _projectId, callbacks) => {
      capturedCallbacks = callbacks;
      const handle: LiveStreamHandle = {
        close: () => {
          closed = true;
        },
        get closed() {
          return closed;
        },
      };
      return handle;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  function emit(data: string, seq: number | null = null): void {
    capturedCallbacks?.onMessage({ seq, data });
  }

  it("debounces a burst of messages into a single refetch", async () => {
    const onRefetch = vi.fn();
    startRealtimeConnection("", "tok", "proj-1", { onRefetch });

    emit('{"event_type":"task.created"}');
    emit('{"event_type":"task.updated"}');
    emit('{"event_type":"task.updated"}');
    await vi.advanceTimersByTimeAsync(299);
    expect(onRefetch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(50);
    expect(onRefetch).toHaveBeenCalledTimes(1);
  });

  it("drops malformed data frames without calling onRefetch or throwing", async () => {
    const onRefetch = vi.fn();
    startRealtimeConnection("", "tok", "proj-1", { onRefetch });

    expect(() => emit("{not json")).not.toThrow();
    await vi.advanceTimersByTimeAsync(500);
    expect(onRefetch).not.toHaveBeenCalled();
  });

  it("calls onConflict for a resource.conflict event, undebounced", () => {
    const onRefetch = vi.fn();
    const onConflict = vi.fn();
    startRealtimeConnection("", "tok", "proj-1", { onRefetch, onConflict });

    emit('{"event_type":"resource.conflict","payload":{"resource_path":"a.tscn"}}');
    expect(onConflict).toHaveBeenCalledTimes(1);
    expect(onConflict.mock.calls[0]?.[0]).toMatchObject({ event_type: "resource.conflict" });
  });

  it("does not call onConflict for a non-conflict event", () => {
    const onConflict = vi.fn();
    startRealtimeConnection("", "tok", "proj-1", { onRefetch: vi.fn(), onConflict });

    emit('{"event_type":"task.created"}');
    expect(onConflict).not.toHaveBeenCalled();
  });

  it("close() cancels a pending debounced refetch and closes the stream", async () => {
    const onRefetch = vi.fn();
    const connection = startRealtimeConnection("", "tok", "proj-1", { onRefetch });

    emit('{"event_type":"task.created"}');
    connection.close();
    await vi.advanceTimersByTimeAsync(1000);

    expect(onRefetch).not.toHaveBeenCalled();
    expect(closed).toBe(true);
  });
});
