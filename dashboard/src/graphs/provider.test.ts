import { describe, expect, it, vi } from "vitest";
import { createDesktopPlatform } from "../platform/desktop";
import { webPlatform } from "../platform/web";
import { createLocalGraphSource } from "./provider";
import { fixturePages } from "./fixtures";
import knowledgeStatus from "../../../contracts/local/fixtures/valid/knowledge.status.ready.json";
import codeStatus from "../../../contracts/local/fixtures/valid/code_graph.status.ready.json";

const workspaceId = "11111111-1111-4111-8111-111111111111";
function desktop(payloads: Record<string, unknown>) {
  const invoke = vi.fn(async (_name: string, args?: Record<string, unknown>) => {
    const request = args?.request as Record<string, unknown>;
    return { kind: "response", protocol: "studio.local/v1", message_id: "response-1", request_id: request.message_id, correlation_id: request.correlation_id, sent_at: "2026-09-21T12:00:00Z", command: request.command, payload: payloads[String(request.command)] };
  });
  return { platform: createDesktopPlatform(invoke), invoke };
}

describe("graph bridge adapter", () => {
  it("web reports unavailability without calling a local bridge", async () => {
    const request = vi.fn(webPlatform.request);
    const source = createLocalGraphSource({ ...webPlatform, request }, "code", workspaceId);
    expect((await source.status()).state).toBe("unavailable");
    expect(request).not.toHaveBeenCalled();
  });
  it.each(["code", "knowledge"] as const)("uses frozen %s status/page/expand commands and schemas", async (kind) => {
    const prefix = kind === "code" ? "code_graph" : "knowledge";
    const page = fixturePages(kind)[0]!;
    const { platform, invoke } = desktop({ [`${prefix}.status`]: kind === "code" ? codeStatus.data : knowledgeStatus.data, [`${prefix}.graph_page`]: page, [`${prefix}.graph_expand`]: page });
    const source = createLocalGraphSource(platform, kind, workspaceId);
    expect((await source.status()).state).toBe("ready");
    expect(await source.page()).toEqual(page);
    await source.expand({ source_id: page.source.source_id, node_id: page.nodes![0]!.node_id });
    expect(invoke.mock.calls).toHaveLength(3);
    await expect(source.expand({ source_id: "alien", node_id: "x" })).rejects.toThrow();
    expect(invoke.mock.calls).toHaveLength(3);
  });
  it("refuses wrong workspace responses and malformed graph data", async () => {
    const { platform } = desktop({ "code_graph.graph_page": fixturePages("code")[0] });
    await expect(createLocalGraphSource(platform, "code", "22222222-2222-4222-8222-222222222222").page()).rejects.toThrow(/autre/);
    const invalid = desktop({ "code_graph.graph_page": { nodes: [] } });
    await expect(createLocalGraphSource(invalid.platform, "code", workspaceId).page()).rejects.toThrow();
  });
  it("search returns reference-only results without manufacturing graph nodes", async () => {
    const { platform } = desktop({ "knowledge.search": { hits: [{ document: { title: "<script>alert(1)</script>", uri: "studio-local://knowledge/11111111-1111-4111-8111-111111111111/test.md", content_hash: "a".repeat(64), modified_at: "2026-09-21T00:00:00Z" }, score: 1 }], index_state: "stale", complete: false, next_cursor: "next" } });
    const result = await createLocalGraphSource(platform, "knowledge", workspaceId).search("test");
    expect(result.partial).toBe(true); expect(result.nextCursor).toBe("next");
    expect(result.hits[0]?.ref).toBeUndefined();
    expect(result.hits[0]?.label).toContain("<script>");
  });
});
