import { describe, expect, it } from "vitest";
import { suspendedShellBannerHtml } from "./studioSuspendedBanner";

describe("N5 · bandeau persistant du shell", () => {
  it("nomme le studio, explique la lecture seule et mène à l'écran dédié", () => {
    const html = suspendedShellBannerHtml("s 1", "Atelier <Phare>");
    expect(html).toContain("Atelier &lt;Phare&gt; est suspendu");
    expect(html).toContain("Lecture seule");
    expect(html).toContain('href="#/studios/s%201/suspended"');
  });
});
