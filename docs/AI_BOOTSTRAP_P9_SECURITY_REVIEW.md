# Project AI Bootstrap P9 — revue de sécurité

Date : 2026-10-03
Base : `origin/dev` (`b4432c43`)
Périmètre : bootstrap/rollback local, TaskLaunch et exécuteur local,
`coordination.*`.

## Verdict

La compatibilité du manifeste, le rollback et les limites fonctionnelles de
coordination sont testés. La revue a néanmoins identifié deux risques élevés du
lancement distant et quatre durcissements serveur encore ouverts. P9 ne doit pas
être déclaré clos tant que ces points ne sont pas corrigés ou acceptés par une
décision explicite.

Le bootstrap local a été durci dans cette branche : écritures du manifeste,
sauvegardes et journal confinées au dépôt ; source de restauration confinée au
dossier exact de backup ; traversal et symlink de backup refusés.

## Constats

| Sévérité | Surface | Constat | État |
|---|---|---|---|
| Élevée | Claude distant | `--setting-sources project` autorise les hooks committés du dépôt à s'exécuter avant toute validation humaine. | Ouvert : n'utiliser que des settings temporaires générés par Studio OS. |
| Élevée | Identité machine | Le harness hérite de l'environnement du daemon, dont le token machine durable nécessaire au MCP. Un dépôt/instruction hostile peut tenter de l'exfiltrer. | Ouvert : environnement allowlisté et jeton éphémère borné au projet, à la tâche et à la session. |
| Élevée | Bootstrap filesystem | Le manifeste, les backups et le journal pouvaient suivre un parent symlink/junction hors dépôt. | Corrigé dans cette branche par confinement avant écriture. |
| Moyenne | Rollback | Un `journal.json` altéré pouvait employer `..` ou un symlink dans `backup` et recopier un fichier local arbitraire dans le dépôt. | Corrigé et couvert par un test de traversal. |
| Moyenne | TaskLaunch | `expected_version` est vérifié puis incrémenté sans verrouillage atomique ; report/cancel concurrents peuvent accepter la même version. | Ouvert : verrou de ligne ou `UPDATE ... WHERE version = expected_version`. |
| Moyenne | TaskLaunch | Un report vérifie la machine de `session_id`, pas sa correspondance avec `launch.task_id`. | Ouvert : exiger même tâche, session vivante et projet cohérent. |
| Moyenne | Coordination | Le quota de 20 signaux fait `COUNT` puis insert sans sérialisation par session. | Ouvert : verrouiller la session émettrice ou utiliser un compteur atomique. |
| Faible | Coordination | Les `decision_ids` référencés ne sont pas validés dans le projet, contrairement aux `task_ids`. | Ouvert : existence et `project_id` obligatoires avant émission. |

## Propriétés confirmées

- Le contrat TaskLaunch ne représente ni commande, ni `cwd`, ni environnement
  ni arguments libres ; motif et transitions utilisent des vocabulaires fermés.
- Le serveur exige l'accès au projet, un owner/grant, l'opt-in et les capacités
  rapportées ; la machine réapplique projet, harness autorisé et concurrence.
- L'exécuteur borne le timeout et la sortie, retire ANSI et rédige les secrets
  connus dans l'extrait rapporté.
- Le texte `coordination.*` est borné à 280 caractères, livré comme donnée citée
  non fiable et testé avec `ignore all previous instructions` sans interprétation.
- La cible et les `task_ids` référencés restent dans le projet ; les intents sont
  fermés, l'émission est attribuée à une session et rejouable par `event_id`.
- Le rollback valide toutes les entrées avant la première mutation, refuse un
  fichier modifié depuis la sauvegarde et rend le second rollback explicite.

## Validation exécutée

- contrats bootstrap + TaskLaunch : **73 tests passés** ;
- bootstrap, launch pull/prepare/execute isolés des fixtures PostgreSQL :
  **66 tests passés** avant le durcissement ;
- bootstrap/rollback après durcissement : **36 tests passés** ;
- onboarding multi-harness et adapters Claude/OpenCode/Codex : **41 tests
  passés** ;
- `ruff check` et `ruff format --check` ciblés : propres.

Les suites API/MCP PostgreSQL (`test_task_launches.py`, `test_coordination.py`,
`test_coordinate.py`) ont été auditées mais pas réexécutées : Docker Desktop et
le serveur PostgreSQL de test sont indisponibles sur ce poste. La dernière CI de
`origin/dev` est verte, mais elle précède les corrections à venir listées ici.
