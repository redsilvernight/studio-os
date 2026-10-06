# UX V2 — Régressions, activation progressive et retour arrière (P06-regression-rollout)

- Date : 2026-10-04 · Roadmap `117dd4c5-b6c9-448c-a25e-edc10ad56aa9` · Tâche `88f44c4a-8384-4d6d-a20e-b6e3ed164102`
- **Hors périmètre : register, login, password, jeton machine, persistance de session.**

## Verdict par critère de l'étape

| Critère | Résultat | Preuve |
|---|---|---|
| Fonctions expertes toujours accessibles | **Conforme** : les 13 destinations de la navigation d'avant la V2 restent à ≤ 2 clics de la navigation simple (1 clic pour le quotidien, 2 pour Administration / Outils experts) et sont listées dans la palette `Ctrl K` | `dashboard/e2e/p06-regression.spec.ts` (13 + 1 tests) |
| Scénarios critiques couverts en régression | **Conforme** : S1–S4 aux cibles C1–C4 (`p06-targets.spec.ts`), accessibilité (`p06-a11y.spec.ts`), 34 variantes de lien profond dont l'alias `#/admin` sans « Page introuvable » ni erreur console/CSP, hash inconnu = 404 explicite | `p06-regression.spec.ts`, `p06-targets.spec.ts`, `p06-a11y.spec.ts` |
| Activation progressive et retour arrière sans perte | **Conforme pour la présentation** (mode de navigation, ci-dessous) ; retour arrière de version par canal (ci-dessous) | `dashboard/src/navMode.ts`, `navMode.test.ts`, test e2e « complete navigation mode » |
| Comparaison avant/après publiée | **Publiée** (ci-dessous) | ce document |

Suites relancées sur le code courant : Vitest 1 342 tests verts, Playwright 260 verts / 1 ignoré (suite complète), `tsc --noEmit` sans erreur.

## Activation progressive : mode de navigation

Le bouton « Navigation complète » (pied de la barre latérale, `data-testid="nav-mode-toggle"`, `aria-pressed`) bascule entre :

- **simple** (défaut) : 5 destinations quotidiennes ; Administration (7) et Outils experts (2) repliés ;
- **complet** : mêmes 14 destinations, groupes déployés en permanence (le rail d'icônes défile dans la barre).

Garanties vérifiées : le mode ne change **que la présentation** — mêmes routes, même URL, même contenu de page avant/après la bascule, un seul statut de connexion (C4) dans les deux modes ; il se mémorise localement (`localStorage`, clé `studio-os.nav-mode`) sans jeton ni secret ; une valeur illisible ou un stockage indisponible retombe sur « simple » ; la bascule inverse restaure l'état initial sans rien perdre, à tout moment.

Limite assumée : l'ancien écran (liste plate de 12–13 entrées, anciennes vues) n'est **pas** conservé comme second code. Le mode complet restitue l'accès d'avant (tout visible) pas l'ancienne disposition des pages ; il n'y a donc pas d'interrupteur serveur « V1 / V2 ».

## Retour arrière de version (déploiement)

Aucun état utilisateur n'est lié à la V2 : pas de migration de données, pas de contrat API modifié, une seule préférence locale optionnelle. Revenir à une version antérieure du dashboard est donc sans perte :

- **Serveur / dashboard web** : retour automatique du code précédent en cas d'échec du déploiement, ou redéploiement d'un commit antérieur (`docs/FLO_LAPTOP_DEPLOYMENT.md`, « Échec et retour arrière ») ; les migrations ne sont jamais rétrogradées, et la V2 n'en ajoute aucune.
- **Desktop** : restauration dans la voie d'origine par `desktop-promote.yml` (`workflow_dispatch`, explicitement humaine), jamais de promotion croisée Dev → Prod (`docs/DESKTOP_P10_PACKAGING.md`, DEC-0162).
- La préférence `studio-os.nav-mode` est ignorée par une version qui ne la connaît pas (clé inconnue).

## Comparaison avant / après

Avant = `baseline.md` (lecture de code, 2026-10-03) ; après = cibles `targets.md` vérifiées par `p06-targets.spec.ts` (1440×900 et 2560×1440) et les tests de navigation.

| Mesure | Avant | Après |
|---|---|---|
| Entrées de navigation de premier niveau | 12 (13 Desktop) | 5 quotidiennes + Administration + Outils experts repliés (14 destinations au total, toutes conservées) |
| Indicateurs de connexion sur l'Accueil | 3 | 1 (`connection-status`) |
| Clics Accueil → fiche tâche (S1) | 1, sans action explicite | ≤ 1, action primaire « verbe + objet » |
| Clics Travail → reprise (S2) | ≥ 2 + balayage de 100 lignes | ≤ 2, vue « Maintenant » par défaut |
| Clics À valider → décision (S3) | 1 (`ai_work_review`), ≥ 3 pour une roadmap | ≤ 2 pour tout type actionnable |
| Clics Projet → étape courante (S4) | 4, étape courante non garantie visible | ≤ 2, étape courante visible |
| UUID / préfixe hexadécimal exposé par défaut | présent en S2, S3, S4 | 0 |
| Éléments majeurs par page (hors repliés) | jusqu'à 12 (nav) / 7 (Accueil) | ≤ 7 |
| Surfaces expertes accessibles | oui (à plat) | oui (≤ 2 clics, palette, mode complet en 1 clic) |

## Limites

- Test humain C1 (3 personnes, ≥ 90 % en ≤ 5 s) : non chronométré (voir `usability-report.md`).
- Les e2e utilisent des données simulées (`support/ui16-stub`) ; Desktop (Tauri) non exécuté dans cette étape ; aucune mesure sur une instance de production peuplée.
- « Avant » provient de la lecture du code, pas d'une exécution : les clics sont structurels.
