from __future__ import annotations

import asyncio
import logging
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from studio_contracts.events import EventCreate, EventType

from studio_client.outbox import OutboxStore, transaction
from studio_client.watchers.base import PollingWatcher, SleepFn

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitState:
    commit_sha: str
    branch: str | None
    """None for a detached HEAD — `git rev-parse --abbrev-ref HEAD` then
    prints the literal string "HEAD", which is not a real branch name."""


@dataclass(frozen=True)
class GitChange:
    repo_path: Path
    previous_commit: str | None
    previous_branch: str | None
    commit_sha: str
    branch: str | None


GitChangeListener = Callable[[GitChange], Awaitable[None]]


GitReader = Callable[[], Awaitable[GitState | None]]
"""Returns None when `repo_path` is not (currently) a readable Git
repository — a poll skips silently rather than treating a missing/not-yet-
cloned repo as an error to log every interval."""


def default_git_reader(repo_path: Path) -> GitReader:
    async def _read() -> GitState | None:
        return await asyncio.to_thread(_read_sync, repo_path)

    return _read


def _read_sync(repo_path: Path) -> GitState | None:
    try:
        commit_sha = _run_git(repo_path, "rev-parse", "HEAD")
        branch_name = _run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        return None
    return GitState(commit_sha=commit_sha, branch=None if branch_name == "HEAD" else branch_name)


def _run_git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return result.stdout.strip()


class GitWatcher(PollingWatcher):
    """Detects local commit and branch changes on `repo_path` and enqueues
    `git.commit` / `git.branch.changed` events (sous-etape 6.6,
    docs/ROADMAP_STEP6_BREAKDOWN.md). `git.pr.opened`/`git.pr.merged` are
    EventType members but are NOT emitted here: a PR only exists on
    GitHub/a remote, and no GitHub client exists yet in Bloc B
    (`IMPLEMENTATION/03_BLOCK_B_PROMPT.md` lists it as a separate future
    responsibility) — there is nothing local to poll for those two types.

    The Resource Claim invariant applies unconditionally: this watcher only
    ever observes and reports, it never blocks or refuses a Git operation
    regardless of any active claim."""

    def __init__(
        self,
        *,
        repo_path: Path,
        project_id: UUID,
        machine_id: UUID,
        outbox: OutboxStore,
        interval_seconds: float = 30.0,
        sleep: SleepFn | None = None,
        reader: GitReader | None = None,
        event_id_factory: Callable[[], UUID] = uuid4,
        now: Callable[[], datetime] | None = None,
        on_change: GitChangeListener | None = None,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds, sleep=sleep)
        self._on_change = on_change
        self._repo_path = repo_path
        self._project_id = project_id
        self._machine_id = machine_id
        self._outbox = outbox
        self._reader = reader or default_git_reader(repo_path)
        self._event_id_factory = event_id_factory
        self._now = now or (lambda: datetime.now(UTC))
        self._sync_key = f"git_watcher:{repo_path}"

    async def poll_once(self) -> None:
        state = await self._reader()
        if state is None:
            return
        previous = self._outbox.get_sync_state(self._sync_key)
        if previous is None:
            self._save_state(state)
            return

        events: list[EventCreate] = []
        if previous.get("branch") != state.branch:
            events.append(
                self._build_event(
                    EventType.GIT_BRANCH_CHANGED,
                    {"from": previous.get("branch"), "to": state.branch},
                )
            )
        if previous.get("commit_sha") != state.commit_sha:
            events.append(
                self._build_event(
                    EventType.GIT_COMMIT, {"sha": state.commit_sha, "branch": state.branch}
                )
            )
        if not events:
            return

        with transaction(self._outbox.connection):
            for event in events:
                self._outbox.enqueue_event(event)
            self._save_state_unlocked(state)
        await self._notify(previous, state)

    async def _notify(self, previous: dict[str, object], state: GitState) -> None:
        if self._on_change is None:
            return
        previous_commit = previous.get("commit_sha")
        previous_branch = previous.get("branch")
        change = GitChange(
            repo_path=self._repo_path,
            previous_commit=previous_commit if isinstance(previous_commit, str) else None,
            previous_branch=previous_branch if isinstance(previous_branch, str) else None,
            commit_sha=state.commit_sha,
            branch=state.branch,
        )
        try:
            await self._on_change(change)
        except Exception:
            logger.warning("git change listener failed", exc_info=True)

    def _build_event(self, event_type: EventType, payload: dict[str, object]) -> EventCreate:
        return EventCreate(
            event_id=self._event_id_factory(),
            event_type=event_type,
            project_id=self._project_id,
            machine_id=self._machine_id,
            actor_type="system",
            actor_id=self._machine_id,
            client_timestamp=self._now(),
            payload=payload,
        )

    def _save_state(self, state: GitState) -> None:
        with transaction(self._outbox.connection):
            self._save_state_unlocked(state)

    def _save_state_unlocked(self, state: GitState) -> None:
        self._outbox.set_sync_state(
            self._sync_key, {"commit_sha": state.commit_sha, "branch": state.branch}
        )
