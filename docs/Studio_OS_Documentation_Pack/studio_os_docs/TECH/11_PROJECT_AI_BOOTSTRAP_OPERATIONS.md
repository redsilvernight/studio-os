# Project AI Bootstrap — contrats d'exploitation

Cette fiche relie les opérations utilisateur aux contrats canoniques. Elle ne
crée aucun nouvel endpoint ni format ; les documents cités restent normatifs.

## Frontières de responsabilité

| Élément | Source de vérité | Propriété |
|---|---|---|
| Règles, skills et agents du projet | `.agents/` | dépôt partagé |
| Manifeste de bootstrap | `.agents/bootstrap.json` | dépôt partagé |
| Projections Claude/OpenCode/Codex | générées depuis `.agents/` | régénérables |
| Workspace, profil et machine | registre local | poste uniquement |
| Opt-in et politique de lancement | `launch_settings.json` local | poste uniquement |
| Tâches, grants et TaskLaunch | API Studio OS | serveur partagé |

Les chemins absolus, tokens, identifiants de profil et secrets ne doivent jamais
être écrits dans les fichiers partagés. `bootstrap scan` contrôle les fichiers
suivis par Git avant une reconstruction sur un autre poste.

## Connexion et reconstruction

`workspaces register` associe localement un `project_id` à un dépôt. Le bootstrap
matérialise les fichiers du dépôt ; ce sont deux transactions distinctes. Sur un
nouveau poste, `bootstrap rebuild --project-id <uuid>` lit le manifeste commité,
contrôle les fuites puis reconstruit le registre et les projections locales.

La compatibilité du manifeste est évaluée avant la validation Pydantic et avant
toute écriture :

- `studio.bootstrap/v1` est la seule version nommée acceptée ;
- l'absence de `format` reste un legacy v1 implicite ;
- une valeur invalide, inconnue ou future échoue de manière fermée ;
- aucune migration v0 ou tolérance N-1 n'est promise.

La politique est définie par
[DEC-0181](../../../decisions/DEC-0181-compatibilite-du-manifest-bootstrap-lecture-v1-uniquement.md),
encore proposée tant qu'elle n'est pas acceptée.

## Drift, conflit et rollback

`bootstrap check` et `bootstrap diff` sont sans écriture. `bootstrap sync` suit la
politique `on_modified` du manifeste et crée une sauvegarde avant remplacement.
Le rollback inverse la dernière synchronisation : il restaure les fichiers
remplacés, supprime les fichiers créés par cette synchronisation et refuse un
contenu modifié depuis la sauvegarde, sauf `--force` explicite.

Ces invariants rendent l'opération rejouable : un second sync sans changement ne
doit produire aucune écriture. Ils ne remplacent pas Git ; le rollback du
bootstrap ne réécrit ni branche ni historique.

## Lancement à distance

Le contrat API de référence est
[TECH/02](02_API_CONTRACT.md) et l'autorisation machine/projet est définie dans
[TECH/04](04_AUTH_SYNC_CONTRACT.md).

Un `TaskLaunch` transporte une intention structurée. Il ne permet pas au demandeur
de fournir une commande, un `cwd`, un environnement ou des arguments libres. Le
serveur exige l'accès au projet et un owner ou un grant explicite. Un grant de
lancement n'élargit jamais l'accès au projet.

La machine tire les lancements après heartbeat, puis applique sa politique
locale :

- opt-in désactivé par défaut ;
- workspace du projet enregistré et dépôt Git résolvable ;
- harness détecté et autorisé ;
- concurrence bornée ;
- timeout dur et sortie bornée/rédigée ;
- rapports idempotents avec `expected_version` et session associée.

Les réglages locaux sont décrits par
[DEC-0179](../../../decisions/DEC-0179-aib-r3-reglages-de-lancement-locaux-persistes-dans-launch.md). Le
lancement non interactif et ses permissions bornées sont définis par
[DEC-0176](../../../decisions/DEC-0176-aib-r3-lancement-non-interactif-des-harness-permissions.md).

## Matrice de validation

| Parcours | Contrôle minimal |
|---|---|
| Connecter un projet | workspace local + `bootstrap check` + `adapters check` |
| Ajouter un harness | dry-run du hook + sync + second sync sans écriture |
| Réparer le drift | check/diff avant sync ; conflit de rollback refusé |
| Reconstruire un poste | scan propre + manifeste compatible + registre local |
| Lancer à distance | accès projet + grant + opt-in + harness + limite locale |

Les tests d'acceptation transverses sont recensés dans
[TECH/10](10_TEST_ACCEPTANCE.md). Les décisions du chantier et son état courant
sont suivis dans [la roadmap Project AI Bootstrap](../../../AI_BOOTSTRAP_ROADMAP.md).
