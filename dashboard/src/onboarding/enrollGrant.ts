/**
 * Négociation `identity.enroll`, isolée de la vue d'onboarding : la
 * déconnexion (`localIdentity`) en a besoin au chargement initial, l'onboarding
 * reste chargé à la demande.
 */
import type { Platform } from "../platform/types";

/**
 * DEC-0130 : la session ne part que vers un démon qui a accordé
 * `identity.enroll` à l'instant (négociation fraîche : un démon redémarré
 * oublie ses accords). Un ancien démon ne la reçoit jamais.
 */
export async function daemonGrantsEnroll(platform: Platform): Promise<boolean> {
  try {
    const peer = (await platform.desktopInfo())?.peer;
    if (!peer) return false;
    const answer = await platform.request("runtime.handshake", { peer });
    if (!answer.ok) return false;
    const reply = answer.response.payload as { outcome?: string; granted_capabilities?: string[] };
    return (
      (reply.outcome === "compatible" || reply.outcome === "compatible_degraded") &&
      (reply.granted_capabilities ?? []).includes("identity.enroll")
    );
  } catch {
    return false;
  }
}
