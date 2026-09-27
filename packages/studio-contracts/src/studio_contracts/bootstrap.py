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
  (DEC-0155: `claude-code`, `opencode`, `codex`), never a vendor catalog.

Frozen by P1: additive-only. A breaking change bumps `BOOTSTRAP_FORMAT` and
goes through reconciliation (skill `contract-change`).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

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
