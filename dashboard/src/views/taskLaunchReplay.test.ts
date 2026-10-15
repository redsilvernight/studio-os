import { describe, expect, it } from "vitest";
import type { TaskLaunchReplayPreview } from "../taskLaunchesApi";
import { replayPreviewHtml, replayVerdictTone } from "./taskLaunchPanel";

const PREVIEW: TaskLaunchReplayPreview = {
  source_launch_id: "11111111-1111-1111-1111-111111111111",
  snapshot_id: "22222222-2222-2222-2222-222222222222",
  snapshot_content_hash: `sha256:${"a".repeat(64)}`,
  verdict: "limited",
  differences: [
    { subject_kind: "harness", stable_key: "harness", recorded: "claude-code", current: "claude-code", change: "unchanged" },
    { subject_kind: "resource", role: "agent", stable_key: "builder", recorded: "v3", current: null, change: "unavailable" },
  ],
  limitations: [
    { code: "library_version_unavailable", severity: "limitation", subject: "builder" },
    { code: "source_worktree_dirty", severity: "limitation" },
  ],
  preview_digest: `sha256:${"b".repeat(64)}`,
  generated_at: "2026-10-14T00:00:00Z",
};

describe("replayPreviewHtml", () => {
  it("renders nothing before the preview is read", () => {
    expect(replayPreviewHtml(undefined)).toBe("");
  });

  it("names an unavailable preview", () => {
    expect(replayPreviewHtml(null)).toContain("indisponible");
  });

  it("lists limitations and only real substitutions", () => {
    const html = replayPreviewHtml(PREVIEW);
    expect(html).toContain("rejouable avec limitations");
    expect(html).toContain('data-testid="replay-limitation-source_worktree_dirty"');
    expect(html).toContain("agent builder — indisponible (v3 → —)");
    expect(html).not.toContain("harness — inchangé");
  });

  it("marks refusals and maps verdict tones", () => {
    const refused: TaskLaunchReplayPreview = {
      ...PREVIEW,
      verdict: "refused",
      differences: [],
      limitations: [{ code: "snapshot_missing", severity: "refusal" }],
    };
    const html = replayPreviewHtml(refused);
    expect(html).toContain("Refus : aucun snapshot");
    expect(html).toContain("Aucune substitution");
    expect(replayVerdictTone("ready")).toBe("success");
    expect(replayVerdictTone("limited")).toBe("warning");
    expect(replayVerdictTone("refused")).toBe("danger");
  });
});
