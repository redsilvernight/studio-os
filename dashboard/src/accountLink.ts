/**
 * A5 — Entry points of the public account screens (DOM-free, unit-testable).
 *
 * Emailed links are `<base>/verify-email#token=…` and
 * `<base>/reset-password#token=…` (services/accounts.py): the secret lives in
 * the fragment, never sent to a server. The caller reads it once, then
 * replaces the URL with `scrubbedPath()` so it never stays in history.
 */
export type AccountLinkKind = "verify" | "reset";

export interface AccountLink {
  kind: AccountLinkKind;
  /** null when the link carries no usable secret. */
  token: string | null;
}

const LINK_PATH = /(?:^|\/)(verify-email|reset-password)\/?$/;

export function readAccountLink(pathname: string, hash: string): AccountLink | null {
  const match = LINK_PATH.exec(pathname);
  if (match === null) return null;
  const kind: AccountLinkKind = match[1] === "verify-email" ? "verify" : "reset";
  const token = new URLSearchParams(hash.replace(/^#/, "")).get("token");
  return { kind, token: token !== null && token.trim() !== "" ? token.trim() : null };
}

/** The application root the link was served under, without secret. */
export function scrubbedPath(pathname: string): string {
  const base = pathname.replace(LINK_PATH, "");
  return base.endsWith("/") ? base : `${base}/`;
}

export type PublicHashScreen = "register" | "forgot" | "resend";

const PUBLIC_HASHES: Record<string, PublicHashScreen> = {
  inscription: "register",
  "mot-de-passe-oublie": "forgot",
  "renvoyer-verification": "resend",
};

/** Shareable pre-login addresses (`#/inscription`, …); null otherwise. */
export function publicHashScreen(hash: string): PublicHashScreen | null {
  const key = hash.replace(/^#\/?/, "").replace(/\/$/, "");
  return PUBLIC_HASHES[key] ?? null;
}

export const PUBLIC_HASH: Record<PublicHashScreen, string> = {
  register: "#/inscription",
  forgot: "#/mot-de-passe-oublie",
  resend: "#/renvoyer-verification",
};
