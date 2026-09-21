from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SelectedFolder:
    path: str
    confirmation_nonce: str


class FolderPicker(Protocol):
    """Shell-side folder selection (P3 owns the native dialog).

    After the user confirms a folder in the native dialog, the shell hands the
    chosen path to the daemon, which mints the P1 `root_confirmation_id` via
    `RootConfirmationService.issue()`. No bridge command exists for picking:
    the P1 allowlist (`workspace.validate/get_config/save_config`) is closed
    and needs no change for P5.
    """

    def select_folder(self, hint: str | None = None) -> SelectedFolder | None:
        raise NotImplementedError


class MockFolderPicker:
    def __init__(self, preselected: list[str], nonce: str = "mock-nonce-1") -> None:
        self._preselected = list(preselected)
        self._nonce = nonce
        self.calls: list[str | None] = []

    def select_folder(self, hint: str | None = None) -> SelectedFolder | None:
        self.calls.append(hint)
        if not self._preselected:
            return None
        return SelectedFolder(path=self._preselected.pop(0), confirmation_nonce=self._nonce)
