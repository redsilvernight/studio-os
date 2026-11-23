"""Liste blanche vulture du contrôle de code mort (PC5).

Format vulture : chaque `_.nom` marque `nom` comme utilisé, quel que soit le fichier (vulture
compare des noms, pas des chemins). Le commentaire en fin de ligne donne l'emplacement signalé.
Toute entrée est justifiée par sa catégorie ou par sa note ; règles et procédure :
docs/library/roadmap-pc/PC5-guard.md. Les catégories structurelles (routes FastAPI, validateurs
Pydantic, dispatch des middlewares, model_config...) sont écartées par les options
[tool.vulture] du pyproject.toml racine, pas ici.
"""

# ruff: noqa: B018, F821


# --- Éléments PC0 « à vérifier » encore présents -------------------------------------------------

# Classés « à vérifier » par PC0 (souvent : utilisés seulement par les tests) et non supprimés en
# PC1-PC4. Chacun reste une décision ouverte, pas un oubli : sa note reprend la preuve de PC0
# (docs/library/roadmap-pc/PC0-annexe-python-*.md). Supprimer l'entrée avec le code quand la
# décision tombe.

# classify_artifact_state — PC0 à vérifier : tests seulement
# (tests/harness/test_drift_taxonomy.py)
_.classify_artifact_state  # studio_client/adapters/base.py

# model_agent_create — PC0 à vérifier : tests seulement
_.model_agent_create  # studio_client/agent_identity.py

# is_legacy_model_key — PC0 à vérifier : tests seulement
_.is_legacy_model_key  # studio_client/agent_identity.py

# healthz — PC0 à vérifier : tests seulement (tests/client/test_api_client.py:100)
_.healthz  # studio_client/api_client.py

# register_agent — PC0 à vérifier : tests seulement (tests/client/test_agents_ensure.py:164)
_.register_agent  # studio_client/api_client.py

# plan_divergences — PC0 à vérifier : tests seulement
# (tests/client/test_bootstrap_p51_divergence.py)
_.plan_divergences  # studio_client/bootstrap.py

# _json_size — PC0 à vérifier : tests seulement (tests/client/context/test_context_library_p9.py)
_._json_size  # studio_client/context/composer.py

# export_diagnostics — PC0 à vérifier : tests seulement ; homonyme commande Tauri Rust
# (desktop/src-tauri/src/shell_commands.rs:246) qui ne l'appelle pas
_.export_diagnostics  # studio_client/daemon/logging.py

# _auto_sync_runner — PC0 à vérifier : attribut écrit jamais lu ; peut servir à garder une
# référence forte sur le runner d'auto-sync
_._auto_sync_runner  # studio_client/daemon/runtime.py

# WorkspaceWatch — PC0 à vérifier : tests seulement (tests/code_graph/test_git_integration.py)
_.WorkspaceWatch  # studio_client/daemon/workspace_watch.py

# minimum_supported — PC0 à vérifier : tests seulement
_.minimum_supported  # studio_client/errors.py

# remaining_bytes — PC0 à vérifier : tests seulement
_.remaining_bytes  # studio_client/errors.py

# is_current — PC0 à vérifier : tests seulement
_.is_current  # studio_client/hook_sync.py

# AGENT_STORE_REL — PC0 à vérifier : tests seulement (tests/client/test_setup_hooks.py)
_.AGENT_STORE_REL  # studio_client/hooks.py

# refresh_graph — PC0 à vérifier : méthode du Protocol GraphProvider ; tests seulement
_.refresh_graph  # studio_client/knowledge/graph.py

# registered_vaults — PC0 à vérifier : champ dataclass rempli (obsidian.py:121,128) mais jamais lu
_.registered_vaults  # studio_client/knowledge/obsidian.py

# launched — PC0 à vérifier : tests seulement (tests/knowledge/test_obsidian.py)
_.launched  # studio_client/knowledge/obsidian.py

# last_synced_at — PC0 à vérifier : tests seulement (module server_mirror testé seulement)
_.last_synced_at  # studio_client/knowledge/server_mirror.py

# list_notes — PC0 à vérifier : tests seulement
_.list_notes  # studio_client/knowledge/server_mirror.py

# ServerMirrorMemoryProvider — PC0 à vérifier : tests seulement
# (tests/client/test_vault_mirror.py)
_.ServerMirrorMemoryProvider  # studio_client/knowledge/server_mirror.py

