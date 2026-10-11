// @vitest-environment happy-dom
/**
 * Boîte « Coordination à traiter » de la page projet : questions et blocages
 * sans réponse, texte d'une autre session toujours échappé, état « indisponible »
 * sans bloquer la page. DOM réel pour le rendu asynchrone (client simulé).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import type { CoordinationItem } from "../coordination";
import { projectCoordinationHtml, renderProjectCoordinationInto } from "./projectDetail";

const TASK_ID = "bbbbbbbb-1111-4222-8333-444444444444";
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

function item(overrides: Partial<CoordinationItem> = {}): CoordinationItem {
  return {
    eventId: "99999999-0000-4000-8000-000000000001",
    intent: "question",
    text: "Le chemin de sortie est-il déjà validé ?",
    taskId: TASK_ID,
    inReplyTo: null,
    fromSessionId: null,
    actorType: "system",
    actorId: "88888888-0000-4000-8000-000000000001",
    machineId: null,
    at: "2026-09-12T09:00:00Z",
    ...overrides,
  };
}

function fakeClient(reply: { data?: unknown; status: number }): StudioClient {
  const get = vi.fn(async () => ({
    data: reply.data,
    error: undefined,
    response: new Response(null, { status: reply.status }),
  }));
  return { GET: get } as unknown as StudioClient;
}

function mount(): HTMLElement {
  const root = document.createElement("div");
  document.body.append(root);
  return root;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("projectCoordinationHtml", () => {
  it("item ouvert : intention, texte, heure et lien vers la tâche", () => {
    const html = projectCoordinationHtml([item()]);
    expect(html).toContain("Coordination à traiter");
    expect(html).toContain("Question");
    expect(html).toContain("Le chemin de sortie est-il déjà validé ?");
    expect(html).toContain("<time");
    expect(html).toContain(`href="#/tasks/${TASK_ID}"`);
    expect(html).toContain('data-coordination-intent="question"');
  });

  it("n'affiche aucun identifiant : ni event, ni session, ni acteur", () => {
    const html = projectCoordinationHtml([item()]);
    const visible = html.slice(0, html.indexOf(`href="#/tasks/${TASK_ID}"`));
    expect(visible).not.toMatch(UUID);
    expect(html).not.toContain("in_reply_to");
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });

  it("une question répondue disparaît ; seules les questions et blocages ouverts restent", () => {
    const answered = item({ eventId: "e-answered" });
    const reply = item({
      eventId: "e-reply",
      intent: "heads_up",
      inReplyTo: answered.eventId,
      text: "Oui, c'est validé.",
    });
    const html = projectCoordinationHtml([answered, reply, item({ eventId: "e-open", intent: "blocked_by" })]);
    expect(html).toContain("Le chemin de sortie est-il déjà validé ?");
    expect(html).toContain("Blocage");
    expect(html).not.toContain("Oui, c'est validé.");
    expect(html.match(/class="ds-list-item"/g)).toHaveLength(1);
  });

  it("rien à traiter : handoff et information seuls ne demandent aucune action", () => {
    const html = projectCoordinationHtml([
      item({ eventId: "e-handoff", intent: "handoff" }),
      item({ eventId: "e-info", intent: "heads_up" }),
    ]);
    expect(html).toContain("Rien à traiter");
    expect(html).not.toContain("ds-list-item");
  });

  it("liste vide : état vide explicite, jamais une section muette", () => {
    const html = projectCoordinationHtml([]);
    expect(html).toContain("Rien à traiter");
    expect(html).not.toContain("<ul");
  });

  it("texte d'une autre session : échappé, jamais interprété", () => {
    const html = projectCoordinationHtml([item({ text: `<script>alert(1)</script>${"x".repeat(300)}` })]);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  it("signal sans tâche liée : l'heure reste, aucun lien mort", () => {
    const html = projectCoordinationHtml([item({ taskId: null })]);
    expect(html).toContain("Question");
    expect(html).not.toContain('href="#/tasks/');
  });

  it("indisponible : la page reste utilisable et l'état est nommé", () => {
    const html = projectCoordinationHtml(null);
    expect(html).toContain("Coordination indisponible");
    expect(html).toContain("data-coordination-unavailable");
    expect(html).not.toContain("role=\"alert\"");
  });
});

describe("renderProjectCoordinationInto", () => {
  it("succès : la boîte est peinte avec les items ouverts", async () => {
    const root = mount();
    await renderProjectCoordinationInto(root, {
      client: fakeClient({ status: 200, data: [{ intent: "question" }] }),
      projectId: "p1",
      authed: true,
    });
    expect(root.innerHTML).toContain("Coordination à traiter");
  });

  it("échec réseau ou 403 : « indisponible », jamais bloquant, pas de rejeu", async () => {
    const root = mount();
    const client = fakeClient({ status: 500 });
    await renderProjectCoordinationInto(root, { client, projectId: "p1", authed: true });
    expect(root.innerHTML).toContain("Coordination indisponible");
    expect(root.innerHTML).not.toContain("role=\"alert\"");
    expect(client.GET).toHaveBeenCalledTimes(1);
    expect((client.GET as unknown as ReturnType<typeof vi.fn>).mock.calls[0]?.[1]).toMatchObject({
      params: { query: { project: "p1" } },
    });
  });

  it("non connecté : rien n'est rendu et aucun appel n'est fait", async () => {
    const root = mount();
    const client = fakeClient({ status: 200, data: [] });
    await renderProjectCoordinationInto(root, { client, projectId: "p1", authed: false });
    expect(root.innerHTML).toBe("");
    expect(client.GET).not.toHaveBeenCalled();
  });
});