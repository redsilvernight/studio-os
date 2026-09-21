---
name: mcp-tools
stable_key: mcp-tools
applies_to: ["**/mcp/**/*.py", "**/mcp_server/**/*.py", "**/*mcp*tool*.py"]
---

# MCP Tool Conventions

Reference: `TECH/07_MCP_CONTRACT.md`.

- Tool names are prefixed `studio_` (`studio_get_task`, `studio_claim_resource`, ...) — keep new tools consistent with the existing list rather than inventing a parallel naming scheme.
- An MCP handler is a thin layer: validate input, call the existing service function used by the API layer, return a compact result. Do not duplicate business logic between the API router and the MCP tool.
- The tool's docstring/description is what the model uses to pick it — write it precise and specific, not generic; a vague description causes wrong tool selection.
- Responses are compact: useful fields only, and support the standard filters (`project`, `task`, `since`, `limit`) where the underlying resource supports them.
- Errors returned to the model must be explicit and machine-readable — catch exceptions in the handler and return a structured error, never let the server crash or leak a raw stack trace.
- Never move large file bytes through an MCP tool call. `studio_create_transfer_metadata` / `studio_get_transfer` / `studio_request_transfer_download` return metadata and authorization only — the actual bytes go client-to-MinIO directly, per `TECH/06_STORAGE_TRANSFER_SPEC.md`.
- Respect the read/write boundary per agent role (`AI/02_AGENT_RULES.md`): a tool that writes shared memory or promotes a Decision must check the caller's role, not assume Claude-orchestrator privileges for every caller.
