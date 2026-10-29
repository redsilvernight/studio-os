import { describe, expect, it } from "vitest";
import type { AuthIdentity } from "../identityApi";
import type { ResolvedAgentDefinition } from "../resolutionApi";
import type { UsageAggregate, UsageSummary } from "../usageApi";
import type {
  ExecutionSnapshot,
  MachineEligibility,
  TaskLaunchWithProtocol,
} from "../taskLaunchesApi";
import {
  canCancelLaunch,
  cancelLaunchConfirmText,
  ineligibilityReasonLabel,
  isTerminalLaunch,
  launchConfirmText,
  launchPanelHtml,
  launchProtocolBadgeHtml,
  launchProtocolBadgeLabel,
  launchProtocolBadgeTone,
  launchProtocolStatus,
  launchProtocolTaskLabel,
  launchReasonCodeLabel,
  launchTtlOptions,
  validLaunchProfile,
  latestHtml,
  linkedSessionHtml,
  machineOptionLabel,
  previewLines,
  provenanceFacts,
  provenanceHtml,
  shortDigest,
  taskLaunchStatusLabel,
  taskLaunchStatusTone,
  type LaunchPanelState,
  type ProvenanceFact,
} from "./taskLaunchPanel";

const identity = (overrides: Partial<AuthIdentity> = {}): AuthIdentity => ({
  user_id: "u1",
  display_name: "Dev",
  email: "dev@example.test",
  role: "developer",
  machine_id: "m1",
  ...overrides,
});

const machine = (overrides: Partial<MachineEligibility> = {}): MachineEligibility =>
  ({
    machine_id: "m1",
    display_name: "flo-laptop",
    status: "online",
    eligible: true,
    free_slots: 2,
    harnesses: [{ harness_id: "claude-code", detected: true, configured: true }],
    ...overrides,
  }) as MachineEligibility;

const launch = (overrides: Partial<TaskLaunchWithProtocol> = {}): TaskLaunchWithProtocol =>
  ({
    id: "l1",
    project_id: "p1",
    task_id: "t1",
    machine_id: "m1",
    requested_by_user_id: "u1",
    harness_id: "claude-code",
    status: "requested",
    reason_code: "none",
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
    expires_at: "2026-10-01T10:15:00Z",
    version: 1,
    ...overrides,
  }) as TaskLaunchWithProtocol;

const state = (overrides: Partial<LaunchPanelState> = {}): LaunchPanelState => ({
  data: { machines: [machine()], agents: [{ stable_key: "review-helper" }], latest: null },
  authed: true,
  canCancel: false,
  selectedMachineId: "",
  selectedHarnessId: "",
  agentStableKey: "",
  preview: null,
  previewLoading: false,
  previewError: "",
  latestLoading: false,
  notice: "",
  error: "",
  ...overrides,
});

describe("reference launch profiles", () => {
  it("offers the existing profiles and keeps the legacy mode available", () => {
    const html = launchPanelHtml(state());
    expect(html).toContain('id="launch-profile"');
    expect(html).toContain('value="coding"');
    expect(html).toContain('value="architecture-read-only"');
    expect(html).toContain("sans profil");
    expect(validLaunchProfile(state())).toBe(true);
  });

  it.each(["coding", "architecture-read-only"])("requires an agent for %s", (profileKey) => {
    const html = launchPanelHtml(state({ selectedMachineId: "m1", selectedHarnessId: "claude-code", profileKey }));
    expect(html).toContain('data-action="launch-submit" disabled');
    expect(html).toContain("Choisissez un agent pour utiliser un profil");
    expect(validLaunchProfile(state({ profileKey, agentStableKey: "review-helper" }))).toBe(true);
  });

  it("refuses an unknown profile even with an agent", () => {
    expect(validLaunchProfile(state({ profileKey: "personal", agentStableKey: "review-helper" }))).toBe(false);
  });

  it("shows the requested permissions and confirms the selected profile", () => {
    const selected = state({ profileKey: "architecture-read-only", agentStableKey: "review-helper", selectedMachineId: "m1", selectedHarnessId: "claude-code" });
    const html = launchPanelHtml(selected);
    expect(html).toContain('value="architecture-read-only" selected');
    expect(html).toContain("Permissions demandées : lecture.");
    expect(html).not.toContain('data-action="launch-submit" disabled');
    expect(launchConfirmText(machine(), "claude-code", "review-helper", false, selected.profileKey)).toContain("Architecture en lecture seule");
  });
});

