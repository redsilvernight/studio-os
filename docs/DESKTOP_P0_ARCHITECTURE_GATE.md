# Studi'OS Desktop — P0 Architecture Gate & Audit

Status: **P0 DECISIONS ACCEPTED — final independent review PASS**
Date: 2026-09-20
Baseline: `desktop/architecture` from `origin/master` at `07a1cb74fda10ac8b42b7366170eba22d3df21f1`
Scope: architecture audit and decisions only; no Desktop implementation.

## 1. Git initial state and baseline

The canonical repository was fetched before the audit. `master` and
`origin/master` were identical (`0 ahead / 0 behind`) at `07a1cb7`
(`docs(roadmaps): accept P10 release gate`). The main worktree already contained
unrelated edits to `AGENTS.md`, `.claude/agents/studio-tester.md`, and
`.codex/agents/studio-tester.toml`, plus untracked `3479c52/` and `output/`.
Those files were neither modified nor moved.

The P0 baseline is therefore the clean, isolated worktree
`.claude/worktrees/desktop-architecture` on branch `desktop/architecture`,
created from the fetched `origin/master`. Other worktrees were left intact.

## 2. Existing repository audit

| Area | Status | Verified implementation | Desktop gap |
|---|---|---|---|
| Dashboard | **EXISTS** | Vanilla TypeScript + Vite 6 (`dashboard/package.json`), hash router (`dashboard/src/router.ts`), typed OpenAPI client (`dashboard/src/api.ts`), JWT authentication (`dashboard/src/auth.ts`), REST and SSE (`dashboard/src/sse.ts`) | No native shell, WebView policy, tray, sidecar, updater, installer, or native bridge |
| Daemon | **PARTIAL** | `HeartbeatDaemon` and composition root in `packages/studio-client/src/studio_client/daemon/heartbeat.py`; bounded retry and interruptible stop | No process supervisor, single-instance guard, health bridge, restart policy, log rotation, or packaged service lifecycle |
| Git watcher | **EXISTS** | `GitWatcher` in `watchers/git_watcher.py`, common `PollingWatcher` in `watchers/base.py`; persists baseline and enqueues events transactionally | Polling only; requires local `git`; no Desktop status/control surface or filesystem relocation handling |
| Godot watcher | **EXISTS** | `GodotWatcher` in `watchers/godot_watcher.py` using `tasklist`/`ps` | Process-name probing is coarse; no Desktop diagnostics |
| Heartbeat | **EXISTS** | Daemon calls `StudioApiClient.send_heartbeat`; server route is `POST /api/v1/heartbeats`; default cadence is approximately 30 seconds with jitter | No visible local health/capability contract; documentation still contains one historical stream path |
| Offline queue | **EXISTS** | SQLite WAL outbox, replay, dead letter, sync state, and multipart state in `outbox/` | Current default path is not partitioned visibly by server/account/workspace; a Desktop profile switch must not replay under the wrong identity |
| Local MCP | **EXISTS** | Read-only stdio server in `services/mcp/src/studio_mcp/local_server.py`; Vault and Graph providers under deny-by-default scope | It is intentionally not a Desktop control bridge and must not be repurposed as one |
| Knowledge/Vault | **PARTIAL** | `VaultMemoryProvider` reads and searches local Markdown; `ScopePolicy` blocks traversal/symlink escape; ADR projection tooling exists | No native browser/editor, persistent search index, lifecycle, workspace bootstrap, or corruption recovery UI |
| Code graph | **PARTIAL** | `GraphifyGraphProvider` reads `graph.json` and `manifest.json`; context composer consumes it locally | No `CodeGraphProvider` contract, installation manager, packaged runtime, invalidation service, progress model, or Desktop UI |
| Machine provisioning | **PARTIAL** | Server provisioning services/routes and `studio-admin`; opaque machine token, revocation, keyring storage in `tokens.py` | Token is produced out of band; no graphical enrolment, rotation, repair, or multi-server profile UX |
| Desktop shell | **ABSENT** | No Tauri, Electron, Cargo, native manifest, installer, or bridge dependency was found | Entire P2+ product surface remains to be built after P0/P1 approval |

