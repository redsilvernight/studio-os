/**
 * Abonnements du projet (DEC-0361) : forfaits mensuels dont le prix est
 * réparti par le serveur, à la lecture, sur la consommation couverte.
 *
 * - Liste, ajout, modification (version optimiste : un conflit est affiché,
 *   jamais écrasé) et suppression confirmée. Après chaque écriture la liste
 *   et la consommation sont relues : le serveur reste la vérité.
 * - Aucun UUID visible.
 */
import type { StudioClient } from "../api";
import { confirmDs } from "../ds/confirm";
import { dsField, dsSectionHeader, dsSkeleton, focusDsErrorBox } from "../ds/ds";
import { formatDay } from "../format";
import { describeError, esc } from "../ui";
import {
  createUsageSubscription,
  deleteUsageSubscription,
  listUsageSubscriptions,
  updateUsageSubscription,
  type UsageSubscription,
  type UsageSubscriptionTerms,
} from "../usageApi";

export interface UsageSubscriptionsContext {
  client: StudioClient;
  projectId: string;
  /** Relit la consommation après une écriture. */
  onChange?: () => void;
  /** Horloge injectable (tests). */
  now?: () => number;
}

function coverageText(subscription: UsageSubscription): string {
  const parts = [...(subscription.harnesses ?? []), ...(subscription.providers ?? [])];
  return parts.length === 0 ? "—" : parts.join(", ");
}

function periodText(subscription: UsageSubscription): string {
  const start = `depuis le ${formatDay(subscription.starts_on)}`;
  return subscription.ends_on ? `${start} jusqu'au ${formatDay(subscription.ends_on)}` : `${start} (en cours)`;
}

export function subscriptionsTableHtml(subscriptions: ReadonlyArray<UsageSubscription>): string {
  if (subscriptions.length === 0) {
    return `<p class="ds-list-sub" data-subscriptions-empty>Aucun abonnement déclaré : seuls les coûts équivalent API sont affichés.</p>`;
  }
  const rows = subscriptions
    .map(
      (subscription, index) =>
        `<tr data-subscription-row><th scope="row">${esc(subscription.label)}</th>` +
        `<td>${esc(`${subscription.monthly_price.replace(".", ",")} ${subscription.currency}`)}</td>` +
        `<td>${esc(coverageText(subscription))}</td><td>${esc(periodText(subscription))}</td>` +
        `<td><button type="button" class="ds-btn" data-subscription-edit="${index}" aria-label="Modifier ${esc(subscription.label)}">Modifier</button> ` +
        `<button type="button" class="ds-btn" data-subscription-delete="${index}" aria-label="Supprimer ${esc(subscription.label)}">Supprimer</button></td></tr>`,
    )
    .join("");
  return (
    `<div class="ds-table-wrap"><table class="ds-table usage-table" data-subscriptions><caption>Abonnements déclarés</caption>` +
    `<thead><tr><th scope="col">Abonnement</th><th scope="col">Prix mensuel</th><th scope="col">Couvre</th><th scope="col">Période</th><th scope="col">Actions</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>`
  );
}

