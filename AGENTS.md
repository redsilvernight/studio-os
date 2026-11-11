# Studio OS — Codex

Français par défaut ; code, chemins, commandes et identifiants restent dans leur langue.

Avant tout travail non trivial, lire `.studio/studio-protocol.md` et appliquer son mode d'entrée — jamais un balayage large du dépôt.

- Ce fichier ne dit rien de l'état courant : le contexte vient du mode d'entrée défini dans ce protocole, pas d'un balayage du dépôt, du vault ou de la documentation. En cas de conflit : contrats et décisions validés > état Studio OS > Git > Graphify > mémoire.
- Rules, skills et agents canoniques : `.agents/` (skills à lire à la demande dans `.agents/skills/<nom>/SKILL.md`). `.claude/`, `.codex/`, `.opencode/` et le bloc généré ci-dessous (marqueurs `GENERATED RULES`) sont des projections : ne pas les éditer, régénérer puis `studio-client adapters check`.
- Graphify, vault AI-Memory et documentation (routage : `docs/Studio_OS_Documentation_Pack/studio_os_docs/00_README.md`) : à la demande seulement ; Graphify uniquement via `scripts/graphify-studio.ps1` et son skill.
- Git : préserver les changements existants ; ni reset, rebase, force-push ni suppression de branche sans confirmation. Ne jamais affirmer une validation (PostgreSQL, MinIO, Docker, tests) qui n'a pas été exécutée.
- Délégation locale : `~/.codex/AGENTS.md` et skill `local-delegation` ; code Godot : agent global `godot-tester` (ne pas en recréer un ici).

<!-- BEGIN GENERATED RULES from .agents/rules -->
# Project rules (studio-client)

Read `.studio/studio-protocol.md` before any task.

Canonical rules live in `.agents/rules/`; before editing a path, read the rules whose `applies_to` front matter matches it (scopes are not automatic in every harness).
<!-- END GENERATED RULES -->
