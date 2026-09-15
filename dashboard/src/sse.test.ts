import { describe, expect, it } from "vitest";
import { SseParser, streamUrl } from "./sse";

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
