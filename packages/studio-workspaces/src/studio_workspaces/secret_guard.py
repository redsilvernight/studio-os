from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from studio_contracts.local.common import contains_secret_material, is_secret_key_name

REFERENCE_FIELDS = frozenset({"ref_id", "kind", "store", "lookup_key", "profile"})
PROFILE_FIELDS = frozenset({"profile_id", "server_origin"})


class SecretMaterialError(ValueError):
    pass


def _walk(node: Any, trail: str, issues: list[str]) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            here = f"{trail}.{key}" if trail else str(key)
            if key == "secret_references" and isinstance(value, list):
                for index, ref in enumerate(value):
                    _walk_reference(ref, f"{here}[{index}]", issues)
                continue
            if isinstance(key, str) and is_secret_key_name(key):
                issues.append(here)
                continue
            _walk(value, here, issues)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _walk(item, f"{trail}[{index}]", issues)
    elif isinstance(node, str):
        if contains_secret_material(node):
            issues.append(trail)


def _walk_reference(ref: Any, trail: str, issues: list[str]) -> None:
    if not isinstance(ref, Mapping):
        issues.append(trail)
        return
    for key in ref:
        if key not in REFERENCE_FIELDS:
            issues.append(f"{trail}.{key}")
    profile = ref.get("profile")
    if isinstance(profile, Mapping):
        for key in profile:
            if key not in PROFILE_FIELDS:
                issues.append(f"{trail}.profile.{key}")
    for key in ("ref_id", "lookup_key"):
        value = ref.get(key)
        if isinstance(value, str) and contains_secret_material(value):
            issues.append(f"{trail}.{key}")


def find_secret_issues(data: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    _walk(data, "", issues)
    return issues


def assert_no_secrets(data: Mapping[str, Any]) -> None:
    issues = find_secret_issues(data)
    if issues:
        raise SecretMaterialError(f"secret-shaped data at: {sorted(issues)}")


def scan_studio_dir(root: Path) -> list[str]:
    studio_dir = root / ".studio"
    if not studio_dir.is_dir():
        return []
    issues: list[str] = []
    for child in sorted(studio_dir.rglob("*")):
        if not child.is_file():
            continue
        try:
            text = child.read_text(encoding="utf-8")
        except OSError:
            issues.append(f"{child.name}: unreadable")
            continue
        try:
            data = json.loads(text)
        except ValueError:
            if contains_secret_material(text):
                issues.append(f"{child.name}: secret-shaped text")
            continue
        if isinstance(data, Mapping):
            for issue in find_secret_issues(data):
                issues.append(f"{child.name}:{issue}")
        elif isinstance(text, str) and contains_secret_material(text):
            issues.append(f"{child.name}: secret-shaped text")
    return issues
