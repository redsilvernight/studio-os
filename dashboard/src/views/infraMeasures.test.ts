// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { getInfraMeasurements, infraMeasuresHtml, renderInfraMeasures, seriesLabel, sparkline, type InfraReport } from "./infraMeasures";

const point = (value: number, at = "2026-11-18T10:00:00Z") => ({ measured_at: at, value });
const report: InfraReport = {
  window_days: 7,
  generated_at: "2026-11-18T12:00:00Z",
  series: [
    { metric: "pg_table_bytes", subject: "events", project_id: null, latest: point(2048), points: [point(1024), point(2048)] },
    { metric: "sse_connections", subject: "", project_id: null, latest: point(3), points: [point(3)] },
  ],
};

describe("infraMeasuresHtml", () => {
  it("affiche un tableau et une courbe étiquetée par série, sans contenu", () => {
    const html = infraMeasuresHtml(report);
    expect(html).toContain("Table PostgreSQL · events");
    expect(html).toContain("2 Ko");
    expect(html.match(/<svg/g)).toHaveLength(2);
    expect(html).toContain('role="img"');
    expect(html.match(/<h1>/g)).toHaveLength(1);
  });
  it("gère vide, chargement et erreur", () => {
    expect(infraMeasuresHtml({ ...report, series: [] })).toContain("Aucun relevé");
    expect(infraMeasuresHtml()).toContain("ds-skeleton");
    expect(infraMeasuresHtml(undefined, "boom")).toContain("boom");
  });
  it("courbe d'un seul point et libellé de projet tronqué", () => {
    expect(sparkline(report.series[1]!)).toContain("<polyline");
    expect(seriesLabel({ metric: "storage_bytes", subject: "", project_id: "12345678-aaaa", latest: point(1), points: [] })).toBe("Stockage du projet · projet 12345678");
  });
});

describe("getInfraMeasurements / renderInfraMeasures", () => {
  it("transmet la fenêtre et rend le rapport", async () => {
    const GET = vi.fn().mockResolvedValue({ response: { ok: true, status: 200 }, data: report });
    const root = document.createElement("div");
    await renderInfraMeasures(root, { client: { GET } as never, authed: true });
    expect(GET).toHaveBeenCalledWith("/api/v1/internal/infra-measurements", { params: { query: { days: 7 } } });
    expect(root.textContent).toContain("Connexions SSE");
  });
  it("un 403 affiche un refus lisible", async () => {
    const GET = vi.fn().mockResolvedValue({ response: { ok: false, status: 403 }, error: { detail: "insufficient role" } });
    await expect(getInfraMeasurements({ GET } as never)).rejects.toBeInstanceOf(ApiError);
    const root = document.createElement("div");
    await renderInfraMeasures(root, { client: { GET } as never, authed: true });
    expect(root.textContent).toContain("Réservé aux administrateurs.");
  });
});