function firstOfMonth(now: number): string {
  const date = new Date(now);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-01`;
}

export function subscriptionFormHtml(editing: UsageSubscription | null, now: number): string {
  const value = (raw: string | null | undefined): string => (raw === null || raw === undefined ? "" : ` value="${esc(raw)}"`);
  const currency = editing?.currency ?? "EUR";
  const currencies = ["EUR", "USD"]
    .map((code) => `<option value="${code}"${code === currency ? " selected" : ""}>${code}</option>`)
    .join("");
  return (
    `<form data-subscription-form class="claims-form" novalidate>` +
    `<h3>${editing ? `Modifier « ${esc(editing.label)} »` : "Déclarer un abonnement"}</h3>` +
    dsField("subscription-label", "Libellé", `<input class="ds-input" id="FIELD" name="label" required maxlength="120" autocomplete="off"${value(editing?.label)} />`) +
    dsField("subscription-price", "Prix mensuel", `<input class="ds-input" id="FIELD" name="monthly_price" type="number" min="0" step="0.01" required${value(editing?.monthly_price)} />`) +
    dsField("subscription-currency", "Devise", `<select class="ds-select" id="FIELD" name="currency">${currencies}</select>`) +
    dsField(
      "subscription-harnesses",
      "Outils couverts",
      `<input class="ds-input" id="FIELD" name="harnesses" autocomplete="off"${value(editing?.harnesses?.join(", "))} />`,
      "Identifiants d'outil tels qu'affichés dans le regroupement par configuration, séparés par des virgules.",
    ) +
    dsField(
      "subscription-providers",
      "Fournisseurs couverts",
      `<input class="ds-input" id="FIELD" name="providers" autocomplete="off"${value(editing?.providers?.join(", "))} />`,
      "Facultatif si un outil est indiqué ; mêmes identifiants que la consommation.",
    ) +
    dsField("subscription-start", "Début", `<input class="ds-input" id="FIELD" name="starts_on" type="date" required${value(editing?.starts_on ?? firstOfMonth(now))} />`) +
    dsField("subscription-end", "Fin (incluse, facultative)", `<input class="ds-input" id="FIELD" name="ends_on" type="date"${value(editing?.ends_on)} />`) +
    `<p class="ds-list-sub">Le prix mensuel complet est réparti chaque mois sur la consommation couverte, au prorata de son coût équivalent API. Le mois en cours reste provisoire.</p>` +
    `<button type="submit" class="ds-btn ds-btn--primary">${editing ? "Enregistrer" : "Ajouter l'abonnement"}</button>` +
    (editing ? ` <button type="button" class="ds-btn" data-subscription-cancel>Annuler</button>` : "") +
    `<div data-subscription-msg class="ds-list-sub" role="status"></div></form>`
  );
}

function splitList(raw: FormDataEntryValue | null): string[] {
  return String(raw ?? "")
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "");
}

/** Termes saisis, ou un message d'erreur lisible (le serveur revalide tout). */
export function readSubscriptionTerms(form: HTMLFormElement): UsageSubscriptionTerms | string {
  const data = new FormData(form);
  const label = String(data.get("label") ?? "").trim();
  const price = String(data.get("monthly_price") ?? "").trim();
  const startsOn = String(data.get("starts_on") ?? "");
  const endsOn = String(data.get("ends_on") ?? "");
  const harnesses = splitList(data.get("harnesses"));
  const providers = splitList(data.get("providers"));
  if (label === "") return "Indiquez un libellé.";
  if (!/^\d+(\.\d{1,2})?$/.test(price)) return "Indiquez un prix mensuel positif (deux décimales au plus).";
  if (harnesses.length === 0 && providers.length === 0) return "Indiquez au moins un outil ou un fournisseur couvert.";
  if (startsOn === "") return "Indiquez la date de début.";
  if (endsOn !== "" && endsOn < startsOn) return "La fin précède le début.";
  return {
    label,
    monthly_price: price,
    currency: String(data.get("currency") ?? "EUR"),
    harnesses,
    providers,
    starts_on: startsOn,
    ends_on: endsOn === "" ? null : endsOn,
  };
}

export async function renderUsageSubscriptionsInto(root: HTMLElement, ctx: UsageSubscriptionsContext): Promise<void> {
  const now = ctx.now ?? Date.now;
  let subscriptions: UsageSubscription[] = [];
  let editing: UsageSubscription | null = null;
  root.innerHTML = `<section aria-label="Abonnements" data-usage-subscriptions-panel>${dsSectionHeader("Abonnements")}<div data-subscriptions-body>${dsSkeleton(2)}</div></section>`;
  const body = root.querySelector<HTMLElement>("[data-subscriptions-body]");
  if (body === null) return;

  const showMessage = (text: string): void => {
    const node = body.querySelector<HTMLElement>("[data-subscription-msg]");
    if (node === null) return;
    node.textContent = text;
    if (text !== "") focusDsErrorBox(node);
  };

  const render = (): void => {
    body.innerHTML = subscriptionsTableHtml(subscriptions) + subscriptionFormHtml(editing, now());
    bind();
  };

  const reload = async (changed: boolean): Promise<void> => {
    try {
      subscriptions = await listUsageSubscriptions(ctx.client, ctx.projectId);
      render();
    } catch (error) {
      body.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Abonnements indisponibles.</strong> ${esc(describeError(error))}</div>`;
    }
    if (changed) ctx.onChange?.();
  };

  const bind = (): void => {
    body.querySelectorAll<HTMLButtonElement>("[data-subscription-edit]").forEach((button) => {
      button.addEventListener("click", () => {
        editing = subscriptions[Number(button.dataset["subscriptionEdit"])] ?? null;
        render();
        body.querySelector<HTMLInputElement>("[name=label]")?.focus();
      });
    });
    body.querySelectorAll<HTMLButtonElement>("[data-subscription-delete]").forEach((button) => {
      button.addEventListener("click", async () => {
        const subscription = subscriptions[Number(button.dataset["subscriptionDelete"])];
        if (subscription === undefined) return;
        if (!(await confirmDs(`Supprimer l'abonnement « ${subscription.label} » ? Sa part ne sera plus répartie, y compris sur les mois passés.`))) return;
        button.disabled = true;
        deleteUsageSubscription(ctx.client, subscription)
          .then(() => {
            if (editing?.id === subscription.id) editing = null;
            return reload(true);
          })
          .catch((error: unknown) => {
            button.disabled = false;
            showMessage(describeError(error));
          });
      });
    });
    body.querySelector<HTMLButtonElement>("[data-subscription-cancel]")?.addEventListener("click", () => {
      editing = null;
      render();
    });
    const form = body.querySelector<HTMLFormElement>("[data-subscription-form]");
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      const terms = readSubscriptionTerms(form);
      if (typeof terms === "string") {
        showMessage(terms);
        return;
      }
      const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
      if (submit !== null) submit.disabled = true;
      const write = editing ? updateUsageSubscription(ctx.client, editing, terms) : createUsageSubscription(ctx.client, ctx.projectId, terms);
      write
        .then(() => {
          editing = null;
          return reload(true);
        })
        .catch((error: unknown) => {
          if (submit !== null) submit.disabled = false;
          showMessage(describeError(error));
        });
    });
  };

  await reload(false);
}
