# Completion evidence and task state

Every tracked task marked completed MUST carry real evidence. The server accepts
legacy calls without it; compatibility is not permission to omit evidence.
Do not change the server schema in P1.

Inspect the connected studio_handoff schema. If it cannot carry completion,
persist evidence in the summary and leave task_status unset for a compatible
closer. Never invent unsupported parameters or success.

Real schema: packages/studio-contracts/src/studio_contracts/completion.py.
format: studio.completion/v1; kind: code|audit|diagnostic|operation;
artifacts (<=10 references); checks (<=20). Each check has name,
kind (command|review|observation|ci), purpose (validation|finding),
status (passed|failed|not_run|environment_unavailable), optional exit_code
and reference. Commands need observed integer exit codes; successful validation
requires 0. CI checks need real references.

- Code: identifiable Git state and diff, commands/results, relevant checks and
  limits. Completion requires versioned=true and an actual revision. Without
  permission to commit, record HEAD + local changes as a checkpoint; do not
  fabricate a versioned revision. Respect required integration and CI gates.
- Audit/diagnostic: sources, findings, evidence levels, verified artifacts,
  performed/unperformed checks and limits. Failed findings remain distinct from
  successful validation of the diagnostic deliverable. Critical findings need
  not make a finished audit unfinished.
- Operation: actual action, observed effect, artifacts/logs and limits;
  effect_verified=true only after checking the effect.

Optional fields: versioned, revision, target_branch, integration_required,
integrated, ci_required, ci_verified, effect_verified, deployed. The four stages
are independent. A tool's completed string is not proof; evidence is declarative
and check_completion returns authoritative=false.

| Case | Business state and evidence |
|---|---|
| Finished and validated | completed only with checks and repository gates met |
| Implemented, untested | checkpoint; required check not_run, no completed |
| Audit with critical findings | audit may complete if its own review passes; findings stay explicit |
| Diagnostic without fix | diagnostic may complete if assigned as the deliverable; correction stays open |
| Partial operation | checkpoint, verified partial effects and remaining work |
| Deployment unauthorized | deployed=false; finish only if deployment is not an acceptance gate |
| Interrupted session | checkpoint with retained IDs, keys, unprocessed signals and NEXT |
| Blocked | blocked with precise dependency and resumption condition |

Future compatible enforcement: negotiate an evidence capability, measure legacy
callers, warn on missing evidence, then version the required-field policy. Keep
historical idempotent replies and old clients valid for the migration window.
No immediate mandatory field for all server requests.
