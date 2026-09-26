/**
 * C1 client/server compatibility (Dashboard side).
 *
 * The server decides (Bloc A is the source of truth): it answers 426 with a
 * structured `client_upgrade_required` when this build is below the family
 * minimum, and flags a build inside its grace window with an advisory
 * `X-Studio-Client-Update: recommended` header on any `/api/v1` answer. This
 * module only *reads* those signals into a shape the UI can show — it never
 * invents a verdict, and it treats anything malformed as "nothing to say".
 */

export type ClientFamily = "dashboard" | "desktop";

/** Baked in by Vite (`define`), sourced from `desktop`/`package.json`. */
export const CLIENT_VERSION: string = __STUDIO_CLIENT_VERSION__;

export interface UpgradeInfo {
  client: string;
  clientVersion: string | null;
  minimumSupported: string | null;
  latest: string | null;
  message: string;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

/** The structured body of a 426 `client_upgrade_required`, or `null` when the
 *  error is anything else (a wrong code, or a detail that is not an object). */
export function parseUpgradeRequired(errorCode: string | null, details: unknown): UpgradeInfo | null {
  if (errorCode !== "client_upgrade_required") return null;
  if (details === null || typeof details !== "object") return null;
  const record = details as Record<string, unknown>;
  const client = str(record["client"]);
  if (client === null) return null;
  return {
    client,
    clientVersion: str(record["client_version"]),
    minimumSupported: str(record["minimum_supported"]),
    latest: str(record["latest"]),
    message:
      str(record["message"]) ??
      "Cette version du client n'est plus prise en charge. Mettez à jour pour continuer.",
  };
}

/** The newest build the server recommends (grace window), or `null` when this
 *  client is current / undeclared. Header names are case-insensitive. */
export function advisoryLatest(headers: Headers): string | null {
  if (headers.get("x-studio-client-update") !== "recommended") return null;
  return str(headers.get("x-studio-client-latest"));
}

/** A one-line advisory for the banner, or `null` when there is nothing to say. */
export function advisoryText(latest: string | null): string | null {
  if (latest === null) return null;
  return `Une mise à jour du client est disponible (${latest}). Mise à jour recommandée.`;
}

/** The blocking copy for an update-required screen. Never claims a signature. */
export function upgradeRequiredText(info: UpgradeInfo): string {
  const target = info.latest !== null ? ` (dernière version : ${info.latest})` : "";
  const floor = info.minimumSupported !== null ? ` Version minimale prise en charge : ${info.minimumSupported}.` : "";
  return `${info.message}${target}.${floor}`;
}