# detach — PC0 à vérifier : tests seulement (tests/knowledge/test_service.py:70)
_.detach  # studio_client/knowledge/service.py

# VaultWriteQueue — PC0 à vérifier : tests seulement (module importé seulement par
# tests/client/test_vault_outbox.py)
_.VaultWriteQueue  # studio_client/knowledge/vault_outbox.py

# enqueue_create — PC0 à vérifier : tests seulement
_.enqueue_create  # studio_client/knowledge/vault_outbox.py

# enqueue_update — PC0 à vérifier : tests seulement
_.enqueue_update  # studio_client/knowledge/vault_outbox.py

# last_snapshot — PC0 à vérifier : tests seulement
_.last_snapshot  # studio_client/knowledge/watch.py

# attempt_count — PC0 à vérifier : champ lu seulement par tests ; colonne SQLite vivante
_.attempt_count  # studio_client/outbox/models.py

# dead_lettered — PC0 à vérifier : tests seulement
_.dead_lettered  # studio_client/outbox/replay.py

# stopped_on_transient_error — PC0 à vérifier : tests seulement
_.stopped_on_transient_error  # studio_client/outbox/replay.py

# enqueue_marker — PC0 à vérifier : tests seulement (tests/client/test_replay.py)
_.enqueue_marker  # studio_client/outbox/store.py

# start_recording — PC0 à vérifier : tests seulement
_.start_recording  # studio_client/recording/recording.py

# finish_recording — PC0 à vérifier : tests seulement
_.finish_recording  # studio_client/recording/recording.py

# create_marketing_candidate — PC0 à vérifier : tests seulement
_.create_marketing_candidate  # studio_client/recording/recording.py

# plan_skill_uninstall — PC0 à vérifier : tests seulement
# (tests/library_rebuild/test_skill_files.py)
_.plan_skill_uninstall  # studio_client/skill_sync.py

# has_removals — PC0 à vérifier : tests seulement
_.has_removals  # studio_code_graph/gitstate.py

# has_node — PC0 à vérifier : tests seulement
_.has_node  # studio_code_graph/index.py

# has_conflicts — PC0 à vérifier : tests seulement ; déplacé depuis studio_client/library_merge.py
# par f099ef02
_.has_conflicts  # studio_contracts/library_merge.py

# LOCAL_CONTRACT_VERSION — PC0 à vérifier : aucune référence, mais constante de version du
# protocole studio.local
_.LOCAL_CONTRACT_VERSION  # studio_contracts/local/common.py

# ClientUpgradeRequired — PC0 à vérifier : modèle jamais référencé (ni services, ni
# dashboard/openapi.json) ; probable corps de réponse 426 construit ailleurs à la main
_.ClientUpgradeRequired  # studio_contracts/version.py

# summarize_features — PC0 à vérifier : tests seulement
_.summarize_features  # studio_workspaces/flows.py

# confirmation_nonce — PC0 à vérifier : lu seulement par tests
_.confirmation_nonce  # studio_workspaces/picker.py

# removed_config — PC0 à vérifier : champ jamais lu ; DissociateResult exporté dans
# studio_workspaces.__all__
_.removed_config  # studio_workspaces/store.py

# preserved_root — PC0 à vérifier : tests seulement
_.preserved_root  # studio_workspaces/store.py

# migrate — PC0 à vérifier : tests seulement
_.migrate  # studio_workspaces/store.py

# dissociate — PC0 à vérifier : tests seulement
_.dissociate  # studio_workspaces/store.py

# write_marker — PC0 à vérifier : tests seulement
_.write_marker  # studio_workspaces/store.py

# HTTP_ACCESS — PC0 à vérifier : utilisé seulement par tests (test_access_registry,
# test_login_anti_enumeration) : registre d'accès vérifié par tests = garde-fou sécurité, à
# conserver a priori
_.HTTP_ACCESS  # studio_api/access_registry.py

# iter_operations — PC0 à vérifier : utilisé seulement par tests (test_access_registry,
# test_account_states)
_.iter_operations  # studio_api/access_registry.py

# require_studio_role, require_operator, studio_clause — authz par rôle de studio (DEC-0382),
# lot 1 : gardes et filtre testés (tests/api/test_authz_studio.py), câblés sur les routers et
# services par les lots 2 à 4 de la tâche f42ee9bc ; ces entrées sont à retirer à ce moment
_.require_studio_role  # studio_api/deps.py
_.require_operator  # studio_api/deps.py
_.studio_clause  # studio_api/services/authz.py

