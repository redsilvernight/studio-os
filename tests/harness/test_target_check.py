"""Target-repo check against the resolved bundle (AIB P5, task 2b67046b).

Exercises the four P5 check states through `observe`: up_to_date
(configured), absent (incomplete), obsolete/modified (drift, told apart by
the managed hash), incompatible (harness cannot represent the projection).
No DB, no server; existing `test_bootstrap_p3.py` stays untouched.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from studio_client.adapters.base import AdapterError, AdapterErrorCode
from studio_client.bootstrap import (
    PlannedFile,
    _observe_state,
    apply_files,
    make_manifest,
    observe,
    plan_files,
)
from studio_client.drift import hash_text
from studio_contracts.bootstrap import BootstrapFileState, OnModified

REPO = Path(__file__).resolve().parents[2]


def _repo(tmp_path: Path) -> Path:
    shutil.copytree(REPO / ".agents", tmp_path / ".agents")
    return tmp_path


def _planned(path: str = "x/agent.md", content: str = "desired\n") -> PlannedFile:
    return PlannedFile(path=path, content=content, kind="agent")


def test_observe_defaults_match_legacy_states(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert _observe_state(repo, _planned()) is BootstrapFileState.ABSENT
    target = repo / "x" / "agent.md"
    target.parent.mkdir(parents=True)
    target.write_text("desired\n", encoding="utf-8")
    assert _observe_state(repo, _planned()) is BootstrapFileState.UP_TO_DATE
    target.write_text("edited\n", encoding="utf-8")
    assert _observe_state(repo, _planned()) is BootstrapFileState.MODIFIED


def test_crlf_on_disk_is_not_drift_without_hashes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = repo / "x" / "agent.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"desired\r\n")
    assert _observe_state(repo, _planned()) is BootstrapFileState.UP_TO_DATE


def test_managed_hash_tells_obsolete_from_modified(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = make_manifest("demo", "Demo", ["claude-code"])
    target = repo / "x" / "agent.md"
    target.parent.mkdir(parents=True)
    target.write_text("old managed\n", encoding="utf-8")
    item = _planned(content="new canonical\n")
    obsolete = observe(
        repo, manifest, planned=[item], managed_hashes={item.path: hash_text("old managed\n")}
    )
    assert obsolete.files[0].state is BootstrapFileState.OBSOLETE
    assert obsolete.summary.obsolete == 1
    modified = observe(
        repo, manifest, planned=[item], managed_hashes={item.path: hash_text("other\n")}
    )
    assert modified.files[0].state is BootstrapFileState.MODIFIED


def test_obsolete_needs_no_confirmation_under_ask(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = make_manifest("demo", "Demo", ["claude-code"], on_modified=OnModified.ASK)
    target = repo / "x" / "agent.md"
    target.parent.mkdir(parents=True)
    target.write_text("old managed\n", encoding="utf-8")
    item = _planned(content="new canonical\n")
    report = observe(
        repo, manifest, planned=[item], managed_hashes={item.path: hash_text("old managed\n")}
    )
    assert report.needs_confirmation is False
    assert report.sync_allowed is True


def test_failed_agent_projection_is_incompatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import studio_client.bootstrap as _bootstrap

    class _RefusingAdapter:
        adapter_id = "claude-code"
        managed_dir = ".claude/agents"

        def translate(self, resolved: object, **kwargs: object) -> object:
            raise AdapterError(AdapterErrorCode.UNSUPPORTED, "cannot represent read-only policy")

    monkeypatch.setattr(_bootstrap, "get_adapter", lambda _id: _RefusingAdapter())
    repo = _repo(tmp_path)
    manifest = make_manifest("demo", "Demo", ["claude-code"])
    planned = plan_files(repo, manifest)
    agents = [item for item in planned if item.kind == "agent"]
    assert agents, "expected at least one incompatible agent entry"
    assert all(item.incompatible for item in agents)
    report = observe(repo, manifest, planned=planned)
    states = {f.state for f in report.files}
    assert BootstrapFileState.INCOMPATIBLE in states
    assert report.summary.incompatible == len(agents)
    assert report.sync_allowed is False
    assert all(
        "cannot represent" in (f.message or "")
        for f in report.files
        if f.state is BootstrapFileState.INCOMPATIBLE
    )


def test_incompatible_blocks_sync_and_is_skipped_by_diff(tmp_path: Path) -> None:
    from studio_client.bootstrap import diff_text

    repo = _repo(tmp_path)
    manifest = make_manifest("demo", "Demo", ["claude-code"])
    item = PlannedFile(
        path=".claude/agents/x.md", content="", kind="agent", incompatible=True, message="nope"
    )
    report = observe(repo, manifest, planned=[item])
    assert diff_text(repo, manifest, planned=[item]) == ""
    with pytest.raises(Exception, match="conflict"):
        apply_files(repo, manifest, report, planned=[item])
