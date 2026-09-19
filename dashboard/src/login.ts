/**
 * Human dashboard login (DASH-4).
 *
 * Collects email/password, calls POST /auth/token, and stores the returned
 * JWT in the same in-memory token store used for machine tokens.
 */
import { apiBaseUrl } from "./api";
import { setToken } from "./auth";
import { joinUrl } from "./config";
import { esc } from "./ui";

export type LoginResult = { ok: true } | { ok: false; error: string };

export function renderLogin(container: HTMLElement, onLogin: () => void): void {
  container.innerHTML = `
    <div class="login-box">
      <h1>Studi'OS</h1>
      <p class="meta">Connectez-vous avec votre compte Studio OS.</p>
      <form id="login-form">
        <label>Email
          <input id="login-email" type="email" autocomplete="email" required />
        </label>
        <label>Mot de passe
          <input id="login-password" type="password" autocomplete="current-password" required />
        </label>
        <button type="submit">Se connecter</button>
      </form>
      <div id="login-error" class="error" role="alert" hidden></div>
      <p class="meta">Un jeton machine ? Collez-le dans le bloc compte de la barre latérale après connexion.</p>
    </div>
  `;

  const form = container.querySelector<HTMLFormElement>("#login-form");
  const emailInput = container.querySelector<HTMLInputElement>("#login-email");
  const passwordInput = container.querySelector<HTMLInputElement>("#login-password");
  const errorBox = container.querySelector<HTMLDivElement>("#login-error");
  const submit = form?.querySelector<HTMLButtonElement>("button[type=submit]") ?? null;

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (errorBox !== null) errorBox.hidden = true;

    const email = emailInput?.value.trim() ?? "";
    const password = passwordInput?.value ?? "";
    if (submit !== null) {
      submit.disabled = true;
      submit.textContent = "Connexion…";
    }
    const result = await attemptLogin(email, password);
    if (result.ok) {
      onLogin();
    } else {
      if (submit !== null) {
        submit.disabled = false;
        submit.textContent = "Se connecter";
      }
      if (errorBox !== null) {
        errorBox.textContent = result.error;
        errorBox.hidden = false;
      }
    }
  });
}

async function attemptLogin(email: string, password: string): Promise<LoginResult> {
  const base = apiBaseUrl();
  const url = joinUrl(base, "/api/v1/auth/token");
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message =
      typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : "Échec de la connexion";
    return { ok: false, error: message };
  }
  const data = (await response.json()) as { access_token?: string };
  if (data.access_token) {
    setToken(data.access_token);
    return { ok: true };
  }
    return { ok: false, error: "Réponse inattendue" };
}

export function loginOverlayHtml(): string {
  return `<div id="login-overlay" class="login-overlay">${esc("Authentification…")}</div>`;
}