# reset_engine — PC0 à vérifier : utilisé seulement par tests (test_events, client/test_cli) +
# DEC-0018
_.reset_engine  # studio_api/db/session.py

# event_listener — PC0 à vérifier : app.state.event_listener lu seulement par
# tests/api/test_events.py:520
_.event_listener  # studio_api/main.py

# server_pid — PC0 à vérifier : server_pid lu seulement par tests/api/test_events.py:588,625
_.server_pid  # studio_api/services/event_listener.py

# get_snapshot — PC0 à vérifier : utilisé seulement par tests (test_execution_snapshots) ;
# documenté docs/mission-control/snapshot-contract.md:91
_.get_snapshot  # studio_api/services/execution_snapshots.py

# create_local_server_from_config — PC0 à vérifier : utilisé seulement par tests
# (tests/mcp/test_local_knowledge*.py)
_.create_local_server_from_config  # studio_mcp/local_server.py

# create_local_server_from_workspace — PC0 à vérifier : utilisé seulement par tests + annoncé «
# additif » dans docs/DESKTOP_P6_KNOWLEDGE_VAULT.md:149
_.create_local_server_from_workspace  # studio_mcp/local_server.py

# HANDOFF_ACK_MAX_CHARS — PC0 à vérifier : utilisé seulement par tests/mcp/test_response_budget.py
# (borne testée, non référencée par le code source)
_.HANDOFF_ACK_MAX_CHARS  # studio_mcp/response_budget.py


# --- Contrat public (PC0) ------------------------------------------------------------------------

# API publique de studio_contracts : contrat versionné, consommé hors Python (desktop, dashboard,
# contracts/) ou par les tests de contrat. Jamais retiré sans le skill contract-change.

# SUPPORTED_LAG — PC0 contrat public : module importé seulement par tests ; principe cité par
# DEC-0137
_.SUPPORTED_LAG  # studio_contracts/compatibility.py

# CHANNELS — PC0 contrat public : miroir dans desktop/scripts/*.mjs ; tests
_.CHANNELS  # studio_contracts/compatibility.py

# classify — PC0 contrat public : tests seulement (tests/contracts/test_version_compatibility.py)
_.classify  # studio_contracts/compatibility.py

# CURRENT_VERSIONS — PC0 contrat public : tests seulement
_.CURRENT_VERSIONS  # studio_contracts/compatibility.py

# COORDINATION_INTENTS — PC0 contrat public : mentionné par dashboard/src/views/activity.ts
_.COORDINATION_INTENTS  # studio_contracts/coordination.py

# profile_drift — PC0 contrat public : tests seulement
_.profile_drift  # studio_contracts/execution_snapshot.py

# INITIALIZATION_FORMAT — PC0 contrat public : tests seulement
_.INITIALIZATION_FORMAT  # studio_contracts/initialization.py

# validate_library_content — PC0 contrat public : tests seulement
# (tests/api/test_library_content.py)
_.validate_library_content  # studio_contracts/library.py

# BRIDGE_MESSAGE_ADAPTER — PC0 contrat public : tests seulement
_.BRIDGE_MESSAGE_ADAPTER  # studio_contracts/local/bridge.py

# check_reply_correlation — PC0 contrat public : tests seulement
_.check_reply_correlation  # studio_contracts/local/bridge.py

# allowlist_violations — PC0 contrat public : tests seulement
_.allowlist_violations  # studio_contracts/local/bridge.py

# SECRET_INPUT_FIELDS — PC0 contrat public : tests seulement
_.SECRET_INPUT_FIELDS  # studio_contracts/local/identity.py

# WorkspaceMigrationPolicy — PC0 contrat public : sous-classe LocalContractModel : exportée
# dynamiquement (local/export.py model_registry) dans contracts/local/manifest.json
_.WorkspaceMigrationPolicy  # studio_contracts/local/workspace.py

# ROADMAP_FORMAT — PC0 contrat public : tests seulement
_.ROADMAP_FORMAT  # studio_contracts/roadmaps.py

# effective_notes — PC0 contrat public : tests seulement ; cité dans une description OpenAPI
_.effective_notes  # studio_contracts/vault.py

# is_valid_slug — PC0 contrat public : tests seulement
_.is_valid_slug  # studio_contracts/vault.py


# --- Utilisés hors du périmètre scanné -----------------------------------------------------------