The repository confirms the intended split: the VPS owns shared business state;
`studio-client` owns local state and resilient synchronization; the Dashboard is
the common business UI. The actual SSE endpoint is
`/api/v1/events/stream`, not the historical `/api/v1/stream` wording still
present in `TECH/01_ARCHITECTURE.md`.

## 3. Tauri 2 versus Electron for Studi'OS

| Criterion | Tauri 2 | Electron | Studi'OS consequence |
|---|---|---|---|
| Existing Vite Dashboard | Direct static frontend reuse | Direct static frontend reuse | Tie; preserve the standalone web build in both cases |
| Native boundary | Rust commands/plugins with explicit capabilities | Node main/preload with `contextBridge` IPC | Tauri's capability model better expresses the required small allowlist |
| Python daemon sidecar | First-class `externalBin`; target-specific binary naming | `child_process`/utility process plus packager configuration | Both work; Tauri maps more directly to the thin-shell target |
| Tray/dialogs/deep links/filesystem | Plugins and scoped permissions | Mature built-in APIs | Electron is operationally familiar; Tauri is narrower by default |
| WebView/runtime size | Uses Windows WebView2 | Ships Chromium and Node | Tauri should produce a smaller shell; no unverified numerical promise is made |
| Security maintenance | Rust core + WebView2 + selected plugins | Electron + Chromium + Node + npm surface | Electron requires continuous framework updates and strict renderer isolation |
| Updater | Signed updater plugin; MSI/NSIS artifacts | `autoUpdater`, Squirrel/MSIX paths | Both are viable; neither removes signing/release obligations |
| Windows signing | Supported; certificate/reputation still required | Supported through Forge/tooling | Tie at the architectural level |
| Build/CI cost | Adds Rust toolchain and Windows target build | Adds Electron/Forge and larger artifacts | Tauri has higher initial toolchain novelty; Electron has larger recurring runtime surface |
| Dashboard autonomy | Preserved if web-only code never imports native APIs directly | Preserved with the same adapter discipline | Mandatory in either choice |

### Decision (accepted 2026-09-20)

Use **Tauri 2** as the primary Desktop architecture, subject to a bounded P2
technical gate after P1 proves: packaged Dashboard loading, typed IPC, Python
sidecar lifecycle, keyring access, REST/SSE connectivity, and Windows signing.
Electron is the documented fallback if that gate fails or the Rust/build cost is
disproportionate. This is not permission to start P1 or P2.

