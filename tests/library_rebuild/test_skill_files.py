from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import library_import as li
import pytest
from pydantic import ValidationError
from studio_client.context.library import LibraryContextItem, LibraryContextProvider
from studio_client.skill_sync import (
    SkillSyncConflictError,
    SkillSyncError,
    apply_skill_sync,
    plan_skill_sync,
    plan_skill_uninstall,
)
from studio_contracts.library import SkillContent

from .conftest import World

SCHEMA = "studio.library.skill/v1"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _item(key: str, files: dict[str, str] | None = None, version: int = 1) -> LibraryContextItem:
    return LibraryContextItem(
        library_kind="skill",
        stable_key=key,
        version=version,
        version_origin="active",
        scope="studio",
        title=key,
        text=f"body {key} v{version}",
        content_schema=SCHEMA,
        files=tuple((files or {}).items()),
    )


def _sync(home: Path, items: list[LibraryContextItem], **kwargs: object) -> tuple[int, int]:
    result = apply_skill_sync(plan_skill_sync(home, items, include_opencode=True), **kwargs)  # type: ignore[arg-type]
    return len(result.written), len(result.removed)


def _targets(home: Path, key: str) -> list[Path]:
    return [
        home / ".agents" / "skills" / key,
        home / ".claude" / "skills" / key,
        home / ".config" / "opencode" / "skills" / key,
    ]


def test_contract_accepts_legacy_and_multifile() -> None:
    legacy = SkillContent.model_validate({"content_schema": SCHEMA, "text": "x"})
    assert legacy.files == []
    file = {"path": "a/b.md", "text": "t", "sha256": _sha("t")}
    assert SkillContent.model_validate({"content_schema": SCHEMA, "text": "x", "files": [file]})


@pytest.mark.parametrize(
    "path",
    ["../x", "/abs", "a/../b", "C:/x", "a\\b", "SKILL.md", "skill.md", "a//b", "con.md", "a/./b"],
)
def test_contract_refuses_unsafe_paths(path: str) -> None:
    file = {"path": path, "text": "t", "sha256": _sha("t")}
    with pytest.raises(ValidationError):
        SkillContent.model_validate({"content_schema": SCHEMA, "text": "x", "files": [file]})


def test_contract_refuses_bad_hash_duplicates_and_file_dir_clash() -> None:
    def build(*files: dict[str, str]) -> dict[str, object]:
        return {"content_schema": SCHEMA, "text": "x", "files": list(files)}

    ok = {"path": "a.md", "text": "t", "sha256": _sha("t")}
    with pytest.raises(ValidationError):
        SkillContent.model_validate(build({**ok, "sha256": "0" * 64}))
    with pytest.raises(ValidationError):
        SkillContent.model_validate(build(ok, {**ok, "path": "A.md"}))
    with pytest.raises(ValidationError):
        SkillContent.model_validate(build(ok, {**ok, "path": "a.md/b.md"}))


def test_legacy_single_file_skill_installs_without_manifest_files(tmp_path: Path) -> None:
    assert _sync(tmp_path, [_item("solo")]) == (3, 0)
    assert all((d / "SKILL.md").is_file() for d in _targets(tmp_path, "solo"))
    manifest = json.loads((tmp_path / ".studio-os/library-skills-manifest.json").read_text("utf-8"))
    assert "files" not in manifest["skills"][0]
    assert _sync(tmp_path, [_item("solo")]) == (0, 0)


def test_multifile_install_update_remove_idempotent(tmp_path: Path) -> None:
    files = {"references/a.md": "A1", "scripts/deep/run.ps1": "echo 1", ".hidden": "h"}
    assert _sync(tmp_path, [_item("multi", files)])[0] == 3 * 4
    for d in _targets(tmp_path, "multi"):
        for rel, text in files.items():
            assert (d / rel).read_text("utf-8") == text
    assert _sync(tmp_path, [_item("multi", files)]) == (0, 0)

    files2 = {"references/a.md": "A2", "scripts/deep/run.ps1": "echo 1"}
    written, removed = _sync(tmp_path, [_item("multi", files2, version=2)])
    assert removed == 3
    for d in _targets(tmp_path, "multi"):
        assert (d / "references/a.md").read_text("utf-8") == "A2"
        assert not (d / ".hidden").exists()
    assert _sync(tmp_path, [_item("multi", files2, version=2)]) == (0, 0)


def test_unmanaged_and_modified_auxiliary_files_are_protected(tmp_path: Path) -> None:
    local = tmp_path / ".claude/skills/multi/references/a.md"
    local.parent.mkdir(parents=True)
    local.write_text("mine", encoding="utf-8")
    plan = plan_skill_sync(tmp_path, [_item("multi", {"references/a.md": "A"})])
    with pytest.raises(SkillSyncConflictError):
        apply_skill_sync(plan)
    assert local.read_text("utf-8") == "mine"
    assert not (tmp_path / ".agents/skills/multi/SKILL.md").exists()

    _sync(tmp_path, [_item("multi", {"references/a.md": "A"})], overwrite=True)
    assert local.read_text("utf-8") == "A"
    assert any(p.read_text("utf-8") == "mine" for p in (tmp_path / ".studio-os").rglob("a.md"))

    local.write_text("edited", encoding="utf-8")
    with pytest.raises(SkillSyncConflictError):
        _sync(tmp_path, [_item("multi", {"references/a.md": "B"}, version=2)])
    assert local.read_text("utf-8") == "edited"


