# P04-gate — profils et snapshots

Tâche `f33a3c2d-59bf-4e76-a5e0-ac485817421a`. Observation partielle du
14 octobre 2026, sur la pile locale de la démonstration P02 (DEC-0212), code
`dev` à `f3a12b3`. **Gate non acceptée ; aucun critère coché.**

## Observé

- Chacun des quatre lancements réels a un snapshot d'exécution enregistré par
  la machine au démarrage : `content_hash` sha256, rétention 90 jours, bloc
  `applied` (harness et version, `git_sha`, `git_dirty`, branche `task/*`,
  `local_policy_digest`, `access_mode`). Capture `partial` /
  `resolution_unavailable`, attendue pour des lancements sans agent.
- Aucun chemin absolu, jeton, en-tête Bearer ni mot de passe dans les quatre
  snapshots relus.
- Contrôle d'accès avec un compte de test non membre du projet (rôle
  `developer`) : liste des lancements, projet, lancement et snapshot répondent
  `403 forbidden` (`resource: project`, `action: read`) ; l'admin lit les
  quatre snapshots (`200`).

## Non démontré

- Mutation d'un profil sans effet sur l'historique : les lancements de démo
  n'avaient ni agent ni profil (`profile: null`). Il faut un lancement avec
  définition d'agent et profil, puis modifier le profil et relire le snapshot.
- Résolution explicable dans l'aperçu de lancement avec un agent réel.
- Revue humaine.

Preuves : `output/gate-demo-local/p04-acces-snapshots.txt`, ignoré par Git.
