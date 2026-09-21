from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from studio_code_graph.graphify.locator import GraphifyInstall, probe_install
from studio_code_graph.graphify.runner import ProcessRunner, SubprocessRunner, sanitized_env
from studio_code_graph.graphify.translate import (
    LANGUAGE_BY_EXTENSION,
    TranslationContext,
    translate_graph,
)
from studio_code_graph.paths import same_location
from studio_code_graph.provider import (
    BuildFailure,
    BuildRequest,
    CodeGraphBuildError,
    ProbeState,
    ProviderProbe,
    RepoGraph,
)

PROVIDER_ID = "graphify"
GRAPH_FILE = "graph.json"
MAX_GRAPH_BYTES = 256 * 1024 * 1024
_PATH_TOKEN = re.compile(r"(?:[A-Za-z]:[\\/]|/)\S*")


def _scrub(text: str, limit: int = 160) -> str:
    return _PATH_TOKEN.sub("<path>", text).strip()[:limit]


class GraphifyProvider:
    """The only module family that knows Graphify: locating the executable,
    building its argv, running it and translating `graph.json`. Everything it
    returns is already in the common graph schema."""

    provider_id = PROVIDER_ID
    display_name = "Graphify code graph"
    capabilities = (
        "files",
        "symbols.class",
        "symbols.function",
        "relations.contains",
        "relations.imports",
        "relations.calls.static",
        "relations.inherits",
        "index.cache_assisted",
    )
    language_by_extension = LANGUAGE_BY_EXTENSION

    def __init__(
        self, *, executable: Path | None = None, runner: ProcessRunner | None = None
    ) -> None:
        self._configured = executable
        self._runner: ProcessRunner = runner or SubprocessRunner()
        self._install: GraphifyInstall | None = None

    def probe(self) -> ProviderProbe:
        probe, install = probe_install(self._configured)
        self._install = install
        return probe

    async def build(self, request: BuildRequest, source_id: str) -> RepoGraph:
        install = self._install
        if install is None:
            probe = await asyncio.to_thread(self.probe)
            install = self._install
            if install is None or probe.state is not ProbeState.AVAILABLE:
                raise CodeGraphBuildError(BuildFailure.NOT_AVAILABLE, probe.reason)
        self._prepare_work_dir(request)
        try:
            result = await self._runner.run(
                [str(install.executable), "update", ".", "--no-cluster", "--force"],
                cwd=request.repo_root,
                env=sanitized_env({"GRAPHIFY_OUT": str(request.work_dir)}),
                timeout_seconds=request.timeout_seconds,
            )
        except OSError as error:
            self._install = None
            raise CodeGraphBuildError(
                BuildFailure.NOT_AVAILABLE, "graphify could not be started"
            ) from error
        if result.timed_out:
            raise CodeGraphBuildError(
                BuildFailure.TIMEOUT, f"no result within {request.timeout_seconds:.0f}s"
            )
        if result.returncode != 0:
            tail = _scrub(result.stderr.strip().splitlines()[-1]) if result.stderr.strip() else ""
            raise CodeGraphBuildError(
                BuildFailure.PROCESS_FAILED, f"exit code {result.returncode} {tail}".strip()
            )
        graph = await asyncio.to_thread(self._read_graph, request.work_dir)
        context = TranslationContext(
            workspace_id=request.workspace_id,
            repo_name=request.repo_name,
            repo_root=request.repo_root,
            source_id=source_id,
            provider_id=PROVIDER_ID,
            include_globs=request.include_globs,
            exclude_globs=request.exclude_globs,
            languages=request.languages,
        )
        translation = await asyncio.to_thread(translate_graph, graph, context)
        return RepoGraph(
            repo_name=request.repo_name,
            provider_id=PROVIDER_ID,
            provider_version=install.version,
            nodes=translation.nodes,
            edges=translation.edges,
            languages=translation.languages,
            dropped=translation.dropped,
        )

    def _prepare_work_dir(self, request: BuildRequest) -> None:
        work_dir, repo_root = request.work_dir.resolve(), request.repo_root.resolve()
        if same_location(work_dir, repo_root) or repo_root in work_dir.parents:
            raise CodeGraphBuildError(BuildFailure.NOT_AVAILABLE, "work dir lies inside the repo")
        if work_dir in repo_root.parents:
            raise CodeGraphBuildError(BuildFailure.NOT_AVAILABLE, "work dir contains the repo")
        if request.full_rebuild and work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / GRAPH_FILE).unlink(missing_ok=True)

    @staticmethod
    def _read_graph(work_dir: Path) -> object:
        path = work_dir / GRAPH_FILE
        try:
            size = path.stat().st_size
        except OSError as error:
            raise CodeGraphBuildError(
                BuildFailure.OUTPUT_MISSING, "graph output not written"
            ) from error
        if size > MAX_GRAPH_BYTES:
            raise CodeGraphBuildError(
                BuildFailure.OUTPUT_CORRUPT, "graph output exceeds the size limit"
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CodeGraphBuildError(
                BuildFailure.OUTPUT_CORRUPT, "graph output is not valid JSON"
            ) from error
