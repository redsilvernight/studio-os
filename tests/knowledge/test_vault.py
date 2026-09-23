from __future__ import annotations

from pathlib import Path

import pytest
from studio_client.knowledge import vault as vault_module
from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.vault import (
    CANONICAL_DIRECTORIES,
    VaultState,
    initialize_vault,
    iter_markdown,
    vault_fingerprint,
    vault_state,
)

from tests.knowledge.factories import write


def test_state_of_missing_directory(tmp_path: Path) -> None:
    assert vault_state(tmp_path / "absent") is VaultState.MISSING


def test_state_of_a_file_is_not_a_directory(tmp_path: Path) -> None:
    target = write(tmp_path / "file.md", "# note\n")
    assert vault_state(target) is VaultState.NOT_A_DIRECTORY


def test_state_of_an_empty_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert vault_state(empty) is VaultState.EMPTY


def test_state_of_an_existing_markdown_folder(tmp_path: Path) -> None:
    folder = tmp_path / "notes"
    write(folder / "a.md", "# A\n")
    assert vault_state(folder) is VaultState.MARKDOWN_EXISTING


def test_state_of_a_studios_vault(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    initialize_vault(root)
    assert vault_state(root) is VaultState.STUDIOS_VAULT


def test_initialization_is_non_destructive(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    user_file = write(root / "projects/mine.md", "# Mine\n\nUser content.\n")
    before = user_file.read_bytes()
    report = initialize_vault(root)
    assert user_file.read_bytes() == before
    assert "projects" in report.skipped
    assert set(CANONICAL_DIRECTORIES) <= {*report.created, *report.skipped}
    assert report.state_before is VaultState.MARKDOWN_EXISTING


def test_initialization_never_overwrites_a_readme(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    readme = write(root / "README.md", "mine, not yours\n")
    report = initialize_vault(root)
    assert readme.read_text(encoding="utf-8") == "mine, not yours\n"
    assert "README.md" in report.skipped


def test_initialization_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    initialize_vault(root)
    second = initialize_vault(root)
    assert second.created == ()
    assert second.state_before is VaultState.STUDIOS_VAULT


def test_initialization_keeps_a_file_where_a_directory_is_expected(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    conflict = write(root / "projects", "not a directory\n")
    report = initialize_vault(root)
    assert conflict.read_text(encoding="utf-8") == "not a directory\n"
    assert "projects" in report.skipped


def test_initialization_refuses_a_file_path(tmp_path: Path) -> None:
    target = write(tmp_path / "note.md", "# n\n")
    with pytest.raises(KnowledgeError) as error:
        initialize_vault(target)
    assert error.value.reason == KnowledgeError.VAULT_NOT_A_DIRECTORY


def test_inaccessible_vault_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "vault"
    root.mkdir()

    def denied(_path: object) -> object:
        raise PermissionError("denied")

    monkeypatch.setattr(vault_module.os, "scandir", denied)
    assert vault_state(root) is VaultState.INACCESSIBLE


def test_fingerprint_changes_when_content_changes(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    note = write(root / "a.md", "# A\n")
    first = vault_fingerprint(root)
    note.write_text("# A\n\nmore\n", encoding="utf-8")
    assert vault_fingerprint(root) != first


def test_iter_markdown_ignores_editor_and_metadata_directories(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    write(root / "keep.md", "# keep\n")
    write(root / ".obsidian/workspace.md", "# editor config\n")
    write(root / ".studio/vault.json", "{}\n")
    write(root / "node_modules/pkg/readme.md", "# dep\n")
    write(root / ".hidden/secret.md", "# hidden\n")
    found = [item.relative_path for item in iter_markdown(root)]
    assert found == ["keep.md"]


def test_iter_markdown_honours_exclude_globs(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    write(root / "keep.md", "# keep\n")
    write(root / "projects/draft.md", "# draft\n")
    found = [item.relative_path for item in iter_markdown(root, exclude_globs=("projects/**",))]
    assert found == ["keep.md"]