# Le contrôle ne scanne que services/*/src et packages/*/src : ces symboles sont importés par
# scripts/library_import.py (et les tests).

_.PublishError  # studio_client/publish.py
_._publish_one  # studio_client/publish.py

# --- Colonnes et attributs ORM -------------------------------------------------------------------

# Colonnes SQLAlchemy mappées (schéma, migrations Alembic) et attributs écrits sur des lignes ORM
# puis persistés par commit.

_.github_integration_id  # studio_api/db/models/build.py
_.studio_id  # studio_api/db/models/studio.py (+1)
_.is_internal  # studio_api/db/models/studio.py
_.is_operator  # studio_api/db/models/user.py
_.renewed_at  # studio_api/db/models/claim.py (+1)
_.released_at  # studio_api/db/models/claim.py (+1)
_.base_update_available  # studio_api/db/models/library.py (+1)
_.base_active_version  # studio_api/db/models/library.py (+1)
_.uploaded_at  # studio_api/db/models/transfer.py (+1)

# --- Champs de modèles Pydantic et réglages ------------------------------------------------------

# Champs de ContractModel / LocalContractModel / BaseModel / BaseSettings : lus par la
# sérialisation (réponses API et MCP, contracts/, OpenAPI du dashboard), par l'environnement ou
# par getattr (réglages *_minimum_version / *_latest_version), jamais par un accès d'attribut
# direct. Inclut les attributs posés sur une réponse Pydantic, les champs de la dataclass
# MergeConflict recopiés dans LibraryMergeConflict et les paramètres imposés de
# BaseSettings.settings_customise_sources.

