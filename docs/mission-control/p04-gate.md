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

## Lancements profilés réels (15 octobre 2026)

Pile jetable `studio-gate-demo` (API 127.0.0.1:8865, migrations 0035) et
daemon isolé (`APPDATA` dédié, politique locale `permissions: ["read"]`),
branche `task/f33a3c2d-launch-profile`. Agent de Bibliothèque `p04-architect`.

- Refus API avant enregistrement : `422 unknown_profile` (profil inconnu),
  `422 profile_requires_agent` (profil sans agent).
- `architecture-read-only` sur `claude-code` 2.1.287 : `succeeded`, snapshot
  `capture ok`, résolution agent v1 et pin de profil, bloc `applied` avec
  `access_mode: read_only` et le même pin ; worktree sans commit ni
  modification.
- `coding` sur `claude-code` : refus local
  `[studio:profile_refused] reason=permission_denied denied=write,execute,launch`.
- `architecture-read-only` sur `opencode` : refus local
  `[studio:profile_refused] reason=read_only_unsupported mode=read_only`.
- Provenance : publication et activation de `p04-architect` v2 ; le snapshot
  du premier lancement est identique octet pour octet (`content_hash`
  inchangé). L'aperçu de rejeu rend `limited`, l'agent `v1 → v2` `changed`,
  et les limitations `git_state_not_pinned`, `output_not_reproducible`,
  `profile_rechecked_on_machine`.
- Rejeu confirmé (`retry` avec `snapshot_content_hash` et `preview_digest`) :
  nouveau lancement `succeeded` en `read_only`, résolu sur la v2 ; le digest du
  pin change, car il compose la version de l'agent.
- Défaut trouvé et corrigé (`85804667`) : la configuration MCP isolée
  reprenait l'URL de l'entrée utilisateur, et le jeton éphémère du lancement
  partait vers un autre serveur. Elle vise maintenant le serveur émetteur.

## Non démontré

- Protocole Studio de bout en bout dans un lancement : le rejeu appelle
  `studio_start_work` mais pas `studio_handoff` (`handoff_not_observed`),
  faute d'`agent_id` injecté. Le hook SessionStart du poste vise le serveur de
  production, pas la pile jetable. Corrigé depuis par `d943816c`
  (16 octobre) : l'instruction de lancement injecte l'`agent_id` du serveur
  émetteur, prioritaire sur le hook. Pas encore redémontré dans un lancement
  profilé avec handoff observé.
- Revue humaine.

Preuves : `output/gate-demo-local/` (`p04-*.txt`, `snapshot-*.json`,
`replay-preview-ro.json`), ignoré par Git.