The relevant upstream facts are documented by Tauri for
[sidecars](https://v2.tauri.app/develop/sidecar/),
[capabilities](https://v2.tauri.app/security/capabilities/),
[updates](https://v2.tauri.app/plugin/updater/), and
[Windows signing](https://v2.tauri.app/distribute/sign/windows/). Electron's
[process model](https://www.electronjs.org/docs/latest/tutorial/process-model),
[security checklist](https://www.electronjs.org/docs/latest/tutorial/security),
and [Windows updater](https://www.electronjs.org/docs/latest/api/auto-updater)
show the viable fallback and its renderer/IPC obligations.

## 4. Graphify audit

| Question | Finding |
|---|---|
| Product | PyPI package `graphifyy`, command/import `graphify`, official repository `Graphify-Labs/graphify` |
| Installed version | `0.9.59`, installed with `uv tool`; Python `>=3.10` |
| Core dependencies | NetworkX, NumPy, RapidFuzz, Tree-sitter plus language grammars; optional extras add MCP, PDF, watch, Office, graph DBs, video, or external model SDKs |
| Current execution | Project launcher `scripts/graphify-studio.ps1` invokes the external installation and forces `GRAPHIFY_OUT=E:\Graphify\Studio-OS\graphify-out` |
| Index/storage | Local `graph.json` node-link graph, `manifest.json`, reports and optional derived artifacts; Studio OS reads existing artifacts only |
| Windows | **Verified locally**: version and queries run on this Windows host |
| Installed footprint | Approximately 175,523,159 bytes and 6,806 files for the current uv tool environment; this is an observed installation, not a release-size guarantee |
| Licence | Distribution contains Apache License 2.0, `NOTICE`, and retained pre-relicensing MIT text; upstream metadata declares Apache-2.0 |
| Redistribution | Core redistribution appears permitted when Apache-2.0/NOTICE obligations are met. **Not fully resolved for an embedded product** until all bundled transitive dependencies, optional extras, trademarks, notices, and build method are audited |
| Update mechanism | Currently `uv tool install/upgrade graphifyy`; no Studio OS managed update or compatibility pin exists |

### Integration decision (accepted 2026-09-20)

P1 defines a neutral `CodeGraphProvider`. Graphify remains an optional adapter.
The P0 recommendation is **managed separate installation**, not an embedded
sidecar or vendored Python package. It is the lowest-risk path while preserving
independent updates and avoiding an unaudited 175 MB dependency environment.

- Embedded sidecar: technically plausible after freezing a Python executable,
  but packaging, startup, integrity, licence inventory, and update coupling are
  unresolved.
- Embedded package/runtime: feasible but exposes the largest Python/dependency
  management surface and is not recommended for the first release.
- Managed separate install: recommended initial mode; detect version and
  capabilities, offer an explicit install/repair action, and keep the feature
  disabled without it.

Sources: installed package metadata and licences; upstream
[repository](https://github.com/Graphify-Labs/graphify),
[pyproject metadata](https://github.com/Graphify-Labs/graphify/blob/v8/pyproject.toml),
and [Apache licence](https://github.com/Graphify-Labs/graphify/blob/v8/LICENSE).

## 5. Knowledge Vault and Obsidian

The current layers are distinct and must remain so:

1. **Canonical local data** — workspace-owned local files. Private by default.
2. **Markdown representation** — recoverable and editable without Studi'OS.
3. **Vault structure** — paths/scopes governed by explicit configuration and
   deny-by-default roots.
4. **Search/indexing** — current provider performs bounded file reads and
   substring search; there is no durable Desktop index yet.
5. **Knowledge graph** — derived data with provenance; never replaces Markdown.
6. **Obsidian integration** — optional editor/deep-link convenience only.

There is no runtime dependency on Obsidian in `studio-client`. To reach the
target, P1 must define `KnowledgeProvider`, workspace roots, canonical URI/path
rules, feature states, index format/version, rebuild semantics, and privacy
policy. P6 can then add an index and UI without changing Markdown ownership.

## 6. Target architecture and ownership

```text
                    shared business UI
          +-----------------------------------+
          | Dashboard TypeScript/Vite         |
          | web mode       | desktop adapter  |
          +-------+--------+---------+---------+
                  | REST/SSE         | typed, allowlisted IPC
                  |                  v
                  |          +------------------------+
                  |          | Tauri Desktop Shell    |
                  |          | window, tray, dialogs, |
                  |          | updater, secure store, |
                  |          | local process manager  |
                  |          +-----------+------------+
                  |                      | private local protocol
                  |                      v
                  |          +------------------------+
                  |          | Local Bridge           |
                  |          | validation/adaptation, |
                  |          | no business rules      |
                  |          +-----------+------------+
                  |                      |
                  |                      v
                  |          +------------------------+
                  |          | studio-client daemon   |
                  |          | outbox, heartbeat,     |
                  |          | Git/Godot watchers,    |
                  |          | Vault/CodeGraph, xfer  |
                  |          +-----------+------------+
                  |                      |
                  +----------------------+ REST/SSE with explicit identity
                                         v
                          +-------------------------------+
                          | VPS FastAPI / MCP / workers    |
                          | PostgreSQL / MinIO             |
                          | canonical shared business data |
                          +-------------------------------+
```

Ownership rules:

- Desktop owns native window/tray/dialog/update/process/secure-storage policy.
- Local Bridge validates a narrow protocol and adapts local services; it owns no
  server business rule and exposes no generic shell/filesystem primitive.
- Daemon owns long-running local services, offline replay and local providers.
- Server owns users, projects, tasks, decisions, machines, events, Library,
  runtimes, authorization and shared transitions.
- Dashboard owns common UI and calls the canonical server API directly in web
  mode. Native features are injected through an optional adapter.
- Human JWT and daemon machine token remain distinct. The Desktop must never
  silently attribute a human action to the daemon machine.

## 7. Minimal local threat model

| Asset/threat | Mandatory P1/P2 control | Verification |
|---|---|---|
| Machine token theft | Windows Credential Manager/keyring; references only in config; never renderer, CLI args, logs, crash dumps, `.studio`, or env by default | Secret scan, log/crash inspection, negative bridge tests |
| Human credential theft | Memory-only access token where possible; refresh/session design explicit; no reuse of daemon token | Auth integration tests and process-memory boundary review |
| Committable `.studio` files | IDs, paths and feature flags only; no secret or bearer token | Fixture scan and Git-status test |
| Vault/code index disclosure | Local-only default; explicit publish action; scoped roots; no telemetry/upload of content | Offline/network capture and privacy tests |
| Path traversal/symlink escape | Canonicalize paths and enforce consented workspace roots | Traversal, junction and symlink tests |
| XSS to native privilege escalation | Packaged local UI only for privileged window; strict CSP; Tauri capabilities per window/command; no remote privileged origin | E2E navigation and denied-command tests |
| Malicious link/navigation | Deny in-WebView navigation outside app; allowlist schemes; validate before opening externally | URL fuzzing and popup tests |
| Process/argument injection | Fixed executable IDs and argument schemas; no shell strings; canonical executable paths; signed sidecars | Injection tests and tamper tests |
| Duplicate daemon/replay | Per-profile single-instance lock and explicit attach/start semantics | Double-launch and crash-recovery tests |
| Update tampering/downgrade | Signed app/updater artifacts, pinned channel, integrity verification, rollback policy | Upgrade/downgrade/tampered-artifact tests |
| Sensitive logs/crash dumps | Structured redaction, bounded retention, opt-in diagnostics export | Golden redaction tests |
| Local bridge exposure | Prefer parent/child private channel; if loopback is ever used, bind loopback, ephemeral auth, Host/Origin checks, no wildcard CORS | DNS rebinding and unauthenticated request tests |

## 8. Version and compatibility strategy

- Desktop and daemon use independent SemVer identities, but a Desktop release
  pins and ships/tests one preferred daemon version.
- The local protocol has its own identifier, initially `studio.local/v1`.
  Compatibility is negotiated by major version plus declared min/max ranges,
  never inferred from package versions alone.
- Handshake returns Desktop/bridge/daemon versions, local protocol range,
  server API target, and structured optional capabilities.
- Server remains on canonical `/api/v1`; its OpenAPI schema and existing
  resource/event versions remain authoritative. P0 does not invent a server
  `/capabilities` endpoint.
- A newer server may add ignorable fields/capabilities. A breaking server
  change requires the existing versioning discipline, never silent fallback.
- An older Desktop may run only if required server and daemon capabilities are
  present; otherwise it shows `incompatible` with actionable version details.
- Optional components report `disabled`, `not_installed`, `unavailable`,
  `indexing`, `ready`, `stale`, `permission_denied`, `incompatible`, or `error`.
- Wrong profile/identity, incompatible protocol, corrupt index, denied path,
  unavailable keyring and failed update are explicit errors; none may degrade
  silently to a less secure identity or broader filesystem scope.

## 9. R1–R12 responsibility matrix

| Requirement | Component | Owner | Acceptance test |
|---|---|---|---|
| R1 installation/onboarding without terminal | Installer + Desktop onboarding + server provisioning API | P10/P11 | Clean Windows VM: install to first authenticated project without terminal |
| R2 Dashboard in native app | Dashboard shared UI + Tauri WebView adapter | P2/P3 | Same core flows in web and packaged modes |
| R3 daemon lifecycle | Desktop process manager + daemon control contract | P4 | Start/attach/stop/crash/reboot/double-launch matrix |
| R4 machine registration/auth | Onboarding + secure store + canonical provisioning | P5/P11, server unchanged unless P1 decides otherwise | Register, revoke, rotate, wrong-token and offline recovery tests |
| R5 folder/project association | Workspace manager + `LocalWorkspaceConfig` | P5 | Existing/new/moved/missing folder and Git repository cases |
| R6 watcher/heartbeat/service visibility | Daemon status/capabilities + Dashboard/Desktop diagnostics | P3/P4 | Live state, stale state, failure reason and retry tests |
| R7 Knowledge Vault | `KnowledgeProvider` + local index + UI | P6 | Disabled, large vault, malformed file, rename, broken link, no Obsidian |
| R8 Code Graph | `CodeGraphProvider` + Graphify adapter/install manager | P7 | Missing/unsupported/corrupt/stale/large repository cases |
| R9 visualizers | Common graph viewer | P8 | Empty/partial/large graph, accessibility and performance budgets |
| R10 Project Graph | Derived projection, never source of truth | P8 | Provenance-only links; no invented relation test |
| R11 harness adapters | Adapter registry + preview/apply/rollback | P9 | Claude Code/OpenCode/absent/unknown harness; no provider credential request |
| R12 independent web Dashboard | Dashboard build/deployment + native adapter isolation | P2/P3/P12 | Use Dashboard from another machine with no Desktop APIs installed |

## 10. Contracts to freeze in P1

1. `LocalRuntimeHandshake`: component versions, protocol range and capabilities.
2. `LocalBridgeProtocol`: commands, events, correlation, cancellation, progress,
   limits and structured errors.
3. `DaemonControl`: instance identity, attach/start/stop/status/restart and
   crash/recovery semantics.
4. `LocalWorkspaceConfig`: server/project/repository paths, feature flags,
   schema version and migrations; explicitly no secrets.
5. `SecretReference` and identity routing: human JWT versus machine token.
6. `KnowledgeProvider` and `CodeGraphProvider`: capability and state models,
   provenance, freshness, rebuild and privacy semantics.
7. `HarnessAdapter`: detect/preview/apply/rollback without provider credentials.
8. Common graph schema: node, edge, provenance, source and local URI.
9. Local/shared publication policy: what stays local and what may be published.
10. Contract fixtures/mocks for Dashboard, shell, daemon and each optional
    provider, including incompatible-version and disabled-feature cases.

P1 must decide whether any existing versioned server contract changes. Until
then, `TECH/02`–`TECH/05` remain unchanged.

## 11. Parallel work after P2

Recommended waves preserve the roadmap dependencies and cap active sessions at
approximately three:

1. **Wave A:** P3 Shell/UX, P4 daemon lifecycle, P5 workspace manager.
2. **Wave B:** P6 Knowledge Vault, P7 Code Graph, P8 graph visualizers using P1
   fixtures while P6/P7 mature.
3. **Wave C:** P9 harness adapters, P10 packaging/security, one integration/test
   lane that owns shared fixtures and conflict detection without starting P11.
4. **Wave D:** P11 onboarding integration after P3–P5 and P9–P10; other sessions
   run targeted security and upgrade validation, not competing feature edits.
5. **Final:** P12 owns reconciliation. Its E2E suites can be partitioned across
   three runners/sessions, but one integrator owns the baseline and verdict.

High-conflict areas need a single owner: Dashboard bootstrap/router/config,
Desktop manifest/capabilities, bridge contracts/fixtures, daemon composition
root, workspace config schema, installer/updater configuration, and shared graph
types. Lanes consume frozen P1 fixtures rather than editing these concurrently.

## 12. Risks, blockers and unresolved questions

- Full transitive licence inventory for an embedded Graphify distribution is
  unresolved; managed separate installation avoids blocking P2.
- The exact Python daemon freezing/packaging tool is unresolved and belongs to
  P2/P4/P10 evaluation.
- Dashboard origin/CORS behavior from a packaged WebView must be proven; native
  REST/SSE adaptation may be preferable to widening server CORS.
- Outbox partitioning by server/account/workspace must be resolved before the
  Desktop exposes profile switching.
- Human Desktop login, machine enrolment, rotation and recovery flows need P1
  identity diagrams; no credential may silently cross roles.
- `TECH/01_ARCHITECTURE.md` contains a stale SSE path and should be corrected in
  a dedicated documentation reconciliation, not mixed into this P0 decision.
- The central Graphify graph contains historical duplicate-worktree nodes and a
  partially stale manifest. Repository code, not those stale edges, was used as
  source of truth for disputed flows.
- Tauri remains conditional on the P2 technical gate; Electron is the explicit
  fallback, not a parallel implementation.

## 13. Documentation created or modified

| File | Purpose |
|---|---|
| `docs/DESKTOP_P0_ARCHITECTURE_GATE.md` | Audit, recommendation, boundaries, threat model, compatibility, R1–R12 and parallelization plan |
| `docs/decisions/DEC-0091-desktop-p0-tauri-shell-frontieres.md` | Accepted Tauri/thin-shell architecture decision (DEC-0091) |
| `docs/decisions/DEC-0092-desktop-p0-codegraph-provider-graphify.md` | Accepted CodeGraphProvider and Graphify distribution decision (DEC-0092) |
| `docs/DECISIONS.md` | Deterministically regenerated decision index |

No product, runtime contract, API schema, database model, Dashboard behavior,
daemon behavior, packaging manifest or CI workflow was modified.

### Explicit A–L deliverable coverage

| Requested deliverable | Evidence in this report |
|---|---|
| A. Existing-system audit | Section 2 |
| B. Recommended Desktop architecture | Sections 6, 8, 10 and 16 |
| C. Tauri versus Electron decision | Section 3 and DEC-0091 |
| D. Graphify/licence/redistribution audit | Section 4 and DEC-0092 |
| E. Vault/Obsidian audit | Section 5 |
| F. Boundary diagram | Section 6 |
| G. Local threat model | Section 7 |
| H. Version/compatibility strategy | Section 8 |
| I. Requirement → component → owner → test | Section 9 |
| J. Contracts to freeze in P1 | Section 10 |
| K. Risks/blockers/open questions | Section 12 |
| L. Parallelization after P2 | Section 11 |

## 14. Tests and validations performed

- `git fetch --prune origin`; verified `master == origin/master` before work.
- `git diff --check`: pass.
- `uv run python -m scripts.adr_index --root . --check`: pass after canonical
  regeneration (`91 decision(s)`).
- `uv run --all-packages pytest tests/graphify/test_adr_migration.py
  tests/graphify/test_decision_graph.py -q`: **22 passed**.
- Qwen local bounded review of this gate: PASS, no actionable defect.
- `studio-tester` independent review: initial FAIL on missing explicit A–L and
  final 1–16 traceability; this section set and the coverage matrix correct that
  defect and require a re-review before closure.
- Graphify exact-path update attempted through the protected incremental path.
  The two ADR extractions failed locally (PowerShell argument transformation,
  then empty/non-JSON Qwen output). The graph remained at 14,901 nodes and
  38,086 edges with no deleted sources pruned; failures were recorded in the
  Graphify ledger. This is reported as a limitation, not a successful update.

No external PostgreSQL, MinIO, Docker, installer, WebView, Tauri, Electron, or
Windows packaging validation was required or claimed for this documentation-only
gate.

## 15. Git final state

Expected P0 diff is restricted to the four documentation files listed in
section 13. The branch is `desktop/architecture`; the diff was prepared uncommitted
for the final review and committed after its PASS.
The pre-existing dirty main worktree remains untouched.

Explicit confirmation: **no Studi'OS Desktop implementation has started**.
There is no Desktop package, Tauri/Electron scaffold, bridge, sidecar bundle,
installer, new business API, functional daemon change, or Dashboard refactor.

## 16. Gate result

**P0 DECISIONS ACCEPTED (DEC-0091, DEC-0092).** The existing architecture can support a thin Desktop
shell without duplicating the server or Dashboard. The recommendation is Tauri
2 + typed local bridge + existing Python daemon/services, with Graphify behind
an optional provider and initially installed separately.

P1 must not start until the corrected document set receives a final independent
PASS and is committed. Graphify must not be bundled or redistributed until the full dependency/licence audit is resolved.
