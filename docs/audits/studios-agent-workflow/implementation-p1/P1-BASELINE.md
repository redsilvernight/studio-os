# P1 — baseline avant modification

Branche `dev`, HEAD `d5912008bf8847835d454d3af5083a779909754c`, index vide. Inventaire exhaustif, SHA-256 et tailles : `baseline.json`; copies exactes : `baseline-files/`. Trois worktrees conservés.

Deux propriétaires : `studio_client.cli._rules_sync` (source `.agents/rules`, marqueurs GENERATED RULES) et `C:/Users/redsi/.codex/sync-claude-config.ps1` (`Sync-ProjectRules`, source `.claude/rules`, marqueurs SYNCED CLAUDE RULES). Le synchroniseur copie aussi agents et skills projet. Aucun correctif externe appliqué.

Six dérives Codex : description doublement quotée, perte de reasoning_effort et marqueur claude-code; contenu importé du synchroniseur personnel, intention humaine des différences inconnue. Préservées, candidats seulement. `.codex/config.toml`, `opencode.json`, pricing/tests usage et tous changements P0 sont hors écrasement.

Conflits P1 : AGENTS.md déjà modifié par doublon externe; six TOML déjà modifiés; autres sources ciblées propres. Aucun reset/clean/changement de branche.

```text
 M .codex/agents/contract-guardian.toml
 M .codex/agents/dashboard-a11y.toml
 M .codex/agents/migration-reviewer.toml
 M .codex/agents/studio-architect.toml
 M .codex/agents/studio-tester.toml
 M .codex/agents/sync-debugger.toml
 M .codex/config.toml
 M AGENTS.md
 M docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/02_API_CONTRACT.md
 M docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/07_MCP_CONTRACT.md
 M docs/mission-control/local-collectors.md
 M opencode.json
 M packages/studio-client/src/studio_client/usage/local/pricing.py
 M packages/studio-contracts/src/studio_contracts/__init__.py
 M packages/studio-contracts/src/studio_contracts/handoff.py
 M packages/studio-contracts/src/studio_contracts/sync.py
 M services/api/src/studio_api/services/handoff.py
 M services/api/src/studio_api/services/sessions.py
 M services/api/src/studio_api/services/sync.py
 M services/api/src/studio_api/services/tasks.py
 M services/mcp/src/studio_mcp/response_budget.py
 M services/mcp/src/studio_mcp/server.py
 M services/mcp/src/studio_mcp/tools/handoff.py
 M tests/contracts/test_version_compatibility.py
 M tests/mcp/test_handoff.py
 M tests/mcp/test_response_budget.py
 M tests/usage_local/test_usage_local.py
?? docs/audits/studios-agent-workflow/01-MCP-INVENTORY.md
?? docs/audits/studios-agent-workflow/02-CURRENT-WORKFLOWS.md
?? docs/audits/studios-agent-workflow/03-OPTIMAL-WORKFLOWS.md
?? docs/audits/studios-agent-workflow/04-SKILLS-ARCHITECTURE.md
?? docs/audits/studios-agent-workflow/05-OPTIMIZATION-OPPORTUNITIES.md
?? docs/audits/studios-agent-workflow/06-IMPLEMENTATION-ROADMAP.md
?? docs/audits/studios-agent-workflow/FINAL-AUDIT.md
?? docs/audits/studios-agent-workflow/implementation-p0/P0-BASELINE.json
?? docs/audits/studios-agent-workflow/implementation-p0/P0-DESIGN.md
?? docs/audits/studios-agent-workflow/implementation-p0/P0-FINAL.md
?? docs/audits/studios-agent-workflow/implementation-p0/P0-IMPLEMENTATION.md
?? docs/audits/studios-agent-workflow/implementation-p0/P0-PRESERVATION.json
?? docs/audits/studios-agent-workflow/implementation-p0/P0-PYTHON-FILES.txt
?? docs/audits/studios-agent-workflow/implementation-p0/P0-TEST-REPORT.md
?? docs/audits/studios-agent-workflow/implementation-p0/contracts.log
?? docs/audits/studios-agent-workflow/implementation-p0/cursor-after.log
?? docs/audits/studios-agent-workflow/implementation-p0/cursor-before.log
?? docs/audits/studios-agent-workflow/implementation-p0/delivery-after.log
?? docs/audits/studios-agent-workflow/implementation-p0/delivery-before.log
?? docs/audits/studios-agent-workflow/implementation-p0/delivery-race-before.log
?? docs/audits/studios-agent-workflow/implementation-p0/final-targeted.log
?? docs/audits/studios-agent-workflow/implementation-p0/final-validation.log
?? docs/audits/studios-agent-workflow/implementation-p0/graphify.log
?? docs/audits/studios-agent-workflow/implementation-p0/migrations.log
?? docs/audits/studios-agent-workflow/implementation-p0/mypy.log
?? docs/audits/studios-agent-workflow/implementation-p0/openapi-comparison.json
?? docs/audits/studios-agent-workflow/implementation-p0/p0-targeted.log
?? docs/audits/studios-agent-workflow/implementation-p0/postgres-stop.log
?? docs/audits/studios-agent-workflow/implementation-p0/regression.log
?? docs/audits/studios-agent-workflow/implementation-p0/resync-before.log
?? docs/audits/studios-agent-workflow/implementation-p0/ruff.log
?? docs/audits/studios-agent-workflow/implementation-p0/task-after.log
?? docs/audits/studios-agent-workflow/implementation-p0/task-before.log
?? docs/audits/studios-agent-workflow/implementation-p0/test-env.log
?? library/studio/README.md
?? library/studio/agents/chef-marketing.md
?? library/studio/agents/devops.md
?? library/studio/agents/godot-tester.md
?? library/studio/agents/graphiste.md
?? library/studio/agents/monteur-video.md
?? library/studio/agents/reader.md
?? library/studio/agents/sound-designer.md
?? library/studio/agents/verifier.md
?? library/studio/agents/worker.md
?? library/studio/hooks/git-guard.md
?? library/studio/hooks/git-guard.ps1
?? library/studio/hooks/session-start.md
?? library/studio/hooks/session-start.ps1
?? library/studio/hooks/stop-check.md
?? library/studio/hooks/stop-check.ps1
?? library/studio/profiles/single-agent.md
?? library/studio/rules/code-minimal.md
?? library/studio/rules/core.md
?? library/studio/rules/git-flow.md
?? library/studio/rules/memory.md
?? library/studio/rules/routing.md
?? library/studio/rules/studio-protocol.md
?? library/studio/rules/studio-workflow.md
?? library/studio/skills/delegate/SKILL.md
?? library/studio/skills/itch-io-publish/SKILL.md
?? library/studio/skills/new-project/SKILL.md
?? library/studio/skills/next/SKILL.md
?? library/studio/skills/phase/SKILL.md
?? library/studio/skills/pixel-art-direction/SKILL.md
?? library/studio/skills/release/SKILL.md
?? library/studio/skills/review-pr/SKILL.md
?? library/studio/skills/roadmap-builder/SKILL.md
?? library/studio/skills/sound-design/SKILL.md
?? library/studio/skills/tiktok-pipeline/SKILL.md
?? library/studio/skills/triage/SKILL.md
?? library/studio/skills/workstation-setup/SKILL.md
?? library/studio/workflows/hotfix.md
?? library/studio/workflows/new-project.md
?? library/studio/workflows/phase.md
?? library/studio/workflows/release.md
?? library/studio/workflows/task.md
?? tests/api/test_p0_task_concurrency.py
?? tests/mcp/test_p0_cursor_concurrency.py
?? tests/mcp/test_p0_delivery.py
?? tests/mcp/test_p0_delivery_races.py
```
