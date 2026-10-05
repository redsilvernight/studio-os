import { describe, expect, it } from "vitest";
import type { BridgeAnswer } from "./platform/contracts";
import { forgetLocalIdentity } from "./localIdentity";
import { fakeDesktop, notSupported } from "./testSupport/fakeDesktop";
import { webPlatform } from "./platform/web";

const ok = (payload: unknown): BridgeAnswer => ({ ok: true, response: { payload } }) as unknown as BridgeAnswer;
const PROFILE = { profile_id: "main", server_origin: "https://studio.example" };

function daemon(granted: string[], forget: BridgeAnswer = ok({ outcome: "forgotten" })) {
  const calls: { command: string; payload: unknown }[] = [];
  const platform = fakeDesktop({
    request: (async (command: string, payload: unknown) => {
      calls.push({ command, payload });
      if (command === "runtime.handshake") return ok({ outcome: "compatible", granted_capabilities: granted });
      if (command === "identity.get_view") return ok({ profile: PROFILE, secrets: [] });
      if (command === "identity.forget") return forget;
      return notSupported;
    }) as never,
  });
  return { platform, calls };
}

describe("forgetLocalIdentity", () => {
  it("asks the daemon to forget the identity of the viewed profile", async () => {
    const { platform, calls } = daemon(["identity.enroll"]);
    await forgetLocalIdentity(platform);
    expect(calls.at(-1)).toEqual({ command: "identity.forget", payload: { profile: PROFILE } });
  });

  it("does nothing when the daemon does not grant identity.enroll", async () => {
    const { platform, calls } = daemon([]);
    await forgetLocalIdentity(platform);
    expect(calls.map((c) => c.command)).toEqual(["runtime.handshake"]);
  });

  it("never throws when the daemon refuses or fails", async () => {
    const { platform } = daemon(["identity.enroll"], notSupported);
    await expect(forgetLocalIdentity(platform)).resolves.toBeUndefined();
    const broken = fakeDesktop({ request: (async () => Promise.reject(new Error("down"))) as never });
    await expect(forgetLocalIdentity(broken)).resolves.toBeUndefined();
  });

  it("is a no-op in web mode", async () => {
    await expect(forgetLocalIdentity(webPlatform)).resolves.toBeUndefined();
  });
});
