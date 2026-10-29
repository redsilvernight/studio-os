from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
from studio_contracts.library import LibraryKind
from studio_contracts.profiles import ProfileElement, profile_digest, reference_work_profile


def test_v2_distinguishes_resources_with_the_same_key_version_and_origin() -> None:
    profile = reference_work_profile("coding", "developer")
    first = ProfileElement(
        kind=LibraryKind.AGENT_DEFINITION,
        stable_key="developer",
        version=1,
        origin="library",
        resource_id=uuid4(),
    )
    second = first.model_copy(update={"resource_id": uuid4()})
    assert profile_digest(profile, [first]) != profile_digest(profile, [second])
    assert profile_digest(profile, [first, second]) == profile_digest(profile, [second, first])


def test_v1_keeps_the_original_digest_bytes_when_read_by_v2() -> None:
    profile = reference_work_profile("coding", "developer", contract_version=1)
    element = ProfileElement(
        kind=LibraryKind.RULE,
        stable_key="standard",
        version=3,
        origin="library",
        resource_id=uuid4(),
    )
    legacy_body = {
        "profile": profile.model_dump(mode="json"),
        "elements": [["rule", "standard", 3, "library"]],
    }
    canonical = json.dumps(legacy_body, sort_keys=True, separators=(",", ":"))
    expected = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    assert profile_digest(profile, [element]) == expected


def test_v2_refuses_unidentified_elements() -> None:
    element = ProfileElement(
        kind=LibraryKind.RULE, stable_key="standard", version=1, origin="library"
    )
    with pytest.raises(ValueError, match="requires resolved resource identities"):
        profile_digest(reference_work_profile("coding", "developer"), [element])
