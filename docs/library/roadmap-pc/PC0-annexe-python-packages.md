# PC0 — Annexe : code Python mort des paquets

Branche `dev`, audit initial sur `6fa6fa78`, revalidé sur `f099ef02` (2026-11-14). Aucun fichier source modifié. Périmètre : sources `src/` de `packages/studio-client`, `studio-contracts`, `studio-code-graph`, `studio-workspaces` (tests = références uniquement).

Classes : **sûr** = aucune référence hors définition et aucun mécanisme dynamique plausible ; **à vérifier** = utilisé seulement par des tests, écrit jamais lu, ou doute ; **contrat public** = symbole de `studio_contracts` sans consommateur applicatif mais exposé/testé/documenté comme contrat.


## Revalidation sur f099ef02

`f099ef02` déplace le moteur de fusion à trois voies de `studio_client/library_merge.py` vers `studio_contracts/library_merge.py` (nouveau, 242 l.). L'ancien module devient une réexportation de 19 lignes. Le moteur est désormais appelé par l'API (`services/api/src/studio_api/services/library.py:44` import, `:329` appel) pour `GET /library/{id}/merge-preview`.

| élément | avant (`6fa6fa78`) | après (`f099ef02`) | preuve | classe |
|---|---|---|---|---|
| `merge_texts` | `studio_client/library_merge.py:72`, tests seulement | `studio_contracts/library_merge.py:72` | `git grep -nw merge_texts` : 36 lignes ; `services/api/src/studio_api/services/library.py:44,329` | à vérifier → **faux positif** (utilisé hors paquet) |
| `start_line`, `base_start`, `base_end` | `studio_client/library_merge.py:39-41`, tests seulement | `studio_contracts/library_merge.py:39-41` | champs de dataclass sérialisés par `asdict(result)` vers `LibraryMergeResult` (`services/library.py:332`), affichés par `dashboard/src/views/libraryMerge.ts` | à vérifier → **faux positif** (champ sérialisé) |
| `has_conflicts` | `studio_client/library_merge.py:54` | `studio_contracts/library_merge.py:54` | `git grep -nw has_conflicts` : 17 lignes, définition + 16 dans `tests/client/test_library_merge.py` | à vérifier (déplacé : compté dans studio-contracts) |
| module `studio_client/library_merge.py` | 242 l., importé seulement par les tests | 19 l. (réexportation) | seul importeur : `tests/client/test_library_merge.py:6` | à vérifier (19 l. au lieu de 242) |
| `start_line`, `base_start`, `base_end`, `result` | — | `studio_contracts/library.py:229-231, 241` | champs Pydantic de `LibraryMergeConflict` et `LibraryMergePreview` (contrat d'API) | nouveau, faux positif (Pydantic) |
| `LibraryMergePreview` | — | `studio_contracts/library.py:239` | `response_model` de `routers/library.py:186`, construit par `services/library.py:330` | nouveau, faux positif (utilisé hors paquet) |
| `position` ×2 | `studio_contracts/roadmaps.py:510,535`, faux positif Pydantic | non signalé | homonyme `position` désormais présent dans `library_merge.py:95` | retiré des candidats |

Décomptes vulture : studio-client 121 → 116, studio-contracts 1567 → 1575 ; studio-code-graph et studio-workspaces inchangés (aucun fichier modifié). Numéros de ligne mis à jour : `api_client.py` (+1 après l'ajout d'une méthode), `local/fixtures.py:1741` → 1742, `library.py:989` → 1011. Les autres candidats sûrs ou à vérifier ont été revérifiés par `git grep -nw <nom>` sur les deux commits. Les seuls autres écarts sont des numéros de ligne dans des fichiers générés (`dashboard/openapi.json`, `openapi-schema.ts`) et des homonymes. Sauf mention contraire, les numéros de ligne des listes de faux positifs se lisent sur `6fa6fa78`.

## studio-client

Candidats vulture ≥60 : **116** sur `f099ef02` (121 sur `6fa6fa78` ; 5 candidats partis avec `library_merge` dans studio-contracts) — sûr 21, à vérifier 59, contrat public 0, faux positifs écartés 36.

| symbole ou fichier | chemin:ligne | vulture | preuve (commande + résultat) | classe | note |
|---|---|---|---|---|---|
| `list_producer_jobs` (method, 8 l.) | `studio_client/api_client.py:572` | 60% | `git grep -nE "\.list_producer_jobs\(" -- '*.py'` : 1 ligne, `producer_service` côté API (homonyme) | **sûr** | aucun appel `.list_producer_jobs(` sur le client ; homonyme serveur `producer_service.list_producer_jobs` distinct |
| `list_transfers` (method, 6 l.) | `studio_client/api_client.py:608` | 60% | `git grep -nE "\.list_transfers\(" -- '*.py'` : 2 lignes, `transfers_service` API/MCP (homonymes) | **sûr** | aucun appel client ; homonymes `transfers_service.list_transfers` (API/MCP) distincts |
| `get_transfer_consumption` (method, 8 l.) | `studio_client/api_client.py:619` | 60% | `git grep -nw get_transfer_consumption` : 3 lignes au total ; hors définition → docs 2 (ex. docs/DEC_EXPORT.json:365) | **sûr** | seulement 2 mentions en docs |
| `SERVER_UNREACHABLE` (variable, 1 l.) | `studio_client/context/errors.py:13` | 60% | `git grep -nw SERVER_UNREACHABLE` : 1 ligne(s), définition seule | **sûr** | constante jamais lue ; la valeur littérale "server_unreachable" est réécrite en dur (daemon/enrollment.py:126) |
| `INVALID_PROJECT` (variable, 1 l.) | `studio_client/context/errors.py:14` | 60% | `git grep -nw INVALID_PROJECT` : 1 ligne(s), définition seule | **sûr** | constante de classe jamais lue |
| `BUDGET_EXCEEDED` (variable, 1 l.) | `studio_client/context/errors.py:15` | 60% | `git grep -nw BUDGET_EXCEEDED` : 1 ligne(s), définition seule | **sûr** | constante de classe jamais lue |
| `package_size_bytes` (method, 3 l.) | `studio_client/context/manifest.py:100` | 60% | `git grep -nw package_size_bytes` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `DriftKind` (variable, 1 l.) | `studio_client/drift.py:36` | 60% | `git grep -nw DriftKind` : 1 ligne(s), définition seule | **sûr** | alias de type jamais utilisé |
| `LIBRARY_PROVENANCE_PREFIX` (variable, 1 l.) | `studio_client/drift.py:47` | 60% | `git grep -nw LIBRARY_PROVENANCE_PREFIX` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `first_heading_line` (property, 3 l.) | `studio_client/knowledge/markdown.py:63` | 60% | `git grep -nw first_heading_line` : 1 lignes au total ; hors définition → py 1 (ex. packages/studio-client/src/studio_client/knowledge/markdown.py:64) | **sûr** | aucune référence |
| `parse_line_fragment` (function, 8 l.) | `studio_client/knowledge/markdown.py:230` | 60% | `git grep -nw parse_line_fragment` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `MIRROR_FILENAME` (variable, 1 l.) | `studio_client/knowledge/server_mirror.py:34` | 60% | `git grep -nw MIRROR_FILENAME` : 1 ligne(s), définition seule | **sûr** | aucune référence (module lui-même testé seulement) |
| `INDEX_DIRECTORY_SUFFIX` (variable, 1 l.) | `studio_client/knowledge/service.py:16` | 60% | `git grep -nw INDEX_DIRECTORY_SUFFIX` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `DEFAULT_EXPOSED_PREFIXES` (variable, 1 l.) | `studio_client/knowledge/vault.py:25` | 60% | `git grep -nw DEFAULT_EXPOSED_PREFIXES` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `is_readable_directory` (function, 6 l.) | `studio_client/knowledge/vault.py:185` | 60% | `git grep -nw is_readable_directory` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `read_markdown` (function, 2 l.) | `studio_client/knowledge/vault.py:254` | 60% | `git grep -nw read_markdown` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `publish_items` (function, 53 l.) | `studio_client/publish.py:107` | 60% | `git grep -nw publish_items` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `active_recording` (method, 2 l.) | `studio_client/recording/recording.py:164` | 60% | `git grep -nw active_recording` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `certified` (method, 2 l.) | `studio_client/usage/collectors/__init__.py:81` | 60% | `git grep -nE "\.certified\("` : 0 ligne (les 7 lignes de `-nw` sont prose/docstring) | **sûr** | aucun appel `.certified(` ; seules des occurrences du mot en docstring |
| `for_harness` (method, 2 l.) | `studio_client/usage/collectors/__init__.py:84` | 60% | `git grep -nw for_harness` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `CERTIFIED_HARNESS_SERIES` (variable, 1 l.) | `studio_client/usage/collectors/claude_code.py:37` | 60% | `git grep -nw CERTIFIED_HARNESS_SERIES` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `classify_artifact_state` (function, 15 l.) | `studio_client/adapters/base.py:73` | 60% | `git grep -nw classify_artifact_state` : 6 lignes au total ; hors définition → tests 5 (ex. tests/harness/test_drift_taxonomy.py:6) | **à vérifier** | tests seulement (tests/harness/test_drift_taxonomy.py) |
| `model_agent_create` (function, 12 l.) | `studio_client/agent_identity.py:42` | 60% | `git grep -nw model_agent_create` : 8 lignes au total ; hors définition → tests 7 (ex. tests/client/test_agent_identity.py:12) | **à vérifier** | tests seulement |
| `is_legacy_model_key` (function, 9 l.) | `studio_client/agent_identity.py:56` | 60% | `git grep -nw is_legacy_model_key` : 8 lignes au total ; hors définition → tests 7 (ex. tests/client/test_agent_identity.py:11) | **à vérifier** | tests seulement |
| `healthz` (method, 3 l.) | `studio_client/api_client.py:203` | 60% | `git grep -nw healthz` : 119 lignes au total ; hors définition → autres 49, docs 44, py 9, tests 16 (ex. packages/studio-client/src/studio_client/api_client.py:203) | **à vérifier** | tests seulement (tests/client/test_api_client.py:100) |
| `server_version` (method, 6 l.) | `studio_client/api_client.py:207` | 60% | `git grep -nw server_version` : 278 lignes au total ; hors définition → autres 142, docs 59, py 41, tests 35 (ex. docs/audits/studios-agent-workflow/implementation-p1/baseline-files/tests/api/test_p0_task_concurrency.py:110) | **à vérifier** | tests seulement (tests/client/test_api_client.py:725) |
| `register_agent` (method, 9 l.) | `studio_client/api_client.py:290` | 60% | `git grep -nw register_agent` : 6 lignes au total ; hors définition → docs 3, py 1, tests 1 (ex. services/api/src/studio_api/routers/agents.py:117) | **à vérifier** | tests seulement (tests/client/test_agents_ensure.py:164) |
| `create_transfer` (method, 11 l.) | `studio_client/api_client.py:596` | 60% | `git grep -nw create_transfer` : 20 lignes au total ; hors définition → docs 11, py 4, tests 4 (ex. services/api/src/studio_api/routers/transfers.py:78) | **à vérifier** | tests seulement (tests d'acceptation transferts) |
| `handoff` (method, 12 l.) | `studio_client/api_client.py:738` | 60% | `git grep -nw handoff` : 1189 lignes au total ; hors définition → autres 81, docs 897, py 77, tests 133 (ex. docs/audits/studios-agent-workflow/implementation-p1/baseline-files/tests/mcp/test_handoff.py:2) | **à vérifier** | tests seulement (tests/client/test_api_client.py:81) ; nom très générique |
| `plan_divergences` (function, 29 l.) | `studio_client/bootstrap.py:353` | 60% | `git grep -nw plan_divergences` : 6 lignes au total ; hors définition → tests 5 (ex. tests/client/test_bootstrap_p51_divergence.py:16) | **à vérifier** | tests seulement (tests/client/test_bootstrap_p51_divergence.py) |
| `_json_size` (function, 2 l.) | `studio_client/context/composer.py:27` | 60% | `git grep -nw _json_size` : 6 lignes au total ; hors définition → tests 5 (ex. tests/client/context/test_context_composer.py:13) | **à vérifier** | tests seulement (tests/client/context/test_context_library_p9.py) |
| `export_diagnostics` (function, 24 l.) | `studio_client/daemon/logging.py:78` | 60% | `git grep -nw export_diagnostics` : 15 lignes au total ; hors définition → autres 10, docs 2, tests 2 (ex. tests/client/test_daemon_logging.py:12) | **à vérifier** | tests seulement ; homonyme commande Tauri Rust (desktop/src-tauri/src/shell_commands.rs:246) qui ne l'appelle pas |
| `_auto_sync_runner` (attribute, 1 l.) | `studio_client/daemon/runtime.py:344` | 60% | `git grep -nw _auto_sync_runner` : 2 lignes au total ; hors définition → py 1 (ex. packages/studio-client/src/studio_client/daemon/runtime.py:592) | **à vérifier** | attribut écrit jamais lu ; peut servir à garder une référence forte sur le runner d'auto-sync |
| `_auto_sync_runner` (attribute, 1 l.) | `studio_client/daemon/runtime.py:592` | 60% | `git grep -nw _auto_sync_runner` : 2 lignes au total ; hors définition → py 1 (ex. packages/studio-client/src/studio_client/daemon/runtime.py:344) | **à vérifier** | idem (affectation dans run) |
| `WorkspaceWatch` (class, 1 l.) | `studio_client/daemon/workspace_watch.py:74` | 60% | `git grep -nw WorkspaceWatch` : 11 lignes au total ; hors définition → docs 1, py 1, tests 9 (ex. packages/studio-client/src/studio_client/daemon/workspace_watch.py:75) | **à vérifier** | tests seulement (tests/code_graph/test_git_integration.py) |
| `client_version` (property, 4 l.) | `studio_client/errors.py:59` | 60% | `git grep -nw client_version` : 23 lignes au total ; hors définition → autres 3, docs 2, py 16, tests 2 (ex. packages/studio-client/src/studio_client/errors.py:60) | **à vérifier** | tests seulement (tests/client/test_api_client.py:684) |
| `minimum_supported` (property, 4 l.) | `studio_client/errors.py:64` | 60% | `git grep -nw minimum_supported` : 36 lignes au total ; hors définition → autres 10, docs 9, py 10, tests 7 (ex. packages/studio-client/src/studio_client/errors.py:52) | **à vérifier** | tests seulement |
| `remaining_bytes` (property, 15 l.) | `studio_client/errors.py:78` | 60% | `git grep -nw remaining_bytes` : 50 lignes au total ; hors définition → autres 25, docs 13, py 8, tests 4 (ex. packages/studio-client/src/studio_client/errors.py:79) | **à vérifier** | tests seulement |
| `is_current` (property, 5 l.) | `studio_client/hook_sync.py:153` | 60% | `git grep -nw is_current` : 2 lignes au total ; hors définition → py 1, tests 1 (ex. packages/studio-client/src/studio_client/hook_sync.py:154) | **à vérifier** | tests seulement |
| `AGENT_STORE_REL` (variable, 1 l.) | `studio_client/hooks.py:8` | 60% | `git grep -nw AGENT_STORE_REL` : 4 lignes au total ; hors définition → tests 3 (ex. tests/client/test_setup_hooks.py:19) | **à vérifier** | tests seulement (tests/client/test_setup_hooks.py) |
| `refresh_graph` (method, 1 l.) | `studio_client/knowledge/graph.py:63` | 60% | `git grep -nw refresh_graph` : 15 lignes au total ; hors définition → docs 12, py 1, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/graph.py:319) | **à vérifier** | méthode du Protocol GraphProvider ; tests seulement |
| `refresh_graph` (method, 9 l.) | `studio_client/knowledge/graph.py:319` | 60% | `git grep -nw refresh_graph` : 15 lignes au total ; hors définition → docs 12, py 1, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/graph.py:63) | **à vérifier** | implémentation Graphify ; tests seulement |
| `propose` (method, 1 l.) | `studio_client/knowledge/memory.py:54` | 60% | `git grep -nw propose` : 117 lignes au total ; hors définition → autres 32, docs 46, py 10, tests 28 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:216) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `write_if_authorized` (method, 1 l.) | `studio_client/knowledge/memory.py:55` | 60% | `git grep -nw write_if_authorized` : 14 lignes au total ; hors définition → docs 9, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:222) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `append_task_log` (method, 1 l.) | `studio_client/knowledge/memory.py:56` | 60% | `git grep -nw append_task_log` : 13 lignes au total ; hors définition → docs 8, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:228) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `create_decision_note` (method, 1 l.) | `studio_client/knowledge/memory.py:57` | 60% | `git grep -nw create_decision_note` : 13 lignes au total ; hors définition → docs 8, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:234) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `propose` (method, 5 l.) | `studio_client/knowledge/memory.py:216` | 60% | `git grep -nw propose` : 117 lignes au total ; hors définition → autres 32, docs 46, py 10, tests 28 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:54) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `write_if_authorized` (method, 5 l.) | `studio_client/knowledge/memory.py:222` | 60% | `git grep -nw write_if_authorized` : 14 lignes au total ; hors définition → docs 9, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:55) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `append_task_log` (method, 5 l.) | `studio_client/knowledge/memory.py:228` | 60% | `git grep -nw append_task_log` : 13 lignes au total ; hors définition → docs 8, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:56) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `create_decision_note` (method, 5 l.) | `studio_client/knowledge/memory.py:234` | 60% | `git grep -nw create_decision_note` : 13 lignes au total ; hors définition → docs 8, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:57) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `registered_vaults` (variable, 1 l.) | `studio_client/knowledge/obsidian.py:41` | 60% | `git grep -nw registered_vaults` : 3 lignes au total ; hors définition → py 2 (ex. packages/studio-client/src/studio_client/knowledge/obsidian.py:121) | **à vérifier** | champ dataclass rempli (obsidian.py:121,128) mais jamais lu |
| `launched` (variable, 1 l.) | `studio_client/knowledge/obsidian.py:48` | 60% | `git grep -nw launched` : 49 lignes au total ; hors définition → autres 6, docs 1, py 22, tests 19 (ex. packages/studio-client/src/studio_client/daemon/launch_runner.py:1) | **à vérifier** | tests seulement (tests/knowledge/test_obsidian.py) |
| `propose` (method, 5 l.) | `studio_client/knowledge/provider.py:648` | 60% | `git grep -nw propose` : 117 lignes au total ; hors définition → autres 32, docs 46, py 10, tests 28 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:54) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `write_if_authorized` (method, 5 l.) | `studio_client/knowledge/provider.py:654` | 60% | `git grep -nw write_if_authorized` : 14 lignes au total ; hors définition → docs 9, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:55) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `append_task_log` (method, 5 l.) | `studio_client/knowledge/provider.py:660` | 60% | `git grep -nw append_task_log` : 13 lignes au total ; hors définition → docs 8, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:56) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `create_decision_note` (method, 5 l.) | `studio_client/knowledge/provider.py:666` | 60% | `git grep -nw create_decision_note` : 13 lignes au total ; hors définition → docs 8, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:57) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `last_synced_at` (variable, 1 l.) | `studio_client/knowledge/server_mirror.py:104` | 60% | `git grep -nw last_synced_at` : 9 lignes au total ; hors définition → py 6, tests 2 (ex. packages/studio-client/src/studio_client/knowledge/server_mirror.py:109) | **à vérifier** | tests seulement (module server_mirror testé seulement) |
| `last_synced_at` (variable, 1 l.) | `studio_client/knowledge/server_mirror.py:109` | 60% | `git grep -nw last_synced_at` : 9 lignes au total ; hors définition → py 6, tests 2 (ex. packages/studio-client/src/studio_client/knowledge/server_mirror.py:104) | **à vérifier** | tests seulement |
| `list_notes` (method, 33 l.) | `studio_client/knowledge/server_mirror.py:405` | 60% | `git grep -nw list_notes` : 4 lignes au total ; hors définition → py 1, tests 2 (ex. packages/studio-client/src/studio_client/knowledge/server_mirror.py:130) | **à vérifier** | tests seulement |
| `ServerMirrorMemoryProvider` (class, 1 l.) | `studio_client/knowledge/server_mirror.py:565` | 60% | `git grep -nw ServerMirrorMemoryProvider` : 5 lignes au total ; hors définition → tests 4 (ex. tests/client/test_vault_mirror.py:16) | **à vérifier** | tests seulement (tests/client/test_vault_mirror.py) |
| `propose` (method, 5 l.) | `studio_client/knowledge/server_mirror.py:634` | 60% | `git grep -nw propose` : 117 lignes au total ; hors définition → autres 32, docs 46, py 10, tests 28 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:54) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `write_if_authorized` (method, 5 l.) | `studio_client/knowledge/server_mirror.py:640` | 60% | `git grep -nw write_if_authorized` : 14 lignes au total ; hors définition → docs 9, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:55) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `append_task_log` (method, 5 l.) | `studio_client/knowledge/server_mirror.py:646` | 60% | `git grep -nw append_task_log` : 13 lignes au total ; hors définition → docs 8, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:56) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `create_decision_note` (method, 5 l.) | `studio_client/knowledge/server_mirror.py:652` | 60% | `git grep -nw create_decision_note` : 13 lignes au total ; hors définition → docs 8, py 3, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/memory.py:57) | **à vérifier** | Protocol MemoryProvider et implémentations : tests seulement (tests/client/test_knowledge_memory.py, test_vault_mirror.py) |
| `detach` (method, 4 l.) | `studio_client/knowledge/service.py:33` | 60% | `git grep -nw detach` : 22 lignes au total ; hors définition → autres 13, docs 3, py 4, tests 1 (ex. packages/studio-contracts/src/studio_contracts/auth.py:172) | **à vérifier** | tests seulement (tests/knowledge/test_service.py:70) |
| `VaultWriteQueue` (class, 1 l.) | `studio_client/knowledge/vault_outbox.py:24` | 60% | `git grep -nw VaultWriteQueue` : 4 lignes au total ; hors définition → tests 3 (ex. tests/client/test_vault_outbox.py:18) | **à vérifier** | tests seulement (module importé seulement par tests/client/test_vault_outbox.py) |
| `enqueue_create` (method, 14 l.) | `studio_client/knowledge/vault_outbox.py:36` | 60% | `git grep -nw enqueue_create` : 7 lignes au total ; hors définition → tests 6 (ex. tests/client/test_vault_outbox.py:145) | **à vérifier** | tests seulement |
| `enqueue_update` (method, 15 l.) | `studio_client/knowledge/vault_outbox.py:51` | 60% | `git grep -nw enqueue_update` : 4 lignes au total ; hors définition → tests 3 (ex. tests/client/test_vault_outbox.py:146) | **à vérifier** | tests seulement |
| `last_snapshot` (property, 3 l.) | `studio_client/knowledge/watch.py:46` | 60% | `git grep -nw last_snapshot` : 2 lignes au total ; hors définition → py 1, tests 1 (ex. packages/studio-client/src/studio_client/knowledge/watch.py:47) | **à vérifier** | tests seulement |
| `attempt_count` (variable, 1 l.) | `studio_client/outbox/models.py:33` | 60% | `git grep -nw attempt_count` : 17 lignes au total ; hors définition → docs 1, py 9, tests 6 (ex. packages/studio-client/src/studio_client/outbox/store.py:37) | **à vérifier** | champ lu seulement par tests ; colonne SQLite vivante |
| `dead_lettered` (variable, 1 l.) | `studio_client/outbox/replay.py:51` | 60% | `git grep -nw dead_lettered` : 30 lignes au total ; hors définition → py 1, tests 28 (ex. packages/studio-client/src/studio_client/outbox/replay.py:172) | **à vérifier** | tests seulement |
| `stopped_on_transient_error` (variable, 1 l.) | `studio_client/outbox/replay.py:52` | 60% | `git grep -nw stopped_on_transient_error` : 21 lignes au total ; hors définition → docs 2, py 1, tests 17 (ex. packages/studio-client/src/studio_client/outbox/replay.py:150) | **à vérifier** | tests seulement |
| `stopped_on_transient_error` (attribute, 1 l.) | `studio_client/outbox/replay.py:150` | 60% | `git grep -nw stopped_on_transient_error` : 21 lignes au total ; hors définition → docs 2, py 1, tests 17 (ex. packages/studio-client/src/studio_client/outbox/replay.py:52) | **à vérifier** | tests seulement |
| `dead_lettered` (attribute, 1 l.) | `studio_client/outbox/replay.py:172` | 60% | `git grep -nw dead_lettered` : 30 lignes au total ; hors définition → py 1, tests 28 (ex. packages/studio-client/src/studio_client/outbox/replay.py:51) | **à vérifier** | tests seulement |
| `enqueue_marker` (method, 11 l.) | `studio_client/outbox/store.py:294` | 60% | `git grep -nw enqueue_marker` : 7 lignes au total ; hors définition → tests 6 (ex. tests/client/test_daemon_runtime.py:108) | **à vérifier** | tests seulement (tests/client/test_replay.py) |
| `start_recording` (method, 32 l.) | `studio_client/recording/recording.py:167` | 60% | `git grep -nw start_recording` : 9 lignes au total ; hors définition → tests 8 (ex. tests/client/test_recording_provider.py:81) | **à vérifier** | tests seulement |
| `finish_recording` (method, 21 l.) | `studio_client/recording/recording.py:200` | 60% | `git grep -nw finish_recording` : 6 lignes au total ; hors définition → docs 2, tests 3 (ex. tests/client/test_recording_provider.py:116) | **à vérifier** | tests seulement |
| `create_marketing_candidate` (method, 23 l.) | `studio_client/recording/recording.py:281` | 60% | `git grep -nw create_marketing_candidate` : 6 lignes au total ; hors définition → docs 2, tests 3 (ex. tests/client/test_recording_provider.py:252) | **à vérifier** | tests seulement |
| `plan_skill_uninstall` (function, 55 l.) | `studio_client/skill_sync.py:348` | 60% | `git grep -nw plan_skill_uninstall` : 11 lignes au total ; hors définition → docs 2, tests 8 (ex. tests/library_rebuild/test_package_lifecycle.py:9) | **à vérifier** | tests seulement (tests/library_rebuild/test_skill_files.py) |
| `upload` (method, 49 l.) | `studio_client/transfers.py:67` | 60% | `git grep -nw upload` : 1680 lignes au total ; hors définition → autres 1227, docs 250, py 79, tests 123 (ex. packages/studio-client/src/studio_client/api_client.py:635) | **à vérifier** | tests seulement ; TransferClient exporté dans studio_client.__all__ |

