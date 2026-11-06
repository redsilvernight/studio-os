# Claude First — application du patch personnel

Date : 05/11/2026 (Europe/Paris).

## Modification autorisée

Fichier : `C:\Users\redsi\.claude\rules\studio-protocol.md`.

La ligne ancienne attendue était présente exactement une fois. Elle a été remplacée par la formulation demandée, sans changement d’une autre ligne. Une copie préalable a été créée :

`C:\Users\redsi\.claude\rules\studio-protocol.md.bak-claude-first-20261105-115958`

| Contrôle | Résultat |
|---|---|
| Compte de l’ancienne ligne avant application | 1 |
| Compte de la nouvelle ligne après application | 1 |
| Ancienne ligne restante | 0 |
| Comparaison complète `backup.Replace(ancienne, nouvelle) == fichier courant` | vraie |
| SHA-256 de la sauvegarde | `777726E00667CAAC6548295A9797541502BEED26678E6C988EFA28241A359FFC` |
| SHA-256 du fichier courant | `5FDEFF5ACF700D754ECD32685C29B08FC2104910D919C4FED716CC49D2C3A715` |

Le fichier et la sauvegarde ont été relus après l’écriture. Aucun autre fichier personnel ni configuration Claude n’a été modifié par cette application.

## Instructions personnelles restantes

`~/.claude/rules/studio-workflow.md` contient encore les parcours `Sans tâche → studio_start_work` et `Avec tâche → studio_start_work`, sans exception readonly explicite. Cette règle peut contredire le nouveau protocole pour un audit sur un projet suivi. Elle n’a pas été modifiée : l’autorisation couvre exclusivement `studio-protocol.md`.

## Chargement effectif

Les sessions Claude Code Round 2 ont effectivement appelé `studio_prepare_context` et des lectures, sans appel Studio OS de mutation. Aucun événement `InstructionsLoaded` ni journal récent identifiant avec certitude les fichiers chargés n’a été retrouvé. Le comportement observé est compatible avec le patch, mais ne prouve pas à lui seul le chargement de chaque instruction personnelle et projet.
