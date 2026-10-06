# UX V2 — Rapport d'utilisabilité et d'accessibilité (P06-usability)

- Date : 2026-10-04 · Roadmap `117dd4c5-b6c9-448c-a25e-edc10ad56aa9` · Tâche `c452d0c4-fa25-445c-b9d9-c32346952fc6`
- Cibles de référence : `targets.md` (C1–C4). **Hors périmètre : register, login, password, jeton machine, persistance de session.**

## Verdict par critère de l'étape

| Critère | Résultat | Preuve |
|---|---|---|
| Quatre scénarios conformes aux cibles P01 | **Automatisé : conforme. Test humain C1 : jugé concluant par le responsable produit (déclaration en session le 2026-10-04, sans chronométrage consigné).** | `dashboard/e2e/p06-targets.spec.ts` (S1–S4 × 1440×900 et 2560×1440, 8 tests verts) |
| Clavier, focus, contrastes, zoom 200 % | **Conforme (automatisé)** | `dashboard/e2e/p06-a11y.spec.ts` (7 pages × 3 contrôles, 21 tests verts, aucun défaut seulement journalisé) |
| Libellés ambigus corrigés | **P1 et P2/P3 non ambigus corrigés ; reste listé ci-dessous** | `usability-labels.md` (audit) + commits P06 sur les libellés |

## Mesures automatisées (C1–C4)

- **C1** : une action primaire visible au-dessus de la ligne de flottaison ; S1 Accueil→fiche 1 clic, S2 « Maintenant »→fiche 1 clic, S3 décision depuis la page sans changer de page, S4 Projet→Roadmap 2 clics avec étape courante visible.
- **C2** : aucun UUID ni préfixe hexadécimal de 8 caractères dans `innerText`, `title`, `aria-label`, `placeholder` hors sections repliées.
- **C3** : ≤ 7 éléments `[data-major]` visibles hors sections repliées ; navigation = 5 entrées quotidiennes + Administration.
- **C4** : exactement un `[data-testid="connection-status"]` par page.

## Accessibilité (automatisé)

- **Clavier** : parcours Tab complet sans piège de focus, indicateur de focus visible (outline ou ombre) sur chaque contrôle atteint, palette `Ctrl K` (ouverture, focus retenu dans la boîte, Échap, retour du focus au déclencheur). Le contrôle a été vérifié sensible : il échoue quand les indicateurs de focus sont supprimés.
- **Contraste** : axe-core (WCAG 2.0/2.1 A et AA) sans violation serious/critical ni `color-contrast` sur les 7 pages. Un seul thème (clair) existe : pas de passe en thème sombre.
- **Zoom 200 %** : simulé par un viewport 720×450 ; aucun défilement horizontal de page, actions primaires atteignables par défilement vertical sans coupure horizontale.

## Libellés

Audit : `usability-labels.md` (≈ 50 constats P1/P2/P3). Corrigés ici : en-tête « Travail », en-tête et onglets de « À valider », cartes de proposition de plan (« Relire le plan », « Ouvrir le plan »), nom humain à la place du préfixe d'UUID sur l'Accueil, « sur » au lieu de « on », jargon « pull » du panneau de lancement, « Identifiant court » à la place de « Slug ». Second lot (2026-10-04) : « Studio OS est joignable/injoignable », « Aucun travail ouvert », « Demande de fusion » (plus de « PR »), « compilations en échec », « À surveiller »/« incidents » (plus de « signaux »), « Kanban », « Toutes les tâches », « À faire » (groupe et badge), « Compétences », « mode d'exécution » (plus de « harnais »), « configuration de lancement », « (facultatif) », « Identifiant du proposant », « Paramètres d'exécution », « Travail réalisé », « Peut démarrer », genre unifié « Bloqué/Terminé » sur l'Accueil, slug retiré du fil d'Ariane du projet. **Non traités (choix de conception ou périmètre plus large)** : nom lisible dans le sélecteur d'agent (`stable_key`), placeholders `uuid`, boutons de cycle de vie et d'export de la roadmap, libellés « Disponible maintenant/En attente », « Postes » vs « Machine », centralisation des sources `language.ts`/`decisionsV2.ts`.

## Limites — à lire avant de cocher la cible C1

- **Test humain C1** : la cible exige 3 personnes, chronométrées, ≥ 90 % de réponses justes en ≤ 5 s. Le proxy déterministe (une action primaire, nombre de clics) est vérifié ; le résultat humain est celui déclaré par le responsable produit, sans mesure archivée ici.
- Zoom 200 % simulé par taille de viewport, pas par zoom navigateur ; lecteur d'écran (NVDA/VoiceOver) non testé ; Desktop (Tauri) non exécuté dans cette étape.
- Les e2e utilisent des données simulées (`support/ui16-stub`), pas un compte de production.
