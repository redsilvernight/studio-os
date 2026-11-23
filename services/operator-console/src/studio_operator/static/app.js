"use strict";

// Console opérateur — squelette minimal séparé (origine, jeton et déploiement
// propres). Vues agrégats uniquement : aucun contenu client, aucun nom de
// projet ni de fichier n'est affiché.

const SESSION_STORAGE_KEY = "studio-operator-token";
const OPERATOR_KEY = "studio-operator-profile";

const root = document.getElementById("root");
const state = { token: sessionStorage.getItem(SESSION_STORAGE_KEY), operator: loadOperator() };

function loadOperator() {
  try {
    return JSON.parse(sessionStorage.getItem(OPERATOR_KEY) || "null");
  } catch {
    return null;
  }
}

// -- DOM helpers ------------------------------------------------------------

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

// -- formatting -------------------------------------------------------------

const GIB = 1024 ** 3;

function slash(n) {
  return n.toLocaleString("fr-FR").replace(/\u202f/g, " ");
}

function bytes(value) {
  if (value === null || value === undefined) return "—";
  if (value >= GIB) {
    return slash(Math.round((value / GIB) * 10) / 10) + " Gio";
  }
  const mib = value / 1024 ** 2;
  return slash(Math.round(mib * 10) / 10) + " Mio";
}

function storageCell(storage) {
  const used = bytes(storage.used_bytes);
  return storage.quota_bytes ? `${used} / ${bytes(storage.quota_bytes)}` : used;
}

function percent(value) {
  return value === null || value === undefined ? "—" : `${slash(value)} %`;
}

function compact(value) {
  if (value === null || value === undefined) return "—";
  if (value >= 1e6) return `${slash(Math.round(value / 1e5) / 10)} M`;
  if (value >= 1e3) return `${slash(Math.round(value / 1e2) / 10)} k`;
  return slash(value);
}

function money(cost) {
  const symbol = { EUR: "€", USD: "$", GBP: "£" }[cost.currency];
  return symbol ? `${slash(Number(cost.amount))} ${symbol}` : `${cost.amount} ${cost.currency}`;
}

function dateLabel(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
}

function sinceLabel(iso) {
  if (!iso) return "—";
  const days = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86400000));
  if (days === 0) return "aujourd’hui";
  return `il y a ${days} j`;
}

const PLAN_LABELS = { free: "Gratuit", pro: "Pro" };
const planLabel = (plan) => PLAN_LABELS[plan] || plan;

function statusPill(status) {
  if (status === "suspended") return h("span", { class: "pill wa", text: "Suspendu" });
  if (status === "active") return h("span", { class: "pill ok", text: "Actif" });
  return h("span", { class: "pill", text: status });
}

function shortId(id) {
  return `${String(id).slice(0, 8)}…`;
}

// -- API --------------------------------------------------------------------

class ApiError extends Error {
  constructor(status, body) {
    const detail = body && body.detail;
    super((detail && detail.message) || "Erreur inattendue.");
    this.status = status;
    this.code = detail && detail.error_code;
    this.detail = detail || {};
  }
}

async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`/api/v1${path}`, Object.assign({}, options, { headers }));
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body);
  return body;
}

function sessionExpired() {
  state.token = null;
  state.operator = null;
  sessionStorage.removeItem(SESSION_STORAGE_KEY);
  sessionStorage.removeItem(OPERATOR_KEY);
  renderLogin("Votre session a expiré. Saisissez un nouveau code.");
}

// -- shell ------------------------------------------------------------------

const NAV = [
  ["dashboard", "Tableau de bord", "#/dashboard"],
  ["studios", "Studios", "#/studios"],
  ["usage", "Usage", "#/usage"],
  ["billing", "Facturation", "#/billing"],
  ["suspensions", "Suspensions", "#/suspensions"],
  ["break-glass", "Demandes break-glass", "#/break-glass"],
];

function shell(active, content) {
  const main = h("main", null, content);
  const initials = state.operator ? state.operator.display_name.slice(0, 2).toUpperCase() : "OP";
  return h(
    "div",
    { class: "app" },
    h(
      "aside",
      { class: "side" },
      h("div", { class: "logo" }, h("i"), "Studi’OS Opérateur"),
      NAV.map(([key, label, href]) =>
        h("a", { class: `nav${key === active ? " on" : ""}`, href }, label)
      ),
      h("div", { class: "foot" }, state.operator ? state.operator.email : ""),
    ),
    h(
      "div",
      null,
      h(
        "div",
        { class: "content" },
        h(
          "div",
          { class: "topbar" },
          h("div"),
          h(
            "div",
            { class: "who" },
            h("span", { class: "avatar", text: initials }),
            state.operator
              ? h(
                  "span",
                  null,
                  state.operator.display_name,
                  h("span", { class: "muted" }, " · MFA vérifiée · 15 min"),
                )
              : null,
            h(
              "button",
              {
                class: "btn g",
                type: "button",
                onclick: async () => {
                  try {
                    await api("/auth/logout", { method: "POST" });
                  } catch {
                    /* stateless */
                  }
                  sessionExpired();
                },
              },
              "Quitter",
            ),
          ),
        ),
        h(
          "div",
          { class: "banner" },
          h("span", { "aria-hidden": "true" }, "🛈"),
          h(
            "span",
            null,
            "Cette console ne montre jamais le contenu des studios : seulement des mesures, ",
            "des statuts et des journaux sans contenu.",
          ),
        ),
        main,
      ),
    ),
  );
}

