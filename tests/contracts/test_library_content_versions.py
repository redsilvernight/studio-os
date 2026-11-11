from __future__ import annotations

from types import SimpleNamespace

import pytest
from studio_client.context.library import LibraryContextItem, LibraryContextProvider
from studio_contracts.library import (
    LibraryKind,
    RuleContent,
    RuleContentV2,
    SkillContent,
    SkillContentV2,
    content_validation_errors,
    parse_rule_content,
    parse_skill_content,
)

SKILL_V1 = {"content_schema": "studio.library.skill/v1", "text": "body"}
SKILL_V2 = {"content_schema": "studio.library.skill/v2", "text": "body"}
RULE_V2 = {"content_schema": "studio.library.rule/v2", "text": "body", "applies_to": ["src/**"]}


def test_skill_v2_flag_defaults_to_false_and_round_trips() -> None:
    assert content_validation_errors(LibraryKind.SKILL, SKILL_V2) == []
    parsed = parse_skill_content(SKILL_V2)
    assert isinstance(parsed, SkillContentV2) and parsed.disable_model_invocation is False
    flagged = parse_skill_content({**SKILL_V2, "disable_model_invocation": True})
    assert isinstance(flagged, SkillContentV2) and flagged.disable_model_invocation is True


def test_skill_v1_stays_valid_and_cannot_carry_the_flag() -> None:
    assert isinstance(parse_skill_content(SKILL_V1), SkillContent)
    errors = content_validation_errors(
        LibraryKind.SKILL, {**SKILL_V1, "disable_model_invocation": True}
    )
    assert errors


def test_skill_v2_rejects_unknown_keys_and_bad_files() -> None:
    assert content_validation_errors(LibraryKind.SKILL, {**SKILL_V2, "model": "x"})
    bad_file = {"path": "../x.md", "text": "t", "sha256": "0" * 64}
    assert content_validation_errors(LibraryKind.SKILL, {**SKILL_V2, "files": [bad_file]})


def test_parse_rule_content_reads_both_versions() -> None:
    assert isinstance(parse_rule_content(RULE_V2), RuleContentV2)
    v1 = parse_rule_content({"content_schema": "studio.library.rule/v1", "text": "t"})
    assert isinstance(v1, RuleContent)


@pytest.mark.parametrize(
    ("kind", "content", "flag"),
    [
        ("rule", RULE_V2, False),
        ("skill", SKILL_V2, False),
        ("skill", {**SKILL_V2, "disable_model_invocation": True}, True),
    ],
)
def test_context_item_reads_v2_contents(kind: str, content: dict[str, object], flag: bool) -> None:
    resource = SimpleNamespace(kind=kind, stable_key="k", scope="project", status="active")
    row = SimpleNamespace(content=content, title="t", description=None)
    item = LibraryContextProvider._to_item(resource, row, 1, "active")
    assert isinstance(item, LibraryContextItem)
    assert item.text == "body" and item.disable_model_invocation is flag


@pytest.mark.parametrize(("flag", "expected"), [(True, True), (False, False)])
def test_projection_source_emits_the_invocation_flag(flag: bool, expected: bool) -> None:
    from studio_client.projection_source import _skill_source

    skill = SimpleNamespace(
        stable_key="k", title="t", content={**SKILL_V2, "disable_model_invocation": flag}
    )
    assert ("disable-model-invocation: true" in _skill_source(skill)) is expected  # type: ignore[arg-type]
