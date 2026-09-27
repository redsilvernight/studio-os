/**
 * End of a signed-in session (DEC-0110, TECH/04 « Cycle de session »): any 401
 * on the current token means expired or revoked — the server never says
 * which. The token is dropped once, then the user is sent back to sign-in
 * with an explicit notice; no automatic retry, so no reconnection loop.
 */
import { clearToken, hasToken } from "./auth";
import { resetIdentityCache } from "./identityApi";

export const SESSION_ENDED_NOTICE =
  "Votre session a expiré ou a été révoquée. Reconnectez-vous pour continuer.";

export function createSessionEndHandler(backToLogin: (notice: string) => void): () => void {
  return () => {
    if (!hasToken()) return;
    clearToken();
    resetIdentityCache();
    backToLogin(SESSION_ENDED_NOTICE);
  };
}