function mount(active, content) {
  clear(root);
  root.append(shell(active, content));
}

function page(title, subtitle, ...body) {
  return [
    h("h1", { class: "pt", text: title }),
    subtitle ? h("p", { class: "sub" }, subtitle) : null,
    body,
  ];
}

function loadingCard() {
  return h(
    "div",
    { class: "card", "aria-busy": "true", "aria-label": "Chargement" },
    h("div", { class: "sk tall" }),
    h("div", { class: "sk" }),
    h("div", { class: "sk" }),
    h("div", { class: "sk" }),
  );
}

function errorCard(title, message, retry) {
  return h(
    "div",
    { class: "card" },
    h("h3", { class: "h3", text: title }),
    h("p", { class: "muted", text: message }),
    h(
      "div",
      { class: "btns" },
      h("button", { class: "btn p", type: "button", onclick: retry }, "Réessayer"),
    ),
  );
}

function emptyState(title, message) {
  return h(
    "div",
    { class: "card empty" },
    h("h3", { class: "h3", text: title }),
    h("p", { text: message }),
  );
}

function kpi(label, value, note) {
  return h(
    "div",
    { class: "kpi" },
    h("div", { class: "kpil", text: label }),
    h("div", { class: "v", text: value }),
    note ? h("div", { class: "n" }, note) : null,
  );
}

// -- connexion (C0) ---------------------------------------------------------

function renderLogin(message) {
  clear(root);
  const email = h("input", {
    class: "fi",
    type: "email",
    name: "email",
    autocomplete: "username",
    required: true,
    value: state.operator ? state.operator.email : "",
  });
  const password = h("input", {
    class: "fi",
    type: "password",
    name: "password",
    autocomplete: "current-password",
    required: true,
  });
  const code = h("input", {
    class: "fi",
    type: "text",
    name: "code",
    inputmode: "numeric",
    autocomplete: "one-time-code",
    placeholder: "482 913",
    maxlength: "8",
    required: true,
  });
  const feedback = h("p", { class: "err", role: "alert" });
  if (message) feedback.textContent = message;

  const submit = h("button", { class: "btn p", type: "submit" }, "Vérifier");

  const form = h(
    "form",
    {
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault();
        feedback.textContent = "";
        const value = code.value.replace(/\s/g, "");
        if (!/^\d{6}$/.test(value)) {
          code.classList.add("bad");
          feedback.textContent = "Saisissez le code à 6 chiffres de votre application d’authentification.";
          return;
        }
        code.classList.remove("bad");
        submit.disabled = true;
        submit.textContent = "Vérification…";
        try {
          const session = await api("/auth/mfa", {
            method: "POST",
            body: JSON.stringify({
              email: email.value.trim(),
              password: password.value,
              code: value,
            }),
          });
          state.token = session.access_token;
          state.operator = session.operator;
          sessionStorage.setItem(SESSION_STORAGE_KEY, session.access_token);
          sessionStorage.setItem(OPERATOR_KEY, JSON.stringify(session.operator));
          location.hash = "#/dashboard";
          route();
        } catch (error) {
          submit.disabled = false;
          submit.textContent = "Vérifier";
          if (error.code === "mfa_locked") {
            feedback.textContent = error.message;
          } else if (error.code === "mfa_invalid" && error.detail.attempts_remaining) {
            code.classList.add("bad");
            feedback.textContent = `Code incorrect. Il vous reste ${error.detail.attempts_remaining} essai(s) avant un verrouillage.`;
          } else if (error.code === "operator_not_allowed") {
            feedback.textContent =
              "Accès refusé. Ce compte n’est pas autorisé à utiliser la console, ou la MFA n’est pas configurée. Aucun détail n’est donné par sécurité.";
          } else {
            feedback.textContent = error.message;
          }
        }
      },
    },
    h("label", { class: "fld" }, h("span", { text: "Adresse professionnelle" }), email),
    h("label", { class: "fld" }, h("span", { text: "Mot de passe" }), password),
    h(
      "label",
      { class: "fld" },
      h("span", { text: "Code à 6 chiffres" }),
      code,
      h(
        "div",
        { class: "hint" },
        "La MFA est obligatoire. Un compte non listé ou sans MFA configurée est refusé : ",
        "contactez l’administrateur de la console.",
      ),
    ),
    feedback,
    h(
      "div",
      { class: "btns" },
      submit,
      h(
        "button",
        { class: "btn g", type: "button", onclick: () => renderEnrollment() },
        "Première connexion : configurer la MFA",
      ),
    ),
  );

  root.append(
    h(
      "div",
      { class: "app" },
      h(
        "main",
        { class: "main c" },
        h(
          "div",
          { class: "card login" },
          h("div", { class: "logo" }, h("i"), "Studi’OS"),
          h("h1", { class: "pt", text: "Console opérateur" }),
          h(
            "p",
            { class: "sub" },
            "Saisissez le code de votre application d’authentification.",
          ),
          form,
        ),
      ),
    ),
  );
  email.focus();
}

