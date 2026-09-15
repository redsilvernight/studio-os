/**
 * SSE client foundation (DASH-0, full loop in DASH-3).
 *
 * Real endpoint: GET /api/v1/events/stream?project=<uuid>
 * Constraints (routers/events.py):
 * - `project` is required; there is no global stream.
 * - Bearer header is required → the native `EventSource` cannot be used
 *   (it sends no Authorization header). This client uses fetch() +
 *   ReadableStream instead.
 * - Frames look like:  `id: <seq>\ndata: <EventEnvelope JSON>\n\n`
 * - Resume: `Last-Event-ID` header (priority) or `?since_seq=`.
 * - Without a cursor the server only sends live events.
 *
 * Architecture (preserved for DASH-3):
 *   SSE → notification → refetch REST of the affected resource → store → UI.
 * SSE payloads are NEVER the source of business truth; `lastSeq` in memory
 * is only a resume cursor. Reconnect/backoff/watchdog hooks are exposed here
 * so DASH-3 wires the loop without rewriting the transport.
 */

export interface SseMessage {
  /** Transport cursor (`id:` line). Null when the server sent no id. */
  seq: number | null;
  /** Raw `data:` payload (EventEnvelope JSON). May span several lines. */
  data: string;
}

export interface SseParserState {
  lastSeq: number | null;
}

/**
 * Incremental SSE frame parser. Feed it decoded text chunks; it returns
 * complete messages. Handles split frames, multi-line data:, comments
 * (`: ...`) and empty keep-alive chunks.
 */
export class SseParser {
  private buffer = "";
  lastSeq: number | null = null;

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const out: SseMessage[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const parsed = SseParser.parseFrame(frame);
      if (parsed !== null) {
        if (parsed.seq !== null) this.lastSeq = parsed.seq;
        out.push(parsed);
      }
      boundary = this.buffer.indexOf("\n\n");
    }
    return out;
  }

  private static parseFrame(frame: string): SseMessage | null {
    let seq: number | null = null;
    const dataLines: string[] = [];
    for (const rawLine of frame.split("\n")) {
      const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
      if (line === "" || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      if (colon === -1) continue;
      const field = line.slice(0, colon);
      const value = line.slice(colon + 1).startsWith(" ") ? line.slice(colon + 2) : line.slice(colon + 1);
      if (field === "id") {
        const parsed = Number.parseInt(value, 10);
        if (!Number.isNaN(parsed)) seq = parsed;
      } else if (field === "data") {
        dataLines.push(value);
      }
    }
    if (dataLines.length === 0) return null;
    return { seq, data: dataLines.join("\n") };
  }
}

export interface StreamCallbacks {
  onMessage: (message: SseMessage) => void;
  onError: (error: Error) => void;
  onClose: () => void;
}

export interface StreamHandle {
  /** Latest transport cursor seen (resume with it). */
  readonly lastSeq: number | null;
  close: () => void;
  readonly closed: boolean;
}

export interface StreamOptions {
  /** Resume cursor. Sent as Last-Event-ID header (server priority). */
  sinceSeq?: number | null;
  /** Query override; header stays authoritative server-side. */
  useQueryCursor?: boolean;
  signal?: AbortSignal;
}

/** Build the stream URL. `project` is required by the backend. */
export function streamUrl(baseUrl: string, projectId: string, sinceSeq?: number | null): string {
  const normalized = baseUrl === "" ? "" : baseUrl.replace(/\/+$/, "");
  const params = new URLSearchParams({ project: projectId });
  if (sinceSeq !== null && sinceSeq !== undefined) params.set("since_seq", String(sinceSeq));
  return `${normalized}/api/v1/events/stream?${params.toString()}`;
}

/**
 * Open a one-shot stream (DASH-0 foundation). The caller owns retry/backoff:
 * on network close without error, `onClose` fires and the caller may call
 * `connectEventStream` again with `handle.lastSeq`. DASH-3 adds the loop,
 * backoff, inactivity watchdog and refetch dispatch on top of this.
 */
export async function connectEventStream(
  baseUrl: string,
  token: string,
  projectId: string,
  callbacks: StreamCallbacks,
  options: StreamOptions = {},
): Promise<StreamHandle> {
  const parser = new SseParser();
  if (options.sinceSeq !== null && options.sinceSeq !== undefined) {
    parser.lastSeq = options.sinceSeq;
  }
  const controller = new AbortController();
  const onAbort = (): void => controller.abort();
  options.signal?.addEventListener("abort", onAbort, { once: true });

  let closed = false;
  const handle: StreamHandle = {
    get lastSeq() {
      return parser.lastSeq;
    },
    get closed() {
      return closed;
    },
    close() {
      closed = true;
      controller.abort();
    },
  };

  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    Authorization: `Bearer ${token}`,
  };
  if (parser.lastSeq !== null) headers["Last-Event-ID"] = String(parser.lastSeq);

  let url = streamUrl(baseUrl, projectId);
  if (options.useQueryCursor === true && parser.lastSeq !== null) {
    url = streamUrl(baseUrl, projectId, parser.lastSeq);
  }

  try {
    const response = await fetch(url, { headers, signal: controller.signal });
    if (!response.ok || response.body === null) {
      throw new Error(`stream HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const message of parser.feed(decoder.decode(value, { stream: true }))) {
        callbacks.onMessage(message);
      }
    }
    for (const message of parser.feed(decoder.decode())) {
      callbacks.onMessage(message);
    }
  } catch (error) {
    if (!closed) {
      callbacks.onError(error instanceof Error ? error : new Error(String(error)));
    }
  } finally {
    closed = true;
    options.signal?.removeEventListener("abort", onAbort);
    callbacks.onClose();
  }
  return handle;
}
