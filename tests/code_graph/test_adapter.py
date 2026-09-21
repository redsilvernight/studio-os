from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest
from studio_code_graph import (
    BuildFailure,
    BuildRequest,
    CodeGraphBuildError,
    CodeGraphProvider,
    ProbeState,
)
from studio_code_graph.graphify import GraphifyProvider
from studio_code_graph.graphify.runner import RunResult

from .support import WORKSPACE_ID
from .test_locator import fake_executable
from .test_translate import link, node


class ScriptedRunner:
    def __init__(self, behaviour: Callable[[Sequence[str], Path, Mapping[str, str]], RunResult]):
        self.behaviour = behaviour
        self.calls: list[tuple[list[str], Path, dict[str, str], float]] = []

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: float,
    ) -> RunResult:
        self.calls.append((list(argv), cwd, dict(env), timeout_seconds))
        return self.behaviour(argv, cwd, env)


def writes_graph(payload: object) -> Callable[[Sequence[str], Path, Mapping[str, str]], RunResult]:
    def behaviour(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> RunResult:
        out = Path(env["GRAPHIFY_OUT"])
        out.mkdir(parents=True, exist_ok=True)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        (out / "graph.json").write_text(text, encoding="utf-8")
        return RunResult(0, "", "")

    return behaviour


GRAPH = {
    "nodes": [
        node("f", "a.py", "a.py"),
        node("fn", "run()", "a.py", kind="function", line="L1"),
    ],
    "links": [link("f", "fn", "contains")],
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def run():\n    pass\n", encoding="utf-8")
    return root


def request(tmp_path: Path, repo: Path, **overrides: object) -> BuildRequest:
    values: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "repo_name": "app",
        "repo_root": repo,
        "work_dir": tmp_path / "work",
        "timeout_seconds": 42.0,
    }
    values.update(overrides)
    return BuildRequest(**values)  # type: ignore[arg-type]


@pytest.fixture
def provider_with(tmp_path: Path) -> Callable[..., tuple[GraphifyProvider, ScriptedRunner]]:
    def make(behaviour: Callable[..., RunResult]) -> tuple[GraphifyProvider, ScriptedRunner]:
        runner = ScriptedRunner(behaviour)
        exe = fake_executable(tmp_path, "graphify 0.9.59")
        return GraphifyProvider(executable=exe, runner=runner), runner

    return make


def test_graphify_provider_satisfies_the_neutral_protocol() -> None:
    assert isinstance(GraphifyProvider(), CodeGraphProvider)


def test_probe_reports_states(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIO_CODE_GRAPH_GRAPHIFY_EXE", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert GraphifyProvider().probe().state is ProbeState.NOT_INSTALLED
    exe = fake_executable(tmp_path, "graphify 0.9.59")
    assert GraphifyProvider(executable=exe).probe().state is ProbeState.AVAILABLE


async def test_build_uses_a_fixed_argv_and_an_external_output_dir(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    provider, runner = provider_with(writes_graph(GRAPH))
    result = await provider.build(request(tmp_path, repo), "code.graphify")
    ((argv, cwd, env, timeout),) = runner.calls
    assert argv[1:] == ["update", ".", "--no-cluster", "--force"]
    assert cwd == repo and timeout == 42.0
    assert env["GRAPHIFY_OUT"] == str(tmp_path / "work")
    assert not (repo / "graphify-out").exists()
    assert result.provider_id == "graphify" and result.provider_version == "0.9.59"
    assert len(result.nodes) == 2 and len(result.edges) == 1


async def test_environment_is_sanitized(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    provider, runner = provider_with(writes_graph(GRAPH))
    await provider.build(request(tmp_path, repo), "code.graphify")
    assert "GITHUB_TOKEN" not in runner.calls[0][2]


async def test_process_without_probe_is_started_lazily(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    provider, _ = provider_with(writes_graph(GRAPH))
    assert provider._install is None
    await provider.build(request(tmp_path, repo), "code.graphify")
    assert provider._install is not None


async def test_not_installed_at_build_time(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STUDIO_CODE_GRAPH_GRAPHIFY_EXE", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(CodeGraphBuildError) as error:
        await GraphifyProvider().build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.NOT_AVAILABLE


async def test_corrupt_output(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    provider, _ = provider_with(writes_graph("{ not json"))
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.OUTPUT_CORRUPT


async def test_structurally_wrong_output(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    provider, _ = provider_with(writes_graph(["not", "a", "graph"]))
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.OUTPUT_CORRUPT


async def test_missing_output(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    provider, _ = provider_with(lambda *_: RunResult(0, "", ""))
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.OUTPUT_MISSING


async def test_stale_output_from_a_previous_run_is_not_reused(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "graph.json").write_text(json.dumps(GRAPH), encoding="utf-8")
    provider, _ = provider_with(lambda *_: RunResult(0, "", ""))
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.OUTPUT_MISSING


async def test_interrupted_process_leaves_partial_output_unused(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    def crash(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> RunResult:
        out = Path(env["GRAPHIFY_OUT"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "graph.json").write_text('{"nodes": [', encoding="utf-8")
        return RunResult(137, "", "Killed")

    provider, _ = provider_with(crash)
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.PROCESS_FAILED


async def test_process_failure_detail_hides_paths(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    provider, _ = provider_with(
        lambda *_: RunResult(2, "", f"Traceback\nboom at {tmp_path}/secret/file.py")
    )
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.PROCESS_FAILED
    assert str(tmp_path) not in error.value.detail and "exit code 2" in error.value.detail


async def test_timeout(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    provider, _ = provider_with(lambda *_: RunResult(-1, "", "", timed_out=True))
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.TIMEOUT


async def test_start_failure(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    def refuse(*_: object) -> RunResult:
        raise FileNotFoundError("gone")

    provider, _ = provider_with(refuse)
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.NOT_AVAILABLE
    assert provider._install is None


@pytest.mark.parametrize("where", ["inside", "same", "parent"])
async def test_work_dir_must_be_disjoint_from_the_repo(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
    where: str,
) -> None:
    provider, runner = provider_with(writes_graph(GRAPH))
    work = {"inside": repo / "out", "same": repo, "parent": tmp_path}[where]
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo, work_dir=work), "code.graphify")
    assert error.value.failure is BuildFailure.NOT_AVAILABLE
    assert runner.calls == []
    assert (repo / "a.py").is_file()


async def test_full_rebuild_wipes_the_work_dir_only(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    work = tmp_path / "work"
    (work / "cache").mkdir(parents=True)
    (work / "cache" / "entry").write_text("x", encoding="utf-8")
    provider, _ = provider_with(writes_graph(GRAPH))
    await provider.build(request(tmp_path, repo), "code.graphify")
    assert (work / "cache" / "entry").is_file()
    await provider.build(request(tmp_path, repo, full_rebuild=True), "code.graphify")
    assert not (work / "cache" / "entry").exists()
    assert (repo / "a.py").is_file()


async def test_oversized_output_is_refused(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("studio_code_graph.graphify.adapter.MAX_GRAPH_BYTES", 10)
    provider, _ = provider_with(writes_graph(GRAPH))
    with pytest.raises(CodeGraphBuildError) as error:
        await provider.build(request(tmp_path, repo), "code.graphify")
    assert error.value.failure is BuildFailure.OUTPUT_CORRUPT


async def test_config_filters_reach_the_translation(
    tmp_path: Path,
    repo: Path,
    provider_with: Callable[..., tuple[GraphifyProvider, ScriptedRunner]],
) -> None:
    provider, _ = provider_with(writes_graph(GRAPH))
    result = await provider.build(request(tmp_path, repo, exclude_globs=("a.py",)), "code.graphify")
    assert result.nodes == [] and result.dropped["excluded_by_config"] == 2
