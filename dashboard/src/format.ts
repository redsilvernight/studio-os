/**
 * R1-formats : un seul endroit pour formater dates, durées, volumes, montants
 * et pluriels. Les vues n'écrivent ni « (s) », ni heure UTC, ni durée en
 * secondes. Toutes les fonctions rendent du texte brut (échapper à l'affichage).
 */

const ABSENT = "—";

function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Suffixe « s » du pluriel français : 0 et 1 restent au singulier. */
export function sfx(count: number): string {
  return count >= 2 ? "s" : "";
}

/** « 3 fichiers », « 1 fichier », « 0 fichier » (pluriel irrégulier en 3e argument). */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count >= 2 ? pluralForm : singular}`;
}

/** Date et heure locales (fuseau du navigateur) : « 22/11/2026 14:05 ». */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (date === null) return ABSENT;
  return date.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

/**
 * Jour calendaire « AAAA-MM-JJ » (sans heure) : affiché tel quel, sans décalage
 * de fuseau. `long` donne « dimanche 22 novembre 2026 ».
 */
export function formatDay(day: string, long = false): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (match === null) return day;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return long
    ? date.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
    : date.toLocaleDateString("fr-FR");
}

/** Mois d'un jour calendaire « AAAA-MM » : « novembre 2026 ». */
export function formatMonth(month: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (match === null) return month;
  return new Date(Number(match[1]), Number(match[2]) - 1, 1).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
}

/** Durée relative : « à l'instant », « il y a 4 min », « il y a 2 h », « il y a 3 jours ». `null` si absent. */
export function formatRelative(value: string | number | Date | null | undefined, now: number): string | null {
  const date = toDate(value);
  if (date === null) return null;
  const seconds = Math.max(Math.floor((now - date.getTime()) / 1000), 0);
  if (seconds < 60) return "à l'instant";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${plural(Math.floor(hours / 24), "jour")}`;
}

/** Durée lisible à partir de secondes : « moins d'une minute », « 5 min », « 2 h 05 », « 3 jours ». */
export function formatDuration(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return ABSENT;
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes < 1) return "moins d'une minute";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return rest === 0 ? `${hours} h` : `${hours} h ${String(rest).padStart(2, "0")}`;
  }
  return plural(Math.floor(hours / 24), "jour");
}

/** Nombre à la française : « 1 234,5 ». */
export function formatNumber(value: number, maxFractionDigits = 1): string {
  return Number.isFinite(value) ? value.toLocaleString("fr-FR", { maximumFractionDigits: maxFractionDigits }) : ABSENT;
}

/** Volume en gibioctets (quotas) : « 2 Gio », « 0,5 Gio ». */
export function formatVolume(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return ABSENT;
  return `${formatNumber(bytes / 1024 ** 3)} Gio`;
}

/** Montant décimal serveur (chaîne) : « 12,50 EUR » ; devise absente → « devise inconnue ». */
export function formatAmount(raw: string, currency: string | null | undefined): string {
  return `${raw.replace(".", ",")} ${currency ?? "(devise inconnue)"}`;
}
