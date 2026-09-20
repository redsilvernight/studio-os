import { createDesktopPlatform, detectTauriInvoke } from "./desktop";
import type { Platform } from "./types";
import { webPlatform } from "./web";

export type { DesktopInfo, Platform, PlatformMode } from "./types";

let cached: Platform | undefined;

/** The adapter for the current runtime (resolved once; Desktop only if the shell injected its bridge). */
export function getPlatform(scope: unknown = globalThis): Platform {
  if (scope !== globalThis) return resolve(scope);
  cached ??= resolve(scope);
  return cached;
}

function resolve(scope: unknown): Platform {
  const invoke = detectTauriInvoke(scope);
  return invoke ? createDesktopPlatform(invoke) : webPlatform;
}
