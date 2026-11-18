/**
 * P3 — premier lancement Desktop (pont local stubbé) : le parcours complet
 * ne demande ni projet ni dossier (bienvenue → connexion → vérification →
 * prêt → terminé), un état persisté hérité reprend sur l'étape valide
 * suivante, et la page « Prêt » ne bloque jamais sur un dossier.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { apiStub, expectClean, newCaptured, watchErrors } from "./support/ui16-stub";

const LEGACY_WS = "11111111-1111-4111-8111-111111111111";

async function installDesktop(page: Page, onboarding: unknown): Promise<void> {
  await page.addInitScript((state) => {
    window.localStorage.setItem("studio-os.onboarding.v1", JSON.stringify(state));
    let counter = 0;
    const answer = (req: { message_id: string; correlation_id: string; command: string }, payload: unknown) => {
      counter += 1;
      return {
        kind: "response",
        protocol: "studio.local/v1",
        message_id: `daemon-p3-${counter}`,
        request_id: req.message_id,
        correlation_id: req.correlation_id,
        sent_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
        command: req.command,
        payload,
      };
    };
    const invoke = async (name: string, args?: { request?: { command: string; message_id: string; correlation_id: string; payload: Record<string, unknown> } }) => {
      if (name === "desktop_info") {
        return { product: "Studi'OS Desktop", desktop_version: "0.1.0", mode: "desktop", protocol: "studio.local/v1", sidecar: { state: "not_started" } };
      }
      if (name === "get_server_origin") return { configured: location.origin, applied: location.origin, restart_required: false };
      if (name !== "bridge_request" || !args?.request) throw new Error("unexpected " + name);
      const command = args.request.command;
      const profile = { profile_id: "main", server_origin: location.origin };
      if (command === "runtime.handshake") {
        return answer(args.request, {
          outcome: "compatible",
          daemon: {
            role: "desktop",
            protocol_id: "studio.local",
            protocol: { minimum: { major: 1, minor: 0 }, maximum: { major: 1, minor: 0 } },
            component_version: "0.1.0",
            server_origin: null,
            capabilities: ["daemon.control", "identity.view"],
            required_capabilities: ["daemon.control", "identity.view"],
            optional_capabilities: [],
            optional_components: [],
          },
          granted_capabilities: ["daemon.control", "identity.view"],
        });
      }
      if (command === "identity.get_view") {
        return answer(args.request, {
          profile,
          secrets: [
            {
              checked_at: "2026-09-22T10:00:00Z",
              reference: {
                kind: "machine_credential",
                lookup_key: "studio-os.pc-e2e",
                profile,
                ref_id: "sec-e2e",
                store: "os_keyring",
              },
              status: "present",
            },
          ],
          workstation_name: "PC E2E",
        });
      }
      if (command === "daemon.status") {
        return answer(args.request, { action: "status", outcome: "ok", status: { state: "running" } });
      }
      throw new Error("unexpected bridge command " + command);
    };
    (window as unknown as { __TAURI__: unknown }).__TAURI__ = { core: { invoke } };
  }, onboarding);
}

async function stubServer(page: Page): Promise<void> {
  const captured = newCaptured();
  await page.route("**/api/**", apiStub(captured));
  await page.route("**/healthz", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
}

test.describe("P3 onboarding Desktop : poste seul", () => {
  test("parcours complet sans projet ni dossier, axe sans violation", async ({ page }) => {
    const watch = watchErrors(page);
    await installDesktop(page, { schema: 1, status: "in_progress", current: "bienvenue" });
    await stubServer(page);
    await page.goto("/#/bienvenue");

    const step = page.locator('[data-testid="onboarding-step"]');
    await expect(step).toHaveAttribute("data-step", "bienvenue");
    await page.locator('[data-action="start"]').click();

    // Connexion : le serveur est joint, le compte se connecte dans l'assistant.
    await expect(step).toHaveAttribute("data-step", "connexion");
    await expect(page.locator('[data-testid="server-probe"]')).toContainText("Serveur joint");
    await page.fill("#login-email", "e2e@example.test");
    await page.fill("#login-password", "e2e-secret");
    await page.locator("#login-form button[type=submit]").click();
    await expect(page.locator('[data-testid="onboarding-notice"]')).toContainText("Connecté");
    await page.locator('[data-testid="onboarding-step"] [data-action="next"]').click();

    // Vérification : poste reconnu, aucune étape projet/dossier.
    await expect(step).toHaveAttribute("data-step", "verification");
    await expect(page.locator('[data-testid="onboarding-step"]')).toContainText("Reconnu");
    await page.locator('[data-testid="onboarding-step"] [data-action="next"]').click();

    // Prêt : résumé du poste, lien Workspaces, fin sans obligation.
    await expect(step).toHaveAttribute("data-step", "final");
    await expect(step).toContainText("Votre poste est prêt");
    await expect(step).not.toContainText("Associez un dossier");
    await expect(page.locator('[data-testid="onboarding-to-workspaces"]')).toHaveAttribute("href", "#/workspaces");
    expect(await page.locator('[data-testid="onboarding-step"] [data-action="finish"]').isDisabled()).toBe(false);
    expect((await new AxeBuilder({ page }).include('[data-testid="onboarding-step"]').analyze()).violations).toEqual([]);

    await page.locator('[data-testid="onboarding-step"] [data-action="finish"]').click();
    await expect(page.locator('[data-testid="onboarding-step"]')).toHaveCount(0);
    const persisted = await page.evaluate(() => JSON.parse(window.localStorage.getItem("studio-os.onboarding.v1") ?? "{}"));
    expect(persisted).toMatchObject({ status: "completed", current: "termine" });
    expectClean(watch);
  });

  test("état hérité sur une étape retirée : reprise sur l'étape valide suivante", async ({ page }) => {
    const watch = watchErrors(page);
    await installDesktop(page, { schema: 1, status: "in_progress", current: "assistant", workspaceId: LEGACY_WS, folderName: "Mon jeu" });
    await stubServer(page);
    await page.goto("/#/bienvenue");
    const step = page.locator('[data-testid="onboarding-step"]');
    await expect(step).toHaveAttribute("data-step", "final");
    await expect(page.locator('[data-testid="onboarding-error"]')).toHaveCount(0);
    expectClean(watch);
  });
});