/** Empreinte de test : seule son identité compte, jamais sa valeur. */
const digest = (seed: string): string => `sha256:${seed.repeat(64).slice(0, 64)}`;

const snapshot = (overrides: Partial<ExecutionSnapshot> = {}): ExecutionSnapshot =>
  ({
    id: "s1",
    project_id: "p1",
    task_launch_id: "l1",
    content_hash: digest("a"),
    schema_version: 1,
    capture_status: "ok",
    capture_reason: null,
    created_at: "2026-10-01T09:59:00Z",
    retention_until: "2026-12-30T09:59:00Z",
    payload: {
      schema_version: 1,
      capture_status: "ok",
      capture_errors: [],
      resolution: {
        agent_stable_key: "review-helper",
        profile: { stable_key: "fast", contract_version: 3, digest: digest("1") },
        resources: [
          {
            role: "rule",
            resource_id: "r1",
            kind: "rule",
            stable_key: "python-conventions",
            scope: "studio",
            version: 2,
            version_origin: "active",
            content_digest: digest("2"),
          },
        ],
        runtime: {
          level: "project_default",
          matched_kind: "agent_definition",
          matched_stable_key: "opencode",
          harness_ref: "claude-code",
          model_ref: "claude-opus",
          capabilities_digest: digest("3"),
        },
      },
      applied: {
        harness_id: "claude-code",
        harness_version: "2.1.0",
        projections: [{ target: ".claude/settings.json", digest: digest("4") }],
        git_sha: "0f1e2d3",
        git_dirty: false,
        worktree_branch: "feat/provenance",
        profile: { stable_key: "fast", contract_version: 3, digest: digest("1") },
        access_mode: "read_only",
      },
    },
    ...overrides,
  }) as unknown as ExecutionSnapshot;

/** Snapshot présent mais presque vide : capture partielle, rien d'inventé. */
const emptySnapshot = (): ExecutionSnapshot =>
  ({
    id: "s2",
    task_launch_id: "l1",
    content_hash: digest("b"),
    schema_version: 1,
    capture_status: "partial",
    capture_reason: "git_sha_unavailable,resolution_unavailable",
    created_at: "2026-10-01T09:59:00Z",
    retention_until: "2026-12-30T09:59:00Z",
    payload: {
      schema_version: 1,
      capture_status: "partial",
      capture_errors: [
        { code: "git_sha_unavailable", field: "applied.git_sha", detail: "git absent du worktree" },
        { code: "resolution_unavailable", field: "resolution", detail: "aucun agent résolu" },
      ],
    },
  }) as unknown as ExecutionSnapshot;

const launchWithProvenance = (overrides: Partial<TaskLaunchWithProtocol> = {}): TaskLaunchWithProtocol =>
  launch({
    status: "succeeded",
    agent_stable_key: "review-helper",
    harness_id: "claude-code",
    finished_at: "2026-10-01T10:05:00Z",
    protocol: { status: "handed_off", session_id: "s1", task_status: "completed" },
    ...overrides,
  });

