# P04-gate — profils et snapshots

Tâche `f33a3c2d-59bf-4e76-a5e0-ac485817421a`. Observation partielle du
14 octobre 2026, sur la pile locale de la démonstration P02 (DEC-0212), code
`dev` à `f3a12b3`. **Gate acceptée par l'humain le 19 octobre 2026, au vu de
la redémonstration ci-dessous.**

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

## Redémonstration (19 octobre 2026)

Même recette, code `dev` à `c80ce25f` (inclut `d943816c` et la PR #156).

- `architecture-read-only` sur `claude-code` 2.1.287 : `succeeded`, sans
  `handoff_not_observed`. Snapshot `capture ok`, `access_mode: read_only`.
- Protocole de bout en bout : `studio_start_work` avec l'`agent_id` du serveur
  émetteur, puis `studio_handoff` (`task_status=completed`) ; tâche `completed`,
  session `ended`.
- Rejeu confirmé (aperçu `limited`, mêmes trois limitations) : `succeeded` en
  `read_only`, second `studio_start_work` + `studio_handoff` avec le même
  `agent_id` ; deux sessions `ended` sur la tâche.
- Outils utilisés par l'agent, dans les deux lancements : `Glob`, `Read` et MCP Studio seulement.
  Worktree sans commit ni modification.
- `--tools Read,Grep,Glob` et `SendMessage` dans `--disallowedTools` : couverts
  par `tests/harness/test_claude_headless_env.py` et
  `tests/client/test_launch_profile_enforce.py` (33 passés), pas observés sur
  la ligne de commande du lancement.

## Non démontré

- `--tools` et `--disallowedTools` sur la ligne de commande réelle (couverts
  par tests seulement).

Preuves : `output/gate-demo-local/` (`p04-*.txt`, `p04-redemo-*.json`,
`snapshot-*.json`, `replay-preview-ro.json`), ignoré par Git.
