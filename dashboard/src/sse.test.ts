import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SseParser, streamUrl, openLiveProjectStream } from "./sse";

const FRAME = 'id: 42\ndata: {"event_type":"task.created"}\n\n';

describe("SseParser", () => {
  it("parses a complete frame with id and data", () => {
    const parser = new SseParser();
    const messages = parser.feed(FRAME);
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ seq: 42, data: '{"event_type":"task.created"}' });
    expect(parser.lastSeq).toBe(42);
  });

  it("reassembles frames split across chunks", () => {
    const parser = new SseParser();
    expect(parser.feed("id: 7\ndata: {\"a\"")).toHaveLength(0);
    const messages = parser.feed(": 1}\n\n");
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ seq: 7 });
    expect(parser.lastSeq).toBe(7);
  });

  it("joins multi-line data with newlines", () => {
    const parser = new SseParser();
    const messages = parser.feed("id: 3\ndata: line1\ndata: line2\n\n");
    expect(messages[0]?.data).toBe("line1\nline2");
  });

  it("ignores comments and keep-alive chunks", () => {
    const parser = new SseParser();
    expect(parser.feed(": ping\n\n")).toHaveLength(0);
    expect(parser.feed("\n")).toHaveLength(0);
    expect(parser.lastSeq).toBeNull();
  });

  it("keeps the previous seq when a frame has no id", () => {
    const parser = new SseParser();
    parser.feed(FRAME);
    const messages = parser.feed('data: {"x":1}\n\n');
    expect(messages[0]).toMatchObject({ seq: null });
    expect(parser.lastSeq).toBe(42);
  });

  it("ignores non-numeric ids without crashing", () => {
    const parser = new SseParser();
    const messages = parser.feed("id: abc\ndata: {}\n\n");
    expect(messages[0]).toMatchObject({ seq: null });
  });

  it("parses several frames in one chunk", () => {
    const parser = new SseParser();
    const messages = parser.feed("id: 1\ndata: a\n\nid: 2\ndata: b\n\n");
    expect(messages.map((m) => m.seq)).toEqual([1, 2]);
    expect(parser.lastSeq).toBe(2);
  });
});

describe("streamUrl", () => {
  it("requires project and appends since_seq only when given", () => {
    expect(streamUrl("", "11111111-2222-4333-8444-555555555555")).toBe(
      "/api/v1/events/stream?project=11111111-2222-4333-8444-555555555555",
    );
    expect(streamUrl("http://h:8000/", "p", 9)).toBe("http://h:8000/api/v1/events/stream?project=p&since_seq=9");
  });
});

interface ControlledStream {
  stream: ReadableStream<Uint8Array>;
  push: (chunk: string) => void;
  close: () => void;
  error: (message: string) => void;
}

function controlledStream(): ControlledStream {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  const encoder = new TextEncoder();
  return {
    stream,
    push: (chunk) => controller.enqueue(encoder.encode(chunk)),
    close: () => controller.close(),
    error: (message) => controller.error(new Error(message)),
  };
}

interface RecordedCall {
  headers: Record<string, string>;
  signal: AbortSignal | undefined;
}

