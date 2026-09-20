export type RoadmapStatus = "draft" | "proposed" | "active" | "completed" | "archived";

export type RoadmapMetadataValue = string | number | boolean | null;
export type RoadmapMetadata = Record<string, RoadmapMetadataValue>;

export interface RoadmapProgress {
  done: number;
  total: number;
  skipped: number;
  ratio: number;
}

export type RoadmapStepState =
  | "not_started"
  | "in_progress"
  | "blocked"
  | "done"
  | "skipped";

export type RoadmapStepStateOverride = "done" | "skipped";

export interface RoadmapProvenance {
  origin: "manual" | "ai_proposal" | "import";
  actor_type: "user" | "agent";
  actor_id: string;
  agent_id: string | null;
  machine_id: string | null;
  at: string;
}

export interface RoadmapDocumentTask {
  hydration_key: string;
  title: string;
  description: string | null;
}

export interface RoadmapDocumentStep {
  key: string;
  title: string;
  objective: string | null;
  context: string | null;
  instructions: string | null;
  acceptance_criteria: string[];
  notes: string | null;
  metadata: RoadmapMetadata;
  depends_on: string[];
  tasks: RoadmapDocumentTask[];
}

export interface RoadmapDocumentPhase {
  key: string;
  title: string;
  objective: string | null;
  steps: RoadmapDocumentStep[];
}

export interface RoadmapDocument {
  format: "studio.roadmap/v1";
  title: string;
  objective: string | null;
  context: string | null;
  metadata: RoadmapMetadata;
  phases: RoadmapDocumentPhase[];
  exported_at: string | null;
  revision_no: number | null;
}

export interface RoadmapLinkedTask {
  task_id: string;
  hydration_key: string;
  origin?: string | null;
}

export interface RoadmapTaskProgress {
  completed: number;
  total: number;
}

export interface RoadmapStep extends RoadmapDocumentStep {
  id?: string;
  roadmap_id?: string;
  phase_id?: string;
  position?: number;
  created_at?: string;
  updated_at?: string | null;
  version?: number;
  criteria_checked?: number[];
  linked_tasks?: RoadmapLinkedTask[];
  state_override?: RoadmapStepStateOverride | null;
  state_override_reason?: string | null;
  state?: RoadmapStepState;
  available?: boolean;
  waiting_on?: string[];
  task_progress?: RoadmapTaskProgress;
  provenance?: RoadmapProvenance;
}

export interface RoadmapPhase extends Omit<RoadmapDocumentPhase, "steps"> {
  id?: string;
  roadmap_id?: string;
  position?: number;
  created_at?: string;
  updated_at?: string | null;
  version?: number;
  progress?: RoadmapProgress;
  steps?: RoadmapStep[];
}

export interface Roadmap {
  id: string;
  project_id: string;
  title: string;
  objective: string | null;
  status: RoadmapStatus;
  revision_no: number;
  approved_revision_no: number | null;
  context: string | null;
  metadata: RoadmapMetadata;
  created_at?: string;
  updated_at?: string | null;
  version?: number;
  progress?: RoadmapProgress;
  current_step_key?: string | null;
  provenance?: RoadmapProvenance;
  phases?: RoadmapPhase[];
}

export type RoadmapReviewDecision = "approve" | "request_changes" | "reject";

export type RoadmapRevisionKind = "proposal" | "snapshot" | "review";
export type RoadmapRevisionStatus =
  | "pending"
  | "approved"
  | "changes_requested"
  | "rejected"
  | "superseded";

export interface RoadmapRevision {
  id: string;
  roadmap_id: string;
  revision_no: number;
  kind: RoadmapRevisionKind;
  status: RoadmapRevisionStatus | null;
  base_revision_no: number | null;
  summary: string | null;
  provenance: RoadmapProvenance;
  reviewed_by_user_id?: string | null;
  reviewed_at?: string | null;
  review_comment?: string | null;
}

export type RoadmapDiffChange = "added" | "removed" | "changed";
export type RoadmapDiffScope = "roadmap" | "phase" | "step" | "dependency" | "task_plan";

export interface RoadmapDiffEntry {
  scope: RoadmapDiffScope;
  key: string | null;
  change: RoadmapDiffChange;
  fields: string[];
}

export interface RoadmapDiff {
  base_revision_no: number | null;
  proposal_revision_no: number;
  entries: RoadmapDiffEntry[];
}

/** A pending revision proposal against an active roadmap (Roadmaps P8). */
export interface RoadmapPendingProposal {
  roadmapId: string;
  roadmapVersion: number;
  revision: RoadmapRevision;
  diff: RoadmapDiff;
}

export interface RoadmapDataSource {
  /** Session-local fixture sources set this; the canonical API source leaves it unset. */
  demo?: boolean;
  load(projectId: string): Promise<Roadmap | null>;
  replaceDocument(projectId: string, document: RoadmapDocument): Promise<Roadmap>;
  reviewProposal(
    projectId: string,
    decision: RoadmapReviewDecision,
    comment?: string,
  ): Promise<Roadmap | null>;
  /** Pending revision proposal on the project's active roadmap, if any (P8). */
  loadPendingProposal(projectId: string): Promise<RoadmapPendingProposal | null>;
  reviewProposalRevision(
    projectId: string,
    revisionNo: number,
    decision: RoadmapReviewDecision,
    comment?: string,
  ): Promise<Roadmap | null>;
}
