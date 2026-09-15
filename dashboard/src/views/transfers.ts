/**
 * DASH-5 — Transfers list + direct-to-storage upload.
 *
 * Read: `GET /api/v1/transfers`, `GET /api/v1/transfers/consumption`.
 * Write: `POST /api/v1/transfers` then, byte-side, the pre-signed URL(s) from
 * `POST /transfers/{id}/upload/initiate` — the dashboard PUTs straight to
 * storage (single PUT or 64 MiB multipart), never through the API. Progress is
 * shown from the returned byte counts; a `413 transfer_too_large` /
 * `507 quota_exceeded` is surfaced as an actionable message (see the quota
 * line), never retried silently.
 */
import type { StudioClient } from "../api";
import { uiState } from "../store";
import {
  createTransfer,
  downloadUrl,
  getConsumption,
  listTransfers,
  uploadPhaseLabel,
  uploadTransfer,
  type Transfer,
  type TransferConsumption,
  type UploadProgress,
} from "../transfersApi";
import { describeError, esc, fmtTime, idCell, section, statusBlock } from "../ui";

export interface TransfersContext {
  client: StudioClient;
  authed: boolean;
  projectId?: string;
}

const CATEGORIES = ["temporary", "build", "asset", "raw_recording"] as const;

function humanBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  const units = ["B", "KiB", "MiB", "GiB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit] ?? "B"}`;
}

export { humanBytes };

function rowsHtml(transfers: Transfer[], authed: boolean): string {
  return transfers
    .map(
      (t) =>
        `<tr><td><code class="mono">${esc(t.transfer_code)}</code></td><td>${esc(t.filename)}<div class="mono">${idCell(t.id)}</div></td>` +
        `<td>${esc(t.category)}</td><td>${humanBytes(t.size_bytes)}</td><td>${esc(t.status)}</td>` +
        `<td>${idCell(t.project_id)}</td><td>${fmtTime(t.created_at)}</td>` +
        `<td class="actions"><button type="button" data-link="${esc(t.id)}" ${authed && t.status === "ready" ? "" : "disabled"}>Get link</button></td></tr>`,
    )
    .join("");
}

function uploadFormHtml(authed: boolean, projectId: string | undefined, consumption: TransferConsumption | null): string {
  const projectField =
    projectId !== undefined
      ? `<span class="meta">project ${esc(projectId)}</span>`
      : `<label>Project ID (optional) <input name="project_id" placeholder="uuid" ${authed ? "" : "disabled"} /></label>`;
  const quota =
    consumption === null
      ? ""
      : `<span class="meta">quota remaining ${humanBytes(consumption.remaining_bytes)} / ${humanBytes(consumption.quota_bytes)}</span>`;
  return `<form data-upload class="inline-form"><h3>Upload a file</h3>
    <label>File <input type="file" name="file" required ${authed ? "" : "disabled"} /></label>
    ${projectField}
    <label>Task ID (optional) <input name="task_id" placeholder="uuid" ${authed ? "" : "disabled"} /></label>
    <label>Recipient user ID (optional) <input name="recipient_user_id" placeholder="uuid" ${authed ? "" : "disabled"} /></label>
    <label>Category <select name="category" ${authed ? "" : "disabled"}>${CATEGORIES.map((c) => `<option value="${c}">${c}</option>`).join("")}</select></label>
    <button type="submit" ${authed ? "" : "disabled"}>Create + upload</button>
    ${quota}
    <span class="meta">bytes go straight to storage via pre-signed URLs, never through the API</span>
    <progress data-progress max="100" value="0" hidden></progress>
    <span data-upload-msg class="meta"></span></form>`;
}

