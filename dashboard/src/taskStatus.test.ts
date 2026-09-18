import { describe, expect, it } from "vitest";
import {
  TASK_COLUMNS,
  TASK_STATUS_LABEL_FR,
  columnToStatus,
  statusColumn,
  taskClaimHint,
  taskStatusLabel,
  taskStatusTone,
} from "./taskStatus";

describe("statusColumn", () => {
  it("maps canonical statuses without merging blocked", () => {
    expect(statusColumn("created")).toBe("TODO");
    expect(statusColumn("in_progress")).toBe("IN PROGRESS");
    expect(statusColumn("blocked")).toBe("BLOCKED");
    expect(statusColumn("completed")).toBe("DONE");
  });

  it("marks unknown statuses instead of inventing a column", () => {
    expect(statusColumn("archived")).toBe("UNKNOWN");
    expect(statusColumn("")).toBe("UNKNOWN");
  });

  it("exposes the four display columns", () => {
    expect(TASK_COLUMNS).toEqual(["TODO", "IN PROGRESS", "BLOCKED", "DONE"]);
  });
});

describe("columnToStatus", () => {
  it("is the exact inverse of statusColumn (drop target → canonical status)", () => {
    for (const column of TASK_COLUMNS) {
      expect(statusColumn(columnToStatus(column))).toBe(column);
    }
    expect(columnToStatus("BLOCKED")).toBe("blocked");
    expect(columnToStatus("DONE")).toBe("completed");
  });
});

describe("UI-5 libellés français (clés backend inchangées)", () => {
  it("traduit les quatre statuts sans toucher aux clés", () => {
    expect(TASK_STATUS_LABEL_FR).toEqual({
      created: "À faire",
      in_progress: "En cours",
      blocked: "Bloqué",
      completed: "Terminé",
    });
    expect(taskStatusLabel("created")).toBe("À faire");
    expect(taskStatusLabel("in_progress")).toBe("En cours");
    expect(taskStatusLabel("blocked")).toBe("Bloqué");
    expect(taskStatusLabel("completed")).toBe("Terminé");
  });

  it("ne montre jamais les clés techniques brutes (TODO, IN PROGRESS…)", () => {
    for (const label of Object.values(TASK_STATUS_LABEL_FR)) {
      expect(["TODO", "IN PROGRESS", "BLOCKED", "DONE"]).not.toContain(label);
    }
  });

  it("replie un statut inconnu sur la clé brute, sans inventer", () => {
    expect(taskStatusLabel("archived")).toBe("archived");
  });

  it("associe une teinte lisible à chaque statut", () => {
    expect(taskStatusTone("created")).toBe("neutral");
    expect(taskStatusTone("in_progress")).toBe("info");
    expect(taskStatusTone("blocked")).toBe("warning");
    expect(taskStatusTone("completed")).toBe("success");
    expect(taskStatusTone("archived")).toBe("neutral");
  });
});

describe("taskClaimHint (données réelles uniquement)", () => {
  it("disponible quand personne ne travaille dessus", () => {
    expect(taskClaimHint({ claimed_by_machine_id: null })).toBe("Disponible");
    expect(taskClaimHint({})).toBe("Disponible");
  });

  it("signale la machine (tronquée) et l'agent quand ils existent", () => {
    expect(taskClaimHint({ claimed_by_machine_id: "abcdef12-3456-7890-abcd-ef1234567890" })).toBe(
      "Prise · machine abcdef12…",
    );
    expect(
      taskClaimHint({ claimed_by_machine_id: "m123456789", claimed_by_agent_id: "a987654321" }),
    ).toBe("Prise · machine m1234567… · agent a9876543…");
  });

  it("n'invente ni priorité ni assigné", () => {
    expect(taskClaimHint({ claimed_by_machine_id: "m1" })).not.toMatch(/priorit/i);
  });
});