const launchUsage = (overrides: Partial<UsageAggregate> = {}): UsageSummary => {
  const unknownMetric = { status: "unknown" as const, known_sum: null, measured_entries: 0, estimated_entries: 0, unknown_entries: 2 };
  const partial = { measured_entries: 1, estimated_entries: 0, unknown_entries: 1 };
  return {
    project_id: "aaaaaaaa-1111-4222-8333-444444444444",
    task_id: null,
    task_launch_id: "cccccccc-1111-4222-8333-444444444444",
    group_by: "none",
    since: null,
    until: null,
    generated_at: "2026-10-13T12:00:00Z",
    total: {
      key: {},
      entries: 2,
      first_period_start: "2026-10-11T10:00:00Z",
      last_period_end: "2026-10-11T10:00:05Z",
      tokens_in: unknownMetric,
      tokens_out: unknownMetric,
      tokens_cached: unknownMetric,
      total_tokens: { status: "partial", known_sum: 330, ...partial },
      cost: { status: "partial", known_sum: "0.125", currency: "USD", by_currency: [], ...partial },
      duration: { status: "exact", known_sum: "17", measured_entries: 2, estimated_entries: 0, unknown_entries: 0 },
      sources: [{ collector: "studio-runner", entries: 2 }],
      ...overrides,
    },
    groups: [],
    truncated: false,
  };
};

const answerOf = (facts: ProvenanceFact[], id: string): string =>
  facts.find((fact) => fact.id === id)?.answer ?? "";

/** Bloc provenance du panneau : il est le dernier avant la fermeture de section. */
const provenancePart = (html: string): string => {
  const start = html.indexOf('<div data-testid="launch-provenance">');
  if (start === -1) return "";
  const end = html.indexOf("</section>", start);
  return html.slice(start, end === -1 ? undefined : end);
};

describe("labels", () => {
  it("traduit les statuts de lancement", () => {
    expect(taskLaunchStatusLabel("requested")).toBe("Demandé");
    expect(taskLaunchStatusLabel("running")).toBe("En cours");
    expect(taskLaunchStatusTone("failed")).toBe("danger");
  });

  it("succeeded décrit le processus, jamais un travail validé", () => {
    expect(taskLaunchStatusLabel("succeeded")).toBe("Processus terminé (code 0)");
    expect(taskLaunchStatusTone("succeeded")).toBe("neutral");
    expect(taskLaunchStatusLabel("succeeded")).not.toContain("succès");
  });

  it("traduit les raisons d'inéligibilité", () => {
    expect(ineligibilityReasonLabel("offline")).toBe("hors ligne");
    expect(ineligibilityReasonLabel("launches_not_accepted")).toContain("non acceptés");
  });

  it("compose le libellé d'un poste éligible et inéligible", () => {
    expect(machineOptionLabel(machine())).toContain("2 place(s) libre(s)");
    expect(machineOptionLabel(machine({ eligible: false, free_slots: 0, reasons: ["offline"] }))).toContain("hors ligne");
  });
});

