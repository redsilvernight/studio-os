"""Project bootstrap manifest contracts (AI Bootstrap P1, AIB-A/DEC-0143, DEC-0155).

A *bootstrap manifest* is the smallest depot-side record expressing "this
project wants to be configured with these harnesses under this policy"
(AIB-A): project identity, targeted harnesses, generation policy. Nothing
else. It references stable keys; content stays in the Library, resolution
stays server-side (AIB-B).

Non-goals, by construction:

- No absolute path is representable: the schema has no path field, and every
  free string is rejected when it uses absolute-path syntax (POSIX root,
  Windows drive, UNC, home expansion). A manifest survives `git clone` to a
  machine that has never seen the author's filesystem (AIB-A gate).
- No secret is representable: the schema has no token/password/key field and
  no free-form metadata dict to smuggle one into (AIB-E gate). A display
  `name`/`description` is never consumed as a credential or a path.
- No provider, model or runtime choice lives here (DEC-0066/DEC-0070): the
  harness ids are open references in the canonical kebab-case vocabulary
  (DEC-0155, examples live in tests/fixtures only), never a vendor catalog.

Frozen by P1: additive-only. A breaking change bumps `BOOTSTRAP_FORMAT` and
goes through reconciliation (skill `contract-change`).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from studio_contracts.common import ContractModel
from studio_contracts.initialization import InitializationProjectSpec

BOOTSTRAP_FORMAT = "studio.bootstrap/v1"
"""Manifest format tag. Additive fields stay in v1; a reader older than the
writer rejects explicitly (`extra="forbid"`) rather than silently truncating."""

# --- bounds: every free-text and collection field is bounded ------------------
MAX_BOOTSTRAP_HARNESSES = 10
MAX_HARNESS_ID = 200
HARNESS_ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/|~(?:[\\/]|$))")
"""Absolute-path syntax, any OS: Windows drive (`C:\\…`, `C:/…`), UNC
(`\\\\host\\…`), POSIX root (`/…`), home expansion (`~`, `~/…`). Matched
against the *start* of a value only: prose may mention a path inline, but no
string field may *be* one. Scope is deliberately narrow (`$VAR`/`%VAR%`,
`~user/…` and single-backslash roots are out of scope): name/description are
display-only and never consumed as paths, so only values shaped *as* absolute
paths are rejected."""


def _reject_absolute_path(value: str | None, *, where: str) -> str | None:
    """Fail-closed on values that *are* absolute paths. `None` passes through
    for optional fields."""
    if value is None:
        return None
    if _ABSOLUTE_PATH_RE.match(value):
        raise ValueError(f"{where}: absolute path {value!r} is not representable in a manifest")
    if "\x00" in value:
        raise ValueError(f"{where}: NUL byte is not representable in a manifest")
    return value


HarnessId = Annotated[
    str, Field(min_length=1, max_length=MAX_HARNESS_ID, pattern=HARNESS_ID_PATTERN)
]
"""Canonical harness identifier (DEC-0155): kebab-case, open vocabulary. A new
harness needs no migration and no resolver change; an unknown-but-well-formed
id parses and fails later, explicitly, at plan time — never silently."""


class BootstrapHarnessRef(ContractModel):
    """One targeted harness, by canonical id only. No version, no path, no
    configuration: machine-local wiring stays machine-local (AIB-E)."""

    id: HarnessId


class OnModified(StrEnum):
    """What generation must do when a managed file was modified by the user
    since (AIB-C: never a silent overwrite)."""

    REFUSE = "refuse"
    ASK = "ask"


class BootstrapPolicy(ContractModel):
    """Generation policy. Deliberately minimal: P1 fixes the vocabulary, P3
    implements the behavior."""

    on_modified: OnModified = OnModified.REFUSE


class BootstrapManifest(ContractModel):
    """The whole manifest. Identity is reused from the initialization contract
    (same `slug` that `studio_get_projects` resolves); at least one harness is
    required — a manifest that targets nothing configures nothing."""

    format: Literal["studio.bootstrap/v1"] = "studio.bootstrap/v1"
    project: InitializationProjectSpec
    harnesses: list[BootstrapHarnessRef] = Field(min_length=1, max_length=MAX_BOOTSTRAP_HARNESSES)
    policy: BootstrapPolicy = Field(default_factory=BootstrapPolicy)

    @model_validator(mode="after")
    def _no_absolute_paths(self) -> BootstrapManifest:
        _reject_absolute_path(self.project.slug, where="project.slug")
        _reject_absolute_path(self.project.name, where="project.name")
        _reject_absolute_path(self.project.description, where="project.description")
        for ref in self.harnesses:
            _reject_absolute_path(ref.id, where="harness.id")
        return self


class BootstrapProblemCode(StrEnum):
    """Closed vocabulary for manifest-internal problems (no server state)."""

    DUPLICATE_HARNESS = "duplicate_harness"


class BootstrapProblem(ContractModel):
    """One structural problem. Problems never block parsing: `model_validate`
    either accepts the manifest or raises `ValidationError`; this list reports
    what is *well-formed but inconsistent* (today: the same harness twice)."""

    code: BootstrapProblemCode
    key: str | None = None
    message: str | None = None


def bootstrap_manifest_problems(manifest: BootstrapManifest) -> list[BootstrapProblem]:
    """Validate the manifest against itself only — never an existence oracle.
    Empty means structurally sound. Server-state checks (Library visibility,
    harness availability on a machine) run separately, in P2/P3, through the
    plan (AIB-B)."""
    problems: list[BootstrapProblem] = []
    seen: set[str] = set()
    for ref in manifest.harnesses:
        if ref.id in seen:
            problems.append(
                BootstrapProblem(code=BootstrapProblemCode.DUPLICATE_HARNESS, key=ref.id)
            )
        seen.add(ref.id)
    return problems


# --- dry-run: states, conflicts, report (P1, task 511de63f) -------------------
MAX_BOOTSTRAP_FILES = 100
MAX_RELATIVE_PATH = 500
HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"


def _reject_non_portable_path(value: str, *, where: str) -> str:
    """Repo-relative, POSIX-style paths only: no absolute syntax, no
    backslashes (Windows consumers translate), no empty/dot/dotdot segments
    (`..` would escape the repo). Normalizing user input is P3's job; the
    contract is strict so a malformed path fails here, explicitly."""
    _reject_absolute_path(value, where=where)
    if "\\" in value:
        raise ValueError(f"{where}: backslash is not a portable separator in {value!r}")
    segments = value.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        raise ValueError(f"{where}: empty, dot or dotdot segment in {value!r}")
    return value


def _relative_path(value: str) -> str:
    return _reject_non_portable_path(value, where="path")


RelativePath = Annotated[
    str, Field(min_length=1, max_length=MAX_RELATIVE_PATH), AfterValidator(_relative_path)
]
"""Repo-relative file path (`docs/decisions/…`, never absolute, never
escaping). Validation lives in the type itself, so every model using it is
covered without an explicit call."""


class BootstrapFileState(StrEnum):
    """Per-file drift state (audit §7). Reported by `check`, consumed by `diff`
    and `sync` in P3 — P1 fixes the vocabulary only."""

    ABSENT = "absent"
    OBSOLETE = "obsolete"
    MODIFIED = "modified"
    # `incompatible` is the bootstrap-level counterpart of the adapters'
    # `HARNESS_MISMATCH`: generated for a harness/runtime the content no
    # longer matches.
    INCOMPATIBLE = "incompatible"
    UP_TO_DATE = "up_to_date"


class BootstrapFileReport(ContractModel):
    """One generated file as observed on the machine: where it is, which
    state it is in, which Library version produced it and which content hash
    was generated. `origin_version`/`content_hash` are absent exactly when the
    file was never generated by us (state `absent`). Requiring a hash for
    `modified`/`up_to_date` is the P3 `check`'s job (it owns observation);
    the contract only fixes the shape."""

    path: RelativePath
    state: BootstrapFileState
    origin_version: int | None = Field(default=None, ge=1)
    content_hash: str | None = Field(default=None, pattern=HASH_PATTERN)
    message: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _coherent_absent(self) -> BootstrapFileReport:
        if self.state is BootstrapFileState.ABSENT and (
            self.origin_version is not None or self.content_hash is not None
        ):
            raise ValueError("an absent file carries no origin version nor content hash")
        return self


class BootstrapConflictCode(StrEnum):
    """Closed vocabulary. A conflict blocks `sync` until resolved; anything
    else is an action (`create`/`refresh`/`review`), never a conflict."""

    MODIFIED_NEEDS_CONFIRMATION = "modified_needs_confirmation"
    INCOMPATIBLE_TARGET = "incompatible_target"


class BootstrapConflict(ContractModel):
    """One sync-blocking conflict, derived from file states under the manifest
    policy (see `bootstrap_dry_run_conflicts`). `path` is `None` only for a
    global (non-file) conflict — none is produced today."""

    code: BootstrapConflictCode
    path: RelativePath | None = None
    blocking: bool = True
    message: str | None = Field(default=None, max_length=500)


class BootstrapFileSummary(ContractModel):
    """State counts: the glanceable roll-up of a dry-run, mirroring
    `InitializationSummary` (created/reused/skipped)."""

    absent: int = 0
    obsolete: int = 0
    modified: int = 0
    incompatible: int = 0
    up_to_date: int = 0


class BootstrapDryRunReport(ContractModel):
    """Read-only outcome of evaluating a manifest against a depot: no side
    effect, exactly what `check` would print and `sync` would do.
    `sync_allowed` true means `sync` may proceed *without asking anything*;
    `needs_confirmation` true means the `ask` policy requires an explicit
    confirmation first (P3 must never read `sync_allowed` alone under `ask`).
    `conflicts` empty and both flags accordingly is the only green state."""

    manifest: BootstrapManifest
    files: list[BootstrapFileReport] = Field(default_factory=list, max_length=MAX_BOOTSTRAP_FILES)
    conflicts: list[BootstrapConflict] = Field(default_factory=list)
    summary: BootstrapFileSummary = Field(default_factory=BootstrapFileSummary)
    sync_allowed: bool = False
    needs_confirmation: bool = False


def bootstrap_dry_run_conflicts(
    manifest: BootstrapManifest, files: list[BootstrapFileReport]
) -> list[BootstrapConflict]:
    """Derive sync-blocking conflicts from file states under the manifest
    policy. Pure and local: `refuse` turns every `modified` file into a
    blocking conflict; `ask` leaves the decision to the confirmation flow
    (reported state, no conflict); `incompatible` always blocks."""
    conflicts: list[BootstrapConflict] = []
    for file in files:
        if file.state is BootstrapFileState.MODIFIED and (
            manifest.policy.on_modified is OnModified.REFUSE
        ):
            conflicts.append(
                BootstrapConflict(
                    code=BootstrapConflictCode.MODIFIED_NEEDS_CONFIRMATION,
                    path=file.path,
                )
            )
        elif file.state is BootstrapFileState.INCOMPATIBLE:
            conflicts.append(
                BootstrapConflict(
                    code=BootstrapConflictCode.INCOMPATIBLE_TARGET,
                    path=file.path,
                )
            )
    return conflicts


def build_dry_run_report(
    manifest: BootstrapManifest, files: list[BootstrapFileReport]
) -> BootstrapDryRunReport:
    """Compose the full report: summary counts, policy-derived conflicts, the
    confirmation flag and the resulting `sync_allowed` flag. Deterministic:
    files are ordered by path, so the same observations always produce the
    same report field for field, whatever order the caller observed them in.
    `sync_allowed` is true only when nothing blocks *and* nothing needs
    asking: fail-closed for a naive P3 reader."""
    ordered = sorted(files, key=lambda f: f.path)
    summary = BootstrapFileSummary(
        absent=sum(1 for f in ordered if f.state is BootstrapFileState.ABSENT),
        obsolete=sum(1 for f in ordered if f.state is BootstrapFileState.OBSOLETE),
        modified=sum(1 for f in ordered if f.state is BootstrapFileState.MODIFIED),
        incompatible=sum(1 for f in ordered if f.state is BootstrapFileState.INCOMPATIBLE),
        up_to_date=sum(1 for f in ordered if f.state is BootstrapFileState.UP_TO_DATE),
    )
    conflicts = bootstrap_dry_run_conflicts(manifest, ordered)
    needs_confirmation = manifest.policy.on_modified is OnModified.ASK and any(
        f.state is BootstrapFileState.MODIFIED for f in ordered
    )
    return BootstrapDryRunReport(
        manifest=manifest,
        files=ordered,
        conflicts=conflicts,
        summary=summary,
        sync_allowed=not needs_confirmation and not any(c.blocking for c in conflicts),
        needs_confirmation=needs_confirmation,
    )
