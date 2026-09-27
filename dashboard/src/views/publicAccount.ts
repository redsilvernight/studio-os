/**
 * A5 — Pre-login account screens, shared by Web and Desktop (same bundle):
 * inscription → lien envoyé → vérification (nom + mot de passe) → compte
 * actif, and mot de passe oublié → lien envoyé → nouveau mot de passe.
 *
 * Messages are fixed French texts per outcome, never server text. Terminal
 * outcomes (inscriptions fermées, récupération indisponible, lien invalide)
 * get their own screen; recoverable ones (réseau, limite, …) an inline alert
 * that keeps the typed values. Secrets from emailed links stay in closures:
 * never in the DOM, storage, URL or logs.
 */
import type { StudioClient } from "../api";
import {
  createIdempotencyKeyer,
  passwordProblem,
  requestEmailFlow,
  resetPassword,
  verifyEmail,
  type AccountErrorKind,
  type AccountOutcome,
  type EmailFlow,
} from "../publicAccountApi";
import { esc } from "../ui";

export type TerminalKind = "registration_unavailable" | "password_recovery_unavailable" | "invalid_or_expired_token";

export type PublicScreen =
  | { name: "register" }
  | { name: "resend" }
  | { name: "forgot" }
  | { name: "sent"; flow: EmailFlow; email: string }
  | { name: "verify"; token: string }
  | { name: "reset"; token: string }
  | { name: "verified" }
  | { name: "resetDone" }
  | { name: "failure"; kind: TerminalKind; flow: "verify" | "reset" | EmailFlow };

export interface PublicAccountDeps {
  client: StudioClient;
  go(screen: PublicScreen): void;
  toLogin(): void;
}

/** Fixed text for every failure kind (A5 : chaque état d'erreur a son écran). */
export const ACCOUNT_MESSAGES: Record<AccountErrorKind, { title: string; message: string }> = {
  registration_unavailable: {
    title: "Inscriptions fermées",
    message: "Ce serveur n'accepte pas de nouvelles inscriptions. Demandez un compte à l'administrateur de votre studio.",
  },
  password_recovery_unavailable: {
    title: "Récupération indisponible",
    message: "La réinitialisation par email n'est pas activée sur ce serveur. Contactez l'administrateur de votre studio.",
  },
  invalid_or_expired_token: {
    title: "Lien invalide ou expiré",
    message: "Ce lien a déjà servi, a été remplacé par un plus récent ou a expiré. Demandez-en un nouveau.",
  },
  rate_limited: {
    title: "Trop de tentatives",
    message: "Trop de tentatives depuis cette connexion. Patientez une minute puis réessayez.",
  },
  invalid_input: {
    title: "Informations refusées",
    message: "Le serveur a refusé ces informations. Vérifiez l'adresse email, le nom et le mot de passe (12 caractères minimum).",
  },
  conflict: {
    title: "Demande déjà en cours",
    message: "Une demande identique est déjà en cours de traitement. Patientez quelques secondes puis réessayez.",
  },
  network: {
    title: "Serveur injoignable",
    message: "Serveur injoignable. Vérifiez votre connexion et l'adresse du serveur, puis réessayez.",
  },
  server: {
    title: "Erreur du serveur",
    message: "Le serveur n'a pas pu traiter la demande. Réessayez dans quelques instants.",
  },
};

function isTerminal(kind: AccountErrorKind): kind is TerminalKind {
  return kind === "registration_unavailable" || kind === "password_recovery_unavailable" || kind === "invalid_or_expired_token";
}

function box(screen: string, title: string, body: string): string {
  return `<div class="login-box" data-testid="account-screen" data-screen="${screen}">
      <h1>Studi'OS</h1>
      <h2 class="account-title">${esc(title)}</h2>
      ${body}
      <p class="meta login-links"><a href="#" data-action="login">Retour à la connexion</a></p>
    </div>`;
}

const ALERT = `<div class="error" role="alert" data-testid="account-error" hidden></div>`;

const EMAIL_FORMS: Record<EmailFlow, { title: string; intro: string; submit: string }> = {
  register: {
    title: "Créer un compte",
    intro: "Indiquez votre adresse email. Vous choisirez votre nom et votre mot de passe en ouvrant le lien de vérification reçu.",
    submit: "Recevoir le lien",
  },
  resend: {
    title: "Renvoyer le lien de vérification",
    intro: "Indiquez l'adresse utilisée à l'inscription. Les liens envoyés auparavant cesseront de fonctionner.",
    submit: "Renvoyer le lien",
  },
  forgot: {
    title: "Mot de passe oublié",
    intro: "Indiquez l'adresse de votre compte pour recevoir un lien de réinitialisation.",
    submit: "Recevoir le lien",
  },
};

