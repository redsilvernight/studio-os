/**
 * A5 — « En attente d'accès » : an active account (typically self-registered,
 * DEC-0109: readonly, no membership) that can see no project yet. Shown on
 * the Accueil instead of an empty dashboard; « Vérifier à nouveau »
 * re-asks the server, which stays the only truth (no local flag).
 */
import type { StudioClient } from "../api";
import { dsPageHeader } from "../ds/ds";
import { fetchIdentity } from "../identityApi";

export type ProjectAccess = "granted" | "none" | "unknown";

/** "unknown" (no identity, network or server error) never blocks a view. */
export async function probeProjectAccess(client: StudioClient): Promise<ProjectAccess> {
  const identity = await fetchIdentity(client);
  if (identity === null || typeof identity.role !== "string") return "unknown";
  if (identity.role === "admin") return "granted";
  try {
    const result = await client.GET("/api/v1/projects");
    if (!result.response.ok || result.data === undefined) return "unknown";
    return result.data.length > 0 ? "granted" : "none";
  } catch {
    return "unknown";
  }
}

export function awaitingAccessHtml(): string {
  return `${dsPageHeader("En attente d'accès", "Votre compte est actif, mais aucun projet ne vous est encore attribué.")}
    <section class="ds-card awaiting-access" data-testid="awaiting-access">
      <p>Un administrateur de votre studio doit vous ajouter comme membre d'un projet. Vos projets apparaîtront ici dès que ce sera fait.</p>
      <p class="meta">Communiquez-lui l'adresse email de votre compte si besoin.</p>
      <button class="ds-btn ds-btn--primary" type="button" data-testid="awaiting-access-recheck">Vérifier à nouveau</button>
    </section>`;
}

export function renderAwaitingAccess(view: HTMLElement, onRecheck: () => void): void {
  view.innerHTML = awaitingAccessHtml();
  const button = view.querySelector<HTMLButtonElement>("[data-testid=awaiting-access-recheck]");
  button?.addEventListener("click", () => {
    button.disabled = true;
    button.textContent = "Vérification…";
    onRecheck();
  });
}
