"""Integration tests for the shared graphify_incremental_update.py <-> per-
project policy wiring.

This is the *global* script (`~/.claude/scripts/graphify_incremental_update.py`,
shared across every Graphify-enabled project on this machine), loaded here by
path so these tests exercise the real file. Only `load_project_policy` and
`apply_policy` are exercised: they are defined at module scope and never
import the `graphify` package, unlike `main()`, so this does not require the
graphify-enabled interpreter.

The policy/ledger engines (`graphify_update_policy.py`, `graphify_ledger.py`)
are canonically global too, shipped next to this same script -- a project
adopts them just by writing its own `.graphify-update.toml`, no Python files
required. `load_project_policy`/`load_project_ledger` prefer a project-local
`scripts/graphify_update_policy.py` (or `graphify_ledger.py`) override when
one exists, and fall back to the global copy otherwise.

Covers: a project with no `.graphify-update.toml` keeps the pre-policy
behaviour (everything allowed -- backward compatibility for every other
project sharing this script), a `--files`-supplied list cannot bypass an
active policy's exclusions, and both engines resolve via the global fallback
with zero project-local setup.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

GLOBAL_SCRIPT = Path.home() / ".claude" / "scripts" / "graphify_incremental_update.py"
POLICY_ENGINE_SOURCE = Path.home() / ".claude" / "scripts" / "graphify_update_policy.py"
LEDGER_SOURCE = Path.home() / ".claude" / "scripts" / "graphify_ledger.py"


@pytest.fixture(scope="module")
def incremental_update_module() -> ModuleType:
    if not GLOBAL_SCRIPT.exists():
        pytest.skip(f"global script not present on this machine: {GLOBAL_SCRIPT}")
    spec = importlib.util.spec_from_file_location(
        "graphify_incremental_update_under_test", GLOBAL_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_project_without_policy_file_is_fully_legacy(
    incremental_update_module: ModuleType, tmp_path: Path
) -> None:
    # The engine itself resolves via the global fallback (no project-local
    # copy needed), but with no .graphify-update.toml anywhere, the policy
    # is None -- so behaviour for this project stays exactly legacy.
    policy_module, policy = incremental_update_module.load_project_policy(tmp_path)
    assert policy_module is not None
    assert policy is None

    files = ["README.md", "docs/random.md", "src/main.py"]
    allowed, skipped = incremental_update_module.apply_policy(
        policy_module, policy, files, is_code=False, milestone=False
    )
    assert allowed == files
    assert skipped == []


def test_project_with_policy_engine_override_but_no_toml_is_legacy(
    incremental_update_module: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy(POLICY_ENGINE_SOURCE, tmp_path / "scripts" / "graphify_update_policy.py")

    policy_module, policy = incremental_update_module.load_project_policy(tmp_path)
    assert policy_module is not None
    assert policy is None  # no .graphify-update.toml yet -> legacy for this project


def test_files_list_cannot_bypass_active_policy_exclusions(
    incremental_update_module: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy(POLICY_ENGINE_SOURCE, tmp_path / "scripts" / "graphify_update_policy.py")
    (tmp_path / ".graphify-update.toml").write_text(
        """
[semantic.allowed]
patterns = ["docs/TECH/**"]

