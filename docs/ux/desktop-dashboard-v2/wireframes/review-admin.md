# Revue Administration — P02-wf-admin (wireframes/admin.html)

Références lues : `dashboard/src/views/machines.ts`, `accounts.ts`, `members.ts`,
`transfers.ts`, `library.ts`, `configuration.ts`, `application.ts`,
`integrations.ts`, `workspacesPage.ts`, `shell.ts` ; langage repris de
`wireframes/index.html` (tokens, rail/sidebar, `?raw&screen=…&w=…`, thèmes).

## Tableau par surface actuelle

| Surface actuelle (code) | Garde | Retire | Déplace |
|---|---|---|---|
| Postes `machines.ts` : cartes + tiroir, filtre local, présence serveur/déduite | Groupes par activité, vocabulaire « activité récente », tiroir de détail | Libellés techniques (source, tonalités brutes), préfixe d'identifiant | Identifiants, présence déduite, runtimes vus → « Détails techniques » replié ; révocation vers API/CLI (rappel, pas de bouton) |
| Comptes `accounts.ts` : table Compte/Rôle/État/Actions, ligne d'accès | Table, recherche nom/e-mail, actions Désactiver/Révoquer/Accès, « Votre compte » sans action | Texte 403 brut, état technique | Accès (`memberships`) → panneau latéral ; jetons/versions → replié |
| Membres `members.ts` (onglet par projet) | Recherche annuaire, ajout, retrait confirmé | Rien (déjà sobre) | Exposé comme 2ᵉ onglet de l'écran Comptes au lieu d'un onglet projet isolé |
| Transferts `transfers.ts` : statuts réels, quota avant envoi | Statuts réels, expiration dérivée signalée, contexte projet/tâche, lien court | Boutons destructifs inventés (annuler/renvoyer/prolonger : aucun endpoint fiable) | Clé S3, sommes, URL signées → replié ; suppression rappelée comme droit expéditeur/admin |
| Bibliothèque `library.ts` : 5 kinds, listes, modale de création | 5 catégories FR, recherche locale, liste aérée, création | Verdict de compatibilité inventé (réel seulement via Inspecteur) | Titres/contenus → versions ; clés/portées/verrous → replié |
| Détail Library : lecture, versions, Activate/Deprecate | Lecture d'abord, versions repliées, confirmations gardées | Provenance brute dans le flux | Dépendances, verrous, shadowing → replié ; compat → lien Inspecteur |
| Configuration `configuration.ts` + `application.ts` + `integrations.ts` : 5 onglets | 5 onglets réels (runtimes, liaisons, projet, application, intégrations IA), niveaux stockés | Surfaces profil/notifications/clés (inexistantes serveur, non fabriquées) | Résolution/compat → Inspecteur (lien) ; origines/versions → replié |
| Espaces `workspacesPage.ts` (Dossiers, desktop) | Sélecteur natif, liste, honnêteté pont non servi, renvoi web→Desktop | Simulation d'association réussie | Chemins, état du suivi → replié |
| Graphes, Inspecteur (`shell.ts`) | Inchangés, hors périmètre de cet écran | Rien | Restent dans la navigation, pas dans l'entrée Administration |

## Écarts assumés

- Une seule entrée « Administration » mène à 6 familles : Graphes et Inspecteur
  restent experts hors de cette entrée (pas de doublon de navigation).
- Configuration en 1 écran à 5 onglets plutôt que 5 écrans : 2ᵉ clic = onglet,
  pas de page ; chaque onglet garde la forme résumé + replié.
- Membres projet remontés comme onglet de Comptes : l'accès se comprend avec
  les comptes, le lien profond vers le projet est conservé.
- Aucune action destructive ou de création machine ajoutée : l'honnêteté du
  code (API/CLI seuls) prime sur la symétrie des maquettes.

## Mapping par largeur

| Écran | 1280 (rail 72) | 1600 (sidebar 236) | 2560 (3ᵉ colonne) |
|---|---|---|---|
| Entrée | héros + familles + contexte 300 | 760 + contexte 340 | + rappels (frontières) |
| Postes | liste + tiroir en ligne | tiroir latéral | + frontières API/CLI |
| Comptes | table + accès en ligne | accès latéral | + garde-fous |
| Transferts | liste + fiche en ligne | contexte quota latéral | + surfaces inexistantes |
| Bibliothèque | compteurs + liste | + lecture honnête | + à activer |
| Détail règle | contenu + état en ligne | état latéral | + voir aussi |
| Configuration | onglets + table | + orientation latérale | + frontières |
| Espaces | liste + aide en ligne | association latérale | + surveillance |

Aucune carte ne s'élargit ; texte courant ≤ 68 ch ; ligne de flottaison commune.

## Justification C1 à C4

- C1 : chaque écran porte une et une seule action primaire verbe + objet, toute famille à 1 clic de l'entrée et tout détail à 2 clics maximum.
- C2 : aucun UUID ni préfixe hexadécimal visible par défaut ; noms humains partout, identifiants seulement derrière « Copier l'identifiant » ou bloc replié.
- C3 : ≤ 3 blocs majeurs par écran (héros/contenu, panneau contexte, 3ᵉ colonne à 2560) ; les 6 familles tiennent dans un seul bloc « Familles ».
- C4 : un seul `connection-status` visible (sous l'avatar, variante rail/sidebar) ; aucun « Connecté », santé ou jeton ailleurs.