function soloCard(title, subtitle, body) {
  return h(
    "div",
    { class: "app" },
    h(
      "main",
      { class: "main c" },
      h(
        "div",
        { class: "card login" },
        h("div", { class: "logo" }, h("i"), "Studi’OS"),
        h("h1", { class: "pt", text: title }),
        h("p", { class: "sub", text: subtitle }),
        body,
      ),
    ),
  );
}

function enrollmentQrCard(data, email) {
  clear(root);
  const code = h("input", {
    class: "fi",
    type: "text",
    inputmode: "numeric",
    autocomplete: "one-time-code",
    placeholder: "482 913",
    maxlength: "8",
    required: true,
  });
  const feedback = h("p", { class: "err", role: "alert" });
  const submit = h("button", { class: "btn p", type: "submit" }, "Activer");
  const form = h(
    "form",
    {
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault();
        feedback.textContent = "";
        submit.disabled = true;
        try {
          await api("/auth/enrollment/confirm", {
            method: "POST",
            body: JSON.stringify({ email, code: code.value.replace(/\s/g, "") }),
          });
          renderLogin("MFA activée. Connectez-vous avec votre mot de passe et un nouveau code.");
        } catch (error) {
          submit.disabled = false;
          feedback.textContent =
            error.code === "enrollment_expired"
              ? "L’enrôlement a expiré. Recommencez la configuration."
              : error.message;
        }
      },
    },
    h(
      "div",
      { class: "qr" },
      h("img", {
        src: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(data.qr_svg),
        alt: "Code QR d’enrôlement MFA",
        width: 200,
        height: 200,
      }),
    ),
    h(
      "p",
      { class: "muted" },
      "Scannez ce code avec votre application d’authentification, ou saisissez le secret : ",
      h("span", { class: "mono", text: data.secret }),
    ),
    h(
      "label",
      { class: "fld" },
      h("span", { text: "Code à 6 chiffres" }),
      code,
      h("div", { class: "hint" }, `Valable ${Math.round(data.expires_in / 60)} minutes.`),
    ),
    feedback,
    h(
      "div",
      { class: "btns" },
      submit,
      h("button", { class: "btn g", type: "button", onclick: () => renderLogin() }, "Retour"),
    ),
  );
  root.append(
    soloCard(
      "Activer la MFA",
      "La MFA est obligatoire. Scannez ce code avec votre application d’authentification.",
      form,
    ),
  );
  code.focus();
}

function renderEnrollment() {
  clear(root);
  const email = h("input", {
    class: "fi",
    type: "email",
    autocomplete: "username",
    required: true,
    value: state.operator ? state.operator.email : "",
  });
  const password = h("input", {
    class: "fi",
    type: "password",
    autocomplete: "current-password",
    required: true,
  });
  const feedback = h("p", { class: "err", role: "alert" });
  const submit = h("button", { class: "btn p", type: "submit" }, "Continuer");
  const form = h(
    "form",
    {
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault();
        feedback.textContent = "";
        submit.disabled = true;
        try {
          const data = await api("/auth/enrollment", {
            method: "POST",
            body: JSON.stringify({ email: email.value.trim(), password: password.value }),
          });
          enrollmentQrCard(data, email.value.trim());
        } catch (error) {
          submit.disabled = false;
          feedback.textContent = error.message;
        }
      },
    },
    h("label", { class: "fld" }, h("span", { text: "Adresse professionnelle" }), email),
    h("label", { class: "fld" }, h("span", { text: "Mot de passe" }), password),
    feedback,
    h(
      "div",
      { class: "btns" },
      submit,
      h("button", { class: "btn g", type: "button", onclick: () => renderLogin() }, "Retour"),
    ),
  );
  root.append(
    soloCard(
      "Configurer la MFA",
      "Confirmez votre mot de passe : le code QR n’est remis qu’à l’opérateur listé.",
      form,
    ),
  );
  email.focus();
}