export async function renderTransfers(root: HTMLElement, ctx: TransfersContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = section("Transfers", "GET /transfers", statusBlock("empty", "Set a machine token to list or send transfers."));
    return;
  }
  root.innerHTML = section("Transfers", "GET /transfers", statusBlock("loading"));
  const projectId = ctx.projectId ?? uiState.selectedProjectId ?? undefined;
  let transfers: Transfer[] = [];
  let consumption: TransferConsumption | null = null;
  try {
    transfers = await listTransfers(ctx.client, projectId);
  } catch (error) {
    root.innerHTML = section("Transfers", "GET /transfers", statusBlock("error", describeError(error)));
    return;
  }
  try {
    consumption = await getConsumption(ctx.client, projectId);
  } catch {
    consumption = null;
  }
  const table =
    transfers.length === 0
      ? statusBlock("empty", "No transfers visible to this token.")
      : `<table><thead><tr><th>Code</th><th>Filename</th><th>Category</th><th>Size</th><th>Status</th><th>Project</th><th>Created</th><th></th></tr></thead><tbody>${rowsHtml(transfers, ctx.authed)}</tbody></table>`;
  root.innerHTML = section(
    "Transfers",
    `GET /transfers${projectId !== undefined ? "?project_id" : ""} · ${transfers.length} shown · retention temporary 7d / build 30d`,
    `${table}${uploadFormHtml(ctx.authed, projectId, consumption)}<div data-msg class="meta"></div>`,
  );
  bind(root, ctx, projectId);
}

function setMsg(root: HTMLElement, text: string): void {
  const node = root.querySelector("[data-upload-msg], [data-msg]");
  if (node !== null) node.textContent = text;
}

function bind(root: HTMLElement, ctx: TransfersContext, projectId: string | undefined): void {
  root.querySelectorAll<HTMLButtonElement>("[data-link]").forEach((button) => {
    button.addEventListener("click", () => {
      button.disabled = true;
      const id = button.dataset["link"] ?? "";
      downloadUrl(ctx.client, id)
        .then(({ download_url }) => {
          window.open(download_url, "_blank", "noopener");
        })
        .catch((error: unknown) => setMsg(root, describeError(error)))
        .finally(() => {
          button.disabled = false;
        });
    });
  });

  const form = root.querySelector<HTMLFormElement>("[data-upload]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const file = data.get("file");
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    const progress = form.querySelector<HTMLProgressElement>("[data-progress]");
    if (!(file instanceof File) || file.size === 0) {
      setMsg(root, "Choose a non-empty file.");
      return;
    }
    const project = projectId ?? String(data.get("project_id") ?? "").trim();
    if (submit !== null) submit.disabled = true;
    if (progress !== null) {
      progress.hidden = false;
      progress.value = 0;
    }
    const report = (state: UploadProgress): void => {
      if (progress !== null) {
        progress.value = state.totalBytes === 0 ? 0 : Math.round((state.uploadedBytes / state.totalBytes) * 100);
      }
      setMsg(root, uploadPhaseLabel(state));
    };
    void (async () => {
      try {
        const transfer = await createTransfer(ctx.client, {
          project_id: project === "" ? null : project,
          task_id: String(data.get("task_id") ?? "").trim() === "" ? null : String(data.get("task_id") ?? "").trim(),
          recipient_user_id:
            String(data.get("recipient_user_id") ?? "").trim() === ""
              ? null
              : String(data.get("recipient_user_id") ?? "").trim(),
          category: String(data.get("category") ?? "temporary") as Transfer["category"],
          filename: file.name,
          content_type: file.type === "" ? "application/octet-stream" : file.type,
          size_bytes: file.size,
        });
        setMsg(root, `Declared ${transfer.transfer_code} — uploading ${humanBytes(file.size)}…`);
        const done = await uploadTransfer(ctx.client, transfer, file, report);
        setMsg(root, `Uploaded ${done.transfer_code} (${done.status}).`);
        await renderTransfers(root, ctx);
      } catch (error) {
        setMsg(root, describeError(error));
        if (submit !== null) submit.disabled = false;
      }
    })();
  });
}
