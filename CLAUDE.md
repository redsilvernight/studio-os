# Studio OS

Français par défaut ; code, chemins, commandes et identifiants restent dans leur langue.

@.studio/studio-protocol.md

- Ce fichier ne dit rien de l'état courant : le contexte vient du mode d'entrée défini dans ce protocole, pas d'un balayage du dépôt, du vault ou de la documentation. En cas de conflit : contrats et décisions validés > état Studio OS > Git > Graphify > mémoire.
- Rules, skills et agents canoniques : Library Studio OS (skills à lire à la demande dans `.claude/skills/<nom>/SKILL.md`). `.claude/`, `.codex/`, `.opencode/` et le bloc généré d'`AGENTS.md` sont des projections : ne pas les éditer, régénérer par `studio-client bootstrap sync --project-id <id>` puis `studio-client adapters check --project-id <id>`.
- Graphify, vault AI-Memory et documentation (routage : `docs/Studio_OS_Documentation_Pack/studio_os_docs/00_README.md`) : à la demande seulement ; Graphify uniquement via `scripts/graphify-studio.ps1` et son skill.
- Git : préserver les changements existants ; ni reset, rebase, force-push ni suppression de branche sans confirmation. Ne jamais affirmer une validation (PostgreSQL, MinIO, Docker, tests) qui n'a pas été exécutée.
