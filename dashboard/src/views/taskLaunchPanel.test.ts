import { describe, expect, it } from "vitest";
import type { AuthIdentity } from "../identityApi";
import type { ResolvedAgentDefinition } from "../resolutionApi";
import type { MachineEligibility, TaskLaunch } from "../taskLaunchesApi";
import {
  canCancelLaunch,
  cancelLaunchConfirmText,
  ineligibilityReasonLabel,
  isTerminalLaunch,
  launchConfirmText,
  launchPanelHtml,
  launchReasonCodeLabel,
  linkedSessionHtml,
  machineOptionLabel,
  previewLines,
  taskLaunchStatusLabel,
  taskLaunchStatusTone,
  type LaunchPanelState,
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

const launch = (overrides: Partial<TaskLaunch> = {}): TaskLaunch =>
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
  }) as TaskLaunch;

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

describe("labels", () => {
  it("traduit les statuts de lancement", () => {
    expect(taskLaunchStatusLabel("requested")).toBe("Demandé");
    expect(taskLaunchStatusLabel("running")).toBe("En cours");
    expect(taskLaunchStatusTone("succeeded")).toBe("success");
    expect(taskLaunchStatusTone("failed")).toBe("danger");
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
  });

  it("données indisponibles : avertissement, jamais d'état inventé", () => {
    const html = launchPanelHtml(state({ data: null }));
    expect(html).toContain("Machines éligibles indisponibles");
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
    expect(text).toContain("Annuler le lancement");
    expect(text).not.toContain("<");
  });
});