describe("launchPanelHtml", () => {
  it("lecture seule : invite à se connecter, aucun formulaire", () => {
    const html = launchPanelHtml(state({ authed: false }));
    expect(html).toContain("Connectez-vous");
    expect(html).not.toContain("launch-machine");
    expect(html).toContain("Le lancement reste une demande");
  });

  it("données indisponibles : avertissement, jamais d'état inventé", () => {
    const html = launchPanelHtml(state({ data: null }));
    expect(html).toContain("Machines éligibles indisponibles");
    expect(html).toContain("Le lancement reste une demande");
  });

  it("poste inéligible : option désactivée avec sa raison ; éligible sélectionnable", () => {
    const data = {
      machines: [
        machine({ machine_id: "m-ok", display_name: "ok" }),
        machine({ machine_id: "m-off", display_name: "off", eligible: false, free_slots: 0, reasons: ["offline"] }),
      ],
      agents: [],
      latest: null,
    };
    const html = launchPanelHtml(state({ data }));
    expect(html).toMatch(/<option value="m-off" disabled>/);
    expect(html).toMatch(/<option value="m-ok">/);
    expect(html).toContain("hors ligne");
    expect(html).toContain("Le lancement reste une demande");
  });

  it("harnais non détecté désactivé ; bouton lancer désactivé sans harnais", () => {
    const data = {
      machines: [
        machine({
          harnesses: [
            { harness_id: "claude-code", detected: true, configured: true },
            { harness_id: "ghost", detected: false, configured: false },
          ],
        }),
      ],
      agents: [],
      latest: null,
    };
    const html = launchPanelHtml(state({ data, selectedMachineId: "m1" }));
    expect(html).toMatch(/<option value="ghost" disabled>/);
    expect(html).toContain('data-action="launch-submit" disabled');
    expect(html).toContain("Le lancement reste une demande");
  });

  it("bouton aperçu désactivé sans agent ; activé avec agent", () => {
    expect(launchPanelHtml(state())).toContain('data-action="launch-preview" disabled');
    expect(launchPanelHtml(state({ agentStableKey: "review-helper" }))).not.toContain(
      'data-action="launch-preview" disabled',
    );
  });

  it("aperçu affiché avant lancement (règles, skills, profil, runtime)", () => {
    const preview = {
      agent: { stable_key: "review-helper", version: 2, deprecated: false },
      rules: [{ stable_key: "python-conventions" }],
      skills: [{ stable_key: "studio-session" }],
      model_profile: { stable_key: "fast", version: 1 },
      runtime: { level: "project_default", target: { harness_ref: "opencode" } },
      requirements: { coding: true },
      composed_agents: [],
      workflows: [],
    } as unknown as ResolvedAgentDefinition;
    const html = launchPanelHtml(state({ preview }));
    expect(html).toContain("launch-preview-list");
    expect(html).toContain("python-conventions");
    expect(html).toContain("studio-session");
    expect(html).toContain("opencode");
  });

  it("dernier lancement : statut rapporté et identifiants", () => {
    const html = launchPanelHtml(state({ data: { machines: [], agents: [], latest: launch({ status: "running" }) } }));
    expect(html).toContain("En cours");
    expect(html).toContain("claude-code");
  });

  it("CSP : aucun handler inline ni style", () => {
    const html = launchPanelHtml(state());
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });
});

describe("previewLines / launchConfirmText", () => {
  it("résume la résolution sans jamais l'inventer", () => {
    const resolved = {
      agent: { stable_key: "x", version: 3, deprecated: false },
      rules: [],
      skills: [],
      model_profile: null,
      runtime: null,
      requirements: { coding: false },
    } as unknown as ResolvedAgentDefinition;
    const lines = previewLines(resolved);
    expect(lines[0]).toContain("x v3");
    expect(lines.join(" ")).not.toContain("Règles");
  });

  it("confirmation nomme poste, harnais et agent", () => {
    const text = launchConfirmText(machine(), "claude-code", "review-helper");
    expect(text).toContain("flo-laptop");
    expect(text).toContain("claude-code");
    expect(text).toContain("review-helper");
    expect(text).not.toContain("<");
  });
});

