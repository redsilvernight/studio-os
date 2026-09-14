"""Integration tests for the shared graphify_incremental_update.py <-> per-
project policy wiring.

This is the *global* script (`~/.claude/scripts/graphify_incremental_update.py`,
shared across every Graphify-enabled project on this machine), loaded here by
path so these tests exercise the real file the Studio OS mandate asked to be
modified. Only `load_project_policy` and `apply_policy` are exercised: they
are defined at module scope and never import the `graphify` package, unlike
`main()`, so this does not require the graphify-enabled interpreter.

Covers: a project with no `.graphify-update.toml` keeps the pre-policy
behaviour (everything allowed -- backward compatibility for every other
project sharing this script), and a `--files`-supplied list cannot bypass an
active policy's exclusions.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

GLOBAL_SCRIPT = Path.home() / ".claude" / "scripts" / "graphify_incremental_update.py"
PROJECT_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
POLICY_ENGINE_SOURCE = PROJECT_SCRIPTS / "graphify_update_policy.py"
LEDGER_SOURCE = PROJECT_SCRIPTS / "graphify_ledger.py"


@pytest.fixture(scope="module")
def incremental_update_module():
    if not GLOBAL_SCRIPT.exists():
        pytest.skip(f"global script not present on this machine: {GLOBAL_SCRIPT}")
    spec = importlib.util.spec_from_file_location(
        "graphify_incremental_update_under_test", GLOBAL_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_project_without_policy_file_is_fully_legacy(
    incremental_update_module, tmp_path: Path
) -> None:
    policy_module, policy = incremental_update_module.load_project_policy(tmp_path)
    assert policy_module is None
    assert policy is None

    files = ["README.md", "docs/random.md", "src/main.py"]
    allowed, skipped = incremental_update_module.apply_policy(
        policy_module, policy, files, is_code=False, milestone=False
    )
    assert allowed == files
    assert skipped == []


def test_project_with_policy_engine_but_no_toml_is_legacy(
    incremental_update_module, tmp_path: Path
) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy(POLICY_ENGINE_SOURCE, tmp_path / "scripts" / "graphify_update_policy.py")

    policy_module, policy = incremental_update_module.load_project_policy(tmp_path)
    assert policy_module is not None
    assert policy is None  # no .graphify-update.toml yet -> legacy for this project


def test_files_list_cannot_bypass_active_policy_exclusions(
    incremental_update_module, tmp_path: Path
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


def test_project_without_ledger_module_gets_none(incremental_update_module, tmp_path: Path) -> None:
    assert incremental_update_module.load_project_ledger(tmp_path) is None


def test_project_with_ledger_module_can_record_an_attempt(
    incremental_update_module, tmp_path: Path
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
    incremental_update_module, monkeypatch
) -> None:
    module = incremental_update_module

    def fake_call_backend(backend, prompt, files, timeout=900):
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


def test_extract_chunk_reports_no_backend_on_total_failure(
    incremental_update_module, monkeypatch
) -> None:
    module = incremental_update_module

    def failing_call_backend(backend, prompt, files, timeout=900):
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
