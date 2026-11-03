import { ApiError, parseErrorBody, type StudioClient } from "./api";
import type { components } from "./openapi-schema";
import { esc } from "./ui";

export type ProductDiscovery = components["schemas"]["ProductDiscovery"];
type Intent = ProductDiscovery["intent"];
const STATE_LABELS = {
  available: "Disponible",
  needs_configuration: "À configurer",
  not_authorized: "Non autorisé",
  unsupported: "Non pris en charge",
};

export async function fetchProductDiscovery(
  client: StudioClient,
  intent: Intent = "overview",
  key?: string,
  limit = 6,
): Promise<ProductDiscovery> {
  const result = await client.GET("/api/v1/capabilities", {
    params: { query: { intent, key, limit } },
  });
  if (!result.response.ok || !result.data) {
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  return result.data;
}

export function productDiscoveryHtml(result: ProductDiscovery): string {
  return `<p>${esc(result.summary)}</p><ul class="ds-list">` +
    (result.capabilities ?? []).map((item) => `<li><strong>${esc(item.title)}</strong> · ${esc(STATE_LABELS[item.state])}` +
      `${item.write_allowed ? "" : " · Lecture seule"}<p>${esc(item.summary)}</p>` +
      (item.reason ? `<p>${esc(item.reason)}</p>` : "") +
      (item.example ? `<p>Exemple : ${esc(item.example)}</p>` : "") +
      [...(item.prerequisites ?? []), ...(item.restrictions ?? [])].map((text) => `<p>${esc(text)}</p>`).join("") +
      `<button class="ds-btn ds-btn--secondary" type="button" data-discovery-key="${esc(item.key)}">Détail</button></li>`).join("") +
    `</ul>` + (result.next_steps ?? []).map((text) => `<p>${esc(text)}</p>`).join("") +
    (result.additional_available ? `<button class="ds-btn ds-btn--secondary" type="button" data-discovery-all>Voir les ${result.additional_available} autres capacités</button>` : "");
}

export function mountProductDiscovery(root: HTMLElement, client: StudioClient): void {
  const section = document.createElement("section");
  section.className = "ds-panel";
  section.setAttribute("aria-label", "Découvrir Studi'OS");
  section.innerHTML = `<header><h2>Découvrir Studi'OS</h2></header><div class="body">` +
    `<button class="ds-btn ds-btn--secondary" type="button" data-discovery-intent="overview">Que peux-tu faire avec Studi'OS ?</button> ` +
    `<button class="ds-btn ds-btn--secondary" type="button" data-discovery-intent="start_project">Démarrer mon projet</button> ` +
    `<button class="ds-btn ds-btn--secondary" type="button" data-discovery-intent="configuration">Vérifier ma configuration</button>` +
    `<div data-discovery-result role="status" aria-live="polite"></div></div>`;
  let intent: Intent = "overview";
  let revision = 0;
  section.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest<HTMLButtonElement>("button");
    if (!button || button.disabled) return;
    const requested = button.dataset.discoveryIntent;
    if (requested === "overview" || requested === "configuration" || requested === "start_project") intent = requested;
    const target = section.querySelector<HTMLElement>("[data-discovery-result]");
    if (!target) return;
    const version = ++revision;
    section.querySelectorAll("button").forEach((item) => { item.disabled = true; });
    target.textContent = "Chargement des capacités…";
    try {
      const result = await fetchProductDiscovery(client, intent, button.dataset.discoveryKey, button.hasAttribute("data-discovery-all") ? 24 : 6);
      if (version === revision && section.isConnected) target.innerHTML = productDiscoveryHtml(result);
    } catch (error) {
      if (section.isConnected) target.textContent = error instanceof ApiError && error.isForbidden
        ? "Accès non autorisé à la découverte pour cette connexion."
        : "La découverte est indisponible. Vérifiez votre connexion puis réessayez.";
    } finally {
      section.querySelectorAll("button").forEach((item) => { item.disabled = false; });
    }
  });
  root.append(section);
}
