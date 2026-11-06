from __future__ import annotations

import copy
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "library_packages", ROOT / "scripts/library_packages.py"
)
lp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lp)

HOME = lp.personal_home()
requires_personal = pytest.mark.skipif(
    not (ROOT / "library/packages/personal/manifest.json").is_file(),
    reason="Personal package is git-ignored: absent from a clean checkout",
)


def _read(layer: str) -> dict:
    return json.loads((ROOT / "library/packages" / layer / "manifest.json").read_text("utf-8"))


def _mans() -> dict:
    return {layer: _read(layer) for layer in lp.LAYERS}


def test_every_historical_definition_has_a_justified_decision() -> None:
    decisions = lp.load_decisions(ROOT)
    old = [d for d in decisions if not d["new"]]
    assert len(old) == 87
    for d in decisions:
        assert d["decision"] in lp.DECISIONS
        assert d["rationale"].strip()
        assert (d["decision"] in lp.DEST) == bool(d["destination"])


@requires_personal
def test_committed_manifests_are_valid() -> None:
    assert lp.check(ROOT) == []


def test_core_and_project_are_public_and_separated() -> None:
    core, project = _read("core"), _read("project")
    assert {e["visibility"] for e in core["entries"]} == {"public"}
    ids = lambda m: {(e["kind"], e["stable_key"]) for e in m["entries"]}  # noqa: E731
    assert not ids(core) & ids(project)
    text = json.dumps([core, project])
    assert not lp.PERSONAL_RE.search(text)


def test_generation_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    for rel in ("library", ".agents", "scripts", "docs/library/rebuild-2026"):
        shutil.copytree(ROOT / rel, root / rel, ignore=shutil.ignore_patterns("personal"))
    first = lp.build(root, HOME)
    snap = {p: p.read_bytes() for p in (root / "library/packages").rglob("*") if p.is_file()}
    lp.build(root, HOME)
    again = {p: p.read_bytes() for p in (root / "library/packages").rglob("*") if p.is_file()}
    assert snap == again
    for layer in ("core", "project"):
        assert len(first[layer]) == len(_read(layer)["entries"])
        assert (root / f"library/packages/{layer}/manifest.json").read_bytes() == (
            ROOT / f"library/packages/{layer}/manifest.json"
        ).read_bytes()


@requires_personal
def test_hash_tamper_missing_file_and_leaks_are_detected() -> None:
    mans = _mans()
    bad = copy.deepcopy(mans)
    bad["core"]["entries"][0]["files"][0]["sha256"] = "0" * 64
    assert any("hash différent" in e for e in lp.validate(bad, ROOT, ROOT))
    bad = copy.deepcopy(mans)
    bad["core"]["entries"][0]["files"][0]["path"] = "library/studio/absent.md"
    assert any("fichier absent" in e for e in lp.validate(bad, ROOT, ROOT))


@requires_personal
def test_collision_unresolved_dependency_and_cycle_are_detected() -> None:
    mans = _mans()
    bad = copy.deepcopy(mans)
    bad["project"]["entries"].append(copy.deepcopy(bad["core"]["entries"][0]))
    assert any("collision" in e or "owner" in e for e in lp.validate(bad, ROOT, ROOT))
    bad = copy.deepcopy(mans)
    bad["core"]["entries"][0]["dependencies"].append({"kind": "rule", "stable_key": "nope"})
    assert any("non résolue" in e for e in lp.validate(bad, ROOT, ROOT))
    bad = copy.deepcopy(mans)
    a, b = bad["core"]["entries"][0], bad["core"]["entries"][1]
    a["dependencies"] = [{"kind": b["kind"], "stable_key": b["stable_key"]}]
    b["dependencies"] = [{"kind": a["kind"], "stable_key": a["stable_key"]}]
    assert any("cycle" in e for e in lp.validate(bad, ROOT, ROOT))


@requires_personal
def test_core_cannot_depend_on_project() -> None:
    bad = copy.deepcopy(_mans())
    target = bad["project"]["entries"][0]
    bad["core"]["entries"][0]["dependencies"].append(
        {"kind": target["kind"], "stable_key": target["stable_key"]}
    )
    assert any("non résolue" in e for e in lp.validate(bad, ROOT, ROOT))


def test_scanner_flags_secrets_and_personal_paths(tmp_path: Path) -> None:
    secret = tmp_path / "a.md"
    secret.write_text("token ghp_" + "a" * 30, encoding="utf-8")
    personal = tmp_path / "b.md"
    personal.write_text("voir C:\\Users\\x\\vault", encoding="utf-8")
    clean = tmp_path / "c.md"
    clean.write_text("rien à signaler", encoding="utf-8")
    assert lp.scan([secret]) and lp.scan([personal]) and not lp.scan([clean])


def test_unreadable_source_is_demoted_not_invented(tmp_path: Path) -> None:
    spec = {
        "scope": "studio",
        "kind": "rule",
        "key": "ghost",
        "version": 1,
        "decision": "CORE_PUBLIC",
        "destination": "core",
        "source": "library/studio/rules/ghost.md",
        "rationale": "x",
        "tier": "base",
        "supersedes": None,
        "new": False,
    }
    packages, effective = lp.build_entries(ROOT, HOME, [spec])
    assert packages["core"] == [] and effective[0]["decision"] == "NOT_READY"


@pytest.mark.skipif(
    not (ROOT / "library/packages/personal/manifest.json").exists(), reason="Personal absent"
)
def test_personal_stays_out_of_git() -> None:
    import subprocess

    out = subprocess.run(
        ["git", "check-ignore", "library/packages/personal/manifest.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0
