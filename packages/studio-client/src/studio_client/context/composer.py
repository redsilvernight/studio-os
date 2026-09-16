from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from studio_client.config import ClientConfig
from studio_client.context.git import read_git_snapshot
from studio_client.context.manifest import (
    ContextPackageManifest,
    Generator,
    Limits,
    Omission,
    SourceRef,
)
from studio_client.knowledge import GraphifyGraphProvider, VaultMemoryProvider


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


@dataclass(frozen=True)
class ContextPackageOptions:
    """Fine-grained controls for one composition (DEC-0057)."""

    include_memory: bool = False
    include_graph: bool = False
    include_git: bool = False
    memory_query: str = ""
    graph_query: str = ""
    budget_bytes: int = 256 * 1024
    events_limit: int = 50
    decisions_limit: int = 20
    ai_work_limit: int = 20
    memory_limit: int = 5
    graph_limit: int = 10
    git_commits_limit: int = 10
    task_only_project_state: bool = False


@dataclass(frozen=True)
class ContextPackage:
    """A composed context package: manifest + serializable data."""

    manifest: ContextPackageManifest
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"manifest": self.manifest.to_dict(), "data": self.data}

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)

    def size_bytes(self) -> int:
        return len(self.to_json().encode("utf-8"))


_SourceName = str
_SourcePriority = int

# Priority order for removal when the budget is exceeded (DEC-0057).
# Lower number = removed first.
_SOURCE_PRIORITY: dict[_SourceName, _SourcePriority] = {
    "memory": 5,
    "graph": 4,
    "git": 3,
    "events": 2,
    "ai_work": 1,
    "decisions": 0,
    "claims": -1,
    "project_state": -2,
    "task": -3,
}