def test_unmanaged_neighbour_files_survive_update_and_uninstall(tmp_path: Path) -> None:
    _sync(tmp_path, [_item("multi", {"references/a.md": "A"})])
    note = tmp_path / ".claude/skills/multi/notes.txt"
    note.write_text("keep", encoding="utf-8")
    _sync(tmp_path, [_item("multi", {}, version=2)])
    assert note.read_text("utf-8") == "keep"
    assert not (tmp_path / ".claude/skills/multi/references").exists()
    apply_skill_sync(plan_skill_uninstall(tmp_path, ["multi"]))
    assert note.read_text("utf-8") == "keep"
    assert not (tmp_path / ".claude/skills/multi/SKILL.md").exists()


def test_malicious_projection_is_refused_before_any_write(tmp_path: Path) -> None:
    for bad in ("../escape.md", "/abs.md", "a/../../x"):
        with pytest.raises(SkillSyncError):
            plan_skill_sync(tmp_path, [_item("multi", {bad: "x"})])
    assert not any(tmp_path.iterdir())
    assert not (tmp_path.parent / "escape.md").exists()


def test_symlinked_directory_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    home = tmp_path / "home"
    (home / ".agents/skills/multi").mkdir(parents=True)
    try:
        os.symlink(outside, home / ".agents/skills/multi/references", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted on this host")
    with pytest.raises(SkillSyncError):
        plan_skill_sync(home, [_item("multi", {"references/a.md": "x"})])
    assert not list(outside.iterdir())


def test_uninstall_reinstall_and_other_skills_untouched(tmp_path: Path) -> None:
    items = [_item("one", {"r/a.md": "A"}), _item("two", {"r/b.md": "B"})]
    _sync(tmp_path, items)
    result = apply_skill_sync(plan_skill_uninstall(tmp_path, ["one"]))
    assert len(result.removed) == 3 * 2
    for d in _targets(tmp_path, "one"):
        assert not d.exists()
    for d in _targets(tmp_path, "two"):
        assert (d / "r/b.md").read_text("utf-8") == "B"
    manifest = json.loads((tmp_path / ".studio-os/library-skills-manifest.json").read_text("utf-8"))
    assert [r["stable_key"] for r in manifest["skills"]] == ["two"]
    assert _sync(tmp_path, items) == (3 * 2, 0)
    with pytest.raises(SkillSyncError):
        plan_skill_uninstall(tmp_path, ["never-installed"])


def test_uninstall_keeps_locally_modified_files(tmp_path: Path) -> None:
    _sync(tmp_path, [_item("one", {"r/a.md": "A"})])
    edited = tmp_path / ".agents/skills/one/r/a.md"
    edited.write_text("edited", encoding="utf-8")
    apply_skill_sync(plan_skill_uninstall(tmp_path, ["one"]))
    assert edited.read_text("utf-8") == "edited"
    assert not (tmp_path / ".agents/skills/one/SKILL.md").exists()


def _source_files(layer: str, key: str) -> dict[str, str]:
    """Expected installed content straight from the verified package manifest."""
    manifest = json.loads((li.ROOT / f"library/packages/{layer}/manifest.json").read_text("utf-8"))
    entry = next(e for e in manifest["entries"] if e["stable_key"] == key)
    base = li.ROOT / ("library/packages/personal" if layer == "personal" else "")
    out: dict[str, str] = {}
    for f in entry["files"]:
        data = (base / f["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["sha256"]
        out[f["path"]] = data.decode("utf-8").replace("\r\n", "\n")
    return out


@pytest.mark.asyncio(loop_scope="session")
async def test_three_real_skills_published_and_installed_with_all_files(
    world: World, rebuilt: object, tmp_path: Path
) -> None:
    layers = {"studio-task": "core", "graphify": "project", "workstation-setup": "personal"}
    actor = {"core": world.admin, "project": world.installer, "personal": world.owner}
    plans = {layer: {i.stable_key: i for i in li.load_plan(layer).items} for layer in actor}
    for key, layer in layers.items():
        published = plans[layer][key].content["files"]
        assert published, key
    # Personal and Core/Project reach the same home through their own principal.
    for key, layer in layers.items():
        project_layer = layer == "project"
        fetched = await LibraryContextProvider(actor[layer].client).fetch(
            world.project_id if project_layer else None, limit=100, kinds=("skill",)
        )
        wanted = "project" if project_layer else ("user" if layer == "personal" else "studio")
        item = next(p for p in fetched.items if p.stable_key == key and p.scope == wanted)
        source = _source_files(layer, key)
        main = min((p for p in source if p.endswith("/SKILL.md")), key=lambda p: p.count("/"))
        root = main.rsplit("/", 1)[0] + "/"
        expected = {p.removeprefix(root): t for p, t in source.items() if p != main}
        assert dict(item.files) == expected
        apply_skill_sync(
            plan_skill_sync(tmp_path, [item], include_opencode=True, allow_project=True)
        )
        for d in _targets(tmp_path, key):
            for rel, text in expected.items():
                assert (d / rel).read_text("utf-8") == text
                assert _sha((d / rel).read_text("utf-8")) == _sha(text)
        again = plan_skill_sync(tmp_path, [item], include_opencode=True, allow_project=True)
        assert not again.drifted and not again.missing


def test_importer_uses_shallowest_skill_md_as_main() -> None:
    texts = {
        "x/assets/nested/SKILL.md": "---\ndescription: nested\n---\nnested body",
        "x/SKILL.md": "---\ndescription: root\n---\nroot body",
        "x/references/a.md": "A",
    }
    _, content, _ = li._content({"stable_key": "x", "kind": "skill"}, texts)
    assert content["text"].strip() == "root body"
    assert [f["path"] for f in content["files"]] == ["assets/nested/SKILL.md", "references/a.md"]
