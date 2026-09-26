/**
 * Human dashboard login (DASH-4).
 *
 * Collects email/password, calls POST /auth/token, and stores the returned
 * JWT in the same in-memory token store used for machine tokens.
 */
import { apiBaseUrl } from "./api";
import { observedFetch } from "./apiEvents";
import { setToken } from "./auth";
import { joinUrl } from "./config";
import { getPlatform } from "./platform";
import { esc } from "./ui";
import { originRefusalMessage } from "./views/application";

export type LoginResult = { ok: true } | { ok: false; error: string };

export interface LoginOptions {
  /** Why the user is here (e.g. the session expired). */
  notice?: string;
  /** Desktop only: show the server address and let the user change it. */
  desktop?: boolean;
  onServerChange?: () => void;
  /** A5: show « Créer un compte » / « Mot de passe oublié ? ». */
  onAccountAction?: (action: "register" | "forgot") => void;
}

/** Fixed French messages (A5): the server's text is never shown. */
export const LOGIN_MESSAGES = {
  invalid:
    "Email ou mot de passe incorrect. Si vous venez de vous inscrire, ouvrez d'abord le lien de vérification reçu par email.",
  rateLimited: "Trop de tentatives depuis cette connexion. Patientez une minute puis réessayez.",
  unreachable: "Serveur injoignable. Vérifiez votre connexion et l'adresse du serveur, puis réessayez.",
  failed: "Échec de la connexion. Réessayez dans quelques instants.",
  unexpected: "Réponse inattendue du serveur.",
} as const;

function accountLinksHtml(): string {
  return `<p class="meta login-links" data-testid="login-account-links">
      <a href="#/inscription" data-account-action="register">Créer un compte</a>
      · <a href="#/mot-de-passe-oublie" data-account-action="forgot">Mot de passe oublié ?</a>
    </p>`;
}

/** The Desktop server line: the address in use and an explicit « Modifier ». */
function serverLineHtml(): string {
  const shown = apiBaseUrl() || "Adresse par défaut de cette version";
  return `<div class="login-server" data-testid="login-server">
    <p class="meta">Serveur : <code class="mono" data-testid="login-server-effective">${esc(shown)}</code>
      <button class="ds-btn ds-btn--ghost" type="button" id="login-server-edit">Modifier</button></p>
    <form id="login-server-form" data-testid="login-server-form" hidden novalidate>
      <label>Adresse du serveur
        <input id="login-server-input" type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://studio.exemple.com" />
      </label>
      <button class="ds-btn" type="submit">Enregistrer</button>
    </form>
    <div id="login-server-msg" class="meta" role="status" hidden></div>
  </div>`;
}

function bindServerLine(container: HTMLElement, options: LoginOptions): void {
  const edit = container.querySelector<HTMLButtonElement>("#login-server-edit");
  const form = container.querySelector<HTMLFormElement>("#login-server-form");
  const input = container.querySelector<HTMLInputElement>("#login-server-input");
  const msg = container.querySelector<HTMLDivElement>("#login-server-msg");
  const say = (text: string, isError: boolean): void => {
    if (msg === null) return;
    msg.textContent = text;
    msg.className = isError ? "error" : "meta";
    msg.hidden = false;
  };
  edit?.addEventListener("click", () => {
    if (form !== null) form.hidden = false;
    input?.focus();
  });
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const platform = getPlatform();
    void platform.setServerOrigin(input?.value ?? "").then(async (result) => {
      if (!result.ok) {
        say(originRefusalMessage(result.reason), true);
        return;
      }
      if (!result.state.restart_required) {
        options.onServerChange?.();
        return;
      }
      say("Adresse enregistrée. Redémarrez l'application pour l'utiliser.", false);
      if (msg !== null && !msg.querySelector("button")) {
        const restart = document.createElement("button");
        restart.type = "button";
        restart.className = "ds-btn ds-btn--primary";
        restart.textContent = "Redémarrer maintenant";
        restart.addEventListener("click", () => {
          void platform.restartDesktop().then((started) => {
            if (!started) say("Le redémarrage n'a pas pu être lancé. Fermez puis rouvrez l'application.", true);
          });
        });
        msg.append(" ", restart);
      }
    });
  });
}

export function renderLogin(container: HTMLElement, onLogin: () => void, options: LoginOptions = {}): void {
  container.innerHTML = `
    <div class="login-box">
      <h1>Studi'OS</h1>
      ${options.notice ? `<p class="state" role="status" data-testid="login-notice">${esc(options.notice)}</p>` : ""}
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
      ${options.onAccountAction ? accountLinksHtml() : ""}
      ${options.desktop ? serverLineHtml() : ""}
      <p class="meta">Un jeton machine ? Collez-le dans le bloc compte de la barre latérale après connexion.</p>
    </div>
  `;

  const form = container.querySelector<HTMLFormElement>("#login-form");
  const emailInput = container.querySelector<HTMLInputElement>("#login-email");
  const passwordInput = container.querySelector<HTMLInputElement>("#login-password");
  const errorBox = container.querySelector<HTMLDivElement>("#login-error");
  const submit = form?.querySelector<HTMLButtonElement>("button[type=submit]") ?? null;
  if (options.desktop) bindServerLine(container, options);
  container.querySelectorAll<HTMLAnchorElement>("a[data-account-action]").forEach((link) =>
    link.addEventListener("click", (event) => {
      event.preventDefault();
      options.onAccountAction?.(link.dataset["accountAction"] === "forgot" ? "forgot" : "register");
    }),
  );

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
  let response: Response;
  try {
    response = await observedFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    return { ok: false, error: LOGIN_MESSAGES.unreachable };
  }
  if (!response.ok) {
    // Unverified, disabled and wrong password are one 401 on purpose (A4).
    if (response.status === 401) return { ok: false, error: LOGIN_MESSAGES.invalid };
    if (response.status === 429) return { ok: false, error: LOGIN_MESSAGES.rateLimited };
    return { ok: false, error: LOGIN_MESSAGES.failed };
  }
  const data = (await response.json().catch(() => ({}))) as { access_token?: string };
  if (data.access_token) {
    setToken(data.access_token);
    return { ok: true };
  }
  return { ok: false, error: LOGIN_MESSAGES.unexpected };
}

export function loginOverlayHtml(): string {
  return `<div id="login-overlay" class="login-overlay">${esc("Authentification…")}</div>`;
}