// -- tableau de bord (C1) ---------------------------------------------------

function servicePill(svc) {
  if (svc.state === "ok") return h("span", { class: "pill ok", text: "Opérationnel" });
  if (svc.state === "degraded") return h("span", { class: "pill wa", text: "Dégradé" });
  return h("span", { class: "pill in", text: "Non disponible" });
}

async function viewDashboard() {
  mount("dashboard", page("Tableau de bord", "", loadingCard()));
  try {
    const data = await api("/dashboard");
    if (!data.has_measures && data.active_studios === 0) {
      mount(
        "dashboard",
        page(
          "Tableau de bord",
          "",
          emptyState(
            "Aucune mesure collectée",
            "Les mesures de la phase M apparaissent ici dès que l’instrumentation est active.",
          ),
        ),
      );
      return;
    }
    const content = page(
      "Tableau de bord",
      h(
        "span",
        null,
        `État du service au ${dateLabel(data.generated_at)}. `,
        h(
          "button",
          { class: "btn g", type: "button", onclick: viewDashboard },
          "Actualiser",
        ),
      ),
      data.alerts.map((alert) =>
        h("div", { class: "banner warn" }, h("b", { text: `${alert.title}. ` }), alert.detail)
      ),
      h(
        "div",
        { class: "kpis" },
        kpi("Studios actifs (7 j)", slash(data.active_studios), `+${data.new_studios_7d} cette semaine`),
        kpi("Stockage total", bytes(data.storage.used_bytes), `${percent(data.storage.percent)} de la capacité`),
        kpi(
          "Erreurs 5xx (24 h)",
          data.error_rate_5xx_24h === null ? "—" : `${slash(data.error_rate_5xx_24h)} %`,
          data.error_rate_5xx_24h === null
            ? "non mesuré"
            : data.error_rate_5xx_24h >= 1
              ? "À surveiller"
              : "Normal",
        ),
        kpi(
          "Impayés en grâce",
          slash(data.unpaid_in_grace),
          "À suivre",
        ),
      ),
      h("h3", { class: "h3", text: "Services" }),
      h(
        "div",
        { class: "card" },
        data.services.map((svc) =>
          h(
            "div",
            { class: "svc" },
            h("b", { text: svc.label }),
            servicePill(svc),
            h("span", { class: "muted", text: svc.detail }),
          )
        ),
      ),
    );
    mount("dashboard", content);
  } catch (error) {
    if (error.status === 401) return sessionExpired();

    mount(
      "dashboard",
      page(
        "Tableau de bord",
        "",
        errorCard("Impossible de charger cette page", "Les mesures n’ont pas pu être lues.", viewDashboard),
      ),
    );
  }
}

// -- studios (C2) -----------------------------------------------------------

function studioRow(studio, extra) {
  return h(
    "tr",
    null,
    h(
      "td",
      null,
      h("div", { text: studio.name }),
      h("div", { class: "mono", text: shortId(studio.id) }),
      extra ? h("div", { class: "muted", text: extra }) : null,
    ),
    h("td", { text: planLabel(studio.plan) }),
    h(
      "td",
      null,
      statusPill(studio.status),
      studio.status === "suspended" && studio.suspension_reason
        ? h("div", { class: "muted", text: studio.suspension_reason })
        : null,
    ),
    h("td", { text: storageCell(studio.storage) }),
    h("td", {
      text: studio.members_limit === null ? String(studio.members) : `${studio.members} / ${studio.members_limit}`,
    }),
    h("td", null, h("a", { class: "btn", href: `#/studios/${studio.id}` }, "Ouvrir")),
  );
}

function studioTable(rows) {
  return h(
    "div",
    { class: "card" },
    h(
      "table",
      { class: "tbl" },
      h(
        "thead",
        null,
        h(
          "tr",
          null,
          h("th", { text: "Studio" }),
          h("th", { text: "Plan" }),
          h("th", { text: "Statut" }),
          h("th", { text: "Stockage" }),
          h("th", { text: "Membres" }),
          h("th"),
        ),
      ),
      h("tbody", null, rows),
    ),
  );
}

