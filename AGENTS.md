# Studio OS — Codex

Français par défaut ; code, chemins, commandes et identifiants restent dans leur langue.

Avant tout travail non trivial, lire `.agents/rules/studio-protocol.md` et appliquer son mode d'entrée — jamais un balayage large du dépôt.

- Ce fichier ne dit rien de l'état courant : le contexte vient du mode d'entrée défini dans ce protocole, pas d'un balayage du dépôt, du vault ou de la documentation. En cas de conflit : contrats et décisions validés > état Studio OS > Git > Graphify > mémoire.
- Rules, skills et agents canoniques : `.agents/` (skills à lire à la demande dans `.agents/skills/<nom>/SKILL.md`). `.claude/`, `.codex/`, `.opencode/` et le bloc généré ci-dessous (marqueurs `GENERATED RULES`) sont des projections : ne pas les éditer, régénérer puis `studio-client adapters check`.
- Graphify, vault AI-Memory et documentation (routage : `docs/Studio_OS_Documentation_Pack/studio_os_docs/00_README.md`) : à la demande seulement ; Graphify uniquement via `scripts/graphify-studio.ps1` et son skill.
- Git : préserver les changements existants ; ni reset, rebase, force-push ni suppression de branche sans confirmation. Ne jamais affirmer une validation (PostgreSQL, MinIO, Docker, tests) qui n'a pas été exécutée.
- Délégation locale : `~/.codex/AGENTS.md` et skill `local-delegation` ; code Godot : agent global `godot-tester` (ne pas en recréer un ici).

<!-- BEGIN GENERATED RULES from .agents/rules -->
# Project rules (studio-client)

# Studio Protocol — minimal permanent rule (canonical)

Studio OS is the persistent memory; LLM context is a temporary cache.

1. Explicit read-only intent is decisive: an audit or observation request uses `studio_prepare_context` and read tools only, even if a task ID or agent ID is supplied. Never start, claim, sync, hand off or write during that audit. Classify intent before choosing a tool.
2. Mutable tracked work: `studio_start_work` once (task, session, context, sync).
3. Load only what is needed: `why` / `matched_terms`, `additional_available` / `omitted_for_budget`. Refresh via `studio_prepare_context`.
4. Follow `studio-task`; group needed claims; `studio_sync` at boundaries: deduplicate event_id, process durably, then ack. Handoff never auto-acks.
5. Replay writes with `idempotency_key`; on 409 reread, merge, retry with `expected_version`.
6. Persist decisions via `studio_add_decision`; resolve only when entitled.
7. Load definitions on demand: `studio_discover_definitions`, `studio_resolve_agent`.
8. One agent by default; subagent on a real trigger. Tracked completed tasks require real completion evidence via `studio_handoff`; failed mandatory checks forbid completion. Separate implemented/tested/integrated/deployed.

Before editing matching paths, read the canonical rule below; scopes are not automatic in every harness.

- `.agents/rules/contracts.md` — applies to ["**/schemas/**/*.py", "**/contracts/**/*.py", "**/*_contract*.py", "**/*contract*.py", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/02_API_CONTRACT.md", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/03_EVENT_CONTRACT.md", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/04_AUTH_SYNC_CONTRACT.md", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/05_DATA_MODEL.md"]

- `.agents/rules/database.md` — applies to ["**/alembic/**/*.py", "**/migrations/**/*.py", "**/models/**/*.py"]

- `.agents/rules/mcp-tools.md` — applies to ["**/mcp/**/*.py", "**/mcp_server/**/*.py", "**/*mcp*tool*.py"]

- `.agents/rules/offline-sync.md` — applies to ["**/daemon/**/*.py", "**/offline/**/*.py", "**/sync/**/*.py", "**/queue/**/*.py", "**/outbox/**/*.py"]

- `.agents/rules/python-conventions.md` — applies to ["**/*.py"]

- `.agents/rules/storage-transfers.md` — applies to ["**/transfer*/**/*.py", "**/storage/**/*.py", "**/*transfer*.py", "**/*multipart*.py"]

- `.agents/rules/testing.md` — applies to ["tests/**/*.py", "pyproject.toml", "services/*/pyproject.toml"]
<!-- END GENERATED RULES -->
