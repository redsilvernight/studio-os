from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath

from studio_workspaces.picker import SelectedFolder
from studio_workspaces.root_confirmation import RootConfirmationService

MAX_PATH_CHARS = 4096


class NativePickStatus(StrEnum):
    SELECTED = "selected"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class NativePick:
    """What the P3 shell reports about one native folder dialog (`PickResult`)."""

    status: NativePickStatus
    path: str | None = None
    code: str | None = None


def _rejected(code: str) -> NativePick:
    return NativePick(NativePickStatus.ERROR, code=code)


def parse_native_pick(payload: object) -> NativePick:
    """Fail closed: anything that is not exactly a P3 `PickResult` is an error,
    never a selection. A path is only accepted when it is absolute, bounded and
    free of control characters — the daemon never widens what the user picked."""
    if not isinstance(payload, dict):
        return _rejected("invalid_pick")
    status = payload.get("status")
    if status == "cancelled":
        return NativePick(NativePickStatus.CANCELLED)
    if status == "unavailable":
        return NativePick(NativePickStatus.UNAVAILABLE)
    if status == "error":
        code = payload.get("code")
        return _rejected(code if isinstance(code, str) and code else "picker_failed")
    if status != "selected":
        return _rejected("invalid_pick")
    path = payload.get("path")
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS:
        return _rejected("invalid_path")
    if any(ord(char) < 32 for char in path):
        return _rejected("invalid_path")
    if not PurePath(path).is_absolute():
        return _rejected("path_not_absolute")
    return NativePick(NativePickStatus.SELECTED, path=path)


Chooser = Callable[[], object]


class NativeFolderPicker:
    """`FolderPicker` backed by the P3 native dialog (`choose_folder`).

    The daemon never opens a dialog itself: `chooser` returns the shell's raw
    `PickResult`, which is validated by `parse_native_pick`. A cancelled,
    unavailable or refused pick selects nothing (`None`): the flow then changes
    nothing. `last` keeps the reason for the UI. `MockFolderPicker` stays for tests.
    """

    def __init__(
        self,
        chooser: Chooser,
        nonce_factory: Callable[[], str] = RootConfirmationService.fresh_nonce,
    ) -> None:
        self._chooser = chooser
        self._nonce_factory = nonce_factory
        self.last: NativePick | None = None

    def select_folder(self, hint: str | None = None) -> SelectedFolder | None:
        # `hint` is deliberately unused: the dialog decides where the user browses.
        try:
            pick = parse_native_pick(self._chooser())
        except Exception:  # noqa: BLE001 - a shell failure must never look like a selection
            pick = _rejected("picker_failed")
        self.last = pick
        if pick.status is not NativePickStatus.SELECTED or pick.path is None:
            return None
        return SelectedFolder(path=pick.path, confirmation_nonce=self._nonce_factory())