async function viewStudios(query) {
  mount("studios", page("Studios", "", loadingCard()));
  try {
    const data = await api(`/studios?q=${encodeURIComponent(query || "")}`);
    const search = h("input", {
      class: "fi",
      type: "search",
      placeholder: "Rechercher un studio…",
      value: query || "",
    });
    search.addEventListener("change", () => {
      location.hash = `#/studios${search.value ? `?q=${encodeURIComponent(search.value)}` : ""}`;
      route();
    });
    const nearLimit = data.studios.filter(
      (studio) => studio.storage.percent !== null && studio.storage.percent >= 90
    );
    const body =
      data.studios.length === 0
        ? emptyState(
            "Aucun studio ne correspond",
            "Vérifiez l’orthographe ou cherchez par adresse du propriétaire.",
          )
        : studioTable(data.studios.map((studio) => studioRow(studio)));
    mount(
      "studios",
      page(
        "Studios",
        `${data.total} studios.`,
        h("div", { style: "max-width:360px;margin-bottom:14px" }, search),
        nearLimit.length
          ? h(
              "div",
              { class: "banner warn" },
              `${nearLimit.length} studio(s) proches d’un plafond de stockage (90 % ou plus).`,
            )
          : null,
        body,
      ),
    );
  } catch (error) {
    if (error.status === 401) return sessionExpired();
    mount(
      "studios",
      page("Studios", "", errorCard("Impossible de charger cette page", "La liste des studios n’a pas pu être lue.", () => viewStudios(query))),
    );
  }
}

function suspendDialog(studio) {
  const reason = h("textarea", { class: "fi", name: "reason", required: true, maxlength: "500" });
  const feedback = h("p", { class: "err", role: "alert" });
  const submit = h("button", { class: "btn d", type: "submit" }, "Suspendre");
  const dialog = h(
    "dialog",
    { "aria-labelledby": "suspend-title" },
    h("h3", { class: "h3", id: "suspend-title", text: `Suspendre ${studio.name} ?` }),
    h(
      "p",
      { class: "muted" },
      `Le studio passe en lecture seule pour ses ${studio.members} membres ; export permis. `,
      "Le propriétaire voit le motif.",
    ),
    h(
      "form",
      {
        onsubmit: async (event) => {
          event.preventDefault();
          if (reason.value.trim().length < 3) {
            feedback.textContent = "Un motif d’au moins 3 caractères est obligatoire.";
            return;
          }
          submit.disabled = true;
          try {
            await api(`/studios/${studio.id}/suspension`, {
              method: "POST",
              body: JSON.stringify({ reason: reason.value.trim() }),
            });
            dialog.close();
            route();
          } catch (error) {
            submit.disabled = false;
            feedback.textContent = error.message;
          }
        },
      },
      h("label", { class: "fld" }, h("span", { text: "Motif (visible du client)" }), reason),
      feedback,
      h(
        "div",
        { class: "dialog-actions" },
        h("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Annuler"),
        submit,
      ),
    ),
  );
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
  reason.focus();
}

async function viewStudio(id) {
  mount("studios", page("Studio", "", loadingCard()));
  try {
    const data = await api(`/studios/${id}`);
    const studio = data.studio;
    const totals = data.usage;
    const costs = totals.costs.length
      ? totals.costs.map(money).join(" · ")
      : "—";
    mount(
      "studios",
      page(
        studio.name,
        `Créé le ${dateLabel(studio.created_at)} · propriétaire : ${studio.owner_email || "—"}`,
        studio.status === "suspended"
          ? h(
              "div",
              { class: "banner warn" },
              h("b", { text: "Studio suspendu. " }),
              studio.suspension_reason || "Motif non renseigné.",
            )
          : null,
        h(
          "div",
          { class: "kpis" },
          kpi("Plan", planLabel(studio.plan), null),
          kpi("Stockage", storageCell(studio.storage), percent(studio.storage.percent)),
          kpi(
            "Membres",
            studio.members_limit === null ? String(studio.members) : `${studio.members} / ${studio.members_limit}`,
            null,
          ),
          kpi("Jetons (30 j)", slash((totals.tokens_in || 0) + (totals.tokens_out || 0)), "mesure phase M"),
        ),
        h("h3", { class: "h3", text: "Actions" }),
        h(
          "div",
          { class: "card" },
          h(
            "div",
            { class: "btns" },
            studio.status === "suspended"
              ? h("span", { class: "pill wa", text: "Studio suspendu" })
              : h(
                  "button",
                  { class: "btn d", type: "button", onclick: () => suspendDialog(studio) },
                  "Suspendre…",
                ),
            h(
              "button",
              { class: "btn", type: "button", onclick: () => breakGlassDialog(studio.id) },
              "Demander un accès d’exception",
            ),
          ),
          h(
            "p",
            { class: "muted" },
            "Aucun accès au contenu : une demande d’accès d’exception passe par l’accord du propriétaire (C6).",
          ),
          h(
            "p",
            { class: "muted" },
            `Coût mesuré : ${costs} · durée ${totals.duration_seconds === null ? "—" : `${slash(totals.duration_seconds)} s`}`,
          ),
        ),
      ),
    );
  } catch (error) {
    if (error.status === 401) return sessionExpired();
    const notFound = error.status === 404;
    mount(
      "studios",
      page(
        "Studio",
        "",
        errorCard(
          notFound ? "Studio introuvable" : "Impossible de charger cette page",
          notFound ? "Ce studio n’existe pas ou a été supprimé." : "La fiche n’a pas pu être lue.",
          () => viewStudio(id),
        ),
      ),
    );
  }
}