describe("suivi et annulation (AIB R4)", () => {
  it("identifie les statuts terminaux", () => {
    expect(isTerminalLaunch("requested")).toBe(false);
    expect(isTerminalLaunch("running")).toBe(false);
    expect(isTerminalLaunch("succeeded")).toBe(true);
    expect(isTerminalLaunch("cancelled")).toBe(true);
  });

  it("seul le demandeur ou un administrateur annule, et seulement un non terminal", () => {
    const running = launch({ status: "running", requested_by_user_id: "u1" });
    expect(canCancelLaunch(running, identity({ user_id: "u1" }))).toBe(true);
    expect(canCancelLaunch(running, identity({ user_id: "u2" }))).toBe(false);
    expect(canCancelLaunch(running, identity({ user_id: "u2", role: "admin" }))).toBe(true);
    expect(canCancelLaunch(running, null)).toBe(false);
    expect(canCancelLaunch(launch({ status: "succeeded" }), identity({ role: "admin" }))).toBe(false);
  });

  it("traduit les codes de motif en clair", () => {
    expect(launchReasonCodeLabel("cancelled_by_requester")).toContain("annulé");
    expect(launchReasonCodeLabel("expired_timeout")).toContain("expiré");
    expect(launchReasonCodeLabel("unknown_code")).toBe("unknown_code");
  });

  it("bouton annuler présent seulement si canCancel", () => {
    const data = { machines: [], agents: [], latest: launch({ status: "running" }) };
    expect(launchPanelHtml(state({ data, canCancel: true }))).toContain('data-action="launch-cancel"');
    expect(launchPanelHtml(state({ data, canCancel: false }))).not.toContain('data-action="launch-cancel"');
  });

  it("bouton actualiser toujours présent, désactivé pendant le chargement", () => {
    const data = { machines: [], agents: [], latest: launch({ status: "running" }) };
    expect(launchPanelHtml(state({ data }))).toContain('data-action="launch-refresh"');
    expect(launchPanelHtml(state({ data, latestLoading: true }))).toContain('data-action="launch-refresh" disabled');
  });

  it("session liée : lien et état résolus, handoff proposé si terminée", () => {
    const sessionId = "abcdefgh-1234-4111-8111-000000000000";
    const running = launch({ status: "running", session_id: sessionId });
    const open = state({
      data: { machines: [], agents: [], latest: running, sessions: [{ id: sessionId, ended_at: null }] },
    });
    const openHtml = linkedSessionHtml(open, running);
    expect(openHtml).toContain("#task-sessions");
    expect(openHtml).toContain("en cours");
    expect(openHtml).not.toContain("#task-ai-work");

    const ended = state({
      data: { machines: [], agents: [], latest: running, sessions: [{ id: sessionId, ended_at: "2026-10-01T10:05:00Z" }] },
    });
    const endedHtml = linkedSessionHtml(ended, running);
    expect(endedHtml).toContain("terminée");
    expect(endedHtml).toContain("#task-ai-work");
  });

  it("sans session liée, aucun lien", () => {
    expect(linkedSessionHtml(state(), launch())).toBe("");
  });

  it("confirmation d'annulation nomme le lancement sans HTML", () => {
    const text = cancelLaunchConfirmText(launch());
    expect(text).toContain("Annuler ce lancement");
    expect(text).not.toContain("<");
  });
});

/** Badge de protocole seul, extrait du HTML rendu (le statut a son propre badge). */
const protocolBadge = (html: string): string | null => {
  const match = html.match(/<span class="ds-badge[^"]*">(?:Protocole non vérifié|Handoff[^<]*)<\/span>/);
  return match === null ? null : match[0];
};

