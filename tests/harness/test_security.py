from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from studio_client.harness import fsafe
from studio_client.harness.base import DetectionState
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.fsafe import FsError, resolve_target
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.probe import (
    MAX_PROBE_OUTPUT_BYTES,
    ProbeFailure,
    locate_executable,
    run_probe,
)
from studio_client.harness.service import HarnessServiceError
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessPreviewRequest,
    HarnessRollbackRequest,
)
from studio_contracts.local.workspace import WorkspaceScope

from tests.harness.support import (
    CLAUDE_VERSION_LINE,
    WORKSPACE_ID,
    Rig,
    base_env,
    install_fake,
    make_rig,
)

SECRET = "sk-SECRET-VALUE-123456"


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def _link_dir(link: Path, target: Path) -> None:
    """A directory symlink, or a junction on Windows when symlinks need rights."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("symlinks unavailable")
        result = subprocess.run(  # noqa: S603
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],  # noqa: S607
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("neither symlinks nor junctions are available")


# --- path confinement -------------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    ["../x.json", "a/../../x.json", "/abs.json", "\\abs.json", "C:/x.json", "a\\b.json", "", "./x"],
)
def test_traversal_and_absolute_targets_are_refused(rig: Rig, relative: str) -> None:
    with pytest.raises(FsError) as refused:
        resolve_target(rig.root, relative)
    assert refused.value.reason == "unsafe_path"


def test_a_symlinked_config_file_is_refused(rig: Rig, tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    try:
        os.symlink(outside, rig.root / ".mcp.json")
    except OSError:
        pytest.skip("file symlinks unavailable")
    assert ClaudeCodeAdapter().detect(rig.context).state is DetectionState.CONFIGURATION_INVALID
    assert outside.read_text() == "{}"


def test_a_workspace_root_that_is_a_link_is_refused(rig: Rig, tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    _link_dir(linked, real)
    with pytest.raises(FsError):
        resolve_target(linked, ".mcp.json")


def test_a_target_below_a_linked_directory_is_refused(rig: Rig, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    _link_dir(rig.root / "sub", outside)
    with pytest.raises(FsError) as refused:
        resolve_target(rig.root, "sub/x.json")
    assert refused.value.reason == "symlink"


def test_adapters_only_ever_target_their_fixed_files() -> None:
    assert ClaudeCodeAdapter.candidate_files == (".mcp.json",)
    assert OpenCodeAdapter.candidate_files == ("opencode.json", "opencode.jsonc")


# --- executables ------------------------------------------------------------


def test_an_executable_inside_the_workspace_is_never_run(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, claude=False, opencode=False)
    marker = rig.root / "ran.txt"
    install_fake(rig.root / "bin", "claude", CLAUDE_VERSION_LINE)
    rig.env["PATH"] = str(rig.root / "bin") + os.pathsep + rig.env["PATH"]
    detection = ClaudeCodeAdapter().detect(rig.context)
    assert detection.state is DetectionState.NOT_INSTALLED
    assert not marker.exists()


def test_relative_and_current_directory_path_entries_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "rel").mkdir()
    install_fake(tmp_path / "rel", "claude", CLAUDE_VERSION_LINE)
    found = locate_executable(
        ("claude",), path_env=os.pathsep.join(["rel", ".", ""]), excluded_dirs=[]
    )
    assert found is None


def test_a_directory_named_like_the_executable_is_not_launched(tmp_path: Path) -> None:
    (tmp_path / "bin").mkdir()
    suffix = ".cmd" if sys.platform == "win32" else ""
    (tmp_path / "bin" / f"claude{suffix}").mkdir()
    assert locate_executable(("claude",), path_env=str(tmp_path / "bin")) is None


def test_a_hanging_probe_is_killed_at_the_timeout(tmp_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(ProbeFailure) as failure:
        run_probe(
            Path(sys.executable),
            ["-c", "import time; time.sleep(60)"],
            env=base_env(),
            cwd=tmp_path,
            timeout=0.5,
        )
    assert failure.value.reason == "timeout"
    assert time.monotonic() - started < 10


def test_probe_output_is_bounded(tmp_path: Path) -> None:
    output = run_probe(
        Path(sys.executable),
        ["-c", "print('x' * 5_000_000)"],
        env=base_env(),
        cwd=tmp_path,
        timeout=20,
    )
    assert len(output.text.encode()) <= MAX_PROBE_OUTPUT_BYTES


def test_the_probe_environment_is_scrubbed(tmp_path: Path) -> None:
    env = {**base_env(), "ANTHROPIC_API_KEY": SECRET, "OPENAI_API_KEY": SECRET, "X_TOKEN": SECRET}
    output = run_probe(
        Path(sys.executable),
        ["-c", "import os; print(sorted(k for k in os.environ if 'KEY' in k or 'TOKEN' in k))"],
        env=env,
        cwd=tmp_path,
        timeout=20,
    )
    assert "ANTHROPIC" not in output.text
    assert "OPENAI" not in output.text
    assert "X_TOKEN" not in output.text


def test_a_missing_executable_path_is_not_executable(tmp_path: Path) -> None:
    with pytest.raises(ProbeFailure) as failure:
        run_probe(tmp_path / "ghost.exe", ["--version"], env=base_env(), cwd=tmp_path)
    assert failure.value.reason in {"not_executable", "permission_denied"}


# --- hostile files ----------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\xfe\x00not utf8",
        b'{"mcpServers": {"a": {"x": "' + b"A" * (fsafe.MAX_CONFIG_BYTES + 10) + b'"}}}',
        b'{"mcpServers": {"studio-os": 1, "studio-os": 2}}',
        b"[" * 500 + b"]" * 500,
        b'{"mcpServers": {}} trailing garbage',
        b"",
    ],
    ids=["not-utf8", "oversized", "duplicate-key", "deep-nesting", "trailing-garbage", "empty"],
)
def test_hostile_files_fail_closed_and_are_never_modified(rig: Rig, content: bytes) -> None:
    path = rig.root / ".mcp.json"
    path.write_bytes(content)
    detection = ClaudeCodeAdapter().detect(rig.context)
    assert detection.state in {DetectionState.CONFIGURATION_INVALID, DetectionState.UNAVAILABLE}
    with pytest.raises(HarnessServiceError):
        rig.service.preview(
            HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
        )
    assert path.read_bytes() == content


def test_prototype_like_and_odd_keys_are_data_not_behaviour(rig: Rig) -> None:
    (rig.root / ".mcp.json").write_text(
        '{"__proto__": {"polluted": true}, "constructor": 1, "mcpServers": {"a.b": {}}}'
    )
    edits = ClaudeCodeAdapter().plan(rig.context)
    after = edits[0].after.decode()
    assert '"__proto__"' in after and '"a.b"' in after


def test_a_directory_in_place_of_the_config_is_refused(rig: Rig) -> None:
    (rig.root / ".mcp.json").mkdir()
    detection = ClaudeCodeAdapter().detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_INVALID
    assert detection.reason == "not_regular"


# --- secrets ----------------------------------------------------------------


def test_no_secret_reaches_logs_backups_plans_or_errors(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.env["STUDIO_MCP_MACHINE_TOKEN"] = SECRET
    rig.env["ANTHROPIC_API_KEY"] = SECRET
    rig.env["OPENAI_API_KEY"] = SECRET
    caplog.set_level(logging.DEBUG)
    seen: list[str] = []
    seen.append(rig.service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID)).model_dump_json())
    plan = rig.service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    seen.append(plan.model_dump_json())
    result = rig.service.apply(
        HarnessApplyRequest(plan_id=plan.plan_id, plan_hash=plan.plan_hash, confirmed=True)
    )
    seen.append(result.model_dump_json())
    assert result.rollback_id is not None
    rolled = rig.service.rollback(
        HarnessRollbackRequest(rollback_id=result.rollback_id, confirmed=True)
    )
    seen.append(rolled.model_dump_json())
    seen.append(caplog.text)
    for path in rig.backups_root.rglob("*"):
        if path.is_file():
            seen.append(path.read_text(encoding="utf-8", errors="replace"))
    assert all("SECRET-VALUE" not in text for text in seen)


def test_the_harness_package_never_names_or_reads_provider_credentials() -> None:
    package = Path(fsafe.__file__).parent
    forbidden = ("ANTHROPIC", "OPENAI", "api_key", "apiKey", "API_KEY", "OPENROUTER")
    offenders = [
        f"{source.name}:{word}"
        for source in package.glob("*.py")
        for word in forbidden
        if word in source.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_only_credential_named_is_a_reference_to_the_studio_token() -> None:
    package = Path(fsafe.__file__).parent
    text = "\n".join(source.read_text(encoding="utf-8") for source in package.glob("*.py"))
    assert "STUDIO_MCP_MACHINE_TOKEN" in text
    assert "environ[" not in text
    assert "getenv" not in text.replace("system_env", "")