// -- usage (C3) -------------------------------------------------------------

async function viewUsage() {
  mount("usage", page("Usage", "", loadingCard()));
  try {
    const data = await api("/usage?days=30");
    const totals = data.totals;
    const costs = totals.costs.length ? totals.costs.map(money).join(" · ") : "—";
    if (!data.has_measures) {
      mount(
        "usage",
        page(
          "Usage",
          "30 derniers jours.",
          emptyState(
            "Aucune consommation sur la période",
            "Élargissez la période ou vérifiez que l’instrumentation est active.",
          ),
        ),
      );
      return;
    }
    mount(
      "usage",
      page(
        "Usage",
        "30 derniers jours.",
        data.over_quota.length
          ? h(
              "div",
              { class: "banner warn" },
              `${data.over_quota.length} studio(s) au-dessus de 90 % de leur stockage : ils verront `,
              "bientôt un refus d’envoi.",
            )
          : null,
        h(
          "div",
          { class: "kpis" },
          kpi(
            "Stockage de la plateforme",
            bytes(data.storage.used_bytes),
            `${percent(data.storage.percent)} de ${bytes(data.storage.quota_bytes)}`,
          ),
          kpi("Envois (volume)", "—", "non mesuré"),
          kpi(
            "Appels API",
            compact(data.api_calls),
            data.api_calls === null ? "non mesuré" : "sur 30 jours",
          ),
        ),
        h("h3", { class: "h3", text: "Mesures phase M" }),
        h(
          "div",
          { class: "kpis" },
          kpi("Jetons entrée", totals.tokens_in === null ? "—" : slash(totals.tokens_in), null),
          kpi("Jetons sortie", totals.tokens_out === null ? "—" : slash(totals.tokens_out), null),
          kpi("Durée mesurée", totals.duration_seconds === null ? "—" : `${slash(totals.duration_seconds)} s`, null),
          kpi("Coût mesuré", costs, null),
        ),
        h("h3", { class: "h3", text: "Top studios" }),
        data.top_studios.length
          ? studioTable(
              data.top_studios.map((studio) => {
                const tokens = (studio.usage.tokens_in || 0) + (studio.usage.tokens_out || 0);
                return studioRow(studio, `${slash(tokens)} jetons · ${percent(studio.storage.percent)} stockage`);
              }),
            )
          : emptyState("Aucun studio", "Aucun studio n’est encore enregistré."),
      ),
    );
  } catch (error) {
    if (error.status === 401) return sessionExpired();
    mount(
      "usage",
      page("Usage", "", errorCard("Impossible de charger cette page", "Les compteurs n’ont pas pu être lus.", viewUsage)),
    );
  }
}

// -- facturation (C4) -------------------------------------------------------

function billingTable(rows, dateKey, dateHeader) {
  return h(
    "table",
    { class: "table" },
    h("thead", {}, h("tr", {}, h("th", { text: "Studio" }), h("th", { text: "Formule" }), h("th", { text: dateHeader }))),
    h(
      "tbody",
      {},
      ...rows.map((row) =>
        h(
          "tr",
          {},
          h("td", { text: row.name }),
          h("td", { text: row.plan }),
          h("td", { text: dateLabel(row[dateKey]) }),
        ),
      ),
    ),
  );
}

async function viewBilling() {
  mount("billing", page("Facturation", "", loadingCard()));
  try {
    const data = await api("/billing");
    const section = (title, rows, dateKey, dateHeader, empty) =>
      h(
        "div",
        { class: "card" },
        h("h3", { class: "h3", text: title }),
        rows.length ? billingTable(rows, dateKey, dateHeader) : h("p", { class: "muted", text: empty }),
      );
    mount(
      "billing",
      page(
        "Facturation",
        "Source : événements Stripe signés. Aucun numéro de carte : Stripe seul le détient.",
        h(
          "div",
          { class: "kpis" },
          kpi("Studios Pro", slash(data.counts.pro), `${slash(data.counts.free)} gratuits`),
          kpi("Impayés en grâce", slash(data.counts.past_due), `Délai de grâce : ${data.grace_days} j`),
          kpi("Essais en cours", slash(data.counts.trialing), "Pro, 14 jours"),
        ),
        section("Impayés", data.past_due, "grace_ends_at", "Fin de la grâce", "Aucun impayé en cours."),
        section("Essais", data.trials, "trial_ends_at", "Fin de l’essai", "Aucun essai en cours."),
        h(
          "div",
          { class: "card" },
          h("h3", { class: "h3", text: "Derniers événements webhook" }),
          data.recent_events.length
            ? h(
                "div",
                {},
                ...data.recent_events.map((event) =>
                  h("p", { class: "muted", text: `${dateLabel(event.processed_at)} · ${event.type}` }),
                ),
              )
            : h("p", { class: "muted", text: "Aucun événement reçu pour l’instant." }),
        ),
      ),
    );
  } catch (error) {
    if (error.status === 401) return sessionExpired();
    mount(
      "billing",
      page("Facturation", "", errorCard("Impossible de charger cette page", "L’état de la facturation n’a pas pu être lu.", viewBilling)),
    );
  }
}

