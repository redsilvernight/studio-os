import type { Platform } from "../platform";
import type { HarnessLaunchPreview } from "../platform/generated/local-contracts.generated";
import { call } from "../harnessApi";
import { esc } from "../ui";

export function launchEnvironmentPreviewHtml(): string {
  return `<button class="ds-btn" type="button" data-action="launch-environment">Voir la préparation des lancements</button>` +
    `<div data-launch-environment role="status" aria-live="polite"></div>`;
}

function previewHtml(preview: HarnessLaunchPreview): string {
  const states = { included: "Prévu", unavailable: "Absent", unverified: "Non vérifié" };
  const items = (values: string[]): string => values.map((value) => `<li>${esc(value)}</li>`).join("");
  const components = (values: HarnessLaunchPreview["hooks"]): string => (values ?? [])
    .map((value) => `<li>${esc(value.name)} — ${esc(states[value.state])} : ${esc(value.reason)}</li>`).join("");
  const modes = (preview.access_modes ?? []).map((mode) => mode === "read_only" ? "Lecture seule" : "Écriture dans le dossier");
  return `<section class="integration-plan"><h4>Préparation locale des lancements</h4>` +
    `<p>Observation avant lancement sur ce poste seulement. Le chargement effectif sera revérifié au lancement ; la présence d’un hook ne vérifie ni son contenu ni son exécution.</p>` +
    `<p>${preview.isolation === "isolated" ? "Configuration isolée prévue" : "Isolation non vérifiée"}</p>` +
    `<h5>Sources de réglages</h5><ul>${items(preview.settings_sources ?? [])}</ul>` +
    `<h5>Hooks Studio</h5><ul>${components(preview.hooks)}</ul>` +
    `<h5>Serveurs MCP</h5><ul>${components(preview.mcp_servers)}</ul>` +
    `<h5>Exclusions et raisons</h5><ul>${items(preview.exclusions ?? [])}</ul>` +
    `<h5>Limites</h5><ul>${items(preview.limitations ?? [])}</ul>` +
    `<p>Modes : ${modes.map(esc).join(", ") || "Non vérifiés"}.</p>` +
    `<p>${preview.production_approval_required
      ? "Cet adaptateur refuse le lancement sans autorisation explicite de production."
      : "Sans autorisation de production, les commandes sont désactivées."} Le profil et la politique du poste restent contrôlés au lancement.</p></section>`;
}

export function bindLaunchEnvironmentPreview(card: HTMLElement, platform: Platform, workspaceId: string, adapterId: string): void {
  const button = card.querySelector<HTMLButtonElement>("[data-action=launch-environment]");
  const result = card.querySelector<HTMLElement>("[data-launch-environment]");
  if (!button || !result) return;
  button.addEventListener("click", () => {
    if (button.disabled) return;
    button.disabled = true;
    result.textContent = "Lecture de la préparation locale…";
    void (async () => {
      try {
        const outcome = await call<HarnessLaunchPreview>(platform, "harness.launch_preview", { workspace_id: workspaceId, adapter_id: adapterId });
        if (outcome.ok && outcome.value.adapter_id === adapterId) {
          result.innerHTML = previewHtml(outcome.value);
        } else {
          result.textContent = "Aperçu indisponible sur ce daemon ou pour cet outil. Vérifiez sa version et la configuration locale.";
        }
      } catch {
        result.textContent = "Aperçu indisponible : la lecture locale a échoué. Réessayez après avoir vérifié la connexion au daemon.";
      } finally {
        button.disabled = false;
      }
    })();
  });
}