_.git_watch_repo_path  # studio_client/config.py
_.git_watch_project_id  # studio_client/config.py
_.dotenv_settings  # studio_client/config.py
_.file_secret_settings  # studio_client/config.py
_.admitted_at  # studio_contracts/admission.py
_.artifact_counts  # studio_contracts/ai_integration.py
_.project_registered  # studio_contracts/ai_integration.py
_.sync_allowed  # studio_contracts/bootstrap.py
_.approval_status  # studio_contracts/budgets.py
_.ceiling_guarantee  # studio_contracts/budgets.py
_.unknown_entries  # studio_contracts/budgets.py (+1)
_.active_launches  # studio_contracts/budgets.py
_.authoritative  # studio_contracts/completion.py (+2)
_.local_policy_digest  # studio_contracts/execution_snapshot.py
_.worktree_branch  # studio_contracts/execution_snapshot.py
_.task_version  # studio_contracts/handoff.py
_.roadmap_present  # studio_contracts/initialization.py
_.pinned_version  # studio_contracts/library.py
_.update_available  # studio_contracts/library.py
_.suggested_pin  # studio_contracts/library.py
_.mutates  # studio_contracts/library.py (+1)
_.start_line  # studio_contracts/library.py (+ dataclass MergeConflict de library_merge.py)
_.base_start  # studio_contracts/library.py
_.base_end  # studio_contracts/library.py
_.intended_use  # studio_contracts/library.py
_.sent_at  # studio_contracts/local/bridge.py
_.unsupported_languages  # studio_contracts/local/code_graph.py
_.daemon_version  # studio_contracts/local/daemon_control.py
_.crashed_at  # studio_contracts/local/daemon_control.py
_.recoveries_attempted  # studio_contracts/local/daemon_control.py
_.observed_at  # studio_contracts/local/daemon_control.py
_.index_fingerprint  # studio_contracts/local/graph.py
_.total_edges  # studio_contracts/local/graph.py
_.component_version  # studio_contracts/local/handshake.py
_.silent_fallback  # studio_contracts/local/handshake.py
_.detected_version  # studio_contracts/local/harness.py
_.settings_sources  # studio_contracts/local/harness.py
_.mcp_servers  # studio_contracts/local/harness.py
_.production_approval_required  # studio_contracts/local/harness.py
_.requires_confirmation  # studio_contracts/local/harness.py (+1)
_.session_expires_at  # studio_contracts/local/identity.py
_.registered_at  # studio_contracts/local/identity.py
_.ref_id  # studio_contracts/local/identity.py
_.lookup_key  # studio_contracts/local/identity.py
_.canonical_source  # studio_contracts/local/knowledge.py
_.outgoing_links  # studio_contracts/local/knowledge.py
_.plugin_state  # studio_contracts/local/machine_setup.py
_.automatic_upload  # studio_contracts/local/publication.py
_.requires_visible_preview  # studio_contracts/local/publication.py
_.requires_explicit_confirmation  # studio_contracts/local/publication.py
_.protocol_version  # studio_contracts/local/publication.py
_.applied_at  # studio_contracts/local/skills.py
_.last_check  # studio_contracts/local/skills.py
_.error_message  # studio_contracts/local/skills.py
_.follow_symlinks  # studio_contracts/local/workspace.py
_.expires_in_s  # studio_contracts/local/workspace.py
_.current_version  # studio_contracts/local/workspace.py
_.oldest_migratable_version  # studio_contracts/local/workspace.py
_.keeps_backup  # studio_contracts/local/workspace.py
_.refuses_newer  # studio_contracts/local/workspace.py
_.data_gaps  # studio_contracts/mission.py
_.refusal_reasons  # studio_contracts/profiles.py
_.matched_terms  # studio_contracts/project_context.py
_.claimed_by_self  # studio_contracts/project_context.py
_.agent_applies  # studio_contracts/project_context.py
_.chars_used  # studio_contracts/project_context.py
_.item_text_cap  # studio_contracts/project_context.py
_.library_scan_capped  # studio_contracts/project_context.py
_.roadmap_scan_capped  # studio_contracts/project_context.py
_.in_context  # studio_contracts/project_context.py
_.criteria_total  # studio_contracts/project_context.py
_.related_tasks  # studio_contracts/project_context.py
_.active_work  # studio_contracts/project_context.py
_.roadmap_overview  # studio_contracts/project_context.py
_.omitted_for_budget  # studio_contracts/project_context.py
_.active_tasks  # studio_contracts/project_state.py
_.user_display_name  # studio_contracts/projects.py
_.user_email  # studio_contracts/projects.py
_.binding_level  # studio_contracts/resolution.py
_.via_resource_id  # studio_contracts/resolution.py
_.via_version  # studio_contracts/resolution.py
_.head_branch  # studio_contracts/review_queue.py
_.exported_at  # studio_contracts/roadmaps.py
_.task_progress  # studio_contracts/roadmaps.py
_.proposal_revision_no  # studio_contracts/roadmaps.py
_.not_applicable_reason  # studio_contracts/roadmaps.py
_.current_phase_key  # studio_contracts/roadmaps.py
_.upcoming_steps  # studio_api/services/project_context_roadmap.py (+1)
_.prepared_context  # studio_contracts/start_work.py
_.resync  # studio_contracts/sync.py
_.stale_since  # studio_contracts/task_launch.py
_.recovery  # studio_contracts/task_launch.py
_.subject_kind  # studio_contracts/task_launch_replay.py
_.limitation_codes  # studio_contracts/task_launch_replay.py
_.consumed_bytes  # studio_contracts/transfers.py
_.quota_bytes  # studio_contracts/transfers.py
_.measured_entries  # studio_contracts/usage.py
_.estimated_entries  # studio_contracts/usage.py
_.first_requested_at  # studio_contracts/usage.py
_.last_requested_at  # studio_contracts/usage.py
_.status_counts  # studio_contracts/usage.py
_.ledger_entries  # studio_contracts/usage.py
_.comparable  # studio_contracts/usage.py
_.population  # studio_contracts/usage.py
_.caveats  # studio_contracts/usage.py
_.matched_anchors  # studio_contracts/vault.py
_.token_type  # studio_api/routers/auth.py
_.expires_in  # studio_api/routers/auth.py
_.refresh_expires_at  # studio_api/routers/auth.py
_.desktop_minimum_version  # studio_api/settings.py
_.daemon_minimum_version  # studio_api/settings.py
_.dashboard_minimum_version  # studio_api/settings.py
_.desktop_latest_version  # studio_api/settings.py
_.daemon_latest_version  # studio_api/settings.py
_.dashboard_latest_version  # studio_api/settings.py
_.subscription_share  # studio_contracts/usage.py

# --- Membres d'Enum ------------------------------------------------------------------------------

# Valeurs de StrEnum sérialisées dans les contrats ; lues par valeur, pas par nom.