function passwordFields(label: string): string {
  return `<label>${esc(label)}
          <input name="password" type="password" autocomplete="new-password" minlength="12" required />
        </label>
        <label>Confirmer le mot de passe
          <input name="confirmation" type="password" autocomplete="new-password" minlength="12" required />
        </label>
        <p class="meta">12 caractères minimum.</p>`;
}

function screenHtml(screen: PublicScreen): string {
  switch (screen.name) {
    case "register":
    case "resend":
    case "forgot": {
      const form = EMAIL_FORMS[screen.name];
      return box(
        screen.name,
        form.title,
        `<p class="meta">${esc(form.intro)}</p>
      <form data-form="email" novalidate>
        <label>Email
          <input name="email" type="email" autocomplete="email" required />
        </label>
        <button type="submit">${esc(form.submit)}</button>
      </form>
      ${ALERT}
      ${screen.name === "register" ? `<p class="meta login-links"><a href="#" data-go="resend">Lien non reçu ou expiré ?</a></p>` : ""}`,
      );
    }
    case "sent": {
      const text =
        screen.flow === "forgot"
          ? `Si un compte existe pour « ${esc(screen.email)} », un lien de réinitialisation vient d'être envoyé.`
          : `Si une inscription est possible pour « ${esc(screen.email)} », un lien de vérification vient d'être envoyé. Ouvrez-le pour choisir votre nom et votre mot de passe.`;
      return box(
        "sent",
        "Vérifiez votre boîte mail",
        `<p class="state" role="status">${text}</p>
      <p class="meta">Le lien expire après un délai limité. Pensez à vérifier les courriers indésirables.</p>
      <form data-form="again"><button type="submit">Renvoyer le lien</button></form>
      <p class="meta" role="status" data-testid="account-notice" hidden></p>
      ${ALERT}`,
      );
    }
    case "verify":
      return box(
        "verify",
        "Finaliser votre inscription",
        `<p class="meta">Choisissez le nom affiché à votre équipe et votre mot de passe.</p>
      <form data-form="verify" novalidate>
        <label>Nom affiché
          <input name="display_name" type="text" autocomplete="name" maxlength="100" required />
        </label>
        ${passwordFields("Mot de passe")}
        <button type="submit">Activer mon compte</button>
      </form>
      ${ALERT}`,
      );
    case "reset":
      return box(
        "reset",
        "Nouveau mot de passe",
        `<p class="meta">Toutes vos sessions ouvertes seront fermées.</p>
      <form data-form="reset" novalidate>
        ${passwordFields("Nouveau mot de passe")}
        <button type="submit">Enregistrer le mot de passe</button>
      </form>
      ${ALERT}`,
      );
    case "verified":
      return box(
        "verified",
        "Adresse vérifiée",
        `<p class="state" role="status">Votre compte est actif. Connectez-vous : un administrateur doit encore vous donner accès à un projet.</p>
      <form data-form="login"><button type="submit">Se connecter</button></form>`,
      );
    case "resetDone":
      return box(
        "resetDone",
        "Mot de passe modifié",
        `<p class="state" role="status">Toutes vos sessions ont été fermées. Connectez-vous avec le nouveau mot de passe.</p>
      <form data-form="login"><button type="submit">Se connecter</button></form>`,
      );
    case "failure": {
      const text = ACCOUNT_MESSAGES[screen.kind];
      const retry =
        screen.kind === "invalid_or_expired_token"
          ? `<form data-form="retry"><button type="submit">Demander un nouveau lien</button></form>`
          : "";
      return box(
        `failure-${screen.kind}`,
        text.title,
        `<p class="error" role="alert" data-testid="account-failure">${esc(text.message)}</p>${retry}`,
      );
    }
  }
}

function showAlert(container: HTMLElement, kind: AccountErrorKind | null, text?: string): void {
  const alert = container.querySelector<HTMLElement>("[data-testid=account-error]");
  if (alert === null) return;
  alert.textContent = text ?? (kind !== null ? ACCOUNT_MESSAGES[kind].message : "");
  alert.hidden = alert.textContent === "";
}

