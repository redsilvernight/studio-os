"""8.2 memory adapter tests. Every fixture is synthetic under `tmp_path` —
never the real AI-Memory vault, on the explicit model of
`tests/graphify/test_vault_sync_and_lint.py`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from studio_client.knowledge import (
    KnowledgeError,
    MemoryProposal,
    ScopePolicy,
    VaultMemoryProvider,
)

EXPOSED = ("projects/demo/", "conventions/")


def _write_note(
    vault: Path,
    relative: str,
    body: str,
    frontmatter: dict[str, object] | None = None,
    raw_header: str | None = None,
) -> Path:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw_header is not None:
        path.write_text(f"---\n{raw_header}\n---\n{body}", encoding="utf-8")
    elif frontmatter is not None:
        header = yaml.safe_dump(dict(frontmatter), sort_keys=True, allow_unicode=True)
        path.write_text(f"---\n{header}---\n{body}", encoding="utf-8")
    else:
        path.write_text(body, encoding="utf-8")
    return path


def _provider(vault: Path | None, prefixes: tuple[str, ...] = EXPOSED) -> VaultMemoryProvider:
    return VaultMemoryProvider(vault, ScopePolicy(allowed_prefixes=prefixes))


def _seed(vault: Path) -> None:
    _write_note(
        vault,
        "projects/demo/alpha.md",
        "# Alpha\n\nThe offline replay uses an idempotency key.\n",
        {"title": "Alpha note"},
    )
    _write_note(
        vault,
        "conventions/style.md",
        "# Style\n\nWrite compact responses for agents.\n",
        {"title": "Style guide"},
    )
    _write_note(
        vault,
        "ai/private-plan.md",
        "# Secret\n\nThe offline replay uses an idempotency key.\n",
        {"title": "Private plan"},
    )


def test_search_finds_exposed_note(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = _provider(tmp_path).search("idempotency")
    assert result.reason is None
    assert [hit.path for hit in result.matches] == ["projects/demo/alpha.md"]
    assert result.matches[0].title == "Alpha note"
    assert "idempotency" in result.matches[0].excerpt.lower()


def test_search_never_surfaces_out_of_scope_note(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = _provider(tmp_path).search("secret")
    assert result.matches == []


def test_read_out_of_scope_by_exact_path_refused(tmp_path: Path) -> None:
    _seed(tmp_path)
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(tmp_path).read("ai/private-plan.md")
    assert exc_info.value.reason == KnowledgeError.OUT_OF_SCOPE


def test_read_parent_traversal_refused(tmp_path: Path) -> None:
    _seed(tmp_path)
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(tmp_path).read("projects/demo/../../ai/private-plan.md")
    assert exc_info.value.reason == KnowledgeError.OUT_OF_SCOPE


def test_read_absolute_path_refused(tmp_path: Path) -> None:
    _seed(tmp_path)
    target = tmp_path / "projects" / "demo" / "alpha.md"
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(tmp_path).read(str(target))
    assert exc_info.value.reason == KnowledgeError.OUT_OF_SCOPE


def test_symlink_escape_refused(tmp_path: Path) -> None:
    secret = tmp_path / "outside-secret.md"
    secret.write_text("# TopSecret\n\nEscape content here.\n", encoding="utf-8")
    link = tmp_path / "projects" / "demo" / "leak.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("symlinks not permitted on this machine")
    provider = _provider(tmp_path)
    assert all(hit.path != "projects/demo/leak.md" for hit in provider.search("escape").matches)
    with pytest.raises(KnowledgeError) as exc_info:
        provider.read("projects/demo/leak.md")
    assert exc_info.value.reason == KnowledgeError.OUT_OF_SCOPE


def test_vault_missing_degrades_explicitly(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-vault"
    result = _provider(missing).search("anything")
    assert result.matches == []
    assert result.reason == KnowledgeError.VAULT_MISSING
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(missing).read("projects/demo/alpha.md")
    assert exc_info.value.reason == KnowledgeError.VAULT_MISSING
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(None).read("projects/demo/alpha.md")
    assert exc_info.value.reason == KnowledgeError.VAULT_MISSING


def test_vault_not_a_directory(tmp_path: Path) -> None:
    impostor = tmp_path / "file-not-dir"
    impostor.write_text("x", encoding="utf-8")
    result = _provider(impostor).search("x")
    assert result.matches == []
    assert result.reason == KnowledgeError.VAULT_NOT_A_DIRECTORY
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(impostor).read("x")
    assert exc_info.value.reason == KnowledgeError.VAULT_NOT_A_DIRECTORY


def test_invalid_frontmatter_skipped_in_search_but_loud_on_read(tmp_path: Path) -> None:
    _write_note(
        tmp_path,
        "projects/demo/broken.md",
        "# Broken\n\nUnparsable marker uniqueword.\n",
        raw_header="title: [unclosed\n  bad: : :",
    )
    provider = _provider(tmp_path)
    assert provider.search("uniqueword").matches == []
    with pytest.raises(KnowledgeError) as exc_info:
        provider.read("projects/demo/broken.md")
    assert exc_info.value.reason == KnowledgeError.INVALID_FRONTMATTER


def test_empty_query_returns_empty_without_crash(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert _provider(tmp_path).search("   ").matches == []


def test_search_respects_max_results(tmp_path: Path) -> None:
    for index in range(30):
        _write_note(
            tmp_path,
            f"projects/demo/note-{index:02d}.md",
            f"# Note {index}\n\nShared marker volumeword.\n",
            {"title": f"Note {index}"},
        )
    result = _provider(tmp_path).search("volumeword", max_results=10)
    assert len(result.matches) == 10


def test_search_excerpt_is_truncated_and_bounded(tmp_path: Path) -> None:
    body = "# Long\n\n" + ("filler sentence. " * 200) + "needleword tail.\n"
    _write_note(tmp_path, "projects/demo/long.md", body, {"title": "Long"})
    (hit,) = _provider(tmp_path).search("needleword").matches
    assert hit.truncated is True
    assert len(hit.excerpt) <= 502  # excerpt chars + ellipsis markers


def test_read_truncates_long_note(tmp_path: Path) -> None:
    body = "# Big\n\n" + ("content line. " * 500)
    _write_note(tmp_path, "projects/demo/big.md", body, {"title": "Big"})
    result = _provider(tmp_path).read("projects/demo/big.md", max_chars=100)
    assert result.truncated is True
    assert len(result.content) <= 102


def test_read_missing_note_is_typed(tmp_path: Path) -> None:
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(tmp_path).read("projects/demo/ghost.md")
    assert exc_info.value.reason == KnowledgeError.NOT_FOUND


def test_note_without_frontmatter_uses_heading(tmp_path: Path) -> None:
    _write_note(tmp_path, "projects/demo/plain.md", "# Plain Title\n\nSome body.\n")
    result = _provider(tmp_path).read("projects/demo/plain.md")
    assert result.title == "Plain Title"
    assert result.truncated is False


def test_empty_vault_dir_searches_empty(tmp_path: Path) -> None:
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    result = _provider(tmp_path).search("anything")
    assert result.matches == []
    assert result.reason is None


def test_default_scope_denies_everything(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert _provider(tmp_path, prefixes=()).search("idempotency").matches == []
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(tmp_path, prefixes=()).read("projects/demo/alpha.md")
    assert exc_info.value.reason == KnowledgeError.OUT_OF_SCOPE


def test_write_methods_are_declared_but_unsupported(tmp_path: Path) -> None:
    _seed(tmp_path)
    provider = _provider(tmp_path)
    before = (tmp_path / "projects" / "demo" / "alpha.md").read_bytes()
    for call in (
        lambda: provider.propose(MemoryProposal(title="x")),
        lambda: provider.write_if_authorized(MemoryProposal(title="x")),
        lambda: provider.append_task_log({"text": "x"}),
        lambda: provider.create_decision_note({"title": "x"}),
    ):
        with pytest.raises(KnowledgeError) as exc_info:
            call()
        assert exc_info.value.reason == KnowledgeError.WRITE_UNSUPPORTED
    assert (tmp_path / "projects" / "demo" / "alpha.md").read_bytes() == before


def test_broken_symlink_in_scope_does_not_crash_search(tmp_path: Path) -> None:
    _seed(tmp_path)
    dangling = tmp_path / "projects" / "demo" / "dangling.md"
    try:
        dangling.symlink_to(tmp_path / "no-such-target.md")
    except OSError:
        pytest.skip("symlinks not permitted on this machine")
    result = _provider(tmp_path).search("idempotency")
    assert [hit.path for hit in result.matches] == ["projects/demo/alpha.md"]


def test_non_utf8_bytes_do_not_crash_search(tmp_path: Path) -> None:
    _seed(tmp_path)
    binary = tmp_path / "projects" / "demo" / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00not text at all")
    result = _provider(tmp_path).search("idempotency")
    assert [hit.path for hit in result.matches] == ["projects/demo/alpha.md"]
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(tmp_path).read("projects/demo/binary.md")
    assert exc_info.value.reason == KnowledgeError.INVALID_FRONTMATTER