Modules entiers importés seulement par des tests (recherche d'imports AST absolus + relatifs sur tous les `.py`) :

| fichier | lignes | preuve | classe |
|---|---|---|---|
| `studio_client/knowledge/server_mirror.py` | 669 | importeurs src = 0 ; `git grep -nw server_mirror` hors tests : 0 ligne | **à vérifier** (tests seulement) |
| `studio_client/knowledge/vault_outbox.py` | 65 | importeurs src = 0 ; `git grep -nw vault_outbox` hors tests : 0 ligne | **à vérifier** (tests seulement) |
| `studio_client/library_merge.py` | 19 | `f099ef02` : réexportation de `studio_contracts.library_merge` (242 l. avant) ; importeurs src = 0 ; seul importeur `tests/client/test_library_merge.py:6` | **à vérifier** (tests seulement ; les tests peuvent importer `studio_contracts.library_merge`) |

`studio_client/cli.py` (2390 l.) n'a aucun importeur src : faux positif, c'est l'entry point `[project.scripts] studio-client = "studio_client.cli:main"` (et `studio-client-daemon = "studio_client.daemon.heartbeat:main"`).


## studio-contracts

Candidats vulture ≥60 : **1575** sur `f099ef02` (1567 sur `6fa6fa78`) — sûr 9, à vérifier 4, contrat public 16, faux positifs écartés 1546.

| symbole ou fichier | chemin:ligne | vulture | preuve (commande + résultat) | classe | note |
|---|---|---|---|---|---|
| `typed_payload` (method, 2 l.) | `studio_contracts/local/bridge.py:553` | 60% | `git grep -nw typed_payload` : 2 lignes au total ; hors définition → py 1 (ex. packages/studio-contracts/src/studio_contracts/local/bridge.py:571) | **sûr** | aucune référence hors l'autre définition homonyme |
| `typed_payload` (method, 2 l.) | `studio_contracts/local/bridge.py:571` | 60% | `git grep -nw typed_payload` : 2 lignes au total ; hors définition → py 1 (ex. packages/studio-contracts/src/studio_contracts/local/bridge.py:553) | **sûr** | idem |
| `MAX_READ_BYTES` (variable, 1 l.) | `studio_contracts/local/common.py:24` | 60% | `git grep -nw MAX_READ_BYTES` : 1 ligne(s), définition seule | **sûr** | aucune référence (ni Python, ni desktop, ni contracts/) |
| `semver_tuple` (function, 7 l.) | `studio_contracts/local/common.py:52` | 60% | `git grep -nw semver_tuple` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `LocalPath` (variable, 1 l.) | `studio_contracts/local/common.py:194` | 60% | `git grep -nw LocalPath` : 1 ligne(s), définition seule | **sûr** | alias Annotated jamais utilisé (le registre d'export ne collecte que des classes) |
| `SERVING_STATES` (variable, 1 l.) | `studio_contracts/local/common.py:345` | 60% | `git grep -nw SERVING_STATES` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `FAILURE_STATES` (variable, 1 l.) | `studio_contracts/local/common.py:346` | 60% | `git grep -nw FAILURE_STATES` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `as_component_state` (method, 2 l.) | `studio_contracts/local/daemon_control.py:171` | 60% | `git grep -nw as_component_state` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `parse_roadmap_document` (function, 6 l.) | `studio_contracts/roadmaps.py:436` | 60% | `git grep -nw parse_roadmap_document` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `LOCAL_CONTRACT_VERSION` (variable, 1 l.) | `studio_contracts/local/common.py:16` | 60% | `git grep -nw LOCAL_CONTRACT_VERSION` : 1 ligne(s), définition seule | **à vérifier** | aucune référence, mais constante de version du protocole studio.local |
| `wrong_action` (function, 2 l.) | `studio_contracts/local/fixtures.py:1742` | 60% | `git grep -nw wrong_action` : 1 ligne(s), définition seule | **à vérifier** | mutateur local jamais câblé dans build_invalid_fixtures (ses voisins le sont) : fixture invalide probablement oubliée |
| `ClientUpgradeRequired` (class, 1 l.) | `studio_contracts/version.py:25` | 60% | `git grep -nw ClientUpgradeRequired` : 1 ligne(s), définition seule | **à vérifier** | modèle jamais référencé (ni services, ni dashboard/openapi.json) ; probable corps de réponse 426 construit ailleurs à la main |
| `has_conflicts` (property, 3 l.) | `studio_contracts/library_merge.py:54` | 60% | `git grep -nw has_conflicts` : 17 lignes au total ; hors définition → tests 16 (ex. tests/client/test_library_merge.py:19) | **à vérifier** | tests seulement ; déplacé depuis `studio_client/library_merge.py` par `f099ef02` |
| `SUPPORTED_LAG` (variable, 1 l.) | `studio_contracts/compatibility.py:28` | 60% | `git grep -nw SUPPORTED_LAG` : 2 lignes au total ; hors définition → docs 1 (ex. docs/mission-control/promotion.md:107) | **contrat public** | module importé seulement par tests ; principe cité par DEC-0137 |
| `CHANNELS` (variable, 1 l.) | `studio_contracts/compatibility.py:31` | 60% | `git grep -nw CHANNELS` : 17 lignes au total ; hors définition → autres 16 (ex. desktop/scripts/build-policy.test.mjs:87) | **contrat public** | miroir dans desktop/scripts/*.mjs ; tests |
| `classify` (function, 11 l.) | `studio_contracts/compatibility.py:86` | 60% | `git grep -nw classify` : 52 lignes au total ; hors définition → autres 7, docs 3, py 1, tests 40 (ex. docs/audits/studios-agent-workflow/implementation-p1/baseline-files/tests/contracts/test_version_compatibility.py:19) | **contrat public** | tests seulement (tests/contracts/test_version_compatibility.py) |
| `CURRENT_VERSIONS` (variable, 1 l.) | `studio_contracts/compatibility.py:99` | 60% | `git grep -nw CURRENT_VERSIONS` : 5 lignes au total ; hors définition → tests 4 (ex. docs/audits/studios-agent-workflow/implementation-p1/baseline-files/tests/contracts/test_version_compatibility.py:16) | **contrat public** | tests seulement |
| `COORDINATION_INTENTS` (variable, 1 l.) | `studio_contracts/coordination.py:20` | 60% | `git grep -nw COORDINATION_INTENTS` : 3 lignes au total ; hors définition → autres 2 (ex. dashboard/src/views/activity.ts:100) | **contrat public** | mentionné par dashboard/src/views/activity.ts |
| `profile_drift` (property, 9 l.) | `studio_contracts/execution_snapshot.py:211` | 60% | `git grep -nw profile_drift` : 6 lignes au total ; hors définition → docs 1, py 1, tests 4 (ex. packages/studio-contracts/src/studio_contracts/execution_snapshot.py:212) | **contrat public** | tests seulement |
| `INITIALIZATION_FORMAT` (variable, 1 l.) | `studio_contracts/initialization.py:45` | 60% | `git grep -nw INITIALIZATION_FORMAT` : 4 lignes au total ; hors définition → py 1, tests 2 (ex. packages/studio-contracts/src/studio_contracts/initialization.py:19) | **contrat public** | tests seulement |
| `validate_library_content` (function, 7 l.) | `studio_contracts/library.py:1011` | 60% | `git grep -nw validate_library_content` : 3 lignes au total ; hors définition → tests 2 (ex. tests/api/test_library_content.py:19) | **contrat public** | tests seulement (tests/api/test_library_content.py) |
| `BRIDGE_MESSAGE_ADAPTER` (variable, 1 l.) | `studio_contracts/local/bridge.py:629` | 60% | `git grep -nw BRIDGE_MESSAGE_ADAPTER` : 6 lignes au total ; hors définition → tests 5 (ex. tests/contracts/test_local_p1.py:16) | **contrat public** | tests seulement |
| `check_reply_correlation` (function, 10 l.) | `studio_contracts/local/bridge.py:649` | 60% | `git grep -nw check_reply_correlation` : 7 lignes au total ; hors définition → tests 6 (ex. tests/contracts/test_local_p1.py:24) | **contrat public** | tests seulement |
| `allowlist_violations` (function, 5 l.) | `studio_contracts/local/bridge.py:661` | 60% | `git grep -nw allowlist_violations` : 4 lignes au total ; hors définition → docs 1, tests 2 (ex. tests/contracts/test_local_p1.py:22) | **contrat public** | tests seulement |
| `SECRET_INPUT_FIELDS` (variable, 1 l.) | `studio_contracts/local/identity.py:205` | 60% | `git grep -nw SECRET_INPUT_FIELDS` : 8 lignes au total ; hors définition → docs 2, tests 5 (ex. tests/contracts/test_local_p1.py:1010) | **contrat public** | tests seulement |
| `WorkspaceMigrationPolicy` (class, 1 l.) | `studio_contracts/local/workspace.py:307` | 60% | `git grep -nw WorkspaceMigrationPolicy` : 6 lignes au total ; hors définition → autres 2, docs 1, tests 2 (ex. tests/contracts/test_local_p1_hardening.py:34) | **contrat public** | sous-classe LocalContractModel : exportée dynamiquement (local/export.py model_registry) dans contracts/local/manifest.json |
| `ROADMAP_FORMAT` (variable, 1 l.) | `studio_contracts/roadmaps.py:34` | 60% | `git grep -nw ROADMAP_FORMAT` : 4 lignes au total ; hors définition → py 1, tests 2 (ex. packages/studio-contracts/src/studio_contracts/roadmaps.py:20) | **contrat public** | tests seulement |
| `effective_notes` (function, 21 l.) | `studio_contracts/vault.py:347` | 60% | `git grep -nw effective_notes` : 10 lignes au total ; hors définition → autres 2, docs 1, py 1, tests 5 (ex. packages/studio-contracts/src/studio_contracts/vault.py:171) | **contrat public** | tests seulement ; cité dans une description OpenAPI |
| `is_valid_slug` (function, 2 l.) | `studio_contracts/vault.py:370` | 60% | `git grep -nw is_valid_slug` : 4 lignes au total ; hors définition → tests 3 (ex. tests/contracts/test_vault_contract.py:28) | **contrat public** | tests seulement |

Modules sans importeur applicatif :

| fichier | lignes | preuve | classe |
|---|---|---|---|
| `studio_contracts/compatibility.py` | 104 | importé seulement par `tests/contracts/test_version_compatibility.py` ; cité par DEC-0137 (`REBUILD_NEVER_TRUSTED`) | **contrat public** |
| `studio_contracts/local/export.py` | 156 | aucun import src, mais point d'entrée `python -m studio_contracts.local.export [--check]` (docs/DESKTOP_P1_LOCAL_CONTRACTS.md:18-19, DEC-0093) + tests/contracts/test_local_p1.py | faux positif (entrée `-m`) |

## studio-code-graph

Candidats vulture ≥60 : **19** — sûr 5, à vérifier 6, contrat public 0, faux positifs écartés 8.

| symbole ou fichier | chemin:ligne | vulture | preuve (commande + résultat) | classe | note |
|---|---|---|---|---|---|
| `queued` (variable, 1 l.) | `studio_code_graph/service.py:87` | 60% | `git grep -nw queued -- '*.py' | grep '\.queued'` : 3 lignes, toutes des écritures (service.py:486/500/522), aucune lecture | **sûr** | champ `_Repo.queued` écrit (service.py:486/500/522) jamais lu, ni en src ni en tests |
| `apply_workspace_status` (method, 12 l.) | `studio_code_graph/service.py:209` | 60% | `git grep -nw apply_workspace_status` : 1 ligne(s), définition seule | **sûr** | aucune référence |
| `queued` (attribute, 1 l.) | `studio_code_graph/service.py:486` | 60% | `git grep -nw queued -- '*.py' | grep '\.queued'` : 3 lignes, toutes des écritures (service.py:486/500/522), aucune lecture | **sûr** | écriture seule |
| `queued` (attribute, 1 l.) | `studio_code_graph/service.py:500` | 60% | `git grep -nw queued -- '*.py' | grep '\.queued'` : 3 lignes, toutes des écritures (service.py:486/500/522), aucune lecture | **sûr** | écriture seule |
| `queued` (attribute, 1 l.) | `studio_code_graph/service.py:522` | 60% | `git grep -nw queued -- '*.py' | grep '\.queued'` : 3 lignes, toutes des écritures (service.py:486/500/522), aucune lecture | **sûr** | écriture seule |
| `total` (property, 3 l.) | `studio_code_graph/gitstate.py:39` | 60% | `git grep -nw total` : 751 lignes au total ; hors définition → autres 189, docs 391, py 116, tests 55 (ex. packages/studio-client/src/studio_client/context/library.py:42) | **à vérifier** | tests seulement (tests/code_graph/test_gitstate.py:118) ; nom générique |
| `has_removals` (property, 3 l.) | `studio_code_graph/gitstate.py:43` | 60% | `git grep -nw has_removals` : 3 lignes au total ; hors définition → py 1, tests 2 (ex. packages/studio-code-graph/src/studio_code_graph/gitstate.py:44) | **à vérifier** | tests seulement |
| `has_node` (method, 2 l.) | `studio_code_graph/index.py:103` | 60% | `git grep -nw has_node` : 2 lignes au total ; hors définition → tests 1 (ex. tests/code_graph/test_index.py:97) | **à vérifier** | tests seulement |
| `forget` (method, 6 l.) | `studio_code_graph/service.py:222` | 60% | `git grep -nw forget` : 31 lignes au total ; hors définition → autres 19, docs 4, py 6, tests 1 (ex. packages/studio-client/src/studio_client/harness/credentials.py:121) | **à vérifier** | tests seulement (tests/code_graph/test_service.py:448) ; non délégué par daemon/local_features.py |
| `diagnostics` (method, 16 l.) | `studio_code_graph/service.py:334` | 60% | `git grep -nw diagnostics` : 244 lignes au total ; hors définition → autres 77, docs 103, py 35, tests 28 (ex. packages/studio-client/src/studio_client/daemon/launch_executor.py:466) | **à vérifier** | tests seulement |
| `discard` (method, 2 l.) | `studio_code_graph/store.py:90` | 60% | `git grep -nw discard` : 24 lignes au total ; hors définition → autres 6, docs 2, py 12, tests 3 (ex. packages/studio-client/src/studio_client/hook_sync.py:261) | **à vérifier** | tests seulement |

## studio-workspaces

Candidats vulture ≥60 : **20** — sûr 1, à vérifier 13, contrat public 0, faux positifs écartés 6.

| symbole ou fichier | chemin:ligne | vulture | preuve (commande + résultat) | classe | note |
|---|---|---|---|---|---|
| `pending_count` (method, 3 l.) | `studio_workspaces/root_confirmation.py:105` | 60% | `git grep -nE "\.pending_count\("` : 7 lignes, toutes sur `OutboxStore` (runtime.py:645, tests/client/test_server_origin_switch.py, test_usage.py) ; aucune sur `RootConfirmationService` | **sûr** | aucun appel sur RootConfirmationService ; homonymes outbox distincts |
| `summarize_features` (function, 10 l.) | `studio_workspaces/flows.py:194` | 60% | `git grep -nw summarize_features` : 3 lignes au total ; hors définition → tests 2 (ex. tests/workspaces/test_flows.py:13) | **à vérifier** | tests seulement |
| `probe_path` (variable, 1 l.) | `studio_workspaces/git_detection.py:21` | 60% | `git grep -nw probe_path` : 10 lignes au total ; hors définition → py 9 (ex. packages/studio-client/src/studio_client/machine_setup.py:225) | **à vérifier** | champ jamais lu, mais argument positionnel de tous les GitRepoInfo(...) |
| `repo_root` (variable, 1 l.) | `studio_workspaces/git_detection.py:22` | 60% | `git grep -nw repo_root` : 132 lignes au total ; hors définition → docs 4, py 105, tests 22 (ex. packages/studio-client/src/studio_client/bootstrap.py:143) | **à vérifier** | tests seulement (tests/workspaces/test_git_detection.py:102) |
| `commit` (variable, 1 l.) | `studio_workspaces/git_detection.py:25` | 60% | `git grep -nw commit` : 946 lignes au total ; hors définition → autres 32, docs 578, py 162, tests 173 (ex. docs/audits/studios-agent-workflow/implementation-p1/baseline-files/tests/api/test_p0_task_concurrency.py:59) | **à vérifier** | tests seulement (tests/workspaces/test_git_detection.py:35) |
| `last` (attribute, 1 l.) | `studio_workspaces/native_picker.py:79` | 60% | `git grep -nw last` : 272 lignes au total ; hors définition → autres 103, docs 88, py 66, tests 14 (ex. packages/studio-client/src/studio_client/adapters/base.py:82) | **à vérifier** | tests seulement (tests/workspaces/test_native_picker.py:43) |
| `last` (attribute, 1 l.) | `studio_workspaces/native_picker.py:87` | 60% | `git grep -nw last` : 272 lignes au total ; hors définition → autres 103, docs 88, py 66, tests 14 (ex. packages/studio-client/src/studio_client/adapters/base.py:82) | **à vérifier** | tests seulement |
| `confirmation_nonce` (variable, 1 l.) | `studio_workspaces/picker.py:10` | 60% | `git grep -nw confirmation_nonce` : 4 lignes au total ; hors définition → py 2, tests 1 (ex. packages/studio-workspaces/src/studio_workspaces/native_picker.py:90) | **à vérifier** | lu seulement par tests |
| `action` (variable, 1 l.) | `studio_workspaces/registration.py:33` | 60% | `git grep -nw action` : 2169 lignes au total ; hors définition → autres 1409, docs 312, py 300, tests 147 (ex. desktop/e2e/a5_enroll_probe.py:73) | **à vérifier** | lu seulement par tests (tests/workspaces/test_store.py:272) |
| `removed_config` (variable, 1 l.) | `studio_workspaces/store.py:49` | 60% | `git grep -nw removed_config` : 2 lignes au total ; hors définition → py 1 (ex. packages/studio-workspaces/src/studio_workspaces/store.py:330) | **à vérifier** | champ jamais lu ; DissociateResult exporté dans studio_workspaces.__all__ |
| `preserved_root` (variable, 1 l.) | `studio_workspaces/store.py:50` | 60% | `git grep -nw preserved_root` : 3 lignes au total ; hors définition → py 1, tests 1 (ex. packages/studio-workspaces/src/studio_workspaces/store.py:331) | **à vérifier** | tests seulement |
| `migrate` (method, 25 l.) | `studio_workspaces/store.py:226` | 60% | `git grep -nw migrate` : 14 lignes au total ; hors définition → docs 3, py 3, tests 7 (ex. packages/studio-client/src/studio_client/config.py:152) | **à vérifier** | tests seulement |
| `dissociate` (method, 12 l.) | `studio_workspaces/store.py:321` | 60% | `git grep -nw dissociate` : 3 lignes au total ; hors définition → docs 1, tests 1 (ex. tests/workspaces/test_store.py:198) | **à vérifier** | tests seulement |
| `write_marker` (method, 12 l.) | `studio_workspaces/store.py:334` | 60% | `git grep -nw write_marker` : 7 lignes au total ; hors définition → docs 3, tests 3 (ex. tests/workspaces/test_store.py:197) | **à vérifier** | tests seulement |

## Faux positifs écartés

| paquet | catégorie | nombre | exemples |
|---|---|---|---|
| studio-client | Paramètre de signature imposée (__exit__/__aexit__, Protocol, validator cls, hook pydantic-settings) | 15 | `exc_type` (api_client.py:128), `exc_value` (api_client.py:129), `traceback` (api_client.py:130) |
| studio-client | Attribut de protocole stdlib (sqlite3.Connection.row_factory, ThreadingMixIn.daemon_threads) | 6 | `daemon_threads` (daemon/service.py:1229), `row_factory` (knowledge/index.py:201), `row_factory` (knowledge/server_mirror.py:153) |
| studio-client | Champ Pydantic / model_config (sérialisé, schéma) | 5 | `model_config` (config.py:41), `model_config` (config.py:63), `git_watch_repo_path` (config.py:111) |
| studio-client | Validator/serializer Pydantic | 4 | `_absolute_repo_path` (config.py:46), `_normalise_git_watches` (config.py:140), `_reject_duplicate_repos` (config.py:160) |
| studio-client | Mécanisme dynamique (PEP 562 module __getattr__/__dir__) | 2 | `__getattr__` (__init__.py:91), `__dir__` (__init__.py:100) |
| studio-client | Utilisé hors paquet (vulture lancé par paquet ne voit pas l'appelant) | 2 | `related_symbols` (knowledge/graph.py:60), `related_symbols` (knowledge/graph.py:262) |
| studio-client | Hook pydantic-settings | 1 | `settings_customise_sources` (config.py:185) |
| studio-client | Champ de dataclass sérialisé dynamiquement (asdict) | 1 | `seq` (context/manifest.py:18) |
| studio-contracts | Champ Pydantic / model_config (sérialisé, schéma) | 902 (900 − `position` ×2 + `library.py` 229-231, 241) | `task_id` (admission.py:47), `step_key` (admission.py:48), `machine_ids` (admission.py:50) |
| studio-contracts | Membre d'Enum (valeur sérialisée du contrat) | 328 | `ROADMAP_NOT_ACTIVE` (admission.py:34), `DEPENDENCY_PENDING` (admission.py:35), `TASK_DATA_MISSING` (admission.py:36) |
| studio-contracts | Utilisé hors paquet (vulture lancé par paquet ne voit pas l'appelant) | 219 (+ `LibraryMergePreview`, `merge_texts`) | `AdmissionBatchRequest` (admission.py:83), `AdmissionBatchRefused` (admission.py:116), `AdmissionBatchResult` (admission.py:125) |
| studio-contracts | Validator/serializer Pydantic | 90 | `_resolution_matches_state` (agent_identity.py:42), `_no_absolute_paths` (bootstrap.py:150), `_coherent_absent` (bootstrap.py:252) |
| studio-contracts | Paramètre de signature imposée (__exit__/__aexit__, Protocol, validator cls, hook pydantic-settings) | 4 | `cls` (budgets.py:143), `cls` (local/workspace.py:114), `cls` (profiles.py:101) |
| studio-contracts | Champ de dataclass sérialisé dynamiquement (asdict) | 3 | `start_line` (library_merge.py:39), `base_start` (library_merge.py:40), `base_end` (library_merge.py:41) |
| studio-code-graph | Utilisé hors paquet (vulture lancé par paquet ne voit pas l'appelant) | 7 | `reindex` (service.py:236), `on_git_change` (service.py:268), `search_symbols` (service.py:287) |
| studio-code-graph | Champ Pydantic / model_config (sérialisé, schéma) | 1 | `model_config` (store.py:30) |
| studio-workspaces | Utilisé hors paquet (vulture lancé par paquet ne voit pas l'appelant) | 6 | `enabled` (daemon_config.py:10), `repo_paths` (daemon_config.py:11), `plan` (watch_source.py:20) |

Notes : les 217 symboles `studio_contracts` « utilisés hors paquet » ont été confirmés par une recherche AST/regex des `from studio_contracts… import <nom>` (et alias `module.<nom>`) dans les `.py` hors `studio-contracts` et hors `tests/` (classes/fonctions), ou par des références `-w` dans des `.py` consommateurs (constantes, propriétés). Toutes les sous-classes `LocalContractModel` de `studio_contracts/local/` sont en plus vivantes par le registre dynamique `local/export.py::model_registry` (pkgutil + inspect). Aucune commande CLI typer/click, fixture pytest ou import `importlib` ciblant ces symboles n'est apparue parmi les candidats ≥60 (les décorateurs CLI ne figuraient pas dans la sortie vulture).


## Estimation

| paquet | sûr : lignes | sûr : fichiers touchés | sûr+à vérifier : lignes | sûr+à vérifier : fichiers touchés | fichiers entièrement supprimables (sûr / sûr+à vérifier) |
|---|---|---|---|---|---|
| studio-client | ~112 | 12 | ~1290 | 34 | 0 / 3 |
| studio-contracts | ~23 | 4 | ~30 | 7 | 0 / 0 |
| studio-code-graph | ~16 | 1 | ~48 | 4 | 0 / 0 |
| studio-workspaces | ~3 | 1 | ~71 | 7 | 0 / 0 |

Lignes = étendue `def`/`class` (décorateurs inclus) ou 1 ligne par variable/attribut ; n'inclut ni imports devenus inutiles ni tests associés. « sûr+à vérifier » pour studio-client compte les 3 modules testés-seulement en entier (753 l. sur `f099ef02` : 669 + 65 + 19 ; 976 l. sur `6fa6fa78`) sans double compte de leurs symboles.


## Méthode

- `uv tool run vulture --version` → `vulture 2.16` ; Python du poste pour les scripts d'analyse ; `rg` 15.2.0 ; `git` (grep).
- Depuis la racine, un run par paquet : `uv tool run vulture packages/<paquet>/src --min-confidence 60 > <dossier temporaire hors dépôt>/<paquet>.txt` → 121 (client), 1567 (contracts), 19 (code-graph), 20 (workspaces) = 1727 candidats sur `6fa6fa78` ; 116, 1575, 19, 20 = 1730 sur `f099ef02`.
- Contexte AST de chaque candidat (classe englobante, ancêtres résolus sur les 4 paquets : BaseModel/BaseSettings/Enum/Protocol/dataclass/exception, décorateurs, fonction englobante) pour les catégories de faux positifs.
- Références : un passage `rg -n -w -F --hidden -g !.git -g !node_modules -g !graphify-out -f names.txt .` sur tout le dépôt (équivalent `git grep -nw --untracked` ; `git grep -f` avec ~1000 motifs `-w` était trop lent sur ce poste), ventilé src/tests/docs/autres, définition exclue ; puis, pour chaque candidat non écarté, `git grep -nw --untracked -I -e <nom>` individuel (colonne preuve), affiné par `git grep -nE "\.<nom>\("` pour les noms génériques.
- Modules jamais importés : parse AST de tous les `.py` (suivis + non ignorés), résolution des imports absolus et relatifs vers les modules des 4 paquets, + `git grep -F <module>` hors `.py` (pyproject, docs, workflows).
- Vérifications manuelles ciblées : registre `_MODULE_BY_NAME`/`__getattr__` de `studio_client/__init__.py`, délégations `daemon/local_features.py` → `CodeGraphService`, dispatch `daemon/service.py` → `WorkspaceBridge`, `asdict` dans `context/manifest.py`, mutateurs de `local/fixtures.py`.

## Limites

- vulture est lancé par paquet : les appels inter-paquets ne sont vus que par la recherche textuelle ; un homonyme peut masquer un symbole réellement mort (classé alors « faux positif » ou « à vérifier », jamais « sûr »).
- Accès par chaîne construite dynamiquement (`getattr(obj, f"...")`) non détectable ; aucun `getattr` sur client/service/bridge trouvé dans `packages/` et `services/`.
- Seuil 60 : les symboles sous 60 % et le code inatteignable dans une fonction vivante ne sont pas couverts ; les champs Pydantic/Enum de `studio_contracts` (1228) sont écartés en bloc comme contrat sérialisé sans vérification d'usage champ par champ.
- Les copies de fichiers sous `docs/audits/**/baseline-files/` sont comptées comme docs, pas comme consommateurs.

## Annexe — liste complète des faux positifs par fichier


### studio-client


**Paramètre de signature imposée (__exit__/__aexit__, Protocol, validator cls, hook pydantic-settings)** (15)

- `studio_client/api_client.py` : exc_type:128, exc_value:129, traceback:130
- `studio_client/config.py` : dotenv_settings:191, file_secret_settings:192
- `studio_client/daemon/runtime.py` : exc_type:166, traceback:168
- `studio_client/knowledge/memory.py` : proposal:54, proposal:55, proposal:216, proposal:222
- `studio_client/knowledge/provider.py` : proposal:648, proposal:654
- `studio_client/knowledge/server_mirror.py` : proposal:634, proposal:640

**Attribut de protocole stdlib (sqlite3.Connection.row_factory, ThreadingMixIn.daemon_threads)** (6)

- `studio_client/daemon/service.py` : daemon_threads:1229
- `studio_client/knowledge/index.py` : row_factory:201
- `studio_client/knowledge/server_mirror.py` : row_factory:153
- `studio_client/outbox/store.py` : row_factory:135, row_factory:148
- `studio_client/usage/local/opencode.py` : row_factory:86

**Champ Pydantic / model_config (sérialisé, schéma)** (5)

- `studio_client/config.py` : model_config:41, model_config:63, git_watch_repo_path:111, git_watch_project_id:112
- `studio_client/knowledge/graph.py` : source_location:21

**Validator/serializer Pydantic** (4)

- `studio_client/config.py` : _absolute_repo_path:46, _normalise_git_watches:140, _reject_duplicate_repos:160, _strip_trailing_slash:180

**Mécanisme dynamique (PEP 562 module __getattr__/__dir__)** (2)

- `studio_client/__init__.py` : __getattr__:91, __dir__:100

**Utilisé hors paquet (vulture lancé par paquet ne voit pas l'appelant)** (2)

- `studio_client/knowledge/graph.py` : related_symbols:60, related_symbols:262

**Hook pydantic-settings** (1)

- `studio_client/config.py` : settings_customise_sources:185

**Champ de dataclass sérialisé dynamiquement (asdict)** (1)

- `studio_client/context/manifest.py` : seq:18

### studio-contracts


**Champ Pydantic / model_config (sérialisé, schéma)** (900)

- `studio_contracts/admission.py` : task_id:47, step_key:48, machine_ids:50, task_id:54, step_key:55, reasons:57, waiting_on:58, roadmap_id:62, roadmap_status:64, roadmap_version:65, harness_id:66, launchable:67, excluded:68, steps_without_tasks:69, machines:70, plan_digest:71, evaluated_at:72, task_id:79, plan_digest:89, harness_id:90, expires_in_seconds:94, task_id:109, exclusion_reasons:112, budget:113, roadmap_id:126, plan_digest:127, launches:128, admitted_at:129
- `studio_contracts/agent_identity.py` : effective_model:30, selection_alias:31, logical_harness:36, selection_alias:38, canonical_agent_id:57, legacy_agent_id:61, canonical_agent_id:62, owner_user_id:63, logical_harness:64, already_linked:74, unmatched_legacy:75
- `studio_contracts/ai_integration.py` : artifact_counts:39, checked_at:47, display_name:59, freshness:61, reported_at:62, project_registered:63, bootstrap:65, desired:74, desired_error:75, machines:76
- `studio_contracts/ai_work.py` : task_id:32, session_id:36, changed_files:39, tests_run:40, started_at:41, ended_at:42, agent_profile:43, task_id:57, session_id:61, changed_files:64, tests_run:65, agent_profile:66, changed_files:75, tests_run:76, session_id:77
- `studio_contracts/auth.py` : display_name:55, email:56, email_verified_at:59, disabled_at:60, owner_user_id:73, display_name:74, last_seen_at:75, workstation_id:77, display_name:98, agent_kind:99, agent_profile:100, owner_user_id:105, superseded_by_agent_id:106, display_name:122, agent_kind:123, agent_profile:124, display_name:144, email:145, owner_user_id:160, display_name:161, workstation_id:162, display_name:168, workstation_id:175, credential:182, harness_id:196, detected:198, configured:199, checked_at:209, project_ids:219, accepts_launches:220, running_launches:221, max_launches:222, bootstrap:223, launch_profiles:224, launch_safety:225, client_timestamp:234, last_seen_at:241, server_timestamp:242, display_name:262, eligible:264, reasons:265, free_slots:267, reported_at:268, task_id:272, harness_id:274, machines:275
- `studio_contracts/bootstrap.py` : absent:288, obsolete:289, modified:290, incompatible:291, up_to_date:292, sync_allowed:307
- `studio_contracts/bootstrap_plan.py` : required_by:74
- `studio_contracts/budgets.py` : period:129, unknown_cost:136, late_usage:137, settle_after_seconds:138, alert_thresholds:139, expected_version:167, expected_version:171, approval_status:177, effective_mode:178, ceiling_guarantee:179, proposed_by_user_id:180, approved_by_user_id:181, approved_at:182, metric:187, threshold:188, metric:197, limit:198, consumed:199, held:200, unknown_entries:201, task_launch_id:206, reserved_cost:208, reserved_tokens:209, settle_basis:210, alerts:211, settled_at:213, effective_mode:222, ceiling_guarantee:223, meters:225, active_launches:226, reservations:227, metric:237, limit:238, consumed:239, held:240, ceiling_guarantee:243
- `studio_contracts/builds.py` : task_id:29, github_integration_id:30, workflow_run_id:31, workflow_name:32, run_number:33, branch:34, commit_sha:35, pr_number:36, conclusion:38, html_url:39, actor_login:40, started_at:41, completed_at:42, repo_full_name:53, default_branch:54, created_by_user_id:56, repo_full_name:61, default_branch:62, repo_full_name:67, default_branch:68, task_id:99, result:100, completed_at:103, task_id:109, github_event:119, build_id:120, pr_number:121, detail:122
- `studio_contracts/claims.py` : task_id:28, resource_path:29, resource_type:30, claimed_by_machine_id:31, claimed_by_agent_id:32, ttl_seconds:34, renewed_at:36, released_at:38, task_id:43, resource_path:44, resource_type:45, ttl_seconds:46
- `studio_contracts/common.py` : model_config:11, limit:28, offset:29
- `studio_contracts/completion.py` : deployed:36, authoritative:41
- `studio_contracts/coordination.py` : task_ids:34, decision_ids:35, from_session_id:49, intent:50, task_id:51, session_id:52, in_reply_to:55, event_id:56, event_id:60, event_type:61, seq:62, task_id:63, session_id:64, event_id:72, intent:73, in_reply_to:76, from_session_id:77
- `studio_contracts/decisions.py` : task_id:23, proposed_by_type:27, proposed_by_id:28, task_id:34, proposed_by_type:37, proposed_by_id:38, superseded_by:48
- `studio_contracts/discovery.py` : write_allowed:19, example:20, prerequisites:21, restrictions:22, intent:27, additional_available:30, next_steps:31
- `studio_contracts/events.py` : event_id:119, event_type:120, task_id:122, actor_type:124, actor_id:125, client_timestamp:126, server_timestamp:127, schema_version:129, event_id:138, event_type:139, task_id:141, actor_type:143, actor_id:144, client_timestamp:145, schema_version:147
- `studio_contracts/execution_snapshot.py` : content_digest:109, capabilities_digest:124, digest:130, digest:149, harness_id:162, harness_version:163, projections:164, git_sha:165, git_dirty:166, local_policy_digest:167, worktree_branch:168, access_mode:170, detail:176, schema_version:182, task_launch_id:234, schema_version:236, capture_reason:238, retention_until:241
- `studio_contracts/handoff.py` : session_id:47, expected_version:48, task_status:49, ai_work_status:52, changed_files:53, tests_run:54, coordination:55, completion:56, task_id:68, task_status:69, task_version:70, session_id:71, released_claims:72, ai_work_id:73, sync:74, handoff_cursor_seq:75, coordination_event_id:76
- `studio_contracts/initialization.py` : reused:218, valid:240, applicable:241, roadmap_present:242, roadmap_status:243, roadmap_id:256, roadmap_status:257
- `studio_contracts/launch_grants.py` : user_id:25, granted_by_user_id:28
- `studio_contracts/library.py` : pinned_version:88, active_version:89, update_available:91, suggested_pin:92, mutates:98, additional_available:100, offset:101, active_version:171, owner_user_id:172, created_by_user_id:174, base_update_available:175, base_active_version:179, derived_from:204, derived_from:217, created_by_user_id:218, detail:235, derived_from:250, expected_resource_version:259, expected_resource_version:266, locked_version:302, created_by_user_id:303, locked_version:310, content_schema:389, content_schema:397, applies_to:399, content_schema:462, content_schema:492, disable_model_invocation:495, content_schema:511, content_schema:525, intended_use:527, content_schema:541, intended_use:543, instructions:544, triggers:545, edit_policy:546, content_schema:624, content_schema:873, timeout_seconds:877
- `studio_contracts/local/bridge.py` : sent_at:527, model_config:533
- `studio_contracts/local/code_graph.py` : languages:43, unsupported_languages:44, kinds:80, limit:81, cursor:82, symbols:86
- `studio_contracts/local/common.py` : model_config:32
- `studio_contracts/local/daemon_control.py` : instance_id:110, pid:113, daemon_version:115, started_at:116, pending_count:132, oldest_pending_at:133, crashed_at:147, recoveries_attempted:149, expected_instance_id:204, observed_at:208, providers:213, expected_instance_id:232, confirm_external:233, drain_outbox:234
- `studio_contracts/local/graph.py` : generated_at:103, index_fingerprint:104, total_edges:160, limit:231, cursor:232, node_kinds:233, direction:239, relations:240, limit:241, cursor:242
- `studio_contracts/local/handshake.py` : component_version:66, silent_fallback:129
- `studio_contracts/local/harness.py` : adapter_id:54, harness_id:55, display_name:56, detected_version:58, adapter_id:91, adapter_id:101, isolation:102, settings_sources:103, mcp_servers:105, exclusions:106, access_modes:108, production_approval_required:109, adapter_id:157, renew:158, adapter_id:163, requires_confirmation:169, confirmed:187, confirmed:212, restored:217, adapter_id:238, adapter_id:242
- `studio_contracts/local/identity.py` : user_id:45, display_name:46, session_expires_at:48, machine_name:56, registered_at:58, ref_id:92, store:94, lookup_key:95, checked_at:102, workstation_name:131, model_config:221, human_session:224, machine_name:225, replace_existing:226, adopt_machine_id:227, view:241, view:265
- `studio_contracts/local/knowledge.py` : integration_id:34, canonical_source:45, integrations:48, modified_at:63, query:74, limit:75, cursor:76, score:81, snippet:82, hits:86, max_bytes:100, markdown:105, outgoing_links:107, confirmed:124, state_before:129
- `studio_contracts/local/launch.py` : max_concurrent:23, confirmed:51
- `studio_contracts/local/machine_setup.py` : detected:86, managed:94, needs_registration:101, requires_confirmation:175, adapters:179, versioning:180, confirmed:199, sync_skills:201, left_modified:229, hook_state:268, guard_state:269, plugin_state:270, checked_at:278
- `studio_contracts/local/project_projections.py` : checked_at:23, updates:27, confirmed:35, ignored:41
- `studio_contracts/local/provider.py` : source_fingerprint:40, display_name:59, provider_version:60
- `studio_contracts/local/publication.py` : automatic_upload:46, requires_visible_preview:47, requires_explicit_confirmation:48, protocol_version:80, generated_at:82, included:88, confirmed:110
- `studio_contracts/local/skills.py` : checked_at:67, selection:103, preview_hash:112, checked_at:124, choice:130, preview_hash:131, confirm:137, auto_sync:155, backups:162, manifest_path:163, added:164, updated:165, applied_at:167, last_successful_sync:174, last_check:175, added:176, updated:177, error_message:179, auto_sync_enabled:180
- `studio_contracts/local/workspace.py` : workspace_root:36, directory_name:64, content_root:69, include_globs:71, exclude_globs:72, integrations:73, languages:79, include_globs:80, exclude_globs:81, debounce_ms:86, max_events_per_second:87, ignore_globs:88, follow_symlinks:89, schema_version:98, project_slug:102, schema_version:149, expires_in_s:257, branch:275, remote:276, detached:277, expected_updated_at:291, current_version:312, oldest_migratable_version:313, keeps_backup:314, refuses_newer:315
- `studio_contracts/mission.py` : reason_code:120, harness_id:121, finished_at:123, started_at:130, ended_at:131, last_activity_at:132, ai_work_id:136, completed_at:139, run_id:143, task_id:145, task_title:146, task_status:147, machine_status:149, launch:150, session:151, handoff:152, protocol_state:153, reasons:155, active_claims:156, data_gaps:157, by_verdict:164, generated_at:170, window_hours:171, runs:172
- `studio_contracts/profiles.py` : refusal_reasons:125, authoritative:202, digest:341
- `studio_contracts/project_context.py` : matched_terms:91, source_references:108, claimed_by_machine_id:110, claimed_by_self:111, why:114, task_id:132, why:137, why:158, agent_applies:159, resource_path:164, resource_type:165, task_id:166, claimed_by_machine_id:167, claimed_by_self:168, why:170, snippet:187, why:191, claims:205, changed_files:218, tests_run:219, started_at:220, ended_at:221, why:224, limit:238, max_chars:239, chars_used:240, item_text_cap:241, library_scan_capped:242, roadmap_scan_capped:243, in_context:261, objective:269, criteria_total:271, linked_tasks:273, objective:281, current_step:283, task_step:284, why:285, draft_pending:301, others:302, query_terms:307, related_tasks:309, ai_work:314, active_work:315, roadmap_overview:317, returned:319, additional_available:320, omitted_for_budget:321, limits:322
- `studio_contracts/project_state.py` : active_tasks:15, active_claims:16, generated_at:17
- `studio_contracts/projects.py` : archived:14, user_id:30, granted_by_user_id:31, user_display_name:33, user_email:34
- `studio_contracts/resolution.py` : locked:113, binding_level:115, via_resource_id:140, via_version:142, session_overrides:315
- `studio_contracts/review_queue.py` : task_id:29, requested_at:32, task_id:39, proposed_by_type:42, requested_at:43, task_id:54, resource_path:56, requested_at:57, task_id:68, workflow_name:70, branch:71, commit_sha:72, conclusion:73, requested_at:74, task_id:85, pr_number:87, head_branch:88, base_branch:89, requested_at:90, task_id:105, roadmap_id:106, revision_no:110, base_revision_no:111, actor_type:113, requested_at:115, generated_at:133
- `studio_contracts/roadmaps.py` : actor_type:220, actor_id:221, at:224, objective:289, context:290, instructions:291, acceptance_criteria:292, objective:302, objective:314, context:315, exported_at:318, revision_no:319, ratio:480, task_id:500, roadmap_id:507, phase_id:508, position:510, objective:512, context:513, instructions:514, acceptance_criteria:515, linked_tasks:521, state_override_reason:523, available:525, waiting_on:526, task_progress:527, roadmap_id:533, position:535, objective:537, objective:546, revision_no:548, approved_revision_no:549, current_step_key:551, context:559, objective:570, context:571, submit:583, objective:596, context:597, objective:605, expected_roadmap_version:606, objective:612, expected_roadmap_version:622, objective:635, context:636, instructions:637, acceptance_criteria:638, state_override_reason:653, ordered_keys:676, expected_roadmap_version:677, step_key:686, depends_on_key:687, expected_roadmap_version:688, task_id:697, expected_version:709, roadmap_id:723, revision_no:724, base_revision_no:727, reviewed_by_user_id:731, reviewed_at:732, review_comment:733, roadmap_id:742, revision_no:743, base_revision_no:746, reviewed_by_user_id:749, reviewed_at:750, review_comment:751, base_revision_no:761, submit:763, expected_version:772, fields:795, base_revision_no:799, proposal_revision_no:800, expected_version:818, step_key:839, task_id:843, create:848, reuse:849, skip:850, roadmap_id:859, roadmap_version:860, applicable:862, not_applicable_reason:863, server_version:908, server_revision_no:909, limit:913, available:921, waiting_on:922, acceptance_criteria:923, linked_task_ids:924, roadmap_id:932, current_phase_key:935, current_step:936, upcoming_steps:937, draft_pending:939
- `studio_contracts/runtime.py` : owner_user_id:111, detach_machine:194, update:218, expected_version:219, owner_user_id:273
- `studio_contracts/sessions.py` : task_id:26, started_at:29, ended_at:30, last_activity_at:31, sync_cursor_seq:32, task_id:38
- `studio_contracts/start_work.py` : task_id:48, objective:49, limit:52, max_chars:53, task_id:62, why:65, session:85, claimed:86, resumed:87, prepared_context:88, sync:90
- `studio_contracts/sync.py` : why:43, seq:44, event_type:45, task_id:46, claim_id:47, resource_path:48, coordination:49, overflow:68, resync:69
- `studio_contracts/task_launch.py` : task_id:118, harness_id:120, allow_production:123, expires_in_seconds:124, task_id:142, requested_by_user_id:144, harness_id:145, reason_code:148, session_id:149, output_excerpt:150, finished_at:152, allow_production:154, session_id:180, task_status:181, machine_status:219, stale_since:220, expires_in_seconds:229, replay:232, attempt:243, retry_of_launch_id:244, recovery:245, replay_basis:246, expected_version:255, reason_code:257, session_id:258, output_excerpt:259, expected_version:267, token:284
- `studio_contracts/task_launch_replay.py` : subject_kind:102, recorded:105, snapshot_id:116, preview_digest:123, generated_at:124, preview_digest:132, preview_digest:141, substitutions:143, limitation_codes:146
- `studio_contracts/tasks.py` : claimed_by_machine_id:26, claimed_by_agent_id:27
- `studio_contracts/timeline.py` : days:22
- `studio_contracts/transfers.py` : transfer_code:37, sender_user_id:38, recipient_user_id:39, task_id:41, build_id:42, category:43, filename:44, object_key:45, content_type:46, size_bytes:47, content_md5:49, uploaded_at:53, downloaded_at:54, deleted_at:55, recipient_user_id:59, task_id:61, build_id:62, category:63, filename:64, content_type:65, size_bytes:66, content_md5:77, transfer_id:86, multipart:87, upload_url:88, upload_id:89, part_urls:90, part_size_bytes:91, part_urls_expires_at:92, upload_id:104, part_size_bytes:105, part_numbers:106, transfer_id:116, upload_id:117, part_size_bytes:118, part_urls:119, uploaded_parts:120, size_bytes:136, upload_id:138, transfer_id:143, download_url:144, consumed_bytes:150, quota_bytes:151, remaining_bytes:152
- `studio_contracts/usage.py` : unit:111, unit:117, unit:125, collector:156, collector_version:157, harness_version:159, price_list_id:171, effective_from:172, source_event_id:245, task_id:249, session_id:250, task_launch_id:251, ai_work_id:252, source_event_id:286, expected_version:287, measured_entries:332, estimated_entries:333, unknown_entries:334, known_sum:343, known_sum:350, known_sum:355, known_sum:366, by_currency:368, collector:374, task_id:383, task_title:384, day:388, first_period_start:398, last_period_end:399, total_tokens:403, sources:406, task_id:416, task_launch_id:417, group_by:418, since:419, until:420, generated_at:421, groups:423, profile_contract_version:448, harness_version:450, numerator:473, denominator:474, covered:475, launches:476, launches:485, first_requested_at:486, last_requested_at:487, status_counts:488, rates:489, ledger_entries:490, ai_work_entries:491, total_tokens:492, comparable:494, ledger_entries:502, ai_work_entries:503, since:514, until:515, generated_at:516, population:517, ranking:518, launches:519, groups:520, unattributed:521, caveats:524
- `studio_contracts/vault.py` : author_type:145, author_id:146, expected_version:209, change_summary:217, note_id:243, change_summary:253, author_type:254, author_id:255, matched_anchors:290, rank:291, snippet:292
- `studio_contracts/version.py` : api_version:17, server_version:18, minimum_supported:19, latest:22, client:27, client_version:28, minimum_supported:29, latest:30
- `studio_contracts/work_profile_pack.py` : pack:35, machine_policy:36, authoritative:42, mutates:43, observed:46

**Membre d'Enum (valeur sérialisée du contrat)** (328)

- `studio_contracts/admission.py` : ROADMAP_NOT_ACTIVE:34, DEPENDENCY_PENDING:35, TASK_DATA_MISSING:36, TASK_COMPLETED:37, TASK_BLOCKED:38, REVIEW_PENDING:39, LAUNCH_ACTIVE:40, TASK_CLAIMED_ELSEWHERE:41, CLAIMS_HELD_ELSEWHERE:42, NO_ELIGIBLE_MACHINE:43, DUPLICATE_ITEM:102, NOT_LAUNCHABLE:103, MACHINE_NOT_ELIGIBLE:104, BUDGET_REFUSED:105
- `studio_contracts/ai_integration.py` : FRESH:28, NEVER_REPORTED:30
- `studio_contracts/ai_work.py` : REVIEW_REQUESTED:19, APPROVED:20, CHANGES_REQUESTED:21
- `studio_contracts/auth.py` : ADMIN:27, READONLY:30, ONLINE:34, IDLE:35, PENDING:45, NO_CAPABILITIES_REPORT:250, CAPABILITIES_STALE:251, OWNER_NO_PROJECT_ACCESS:252, PROJECT_NOT_REGISTERED:253, LAUNCHES_NOT_ACCEPTED:254, LAUNCH_SAFETY_UNSUPPORTED:255, HARNESS_INCOMPATIBLE:256, AT_CAPACITY:257
- `studio_contracts/bootstrap.py` : UNMANAGED_TARGET:267
- `studio_contracts/budgets.py` : DAY:51, LIFETIME:53, IGNORE:62, RELEASE:72, NOT_REQUIRED:76, PENDING:77, APPROVED:78, COST:91, SLOTS:93, COST_EXHAUSTED:99, BUDGET_TOKENS_EXHAUSTED:100, SLOTS_EXHAUSTED:101, THRESHOLD_REACHED:105, SLOTS_EXHAUSTED:107, UNKNOWN_USAGE:108, ENFORCE_PENDING_APPROVAL:109, HELD:116, SETTLED:117, RELEASED:118, MEASURED:122, RESERVATION:123
- `studio_contracts/builds.py` : PRIORITY_ANALYSIS:76, BLOCKER_DETECTION:77, PARALLELIZATION:78, DECOMPOSITION:79
- `studio_contracts/claims.py` : FOLDER:12, RELEASED:21
- `studio_contracts/decisions.py` : SUPERSEDED:13
- `studio_contracts/events.py` : PROJECT_CREATED:16, TASK_CREATED:18, TASK_STARTED:19, TASK_UPDATED:20, TASK_BLOCKED:21, TASK_COMPLETED:22, TASK_LAUNCH_REQUESTED:24, TASK_LAUNCH_ACCEPTED:25, TASK_LAUNCH_REJECTED:26, TASK_LAUNCH_CANCELLED:27, TASK_LAUNCH_EXPIRED:28, TASK_LAUNCH_FINISHED:29, SESSION_STARTED:31, SESSION_ENDED:32, RESOURCE_CLAIMED:34, RESOURCE_RENEWED:35, RESOURCE_RELEASED:36, DECISION_PROPOSED:39, DECISION_CREATED:40, DECISION_ACCEPTED:41, DECISION_SUPERSEDED:42, LIBRARY_VERSION_CREATED:44, LIBRARY_VERSION_ACTIVATED:45, LIBRARY_RESOURCE_DEPRECATED:46, LIBRARY_LOCK_SET:47, LIBRARY_LOCK_RELEASED:48, ROADMAP_CREATED:50, ROADMAP_UPDATED:51, ROADMAP_PROPOSED:52, ROADMAP_APPROVED:53, ROADMAP_CHANGES_REQUESTED:54, ROADMAP_REJECTED:55, ROADMAP_ACTIVATED:56, ROADMAP_COMPLETED:57, ROADMAP_ARCHIVED:58, ROADMAP_HYDRATED:59, AGENT_STARTED:61, AGENT_STOPPED:62, AI_WORK_STARTED:64, AI_WORK_COMPLETED:65, AI_WORK_FAILED:66, AI_WORK_REVIEW_REQUESTED:67, AI_WORK_APPROVED:68, AI_WORK_CHANGES_REQUESTED:69, GIT_COMMIT:71, GIT_BRANCH_CHANGED:72, GIT_PR_OPENED:73, GIT_PR_MERGED:74, GRAPH_UPDATED:76, MEMORY_PROPOSED:77, MEMORY_UPDATED:78, GODOT_STARTED:80, GODOT_STOPPED:81, RECORDING_STARTED:83, RECORDING_FINISHED:84, RECORDING_MARKER_CREATED:85, BUILD_STARTED:87, BUILD_SUCCEEDED:88, BUILD_FAILED:89, PRODUCER_JOB_REQUESTED:91, PRODUCER_JOB_COMPLETED:92, PRODUCER_JOB_FAILED:93, TRANSFER_CREATED:95, TRANSFER_UPLOADING:96, TRANSFER_READY:97, TRANSFER_DOWNLOADED:98, TRANSFER_EXPIRED:99, TRANSFER_DELETED:100, MARKETING_CANDIDATE_CREATED:102, MARKETING_POST_PUBLISHED:103, COORDINATION_HEADS_UP:105, COORDINATION_QUESTION:106, COORDINATION_BLOCKED_BY:107, COORDINATION_HANDOFF:108
- `studio_contracts/execution_snapshot.py` : RESOLUTION_UNAVAILABLE:75, PROFILE_UNAVAILABLE:76, HARNESS_VERSION_UNKNOWN:77, PROJECTION_DIGEST_UNAVAILABLE:78, GIT_SHA_UNAVAILABLE:79, LOCAL_POLICY_UNAVAILABLE:80, REDACTION_REQUIRED:81, PAYLOAD_TOO_LARGE:82, INTERNAL:83, WORKTREE_UNVERIFIED:84
- `studio_contracts/initialization.py` : PROJECT_ALREADY_EXISTS:89, ROADMAP_ALREADY_EXISTS:90, TASK_ALREADY_EXISTS:91, RESOURCE_OPTIONAL_MISSING:92, RESOURCE_REQUIRED_MISSING:93, RESOURCE_ALREADY_ATTACHED:94, BINDING_ALREADY_SET:95, BINDING_UNAVAILABLE:96, NO_ROADMAP:97, NO_TASKS:98, NO_RESOURCES:99, NO_BINDINGS:100, RESOURCE_NOT_FOUND:114, BINDING_TARGET_NOT_FOUND:115, BINDING_INCOMPATIBLE:116
- `studio_contracts/library.py` : DEPRECATED:39, PIN:277, SESSION_START:821, SESSION_END:822, SUBAGENT_STOP:827, NOTIFICATION:828, PRE_COMPACT:829, WINDOWS:843, LINUX:844, MACOS:845, PWSH:849, BASH:850, SH:851, PYTHON:852, NODE:853
- `studio_contracts/local/code_graph.py` : FULL_REBUILD:100
- `studio_contracts/local/common.py` : WATCHER:366, INVALID_REQUEST:373, UNKNOWN_COMMAND:374, PAYLOAD_TOO_LARGE:375, TIMEOUT:380, LANGUAGE_UNSUPPORTED:402
- `studio_contracts/local/daemon_control.py` : NOT_RUNNING:69
- `studio_contracts/local/graph.py` : OUT:224, IN:225
- `studio_contracts/local/handshake.py` : ENABLE_FEATURE:105
- `studio_contracts/local/identity.py` : PROCESS_ENVIRONMENT:67
- `studio_contracts/local/knowledge.py` : FULL_REBUILD:112, EMPTY:117, MARKDOWN_EXISTING:118, STUDIOS_VAULT:119
- `studio_contracts/local/machine_setup.py` : PLUGIN:35, NOT_SIGNED_IN:59, CREDENTIAL_REJECTED:60, LIBRARY_UNREACHABLE:61, INVALID_SKILL:62, NOT_APPLICABLE:67, MANAGED:259, FOREIGN:261
- `studio_contracts/local/outbox.py` : PENDING_MARKERS:16, DEAD_LETTER:17, MULTIPART_UPLOADS:18
- `studio_contracts/local/publication.py` : PATHS:24, VAULT_CONTENT:25, INDEXES:26, FILESYSTEM_DETAILS:28, HARNESS_CONFIG:29, SENSITIVE_DIAGNOSTICS:30, WORKSPACE_CONFIG:31, SECRETS:32, SHAREABLE_SUMMARY:37
- `studio_contracts/local/skills.py` : UPDATED:93, UPDATE_PENDING:94, CONFLICTS:95, NOT_SYNCED:96
- `studio_contracts/local/workspace.py` : INVALID_REPO:263
- `studio_contracts/mission.py` : PENDING:64, WAITING_HUMAN:66, NEEDS_ATTENTION:67, LAUNCH_CANCELLED:77, LAUNCH_CANCELLED_SESSION_OPEN:78, LAUNCH_FAILED:79, LAUNCH_REJECTED:80, LAUNCH_EXPIRED:81, REVIEW_REQUESTED:82, DECISION_PROPOSED:83, HANDED_OFF:84, PROCESS_EXITED_WITHOUT_SESSION:85, SESSION_ENDED_WITHOUT_HANDOFF:86, PROCESS_EXITED_SESSION_OPEN:87, SESSION_EXPIRED:88, MACHINE_OFFLINE:89, LAUNCH_PENDING:90, PROCESS_RUNNING:91, SESSION_IDLE:92, OPEN:102, HANDED_OFF:103, ENDED_WITHOUT_HANDOFF:104, MACHINE_UNKNOWN:112, SESSION_NOT_FOUND:113, TASK_NOT_FOUND:114
- `studio_contracts/resolution.py` : DEFINITION_NOT_FOUND:57
- `studio_contracts/roadmaps.py` : SNAPSHOT:134, REVIEW:135, PENDING:141, APPROVED:142, CHANGES_REQUESTED:143, SUPERSEDED:145, INVALID_REORDER:336, ADDED:783, REMOVED:784, CHANGED:785, STEP_DONE:833, STEP_SKIPPED:834, ROADMAP_NOT_ACTIVE:835, NOT_FOUND:883, REFERENCE_NOT_FOUND:884, VERSION_CONFLICT:885, BASE_REVISION_STALE:886, ACTIVE_ROADMAP_EXISTS:887, INVALID_STATE:888, STEP_HAS_LINKS:890, DUPLICATE_KEY:891, IDEMPOTENCY_KEY_PAYLOAD_MISMATCH:892, ACTOR_NOT_OWNED:893, FORBIDDEN:894, TASK_PROJECT_MISMATCH:896
- `studio_contracts/sessions.py` : IDLE:19, ENDED:21
- `studio_contracts/task_launch.py` : NOT_OPTED_IN:66, PROJECT_NOT_REGISTERED:67, HARNESS_NOT_ALLOWED:68, HARNESS_NOT_FOUND:69, AGENT_NOT_FOUND:70, CAPACITY_REACHED:71, PREPARATION_FAILED:72, HARNESS_EXITED:73, CANCELLED_BY_REQUESTER:74, EXPIRED_UNPULLED:75, EXPIRED_TIMEOUT:76, NOT_APPLICABLE:169, AWAITING:170, UNVERIFIED:171, HANDED_OFF:172, OFFLINE_WIP:197, LAUNCH_FAILED:205, LAUNCH_EXPIRED:206, MACHINE_OFFLINE:207
- `studio_contracts/task_launch_replay.py` : RESOLUTION_UNRECORDED:56, LIBRARY_VERSION_UNAVAILABLE:57, SOURCE_WORKTREE_DIRTY:58, SOURCE_GIT_UNRECORDED:59, GIT_STATE_NOT_PINNED:60, PROFILE_RECHECKED_ON_MACHINE:61, OUTPUT_NOT_REPRODUCIBLE:62, CHANGED:86, ADDED:87, REMOVED:88, RESOURCE:94, RUNTIME:95
- `studio_contracts/transfers.py` : UPLOADING:14, DOWNLOADED:16, DELETED:18, TEMPORARY:26, BUILD:27, ASSET:28, RAW_RECORDING:29
- `studio_contracts/usage.py` : MEASURED:75, TASK:308, CONFIGURATION:309, DAY:310, EXACT:324, MIXED_CURRENCY:328, SESSION_LINKED:462, USAGE_MEASURED:463
- `studio_contracts/vault.py` : CONVENTION:69, PROCEDURE:70, REFERENCE:71, LESSON:72, VALIDATED:83, SUPERSEDED:84, RELATES_TO:90, DERIVED_FROM:91, SUPERSEDES:92, SYSTEM:98, ANCHOR:279, LINKED:280, LEXICAL:281

**Utilisé hors paquet (vulture lancé par paquet ne voit pas l'appelant)** (217)

- `studio_contracts/admission.py` : AdmissionBatchRequest:83, AdmissionBatchRefused:116, AdmissionBatchResult:125
- `studio_contracts/agent_identity.py` : logical_harness:22, AgentIdentityRequest:27, AgentIdentityResult:34, AgentIdentityLinkRequest:53, AgentIdentityReconciliationPlan:69
- `studio_contracts/ai_integration.py` : AiIntegrationStatus:68
- `studio_contracts/ai_work.py` : AIWorkLog:24, AIWorkLogCreate:49, AIWorkLogUpdate:72
- `studio_contracts/auth.py` : User:50, AgentCreate:109, AgentEnsureResult:131, UserCreate:139, MachineCreate:149, MachineUpdate:165, MachineWorkstationUpdate:171, MachineCreated:178, HeartbeatRequest:228, HeartbeatResponse:238, EligibleMachines:271
- `studio_contracts/bootstrap.py` : bootstrap_version_gate:70, bootstrap_manifest_problems:176, build_dry_run_report:339
- `studio_contracts/bootstrap_plan.py` : segment_for_scope:40, BootstrapPlanRequest:50, BootstrapPlan:79
- `studio_contracts/budgets.py` : BudgetPolicyUpdate:163, BudgetPolicyApprove:170, BudgetStatus:216, BudgetRefusal:232
- `studio_contracts/builds.py` : Build:22, GitHubIntegration:45, GitHubIntegrationCreate:59, GitHubIntegrationUpdate:66, ProducerJob:89, ProducerJobRequest:106, GitHubWebhookResult:112
- `studio_contracts/claims.py` : ResourceClaimCreate:41
- `studio_contracts/common.py` : Page:26
- `studio_contracts/completion.py` : check_completion:46
- `studio_contracts/coordination.py` : COORDINATION_PATH_MAX:23, COORDINATION_SESSION_LIMIT:24, COORDINATION_EVENT_PREFIX:25, CoordinationEmit:42, CoordinationEmitted:59
- `studio_contracts/decisions.py` : Decision:16, DecisionCreate:32, DecisionSupersede:41
- `studio_contracts/discovery.py` : ProductDiscovery:25
- `studio_contracts/events.py` : EventCreate:132
- `studio_contracts/execution_snapshot.py` : capture_reason:221, ExecutionSnapshot:229, check_payload_size:291, resolution_refs:375
- `studio_contracts/handoff.py` : HandoffRequest:34, HandoffResult:59
- `studio_contracts/initialization.py` : ProjectInitializationRequest:194, InitializationPreview:236, InitializationResult:249, initialization_plan_problems:279, count_actions:364, blocking_problems:372
- `studio_contracts/launch_grants.py` : MachineLaunchGrantCreate:9, MachineLaunchGrant:18
- `studio_contracts/library.py` : parse_dependency_selection:81, DependencyUpdates:95, binding_scope_allows:137, LibraryResource:161, LibraryResourceCreate:189, LibraryVersionBatchGet:225, LibraryVersionBatchResult:238, LibraryVersionCreate:245, LibraryActivate:253, LibraryDeprecate:262, LibraryResolution:280, LibraryProjectLock:295, LibraryLockCreate:307, workflow_validation_errors:672, hook_validation_errors:895, parse_rule_content:973, parse_skill_content:981
- `studio_contracts/local/bridge.py` : check_capability:634
- `studio_contracts/local/workspace.py` : WORKSPACE_MARKER_RELATIVE_PATH:26, WORKSPACE_CONFIG_BACKUP_SUFFIX:27, WorkspaceMarker:145, workspace_config_relative_path:318
- `studio_contracts/mission.py` : MISSION_DEFAULT_LIMIT:56, MISSION_MAX_LIMIT:57, ProjectMission:168
- `studio_contracts/profiles.py` : ProfileEnforcementCode:59, reference_work_profile:156, resolve_profile:280, pin_profile:363
- `studio_contracts/project_context.py` : MAX_LIMIT:48, MIN_MAX_CHARS:50, MAX_MAX_CHARS:51, ITEM_TEXT_CAP:52, PROJECT_DESCRIPTION_CAP:53, MIN_TEXT_CHARS:54, MAX_QUERY_TERMS:56, MAX_KNOWN_IDS:58, MAX_PATH_CHARS:59, MAX_SOURCE_REFERENCES:60, LIBRARY_SCAN_CAP:61, MIN_TERM_LENGTH:62, MAX_MATCHED_TERMS_SHOWN:63, ROADMAP_BUDGET_SHARE:64, AIWORK_BUDGET_SHARE:65, AIWORK_LIST_CAP:66, NOTES_BUDGET_SHARE:68, NOTE_SUMMARY_CAP:69
- `studio_contracts/project_state.py` : ProjectState:11
- `studio_contracts/projects.py` : Project:9, ProjectCreate:17, ProjectMember:23
- `studio_contracts/resolution.py` : AgentResolutionRequest:305, resolve_agent:383
- `studio_contracts/review_queue.py` : ReviewQueue:129
- `studio_contracts/roadmaps.py` : MAX_LINKS_PER_STEP:58, transition_target:191, transition_requires_provision:195, is_agent_write:227, write_allowed:270, derive_step_state:445, waiting_on:464, compute_progress:483, Roadmap:555, RoadmapCreate:565, RoadmapImport:576, RoadmapUpdate:589, PhaseCreate:602, PhaseUpdate:610, StepCreate:616, StepUpdate:626, Reorder:671, DependencyChange:681, LinkTask:692, RoadmapRevision:721, RoadmapRevisionSummary:736, ProposalCreate:754, RoadmapDiff:798, HydrationApplyRequest:813, HydrationResult:853, count_hydration:868, RoadmapErrorDetail:900
- `studio_contracts/runtime.py` : RuntimeRegistrationUpdateRequest:210, RuntimeBinding:262, RuntimeBindingCreate:281, RuntimeResolution:292
- `studio_contracts/sessions.py` : WorkSessionCreate:37
- `studio_contracts/start_work.py` : StartWorkRequest:34, StartWorkResult:68
- `studio_contracts/sync.py` : SYNC_DEFAULT_LIMIT:21, SYNC_MAX_LIMIT:22, SYNC_SCAN_CAP:23
- `studio_contracts/task_launch.py` : TERMINAL_STATUSES:79, ALLOWED_TRANSITIONS:91, TaskLaunchCreate:111, TaskLaunchRetry:223, TaskLaunchView:235, TaskLaunchMachineReport:249, TaskLaunchCancel:262, TaskLaunchPull:270, TaskLaunchCredential:277
- `studio_contracts/task_launch_replay.py` : TaskLaunchReplayPreview:110, verdict_for:149, limitation:157, preview_digest:162, substitutions:181
- `studio_contracts/tasks.py` : TaskCreate:30
- `studio_contracts/timeline.py` : Timeline:15
- `studio_contracts/transfers.py` : Transfer:32, TransferCreate:58, UploadInitiateRequest:69, UploadInitiateResponse:80, UploadPartsRefreshRequest:95, UploadPartsRefreshResponse:109, UploadCompleteRequest:124, DownloadUrlResponse:142, TransferConsumption:148
- `studio_contracts/usage.py` : coverage_by_metric:198, total_tokens:208, UsageLedgerEntryCreate:261, UsageLedgerEntry:269, UsageLedgerCorrection:277, USAGE_SUMMARY_MAX_GROUPS:299, UsageSummary:409, CONFIGURATION_HISTORY_MAX_GROUPS:429, CONFIGURATION_MIXED:430, TESTS_NOT_QUALITY_CAVEAT:434, NOT_RANKED_CAVEAT:435, NO_MINIMUM_CAVEAT:436, LEDGER_DERIVED_CAVEAT:437, ConfigurationHistory:506
- `studio_contracts/vault.py` : VAULT_SEARCH_LIMIT_DEFAULT:26, VAULT_SEARCH_LIMIT_MAX:27, VAULT_SEARCH_MAX_CHARS_DEFAULT:29, VAULT_SEARCH_MAX_CHARS_MAX:30, VAULT_SEARCH_PATHS_MAX:31, VaultNoteCreate:176, VaultNoteUpdate:203, VaultTreePage:259, VaultVersionPage:267, VaultSearchResult:295
- `studio_contracts/version.py` : CLIENT_FAMILIES:5, CLIENT_HEADER:7, VERSION_HEADER:8, UPDATE_HEADER:9, LATEST_HEADER:10, CLIENT_STATUS_CURRENT:12, CLIENT_STATUS_RECOMMENDED:13, VersionInfo:16
- `studio_contracts/work_profile_pack.py` : WorkProfilePackRequest:34, WorkProfilePackPreview:40

**Validator/serializer Pydantic** (90)

- `studio_contracts/agent_identity.py` : _resolution_matches_state:42
- `studio_contracts/bootstrap.py` : _no_absolute_paths:150, _coherent_absent:252
- `studio_contracts/budgets.py` : _thresholds:141, _enforceable:148
- `studio_contracts/execution_snapshot.py` : _consistent_status:188, _no_secret_material:202
- `studio_contracts/initialization.py` : _persistable_level:168
- `studio_contracts/library.py` : _check:447, _check_files:466, _check_files:497
- `studio_contracts/local/bridge.py` : _payload_matches_spec:540, _payload_matches_spec:563, _error_correlates:580, _payload_matches_event:592, _bounded:608
- `studio_contracts/local/code_graph.py` : _consistent:47, _partial_when_not_ready:91, _accepted_has_operation:115
- `studio_contracts/local/daemon_control.py` : _lock_key_matches_profile:118, _partition_and_block:137, _shape:160, _timestamps_and_error:184, _service_shapes:215, _error_matches_outcome:244
- `studio_contracts/local/graph.py` : _members:107, _inferred_needs_evidence:126, _well_formed:176
- `studio_contracts/local/handshake.py` : _ordered:35, _unique:73, _consistent:131
- `studio_contracts/local/harness.py` : _consistent:63, _hashes_fit_kind:138, _plan_window:171, _applied_is_reversible:197, _consistent:248
- `studio_contracts/local/identity.py` : _error_matches_status:105, _single_profile:133, _enrolled_has_machine:243
- `studio_contracts/local/knowledge.py` : _consistent:51, _partial_when_not_ready:91, _accepted_has_operation:145
- `studio_contracts/local/launch.py` : _unique_harnesses:26, _unique_detected:40
- `studio_contracts/local/machine_setup.py` : _diff_only_when_differs:103, _reason_matches_state:120, _counts:136, _counts:154, _plan_window:182, _unique_items:203, _backup_implies_write_attempt:215, _written_only_when_synced:231, _backups_flag:246
- `studio_contracts/local/outbox.py` : _counts_match_presence:33
- `studio_contracts/local/provider.py` : _shape:44
- `studio_contracts/local/publication.py` : _all_classes_local:50, _shape:94, _shape:126
- `studio_contracts/local/skills.py` : _one_target_per_harness:49, _consistent:69, _consistent_resolutions:141
- `studio_contracts/local/workspace.py` : _unique_repos:39, _default_watcher_config:112, _features_have_config:126, _matches_behavior:206, _root_transition_is_confirmed:298
- `studio_contracts/profiles.py` : _supported_version:99, _unique_permissions:109
- `studio_contracts/project_context.py` : _drop_known_text:116, _drop_known_text:139, _drop_known_text:193, _drop_known_text:226, _drop_unset_roadmap_cap:245, _drop_absent_roadmap:324
- `studio_contracts/roadmaps.py` : _consistent:660, _comment_required:713, _comment_required:775
- `studio_contracts/runtime.py` : _validate_registry_row:134, _validate_registry_create:164, _validate_registry_update:201, _require_anchor:247
- `studio_contracts/usage.py` : _coverage_matches_value:97, _value_needs_a_currency:128, _cache_not_larger_than_input:187, _consistent:255, _consistent:293
- `studio_contracts/vault.py` : _consistent:148, _consistent:193, _changes_something:219
- `studio_contracts/work_profile_pack.py` : _explicit_agent_references:19

**Paramètre de signature imposée (__exit__/__aexit__, Protocol, validator cls, hook pydantic-settings)** (4)

- `studio_contracts/budgets.py` : cls:143
- `studio_contracts/local/workspace.py` : cls:114
- `studio_contracts/profiles.py` : cls:101, cls:111

### studio-code-graph


**Utilisé hors paquet (vulture lancé par paquet ne voit pas l'appelant)** (7)

- `studio_code_graph/service.py` : reindex:236, on_git_change:268, search_symbols:287, graph_page:305, graph_expand:317, wait_idle:351, close:363

**Champ Pydantic / model_config (sérialisé, schéma)** (1)

- `studio_code_graph/store.py` : model_config:30

### studio-workspaces


**Utilisé hors paquet (vulture lancé par paquet ne voit pas l'appelant)** (6)

- `studio_workspaces/daemon_config.py` : enabled:10, repo_paths:11
- `studio_workspaces/watch_source.py` : plan:20
- `studio_workspaces/workspace_bridge.py` : get_config:62, confirm:76, git_status:96