describe("preuve de protocole (TaskLaunchView.protocol)", () => {
  it("un protocole absent vaut « non vérifié », jamais « validé »", () => {
    expect(launchProtocolStatus(launch())).toBe("unverified");
    expect(launchProtocolBadgeLabel(undefined)).toBe("Protocole non vérifié");
    expect(launchProtocolBadgeLabel({ status: "unverified" })).toBe("Protocole non vérifié");
    expect(launchProtocolBadgeTone("unverified")).toBe("warning");
  });

  it("handoff attendu : informatif, jamais un succès", () => {
    expect(launchProtocolBadgeLabel({ status: "awaiting", session_id: "s1" })).toBe("Handoff attendu");
    expect(launchProtocolBadgeTone("awaiting")).toBe("info");
  });

  it("handoff reçu : qualifie la tâche sans la valider", () => {
    expect(launchProtocolBadgeLabel({ status: "handed_off", session_id: "s1", task_status: "completed" })).toBe(
      "Handoff reçu · tâche : à relire",
    );
    expect(launchProtocolBadgeLabel({ status: "handed_off", session_id: "s1", task_status: "in_progress" })).toBe(
      "Handoff reçu · tâche : En cours",
    );
    expect(launchProtocolBadgeLabel({ status: "handed_off", session_id: "s1", task_status: "blocked" })).toBe(
      "Handoff reçu · tâche : Bloqué",
    );
    expect(launchProtocolBadgeLabel({ status: "handed_off", session_id: "s1" })).toBe("Handoff reçu");
    expect(launchProtocolBadgeTone("handed_off")).toBe("neutral");
    expect(launchProtocolTaskLabel(null)).toBeNull();
    expect(launchProtocolTaskLabel("completed")).toBe("à relire");
  });

  it("aucun libellé de handoff ne parle de validation", () => {
    const labels = (["completed", "in_progress", "blocked", "created"] as const)
      .map((task_status) => launchProtocolBadgeLabel({ status: "handed_off", task_status }) ?? "")
      .join(" ");
    expect(labels).not.toMatch(/valid|approuv|succès/i);
  });

  it("protocole non applicable : aucun badge", () => {
    expect(launchProtocolBadgeLabel({ status: "not_applicable" })).toBeNull();
    expect(launchProtocolBadgeHtml(launch({ protocol: { status: "not_applicable" } }))).toBe("");
  });

  it("succeeded + unverified : le processus est terminé, le travail reste non vérifié", () => {
    const html = latestHtml(
      state({
        data: {
          machines: [],
          agents: [],
          latest: launch({ status: "succeeded", protocol: { status: "unverified" } }),
        },
      }),
    );
    expect(html).toContain("Processus terminé (code 0)");
    expect(html).toContain("Protocole non vérifié");
    expect(html).not.toContain("ds-badge--success");
    expect(protocolBadge(html)).toContain("ds-badge--warning");
  });

  it("failed + handed_off : le handoff neutralise l'erreur du protocole", () => {
    const html = latestHtml(
      state({
        data: {
          machines: [],
          agents: [],
          latest: launch({ status: "failed", protocol: { status: "handed_off", task_status: "blocked" } }),
        },
      }),
    );
    expect(html).toContain("Échec");
    expect(protocolBadge(html)).toContain("Handoff reçu · tâche : Bloqué");
    expect(protocolBadge(html)).not.toContain("ds-badge--danger");
    expect(protocolBadge(html)).not.toContain("ds-badge--success");
  });

  it("handoff attendu et not_applicable rendus à côté du statut", () => {
    const awaiting = latestHtml(
      state({
        data: {
          machines: [],
          agents: [],
          latest: launch({ status: "running", protocol: { status: "awaiting", session_id: "s1" } }),
        },
      }),
    );
    expect(protocolBadge(awaiting)).toContain("Handoff attendu");

    const notApplicable = latestHtml(
      state({
        data: {
          machines: [],
          agents: [],
          latest: launch({ status: "rejected", protocol: { status: "not_applicable" } }),
        },
      }),
    );
    expect(protocolBadge(notApplicable)).toBeNull();
    expect(notApplicable).not.toContain("Protocole non vérifié");
  });
});