// -- suspensions ------------------------------------------------------------

async function viewSuspensions() {
  mount("suspensions", page("Suspensions", "", loadingCard()));
  try {
    const data = await api("/suspensions");
    if (data.studios.length === 0) {
      mount(
        "suspensions",
        page(
          "Suspensions",
          "",
          emptyState("Aucun studio suspendu", "C’est l’état normal : aucun studio n’est en lecture seule."),
        ),
      );
      return;
    }
    mount(
      "suspensions",
      page(
        "Suspensions",
        `${data.total} studio(s) suspendu(s).`,
        h(
          "div",
          { class: "card" },
          h(
            "table",
            { class: "tbl" },
            h(
              "thead",
              null,
              h(
                "tr",
                null,
                h("th", { text: "Studio" }),
                h("th", { text: "Plan" }),
                h("th", { text: "Statut" }),
                h("th", { text: "Motif" }),
                h("th", { text: "Depuis" }),
                h("th"),
              ),
            ),
            h(
              "tbody",
              null,
              data.studios.map((studio) =>
                h(
                  "tr",
                  null,
                  h(
                    "td",
                    null,
                    h("div", { text: studio.name }),
                    h("div", { class: "mono", text: shortId(studio.id) }),
                  ),
                  h("td", { text: planLabel(studio.plan) }),
                  h("td", null, statusPill("suspended")),
                  h("td", { class: "muted", text: studio.suspension_reason || "—" }),
                  h("td", { text: sinceLabel(studio.since) }),
                  h(
                    "td",
                    null,
                    h(
                      "button",
                      {
                        class: "btn",
                        type: "button",
                        onclick: async (event) => {
                          event.currentTarget.disabled = true;
                          try {
                            await api(`/studios/${studio.id}/suspension`, { method: "DELETE" });
                            viewSuspensions();
                          } catch (error) {
                            event.currentTarget.disabled = false;
                            alert(error.message);
                          }
                        },
                      },
                      "Réactiver",
                    ),
                  ),
                )
              ),
            ),
          ),
        ),
      ),
    );
  } catch (error) {
    if (error.status === 401) return sessionExpired();
    mount(
      "suspensions",
      page("Suspensions", "", errorCard("Impossible de charger cette page", "La liste n’a pas pu être lue.", viewSuspensions)),
    );
  }
}

// -- break-glass (C5) -------------------------------------------------------

const BREAK_GLASS_SCOPES = {
  metadata: "Métadonnées (état des services, sans contenu)",
  support: "Support (journaux techniques, sans contenu)",
};

const BREAK_GLASS_STATUSES = {
  requested: ["En attente", "wa"],
  approved: ["Accordé", "ok"],
  denied: ["Refusé", "nd"],
  expired: ["Expiré", "nd"],
  revoked: ["Révoqué", "nd"],
};

function breakGlassPill(status) {
  const [label, kind] = BREAK_GLASS_STATUSES[status] || [status, "nd"];
  return h("span", { class: `pill ${kind}`, text: label });
}

function scopedLabel(scope) {
  return BREAK_GLASS_SCOPES[scope] || scope;
}

