/**
 * Application shell (DASH-0).
 *
 * Navigation: Dashboard (live in DASH-1) + future sections shown DISABLED —
 * no fake content. No Machines entry (no canonical HTTP read exists).
 * Token bar: manual Bearer entry, memory-only, one-click clear.
 */
import { apiBaseUrl, createApiClient } from "./api";
import { resolveApiUrl } from "./config";
import { clearToken, hasToken, setToken } from "./auth";
import { subscribe } from "./store";
import { renderOverview } from "./views/overview";
import { esc } from "./ui";
import "./styles.css";

const FUTURE_SECTIONS = ["Projects", "Tasks", "Activity", "Agents", "Worklogs", "Decisions", "Transfers"] as const;

function shellHtml(apiUrl: string): string {
  const shownUrl = apiUrl === "" ? "same-origin" : apiUrl;
  const future = FUTURE_SECTIONS.map(
    (name) => `<span class="nav-item disabled" title="Planned after DASH-1">${esc(name)}<span class="badge">DASH-2+</span></span>`,
  ).join("");
  return `
  <header class="topbar">
    <div class="brand">Studi'OS <span class="v0">dashboard v0</span></div>
    <nav class="nav"><span class="nav-item active">Dashboard</span>${future}</nav>
    <div class="api-url" title="API base URL (VITE_STUDIO_API_URL, empty = same-origin)">${esc(shownUrl)}</div>
  </header>
  <div class="tokenbar">
    <label>Machine token
      <input id="token-input" type="password" autocomplete="off" spellcheck="false" placeholder="Bearer token (memory only)" />
    </label>
    <button id="token-set" type="button">Set</button>
    <button id="token-clear" type="button">Clear</button>
    <span id="token-state" class="meta"></span>
    <span class="meta warn" title="The token stays in page memory. It is never stored, never logged, never rendered back. Clearing drops it from this session.">memory-only · never stored</span>
  </div>
  <main id="view"></main>`;
}

function refreshTokenState(): void {
  const state = document.getElementById("token-state");
  const input = document.getElementById("token-input") as HTMLInputElement | null;
  if (state !== null) state.textContent = hasToken() ? "token set (hidden)" : "no token";
  if (input !== null && hasToken()) input.value = "";
}

async function render(): Promise<void> {
  const view = document.getElementById("view");
  if (view === null) return;
  const baseUrl = resolveApiUrl(apiBaseUrl());
  const client = createApiClient(baseUrl);
  await renderOverview(view, { client, baseUrl, authed: hasToken() });
}

export function boot(): void {
  const app = document.getElementById("app");
  if (app === null) throw new Error("#app missing");
  app.innerHTML = shellHtml(resolveApiUrl(apiBaseUrl()));

  const input = document.getElementById("token-input") as HTMLInputElement;
  document.getElementById("token-set")?.addEventListener("click", () => {
    setToken(input.value);
    input.value = "";
    refreshTokenState();
    void render();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      setToken(input.value);
      input.value = "";
      refreshTokenState();
      void render();
    }
  });
  document.getElementById("token-clear")?.addEventListener("click", () => {
    clearToken();
    refreshTokenState();
    void render();
  });
  refreshTokenState();
  subscribe(() => {
    void render();
  });
  window.addEventListener("hashchange", () => {
    void render();
  });
  void render();
}

boot();