describe("provenance (DEC-0199)", () => {
  it("neuf questions, neuf réponses, chacune tirée du snapshot figé", () => {
    const facts = provenanceFacts(launchWithProvenance(), snapshot());
    expect(facts).toHaveLength(9);
    expect(facts.map((fact) => fact.question)).toEqual([
      "Qui",
      "Où",
      "Quelle configuration",
      "Quel contexte",
      "Quel code",
      "Quand",
      "Combien",
      "Quel résultat",
      "Quelles erreurs de capture",
    ]);
    expect(new Set(facts.map((fact) => fact.id)).size).toBe(9);

    expect(answerOf(facts, "who")).toContain("u1");
    expect(answerOf(facts, "who")).toContain("review-helper");
    expect(answerOf(facts, "where")).toContain("m1");
    expect(answerOf(facts, "where")).toContain("feat/provenance");
    expect(answerOf(facts, "config")).toContain("fast v3");
    expect(answerOf(facts, "config")).toContain("claude-code 2.1.0");
    expect(answerOf(facts, "config")).toContain("read_only");
    expect(answerOf(facts, "context")).toContain("règle python-conventions v2");
    expect(answerOf(facts, "context")).toContain("projections : .claude/settings.json");
    expect(answerOf(facts, "code")).toContain("0f1e2d3");
    expect(answerOf(facts, "code")).toContain("worktree propre");
    expect(answerOf(facts, "when")).toContain("demandé le");
    expect(answerOf(facts, "outcome")).toContain("Processus terminé (code 0)");
    expect(answerOf(facts, "outcome")).toContain("à relire");
    expect(answerOf(facts, "capture")).toContain("capture complète");
  });

  it("les neuf questions sont bien rendues dans le panneau", () => {
    const html = provenanceHtml(launchWithProvenance(), snapshot());
    expect(html.match(/data-testid="provenance-/g)).toHaveLength(9);
    for (const id of ["who", "where", "config", "context", "code", "when", "how-much", "outcome", "capture"]) {
      expect(html).toContain(`data-testid="provenance-${id}"`);
    }
    expect(html).toContain("Quelles erreurs de capture");
  });

  it("chaque fait manquant vaut « inconnu », jamais une valeur inventée", () => {
    const bare = launch({
      machine_id: "",
      requested_by_user_id: "",
      agent_stable_key: null,
      created_at: "",
      expires_at: "",
      finished_at: null,
    });
    const facts = provenanceFacts(bare, emptySnapshot());
    expect(facts).toHaveLength(9);
    for (const id of ["who", "where", "config", "context", "code", "when"]) {
      expect(answerOf(facts, id)).toContain("inconnu");
    }
    expect(answerOf(facts, "code")).toContain("inconnu (commit non capturé)");
    expect(answerOf(facts, "when")).toContain("inconnu (lancement non terminé)");
    expect(facts.every((fact) => fact.answer.trim() !== "")).toBe(true);
    // Sans snapshot, la neuvième réponse dit l'absence, elle ne suppose rien.
    expect(answerOf(provenanceFacts(bare, null), "capture")).toContain("inconnu (aucune capture)");

    // Sans usage rattaché au lancement, « Combien » reste inconnu, même complet.
    const complete = provenanceFacts(launchWithProvenance(), snapshot());
    expect(answerOf(complete, "how-much")).toContain("inconnu");
    expect(answerOf(complete, "how-much")).not.toMatch(/\d/);
    expect(answerOf(provenanceFacts(bare, null, null), "how-much")).toContain("inconnu (consommation illisible)");
    expect(answerOf(provenanceFacts(bare, null, launchUsage({ entries: 0 })), "how-much")).toContain(
      "inconnu (aucune mesure d'usage rattachée à ce lancement)",
    );
  });

  it("Combien : le total serveur du lancement, sans présenter un coût partiel comme exact", () => {
    const answer = answerOf(provenanceFacts(launchWithProvenance(), snapshot(), launchUsage()), "how-much");
    expect(answer).toContain("2 mesures");
    expect(answer).toContain("durée 17 s");
    expect(answer).toContain("coût au moins 0,125 USD · inconnu pour 1 entrée");
    expect(answer).toContain("jetons au moins 330");
  });

  it("capture partielle : les erreurs nommées par le snapshot sont affichées telles quelles", () => {
    const facts = provenanceFacts(launchWithProvenance(), emptySnapshot());
    expect(answerOf(facts, "capture")).toContain("capture partielle");
    expect(answerOf(facts, "capture")).toContain("git_sha_unavailable");
    expect(answerOf(facts, "capture")).toContain("resolution_unavailable");
  });

  it("404 : la provenance nomme l'absence de snapshot au lieu d'un profil vide", () => {
    const html = provenanceHtml(launchWithProvenance(), null);
    expect(html).toContain("aucun snapshot");
    expect(html).toContain('data-testid="launch-provenance-notice"');
    expect(html.match(/data-testid="provenance-/g)).toHaveLength(9);
    expect(html).not.toContain("undefined");

    const panel = launchPanelHtml(
      state({ data: { machines: [], agents: [], latest: launchWithProvenance(), snapshot: null } }),
    );
    expect(panel).toContain("aucun snapshot");
  });

  it("le rendu ne dépend que du snapshot : une configuration courante modifiée ne le change pas", () => {
    const captured = snapshot();
    const data = { machines: [machine()], agents: [], latest: launchWithProvenance(), snapshot: captured };
    const previewFor = (stableKey: string, version: number): ResolvedAgentDefinition =>
      ({
        agent: { stable_key: "review-helper", version: 3, deprecated: false },
        rules: [],
        skills: [],
        model_profile: { stable_key: stableKey, version },
        runtime: null,
        requirements: { coding: false },
      }) as unknown as ResolvedAgentDefinition;

    const before = provenancePart(launchPanelHtml(state({ data, preview: previewFor("fast", 3) })));
    // Profil courant et postes affichés changent après la capture : la
    // provenance, elle, reste celle du run.
    const after = provenancePart(
      launchPanelHtml(
        state({
          data: { ...data, machines: [machine({ display_name: "renamed", free_slots: 9 })] },
          preview: previewFor("slow", 9),
        }),
      ),
    );
    expect(before).not.toBe("");
    expect(after).toBe(before);
    expect(after).toContain("fast v3");
    expect(after).not.toContain("slow");
    expect(after).not.toContain("renamed");
  });

  it("échappe tout texte venu du snapshot ou du lancement", () => {
    const evil = '<script>alert("x")</script>';
    const hostile = (): ExecutionSnapshot =>
      snapshot({
        payload: {
          schema_version: 1,
          capture_status: "partial",
          capture_errors: [{ code: "internal", field: "applied", detail: evil }],
          resolution: { agent_stable_key: evil },
          applied: { harness_id: evil, git_sha: evil, worktree_branch: evil },
        },
      } as unknown as Partial<ExecutionSnapshot>);
    const html = provenanceHtml(
      launchWithProvenance({ machine_id: evil, requested_by_user_id: "\"><b>x</b>" }),
      hostile(),
    );
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<b>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("&lt;b&gt;x&lt;/b&gt;");
    // Aucune valeur hostile ne devient un attribut exécutable.
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });

  it("une empreinte reste une empreinte, même sans préfixe", () => {
    expect(shortDigest(digest("1"))).toBe(`sha256:${"1".repeat(12)}…`);
    expect(shortDigest("court")).toBe("court");
  });
});


describe("production approval", () => {
  it("starts unchecked and is explicit in the launch confirmation", () => {
    const html = launchPanelHtml(state());
    expect(html).toContain('id="launch-production"');
    expect(html).not.toContain('id="launch-production" checked');
    expect(launchConfirmText(machine(), "claude-code", "", false)).toContain("Mode protégé");
    expect(launchConfirmText(machine(), "claude-code", "", true)).toContain("explicitement");
    expect(launchConfirmText(machine(), "claude-code", "", true)).toContain("ce lancement uniquement");
  });
  it("shows the persisted approval and keeps the user's current choice", () => {
    expect(launchPanelHtml(state({ allowProduction: true }))).toContain('id="launch-production" checked');
    expect(latestHtml(state({ data: { machines: [], agents: [], latest: launch({ allow_production: true }) } }))).toContain("Production autorisée pour ce lancement");
  });
});

describe("launch expiry delay", () => {
  it("offers an explicit delay and defaults to the server's two hours", () => {
    const html = launchPanelHtml(state());
    expect(html).toContain('id="launch-ttl"');
    expect(html).toContain('<option value="7200" selected>2 heures (recommandé)</option>');
    expect(html).toContain('<option value="1800"');
    expect(html).toContain('<option value="86400"');
    expect(html).not.toContain('<option value="900"');
  });
  it("keeps the chosen delay selected", () => {
    const options = launchTtlOptions(state({ expiresInSeconds: 14400 }));
    expect(options).toContain('<option value="14400" selected>4 heures</option>');
    expect(options.match(/selected/g)).toHaveLength(1);
  });
});