async function breakGlassDialog(studioId) {
  const select = h("select", { class: "fi", name: "studio", required: true });
  const reason = h("textarea", { class: "fi", name: "reason", required: true, maxlength: "2000" });
  const scope = h(
    "select",
    { class: "fi", name: "scope" },
    Object.entries(BREAK_GLASS_SCOPES).map(([value, label]) =>
      h("option", { value, text: label }),
    ),
  );
  const feedback = h("p", { class: "err", role: "alert" });
  const submit = h("button", { class: "btn p", type: "submit" }, "Envoyer la demande");
  const dialog = h(
    "dialog",
    { "aria-labelledby": "break-glass-title" },
    h("h3", { class: "h3", id: "break-glass-title", text: "Demander un accès d’exception" }),
    h(
      "p",
      { class: "muted" },
      "La demande n’ouvre rien : le propriétaire du studio doit l’accepter, pour 24 heures au maximum. ",
      "Aucun contenu client n’est lisible par la console.",
    ),
    h(
      "form",
      {
        onsubmit: async (event) => {
          event.preventDefault();
          const text = reason.value.trim();
          if (!select.value) {
            feedback.textContent = "Choisissez un studio.";
            return;
          }
          if (text.length < 3) {
            feedback.textContent = "Un motif d’au moins 3 caractères est obligatoire.";
            return;
          }
          submit.disabled = true;
          try {
            await api("/break-glass", {
              method: "POST",
              body: JSON.stringify({
                studio_id: select.value,
                reason: text,
                scope: scope.value,
              }),
            });
            dialog.close();
            viewBreakGlass();
          } catch (error) {
            submit.disabled = false;
            feedback.textContent = error.message;
          }
        },
      },
      h("label", { class: "fld" }, h("span", { text: "Studio" }), select),
      h("label", { class: "fld" }, h("span", { text: "Motif (visible du client)" }), reason),
      h("label", { class: "fld" }, h("span", { text: "Portée" }), scope),
      feedback,
      h(
        "div",
        { class: "dialog-actions" },
        h("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Annuler"),
        submit,
      ),
    ),
  );
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
  try {
    const data = await api("/studios?limit=200");
    for (const studio of data.studios) {
      select.append(h("option", { value: studio.id, text: `${studio.name} · ${planLabel(studio.plan)}` }));
    }
    if (studioId) select.value = studioId;
  } catch (error) {
    feedback.textContent = error.message;
  }
  reason.focus();
}

async function viewBreakGlass() {
  mount("break-glass", page("Demandes break-glass", "", loadingCard()));
  try {
    const data = await api("/break-glass");
    const newButton = h(
      "button",
      { class: "btn p", type: "button", onclick: () => breakGlassDialog() },
      "Nouvelle demande",
    );
    if (data.requests.length === 0) {
      mount(
        "break-glass",
        page(
          "Demandes break-glass",
          "Aucun accès sans accord du propriétaire.",
          h(
            "div",
            { class: "card" },
            h("h3", { class: "h3", text: "Aucune demande" }),
            h(
              "p",
              { class: "muted" },
              "Une demande non traitée expire seule au bout de 24 heures.",
            ),
            h("div", { class: "btns" }, newButton),
          ),
        ),
      );
      return;
    }
    mount(
      "break-glass",
      page(
        "Demandes break-glass",
        `${data.total} demande(s). Aucun accès sans accord du propriétaire.`,
        h(
          "div",
          { class: "btns" },
          newButton,
        ),
        h(
          "div",
          { class: "card" },
          h(
            "table",
            { class: "tbl" },
            h(
              "thead",
              null,
              h(
                "tr",
                null,
                h("th", { text: "Studio" }),
                h("th", { text: "Motif" }),
                h("th", { text: "Portée" }),
                h("th", { text: "Statut" }),
                h("th", { text: "Demandée" }),
                h("th", { text: "Décision" }),
              ),
            ),
            h(
              "tbody",
              null,
              data.requests.map((item) =>
                h(
                  "tr",
                  null,
                  h(
                    "td",
                    null,
                    h("div", { text: item.studio_name || shortId(item.studio_id) }),
                    h("div", { class: "mono", text: item.operator_ref }),
                  ),
                  h("td", { class: "muted", text: item.reason }),
                  h("td", { class: "muted", text: scopedLabel(item.scope) }),
                  h("td", null, breakGlassPill(item.status)),
                  h("td", { text: dateLabel(item.requested_at) }),
                  h(
                    "td",
                    { class: "muted", text: item.decided_at ? dateLabel(item.decided_at) : "—" },
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  } catch (error) {
    if (error.status === 401) return sessionExpired();
    mount(
      "break-glass",
      page(
        "Demandes break-glass",
        "",
        errorCard("Impossible de charger cette page", "La file n’a pas pu être lue. Aucun accès n’est ouvert.", viewBreakGlass),
      ),
    );
  }
}

// -- routing ----------------------------------------------------------------

async function route() {
  if (!state.token) {
    renderLogin();
    return;
  }
  if (!state.operator) {
    try {
      state.operator = await api("/auth/me");
      sessionStorage.setItem(OPERATOR_KEY, JSON.stringify(state.operator));
    } catch (error) {
      if (error.status === 401) return sessionExpired();
    }
  }
  const raw = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [path, search] = raw.split("?");
  const params = new URLSearchParams(search || "");
  const [view, id] = path.split("/");
  try {
    if (view === "studios" && id) viewStudio(id);
    else if (view === "studios") viewStudios(params.get("q"));
    else if (view === "usage") viewUsage();
    else if (view === "billing") viewBilling();
    else if (view === "suspensions") viewSuspensions();
    else if (view === "break-glass") viewBreakGlass();
    else viewDashboard();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) sessionExpired();
    else throw error;
  }
}

window.addEventListener("hashchange", route);
route();
