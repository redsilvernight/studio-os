/**
 * Adresses (R2-adresses, DEC-0394) : les adresses canoniques sont en français,
 * chaque ancienne adresse y redirige. Une seule table pilote les deux sens ;
 * `*` désigne un identifiant, les segments suivants sont conservés tels quels.
 * Le studio n'est pas dans l'adresse : il reste porté par la session.
 */

/** [ancienne, nouvelle]. Plusieurs anciennes → une nouvelle : la première fait foi au retour. */
const ALIASES: ReadonlyArray<readonly [old: string, next: string]> = [
  ["projects", "projets"],
  ["projects/*", "projets/*"],
  ["projects/*/roadmap", "projets/*/plan"],
  ["projects/*/mission", "projets/*/executions"],
  ["projects/*/tasks", "projets/*/taches"],
  ["projects/*/claims", "projets/*/reservations"],
  ["projects/*/activity", "projets/*/activite"],
  ["projects/*/history", "projets/*/historique"],
  ["projects/*/members", "projets/*/equipe"],
  ["projects/*/ai-integration", "projets/*/integration-ia"],
  ["tasks", "taches"],
  ["decisions", "a-valider"],
  ["agents", "equipe-ia"],
  ["library", "connaissances/savoir-faire"],
  ["vault", "connaissances/notes"],
  ["vault/atlas", "connaissances/carte"],
  ["inspector", "reglages/avance/inspecteur"],
  ["transfers", "fichiers"],
  ["administration", "reglages"],
  ["admin", "reglages"],
  ["administration/mesures", "reglages/mesures"],
  ["admin/mesures", "reglages/mesures"],
  ["accounts", "reglages/equipe-acces"],
  ["machines", "reglages/appareils"],
  ["configuration/runtimes", "reglages/moteurs"],
  ["configuration", "reglages/moteurs"],
  ["configuration/bindings", "reglages/moteurs/affectations"],
  ["configuration/integrations", "reglages/connexions-ia"],
  ["configuration/application", "reglages/application"],
  ["configuration/project", "reglages/avance/projet"],
  ["design-system", "reglages/avance/design-system"],
  ["workspaces", "reglages/dossiers"],
];

function translate(hash: string, from: 0 | 1): string {
  const queryAt = hash.indexOf("?");
  const path = queryAt === -1 ? hash : hash.slice(0, queryAt);
  const query = queryAt === -1 ? "" : hash.slice(queryAt);
  const parts = path.replace(/^#\/?/, "").split("/").filter((p) => p !== "");
  let best: { pattern: string[]; target: string } | null = null;
  for (const pair of ALIASES) {
    const pattern = pair[from].split("/");
    const matches = pattern.length <= parts.length && pattern.every((seg, i) => seg === "*" || seg === parts[i]);
    // Le plus long l'emporte ; à égalité, un segment littéral bat `*`.
    const better =
      best === null ||
      pattern.length > best.pattern.length ||
      (pattern.length === best.pattern.length && best.pattern.filter((s) => s === "*").length > pattern.filter((s) => s === "*").length);
    if (matches && better) best = { pattern, target: pair[from === 0 ? 1 : 0] };
  }
  if (best === null) return hash;
  const { pattern, target } = best;
  const params = parts.filter((_, i) => pattern[i] === "*");
  const head = target.split("/").map((seg) => (seg === "*" ? params.shift() : seg));
  return `#/${[...head, ...parts.slice(pattern.length)].join("/")}${query}`;
}

/** Adresse canonique d'un hash ; inchangé s'il l'est déjà ou s'il est inconnu. */
export function canonicalHash(hash: string): string {
  // L'ancien onglet Graph est fusionné dans la carte, quel que soit le sous-chemin.
  if (/^#\/?graphs(\/|\?|$)/.test(hash)) return "#/connaissances/carte";
  return translate(hash, 0);
}

/** Forme interne lue par `parseRoute` (les segments historiques). */
export function legacyHash(hash: string): string {
  return translate(hash, 1);
}