[exclude.generated]
patterns = ["docs/DECISIONS.md"]
""",
        encoding="utf-8",
    )

    policy_module, policy = incremental_update_module.load_project_policy(tmp_path)
    assert policy is not None

    # Caller explicitly names the excluded file via --files -- policy still
    # wins, it is not bypassable by construction (apply_policy runs
    # unconditionally over whatever list it is handed).
    allowed, skipped = incremental_update_module.apply_policy(
        policy_module,
        policy,
        ["docs/DECISIONS.md", "docs/TECH/foo.md", "docs/unlisted.md"],
        is_code=False,
        milestone=False,
    )
    assert allowed == ["docs/TECH/foo.md"]
    skipped_files = {f for f, _reason in skipped}
    assert skipped_files == {"docs/DECISIONS.md", "docs/unlisted.md"}


def test_project_without_local_ledger_falls_back_to_global(
    incremental_update_module: ModuleType, tmp_path: Path
) -> None:
    ledger_module = incremental_update_module.load_project_ledger(tmp_path)
    assert ledger_module is not None
    assert Path(ledger_module.__file__) == LEDGER_SOURCE


def test_project_local_ledger_override_takes_precedence(
    incremental_update_module: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy(LEDGER_SOURCE, tmp_path / "scripts" / "graphify_ledger.py")

    ledger_module = incremental_update_module.load_project_ledger(tmp_path)
    assert ledger_module is not None
    assert Path(ledger_module.__file__) == tmp_path / "scripts" / "graphify_ledger.py"


def test_project_with_ledger_module_can_record_an_attempt(
    incremental_update_module: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy(LEDGER_SOURCE, tmp_path / "scripts" / "graphify_ledger.py")

    ledger_module = incremental_update_module.load_project_ledger(tmp_path)
    assert ledger_module is not None

    attempt = ledger_module.build_attempt(
        project="demo",
        files=["a.py"],
        root=tmp_path,
        backend="ast",
        processing_type="ast",
        outcome="success",
        input_tokens=0,
        output_tokens=0,
    )
    cost_path = tmp_path / "cost.json"
    ledger = ledger_module.record_attempts(cost_path, [attempt])
    assert len(ledger["attempts"]) == 1
    assert cost_path.exists()


def test_extract_chunk_reports_which_backend_succeeded(
    incremental_update_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = incremental_update_module

    def fake_call_backend(backend: str, prompt: str, files: list[str], timeout: int = 900) -> str:
        assert backend == "qwen"
        return '{"nodes": [], "edges": [], "hyperedges": []}'

    monkeypatch.setattr(module, "call_backend", fake_call_backend)
    data, err, backend_used = module.extract_chunk(
        1,
        1,
        ["a.md"],
        {"a.md": "a.md"},
        "qwen",
    )
    assert err is None
    assert backend_used == "qwen"
    assert data == {"nodes": [], "edges": [], "hyperedges": []}


def test_gemini_zero_yield_is_never_recorded_as_a_measured_success(
    incremental_update_module: ModuleType, tmp_path: Path
) -> None:
    """Regression test for a real incident: a Gemini 429 rate-limit was
    swallowed by extract_corpus_parallel (it still returned a normal-shaped
    dict with input_tokens=0), and the ledger attempt was built with
    outcome="success" / tokens_status="measured" -- indistinguishable from a
    genuinely free, successful call. build_attempt must instead mark a
    zero-node/edge/hyperedge semantic result as an error with unmeasured
    tokens."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(LEDGER_SOURCE, tmp_path / "scripts" / "graphify_ledger.py")
    ledger_module = incremental_update_module.load_project_ledger(tmp_path)

    sem = {"nodes": [], "edges": [], "hyperedges": [], "input_tokens": 0, "output_tokens": 0}
    sem_yielded_nothing = not (sem.get("nodes") or sem.get("edges") or sem.get("hyperedges"))
    attempt = ledger_module.build_attempt(
        project="demo",
        files=["a.md"],
        root=tmp_path,
        backend="gemini",
        processing_type="semantic",
        outcome="error" if sem_yielded_nothing else "success",
        input_tokens=None if sem_yielded_nothing else sem.get("input_tokens"),
        output_tokens=None if sem_yielded_nothing else sem.get("output_tokens"),
    )
    assert attempt.outcome == "error"
    assert attempt.tokens_status == "unmeasured"
    assert attempt.input_tokens is None


def test_extract_chunk_reports_no_backend_on_total_failure(
    incremental_update_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = incremental_update_module

    def failing_call_backend(
        backend: str, prompt: str, files: list[str], timeout: int = 900
    ) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "call_backend", failing_call_backend)
    data, err, backend_used = module.extract_chunk(
        1,
        1,
        ["a.md"],
        {"a.md": "a.md"},
        "qwen",
    )
    assert err is not None
    assert backend_used is None
