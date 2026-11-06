# P1.6 — baseline

Date : 05/11/2026 (Europe/Paris). Périmètre de cette première passe : état initial et diagnostic causal de F01/F02. Aucun fichier préexistant modifié avant la baseline.

## Git et préservation

- Branche `dev`, HEAD `d5912008bf8847835d454d3af5083a779909754c`, index vide; branche en retard de neuf commits sur `origin/dev` au relevé.
- Trois worktrees : dépôt principal; `wt-compact` détaché, HEAD `18c14aede157fc32e6b22d54e6b22d54aee29b0`; `.worktrees/bina-monitor-caddy`, HEAD `7e6b92a998b5d362d911f96b7d0b93f358cd8c7c`.
- Le dépôt contient déjà les changements non commités P0/P1/P1.5 (58 fichiers suivis modifiés et plusieurs fichiers/répertoires non suivis). Ils sont antérieurs à P1.6 et restent protégés; aucune remise à zéro, suppression, commit ou régénération n’a été faite.
- Recalcul SHA-256 des chemins enregistrés dans `validation-p1-e2e/traces/baseline.json` : 2 328 chemins vérifiés, 0 différent et 0 absent. `preservation.json` confirme aussi que HEAD, index et worktrees correspondaient à la baseline de fin P1.5.
- Aucun processus PostgreSQL, Docker, OpenCode, Claude ou Codex n’était visible pendant le relevé. Les ports PostgreSQL de test 5432 et MinIO 9000 n’étaient pas accessibles.

## État Studio OS

Projet `studio-os` identifié (`2a836038-153c-41cf-879a-73bd794760b0`). Aucune tâche P1.6 correspondante n’apparaît dans l’état actif. Le contexte a été lu via `studio_prepare_context` uniquement; aucune session, claim, tâche ou journal n’a été créé. La mission interdit les mutations d’un MCP distant; le suivi Studio OS reste donc en lecture seule.

## Baseline P1.5 et isolation

Les essais historiques expurgés dans `validation-p1-e2e/traces/` servent au diagnostic, jamais comme preuve d’après-correction. Versions rapportées : Claude Code 2.1.316, Codex CLI 0.166.0-alpha.6, OpenCode 1.18.32. Fixture `p15-e2e` sur PostgreSQL temporaire; API distante non attestée API 5; MinIO indisponible; aucun mutant envoyé au serveur distant.

Mise à jour après les essais : le cluster PostgreSQL existant de P1.5 a été démarré de façon réversible, sans changer ses données P1.5; la base dédiée `studio_p16_test` a servi aux tests d’intégration et aux trois runs OpenCode. Les seules mutations sont celles de trois tâches isolées de fixture P1.6. Le port 5432 et MinIO restent indisponibles; `scripts/test-env.ps1` demeure bloqué par MinIO. Aucun MCP distant n’a été appelé.

## Sources

- `validation-p1-e2e/E2E-BASELINE.md`, `E2E-FINDINGS.md`, `E2E-RESULTS.md`, `E2E-FINAL.md`.
- Traces `baseline.json`, `preservation.json`, `state-before.json`, `state-after-readonly.json`, `analysis.json`.
- Traces OpenCode `initial-opencode-readonly.jsonl`, `opencode-readonly.jsonl`, `opencode-readonly-paths-fixed.jsonl`; suivis `claude-tracked.jsonl`, `codex-tracked.jsonl`, `opencode-tracked-paths-fixed.jsonl`.
- Contrats/sources locales : `.agents/skills/studio-task/SKILL.md`, `.agents/skills/studio-handoff/SKILL.md`, `services/api/src/studio_api/services/sync.py`, `services/api/src/studio_api/services/sessions.py`, `services/api/src/studio_api/services/handoff.py`, `services/mcp/src/studio_mcp/server.py`.