class ContextPackageComposer:
    """Compose a Context Package locally (Bloc B) per DEC-0057.

    The shared state comes from the existing HTTP API via `StudioApiClient`;
    local sources come from the `VaultMemoryProvider`, `GraphifyGraphProvider`
    and a bounded Git snapshot. Nothing local ever leaves the machine unless
    the caller explicitly writes the package to disk with `--out`.
    """

    def __init__(
        self,
        api_client: Any,
        config: ClientConfig,
        *,
        memory_provider: VaultMemoryProvider | None = None,
        graph_provider: GraphifyGraphProvider | None = None,
    ) -> None:
        self._api = api_client
        self._config = config
        self._memory = memory_provider
        self._graph = graph_provider

    async def generate(
        self,
        project_id: UUID,
        task_id: UUID | None = None,
        options: ContextPackageOptions | None = None,
    ) -> ContextPackage:
        opts = options or ContextPackageOptions()
        manifest = ContextPackageManifest(
            project_id=project_id,
            task_id=task_id,
            generator=Generator(machine_id=self._config.machine_id),
            limits=Limits(
                budget_bytes=opts.budget_bytes,
                events_limit=opts.events_limit,
                decisions_limit=opts.decisions_limit,
                ai_work_limit=opts.ai_work_limit,
                memory_limit=opts.memory_limit,
                graph_limit=opts.graph_limit,
                git_commits_limit=opts.git_commits_limit,
            ),
        )

        sources: dict[str, tuple[SourceRef, Any]] = {}
        omitted: list[Omission] = []

        # Shared sources (server).
        shared = await self._gather_shared(project_id, task_id, opts)
        for name, (ref, payload) in shared.items():
            if ref is not None:
                sources[name] = (ref, payload)
            elif payload is not None:
                omitted.append(payload)

        # Local sources (opt-in).
        if opts.include_memory and self._memory is not None:
            ref, payload = self._compose_memory(opts)
            if ref is not None:
                sources["memory"] = (ref, payload)
            elif payload is not None:
                omitted.append(payload)
        elif opts.include_memory:
            omitted.append(Omission("memory", 0, "vault_not_configured"))

        if opts.include_graph and self._graph is not None:
            ref, payload = self._compose_graph(opts)
            if ref is not None:
                sources["graph"] = (ref, payload)
            elif payload is not None:
                omitted.append(payload)
        elif opts.include_graph:
            omitted.append(Omission("graph", 0, "graph_dir_not_configured"))

        if opts.include_git:
            git = await read_git_snapshot(
                self._config.git_watch_repo_path, commits_limit=opts.git_commits_limit
            )
            if git is not None:
                ref = SourceRef(
                    kind="git",
                    ref=f"git:{git.head}",
                    included=len(git.recent_commits),
                )
                sources["git"] = (ref, git.__dict__)
            else:
                omitted.append(Omission("git", 0, "repo_not_configured"))

        # Apply hard budget.
        manifest, sources, omitted, truncated = self._apply_budget(manifest, sources, omitted, opts)

        data: dict[str, Any] = {name: payload for name, (_, payload) in sorted(sources.items())}
        final_manifest = ContextPackageManifest(
            schema_version=manifest.schema_version,
            package_id=manifest.package_id,
            generated_at=manifest.generated_at,
            project_id=manifest.project_id,
            task_id=manifest.task_id,
            generator=manifest.generator,
            manifest_scope=manifest.manifest_scope,
            limits=manifest.limits,
            sources=[ref for _, (ref, _) in sorted(sources.items())],
            omitted=omitted,
            truncated=truncated,
        )
        return ContextPackage(manifest=final_manifest, data=data)

    async def _gather_shared(
        self,
        project_id: UUID,
        task_id: UUID | None,
        opts: ContextPackageOptions,
    ) -> dict[str, tuple[SourceRef | None, Any]]:
        """Fetch shared sources from the server. Each failure is recorded as
        an omission rather than raised."""
        result: dict[str, tuple[SourceRef | None, Any]] = {}

        async def _task() -> tuple[str, tuple[SourceRef | None, Any]] | None:
            if task_id is None:
                return None
            try:
                task = await self._api.get_task(task_id)
                ref = SourceRef(kind="task", ref=str(task_id), version=None)
                return "task", (ref, task.model_dump(mode="json"))
            except Exception as exc:  # noqa: BLE001
                reason = "server_unreachable" if self._is_transport_error(exc) else "missing"
                return "task", (None, Omission("task", 0, reason))

        async def _project_state() -> tuple[str, tuple[SourceRef | None, Any]] | None:
            try:
                state = await self._api.get_project_state(project_id)
                ref = SourceRef(
                    kind="project_state",
                    ref=str(project_id),
                    server_timestamp=state.generated_at,
                )
                payload = state.model_dump(mode="json")
                if opts.task_only_project_state and task_id is not None:
                    payload = {
                        **payload,
                        "active_tasks": [
                            t
                            for t in payload.get("active_tasks", [])
                            if t.get("id") == str(task_id)
                        ],
                    }
                return "project_state", (ref, payload)
            except Exception as exc:  # noqa: BLE001
                reason = "server_unreachable" if self._is_transport_error(exc) else "missing"
                return "project_state", (None, Omission("project_state", 0, reason))

        async def _claims() -> tuple[str, tuple[SourceRef | None, Any]] | None:
            try:
                claims = await self._api.list_claims(project_id=project_id)
                ref = SourceRef(kind="claims", ref=str(project_id), included=len(claims))
                return "claims", (ref, [c.model_dump(mode="json") for c in claims])
            except Exception as exc:  # noqa: BLE001
                reason = "server_unreachable" if self._is_transport_error(exc) else "missing"
                return "claims", (None, Omission("claims", 0, reason))

        async def _decisions() -> tuple[str, tuple[SourceRef | None, Any]] | None:
            try:
                decisions = await self._api.list_decisions(project_id=project_id)
                limited = decisions[: opts.decisions_limit]
                ref = SourceRef(
                    kind="decisions",
                    ref=str(project_id),
                    included=len(limited),
                    truncated=len(limited) < len(decisions),
                )
                return "decisions", (ref, [d.model_dump(mode="json") for d in limited])
            except Exception as exc:  # noqa: BLE001
                reason = "server_unreachable" if self._is_transport_error(exc) else "missing"
                return "decisions", (None, Omission("decisions", 0, reason))

        async def _ai_work() -> tuple[str, tuple[SourceRef | None, Any]] | None:
            try:
                work = await self._api.list_ai_work(project_id=project_id, task_id=task_id)
                limited = work[: opts.ai_work_limit]
                ref = SourceRef(
                    kind="ai_work",
                    ref=str(project_id),
                    included=len(limited),
                    truncated=len(limited) < len(work),
                )
                return "ai_work", (ref, [w.model_dump(mode="json") for w in limited])
            except Exception as exc:  # noqa: BLE001
                reason = "server_unreachable" if self._is_transport_error(exc) else "missing"
                return "ai_work", (None, Omission("ai_work", 0, reason))

        async def _events() -> tuple[str, tuple[SourceRef | None, Any]] | None:
            try:
                events = await self._api.list_events(
                    project_id=project_id,
                    task_id=task_id,
                    limit=opts.events_limit,
                )
                ref = SourceRef(
                    kind="events",
                    ref=str(project_id),
                    included=len(events),
                    server_timestamp=events[-1].server_timestamp if events else None,
                    seq=events[-1].schema_version if events else None,
                )
                return "events", (ref, [e.model_dump(mode="json") for e in events])
            except Exception as exc:  # noqa: BLE001
                reason = "server_unreachable" if self._is_transport_error(exc) else "missing"
                return "events", (None, Omission("events", 0, reason))

        coroutines = [_task(), _project_state(), _claims(), _decisions(), _ai_work(), _events()]
        for item in await asyncio.gather(*coroutines):
            if item is not None:
                key, value = item
                result[key] = value
        return result

    def _compose_memory(self, opts: ContextPackageOptions) -> tuple[SourceRef | None, Any]:
        assert self._memory is not None
        query = opts.memory_query.strip()
        if not query:
            return None, Omission("memory", 0, "no_query")
        result = self._memory.search(query, max_results=opts.memory_limit)
        if result.reason:
            return None, Omission("memory", 0, result.reason)
        ref = SourceRef(kind="memory", ref=query, included=len(result.matches))
        payload = [
            {"path": hit.path, "title": hit.title, "excerpt": hit.excerpt} for hit in result.matches
        ]
        return ref, payload

    def _compose_graph(self, opts: ContextPackageOptions) -> tuple[SourceRef | None, Any]:
        assert self._graph is not None
        query = opts.graph_query.strip()
        if not query:
            return None, Omission("graph", 0, "no_query")
        result = self._graph.relevant_files(query, limit=opts.graph_limit)
        ref = SourceRef(
            kind="graph",
            ref=query,
            included=len(result.files),
            stale=result.stale,
            stale_reason=result.stale_reason,
        )
        payload = {"files": result.files}
        return ref, payload

    def _apply_budget(
        self,
        manifest: ContextPackageManifest,
        sources: dict[str, tuple[SourceRef, Any]],
        omitted: list[Omission],
        opts: ContextPackageOptions,
    ) -> tuple[ContextPackageManifest, dict[str, tuple[SourceRef, Any]], list[Omission], bool]:
        """Remove lowest-priority sources until the package fits the budget."""
        truncated = False
        manifest_size = manifest.package_size_bytes()
        current_size = manifest_size + sum(_json_size(payload) for _, payload in sources.values())

        while current_size > opts.budget_bytes and sources:
            # Pick removable source with lowest priority number.
            removable = [
                (name, _SOURCE_PRIORITY.get(name, 0))
                for name in sources
                if _SOURCE_PRIORITY.get(name, 0) >= 0
            ]
            if not removable:
                break
            removable.sort(key=lambda item: (item[1], item[0]))
            name_to_drop = removable[0][0]
            ref, payload = sources.pop(name_to_drop)
            dropped_size = _json_size(payload)
            omitted.append(
                Omission(
                    kind=name_to_drop,
                    count=getattr(ref, "included", 0) or 0,
                    reason="budget",
                )
            )
            current_size -= dropped_size
            truncated = True

        if current_size > opts.budget_bytes and sources:
            # Even the core sources don't fit — flag it but keep them.
            truncated = True

        return manifest, sources, omitted, truncated

    @staticmethod
    def _is_transport_error(exc: Exception) -> bool:
        """Heuristic: treat connection errors as 'server unreachable'."""
        from studio_client.errors import TransportError

        return isinstance(exc, TransportError) or "ConnectError" in type(exc).__name__