/** Run a submit with the button busy; terminal outcomes switch screen. */
async function submitting(
  form: HTMLFormElement,
  busyLabel: string,
  run: () => Promise<AccountOutcome>,
): Promise<AccountOutcome> {
  const button = form.querySelector<HTMLButtonElement>("button[type=submit]");
  const label = button?.textContent ?? "";
  if (button !== null) {
    button.disabled = true;
    button.textContent = busyLabel;
  }
  try {
    return await run();
  } finally {
    if (button !== null) {
      button.disabled = false;
      button.textContent = label;
    }
  }
}

function field(form: HTMLFormElement, name: string): string {
  return form.querySelector<HTMLInputElement>(`input[name="${name}"]`)?.value ?? "";
}

export function renderPublicAccount(container: HTMLElement, screen: PublicScreen, deps: PublicAccountDeps): void {
  container.innerHTML = screenHtml(screen);
  const keyer = createIdempotencyKeyer();

  const fail = (kind: AccountErrorKind, flow: "verify" | "reset" | EmailFlow): void => {
    if (isTerminal(kind)) deps.go({ name: "failure", kind, flow });
    else showAlert(container, kind);
  };

  container.querySelectorAll<HTMLAnchorElement>("a[data-action=login]").forEach((link) =>
    link.addEventListener("click", (event) => {
      event.preventDefault();
      deps.toLogin();
    }),
  );
  container.querySelector<HTMLAnchorElement>("a[data-go=resend]")?.addEventListener("click", (event) => {
    event.preventDefault();
    deps.go({ name: "resend" });
  });

  const form = container.querySelector<HTMLFormElement>("form[data-form]");
  if (form === null) return;
  const kind = form.dataset["form"];

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    showAlert(container, null);
    if (kind === "login") {
      deps.toLogin();
      return;
    }
    if (kind === "retry" && screen.name === "failure") {
      deps.go({ name: screen.flow === "reset" || screen.flow === "forgot" ? "forgot" : "resend" });
      return;
    }
    if (kind === "email" && (screen.name === "register" || screen.name === "resend" || screen.name === "forgot")) {
      const flow = screen.name;
      const email = field(form, "email").trim();
      if (!/^[^@\s]+@[^@\s]+$/.test(email) || email.length > 254) {
        showAlert(container, null, "Saisissez une adresse email valide.");
        return;
      }
      void submitting(form, "Envoi…", () => requestEmailFlow(deps.client, flow, email, keyer.keyFor(email))).then((outcome) => {
        if (outcome.ok) deps.go({ name: "sent", flow, email });
        else fail(outcome.kind, flow);
      });
      return;
    }
    if (kind === "again" && screen.name === "sent") {
      const flow: EmailFlow = screen.flow === "forgot" ? "forgot" : "resend";
      void submitting(form, "Envoi…", () => requestEmailFlow(deps.client, flow, screen.email, keyer.keyFor(screen.email))).then(
        (outcome) => {
          if (!outcome.ok) {
            fail(outcome.kind, flow);
            return;
          }
          // A deliberate new request: the next click must not replay this one.
          keyer.reset();
          const notice = container.querySelector<HTMLElement>("[data-testid=account-notice]");
          if (notice !== null) {
            notice.textContent = "Un nouveau lien a été demandé. Seul le plus récent fonctionne.";
            notice.hidden = false;
          }
        },
      );
      return;
    }
    if (kind === "verify" && screen.name === "verify") {
      const displayName = field(form, "display_name").trim();
      if (displayName === "" || displayName.length > 100) {
        showAlert(container, null, "Indiquez un nom affiché (100 caractères maximum).");
        return;
      }
      const password = field(form, "password");
      const problem = passwordProblem(password, field(form, "confirmation"));
      if (problem !== null) {
        showAlert(container, null, problem);
        return;
      }
      void submitting(form, "Activation…", () =>
        verifyEmail(deps.client, { token: screen.token, password, display_name: displayName }),
      ).then((outcome) => {
        if (outcome.ok) deps.go({ name: "verified" });
        else fail(outcome.kind, "verify");
      });
      return;
    }
    if (kind === "reset" && screen.name === "reset") {
      const password = field(form, "password");
      const problem = passwordProblem(password, field(form, "confirmation"));
      if (problem !== null) {
        showAlert(container, null, problem);
        return;
      }
      void submitting(form, "Enregistrement…", () => resetPassword(deps.client, { token: screen.token, new_password: password })).then(
        (outcome) => {
          if (outcome.ok) deps.go({ name: "resetDone" });
          else fail(outcome.kind, "reset");
        },
      );
    }
  });

  container.querySelector<HTMLInputElement>("form input")?.focus();
}