_.LIFETIME  # studio_contracts/budgets.py
_.IGNORE  # studio_contracts/budgets.py
_.RELEASE  # studio_contracts/budgets.py
_.MEASURED_BILLED  # studio_contracts/usage.py
_.FOLDER  # studio_contracts/claims.py
_.PROJECT_CREATED  # studio_contracts/events.py
_.DECISION_CREATED  # studio_contracts/events.py
_.AGENT_STARTED  # studio_contracts/events.py
_.AGENT_STOPPED  # studio_contracts/events.py
_.GRAPH_UPDATED  # studio_contracts/events.py
_.MEMORY_PROPOSED  # studio_contracts/events.py
_.MEMORY_UPDATED  # studio_contracts/events.py
_.TRANSFER_CREATED  # studio_contracts/events.py
_.TRANSFER_UPLOADING  # studio_contracts/events.py
_.TRANSFER_READY  # studio_contracts/events.py
_.TRANSFER_DOWNLOADED  # studio_contracts/events.py
_.TRANSFER_EXPIRED  # studio_contracts/events.py
_.TRANSFER_DELETED  # studio_contracts/events.py
_.MARKETING_POST_PUBLISHED  # studio_contracts/events.py
_.COORDINATION_HEADS_UP  # studio_contracts/events.py
_.COORDINATION_QUESTION  # studio_contracts/events.py
_.COORDINATION_BLOCKED_BY  # studio_contracts/events.py
_.COORDINATION_HANDOFF  # studio_contracts/events.py
_.PROFILE_UNAVAILABLE  # studio_contracts/execution_snapshot.py
_.PAYLOAD_TOO_LARGE  # studio_contracts/execution_snapshot.py (+1)
_.INTERNAL  # studio_contracts/execution_snapshot.py
_.WATCHER  # studio_contracts/local/common.py
_.UNKNOWN_COMMAND  # studio_contracts/local/common.py
_.LANGUAGE_UNSUPPORTED  # studio_contracts/local/common.py
_.ENABLE_FEATURE  # studio_contracts/local/handshake.py
_.PROCESS_ENVIRONMENT  # studio_contracts/local/identity.py
_.PLUGIN  # studio_contracts/local/machine_setup.py
_.PENDING_MARKERS  # studio_contracts/local/outbox.py
_.DEAD_LETTER  # studio_contracts/local/outbox.py
_.MULTIPART_UPLOADS  # studio_contracts/local/outbox.py
_.PATHS  # studio_contracts/local/publication.py
_.VAULT_CONTENT  # studio_contracts/local/publication.py
_.INDEXES  # studio_contracts/local/publication.py
_.FILESYSTEM_DETAILS  # studio_contracts/local/publication.py
_.HARNESS_CONFIG  # studio_contracts/local/publication.py
_.SENSITIVE_DIAGNOSTICS  # studio_contracts/local/publication.py
_.WORKSPACE_CONFIG  # studio_contracts/local/publication.py
_.SECRETS  # studio_contracts/local/publication.py
_.SHAREABLE_SUMMARY  # studio_contracts/local/publication.py
_.REVIEW  # studio_contracts/roadmaps.py
_.IDEMPOTENCY_KEY_PAYLOAD_MISMATCH  # studio_contracts/roadmaps.py
_.FORBIDDEN  # studio_contracts/roadmaps.py
_.AGENT_NOT_FOUND  # studio_contracts/task_launch.py
_.UPLOADING  # studio_contracts/transfers.py
_.DOWNLOADED  # studio_contracts/transfers.py
_.DELETED  # studio_contracts/transfers.py
_.ASSET  # studio_contracts/transfers.py
_.RAW_RECORDING  # studio_contracts/transfers.py
_.CONVENTION  # studio_contracts/vault.py
_.PROCEDURE  # studio_contracts/vault.py
_.REFERENCE  # studio_contracts/vault.py
_.LESSON  # studio_contracts/vault.py
_.RELATES_TO  # studio_contracts/vault.py
_.DERIVED_FROM  # studio_contracts/vault.py

# --- Protocoles de la bibliothèque standard et annotations en chaîne -----------------------------

# daemon_threads : attribut lu par socketserver ; CursorResult : utilisé dans
# cast("CursorResult[Any]", ...) que vulture ne lit pas.

_.daemon_threads  # studio_client/daemon/service.py
_.CursorResult  # studio_api/admin_cli.py

# --- Atelier : champs écrits ou appelés hors des chemins analysés ---------------------------------

# suspension_reason : colonne écrite par la console opérateur, exposée par StudioRead ;
# reset_request_windows : réinitialisation du budget de requêtes, appelée par tests/conftest.py.

_.suspension_reason  # studio_api/db/models/studio.py, routers/users.py
_.reset_request_windows  # studio_api/services/entitlements.py
