# Studio OS

Français par défaut ; code, chemins, commandes et identifiants restent dans leur langue.

@.agents/rules/studio-protocol.md

- Ce fichier ne dit rien de l'état courant : le contexte vient de `studio_prepare_context`, pas d'un balayage du dépôt, du vault ou de la documentation. En cas de conflit : contrats et décisions validés > état Studio OS > Git > Graphify > mémoire.
- Rules, skills et agents canoniques : `.agents/` (skills à lire à la demande dans `.agents/skills/<nom>/SKILL.md`). `.claude/`, `.codex/`, `.opencode/` et le bloc généré d'`AGENTS.md` sont des projections : ne pas les éditer, régénérer puis `studio-client adapters check`.
- Graphify, vault AI-Memory et documentation (routage : `docs/Studio_OS_Documentation_Pack/studio_os_docs/00_README.md`) : à la demande seulement ; Graphify uniquement via `scripts/graphify-studio.ps1` et son skill.
- Git : préserver les changements existants ; ni reset, rebase, force-push ni suppression de branche sans confirmation. Ne jamais affirmer une validation (PostgreSQL, MinIO, Docker, tests) qui n'a pas été exécutée.
