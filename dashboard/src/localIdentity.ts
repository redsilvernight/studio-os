/**
 * Déconnexion (Desktop) : l'identité locale du poste (jeton machine, cache
 * d'identité) est oubliée par le démon via `identity.forget`. Un démon qui ne
 * l'accorde pas (ancienne version) ou injoignable ne bloque jamais la
 * déconnexion.
 */
import { daemonGrantsEnroll } from "./onboarding/view";
import type { Platform } from "./platform/types";

export async function forgetLocalIdentity(platform: Platform): Promise<void> {
  if (platform.mode !== "desktop") return;
  try {
    if (!(await daemonGrantsEnroll(platform))) return;
    const view = await platform.request("identity.get_view", {});
    if (!view.ok) return;
    const profile = (view.response.payload as { profile?: unknown }).profile;
    if (profile === undefined) return;
    await platform.request("identity.forget", { profile });
  } catch {
    // Best effort: the sign-out itself has already happened.
  }
}