describe("openLiveProjectStream", () => {
  let calls: RecordedCall[];
  let controlled: ControlledStream[];

  beforeEach(() => {
    vi.useFakeTimers();
    calls = [];
    controlled = [];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function installFetch(count: number): void {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        const cs = controlledStream();
        controlled.push(cs);
        calls.push({ headers: { ...(init.headers as Record<string, string>) }, signal: init.signal ?? undefined });
        // A real aborted fetch's body reader rejects/errors — the mock stream
        // must do the same so an abort (watchdog or handle.close()) actually
        // unblocks the pending `reader.read()` in connectEventStream.
        init.signal?.addEventListener("abort", () => cs.error("aborted"));
        return Promise.resolve(new Response(cs.stream, { status: 200 }));
      }),
    );
    void count;
  }

  it("resumes with Last-Event-ID after a clean close, then reconnects", async () => {
    installFetch(2);
    const messages: number[] = [];
    const handle = openLiveProjectStream("", "tok", "proj-1", {
      onMessage: (m) => {
        if (m.seq !== null) messages.push(m.seq);
      },
    });

    controlled[0]?.push('id: 5\ndata: {"event_type":"task.created"}\n\n');
    controlled[0]?.close();
    await vi.waitFor(() => expect(messages).toEqual([5]));

    // A clean close (no error) resets backoff to its initial value.
    await vi.advanceTimersByTimeAsync(1500);
    await vi.waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]?.headers["Last-Event-ID"]).toBe("5");

    handle.close();
  });

  it("grows backoff across consecutive errors and resets after a success", async () => {
    installFetch(4);
    const handle = openLiveProjectStream(
      "",
      "tok",
      "proj-1",
      { onMessage: () => {} },
      { backoffInitialMs: 1000, backoffMaxMs: 30000 },
    );

    await vi.waitFor(() => expect(calls).toHaveLength(1));
    controlled[0]?.error("network down");
    await vi.advanceTimersByTimeAsync(999);
    expect(calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(2000);
    await vi.waitFor(() => expect(calls).toHaveLength(2));

    // Second consecutive error: backoff must have grown (attempt 1 -> 2,
    // ~4000ms vs. ~2000ms) — 1999ms must still be within the first delay's
    // jittered range floor for that growth to be observable.
    controlled[1]?.error("network down again");
    await vi.advanceTimersByTimeAsync(1999);
    expect(calls).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(3001);
    await vi.waitFor(() => expect(calls).toHaveLength(3));

    // A message (implicit success) resets backoff back to ~backoffInitialMs
    // (~1000ms, well below the ~4000ms it would be without a reset).
    controlled[2]?.push('id: 1\ndata: {"event_type":"task.created"}\n\n');
    controlled[2]?.close();
    await vi.advanceTimersByTimeAsync(700);
    expect(calls).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(2000);
    await vi.waitFor(() => expect(calls).toHaveLength(4));

    handle.close();
  });

  it("watchdog aborts a silent connection and triggers a reconnect", async () => {
    installFetch(2);
    const handle = openLiveProjectStream(
      "",
      "tok",
      "proj-1",
      { onMessage: () => {} },
      { watchdogMs: 5000, backoffInitialMs: 1000 },
    );

    await vi.waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.signal?.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(5001);
    expect(calls[0]?.signal?.aborted).toBe(true);

    // Watchdog-triggered abort counts as an error: backoff grows to
    // ~2000ms (range [1600, 2400]) before the reconnect attempt.
    await vi.advanceTimersByTimeAsync(2500);
    await vi.waitFor(() => expect(calls).toHaveLength(2));

    handle.close();
  });

  it.each([403, 401])("stops for good on HTTP %i instead of retrying forever", async (status) => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response("", { status })));
    vi.stubGlobal("fetch", fetchMock);
    const denied: number[] = [];
    const handle = openLiveProjectStream("", "tok", "proj-1", {
      onMessage: () => {},
      onDenied: (s) => denied.push(s),
    });

    await vi.waitFor(() => expect(denied).toEqual([status]));
    await vi.advanceTimersByTimeAsync(120000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(handle.closed).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps retrying a transient HTTP failure (503)", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response("", { status: 503 })));
    vi.stubGlobal("fetch", fetchMock);
    const onDenied = vi.fn();
    const handle = openLiveProjectStream(
      "",
      "tok",
      "proj-1",
      { onMessage: () => {}, onDenied },
      { backoffInitialMs: 1000 },
    );

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(2500);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(onDenied).not.toHaveBeenCalled();
    handle.close();
  });

  it("close() during a pending backoff prevents any further reconnect and leaves no pending timer", async () => {
    installFetch(1);
    const handle = openLiveProjectStream("", "tok", "proj-1", { onMessage: () => {} });

    await vi.waitFor(() => expect(calls).toHaveLength(1));
    controlled[0]?.error("network down");
    await vi.advanceTimersByTimeAsync(10);

    handle.close();
    await vi.advanceTimersByTimeAsync(60000);

    expect(calls).toHaveLength(1);
    // Regression: close() must resolve the pending backoff promise itself
    // (clearTimeout alone doesn't) — otherwise `loop()` and everything it
    // closes over (callbacks, token, lastSeq) leaks, suspended forever.
    // A stray pending timer here would mean that promise is still waiting.
    expect(vi.getTimerCount()).toBe(0);
  });
});
