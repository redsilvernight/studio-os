/**
 * Pré-rendu du thème — script classique, exécuté avant le premier rendu.
 *
 * Pourquoi un fichier servi à part plutôt qu'un module importé par
 * `main.ts` : un module est différé, le navigateur peut peindre avant
 * son exécution (flash de thème clair sur une machine en thème sombre).
 * Un script classique dans `<head>` est bloquant : il s'exécute avant la
 * première peinture. Aucun script inline (CSP `script-src 'self'`), donc
 * le contrat est rejoué ici à la main — `src/theme.test.ts` verrouille
 * la concordance des deux implémentations.
 *
 * Contrat (identique à `src/theme.ts`) :
 *   - clé localStorage : `studio-os.theme` ;
 *   - absence de clé, valeur illisible ou « system » = suit le système
 *     → aucun attribut `data-theme` sur `<html>` (les media queries de
 *     `src/ds/tokens.css` décident) ;
 *   - « light » / « dark » → attribut `data-theme` explicite.
 */
(function () {
  "use strict";
  var KEY = "studio-os.theme";
  var mode = null;
  try {
    mode = window.localStorage.getItem(KEY);
  } catch (error) {
    // Stockage indisponible (navigation privée) : on suit le système.
    mode = null;
  }
  if (mode !== "light" && mode !== "dark") return;
  var root = document.documentElement;
  if (root) root.setAttribute("data-theme", mode);
})();
