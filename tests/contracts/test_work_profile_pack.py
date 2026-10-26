from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from studio_contracts.work_profile_pack import WorkProfilePack


def _pack() -> dict[str, object]:
    return {
        "format": "studio.work-profile-pack/v1",
        "profile": {"stable_key": "example", "title": "Example", "agent_stable_key": "base"},
        "base": {
            "resource_id": str(uuid4()),
            "kind": "agent_definition",
            "stable_key": "base",
            "version": 1,
        },
    }


def test_pack_reuses_work_profile_and_has_no_definition_content() -> None:
    pack = WorkProfilePack.model_validate(_pack())
    assert pack.profile.agent_stable_key == "base"
    assert pack.adaptations == []
    assert "content" not in pack.model_dump()


@pytest.mark.parametrize(
    "override",
    [
        {"format": "studio.work-profile-pack/v99"},
        {"content": {"text": "not allowed"}},
        {"adaptations": [{}]},
        {"profile": {"stable_key": "x", "title": "x", "agent_stable_key": "wrong"}},
    ],
)
def test_unknown_incompatible_or_content_bearing_pack_is_refused(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        WorkProfilePack.model_validate({**_pack(), **override})


def test_format_is_required_and_duplicate_references_are_rejected() -> None:
    raw = _pack()
    raw.pop("format")
    with pytest.raises(ValidationError):
        WorkProfilePack.model_validate(raw)
    raw = _pack()
    raw["adaptations"] = [raw["base"]]
    with pytest.raises(ValidationError):
        WorkProfilePack.model_validate(raw)
