"""`studio_start_work` contract shapes (L2): request/response defaults,
required fields, compactness of candidates, and the UC-2B hygiene rule —
no numbered `DEC-` reference in any schema description (such docstrings
propagate into OpenAPI). No DB, no app."""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from pydantic import ValidationError
from studio_contracts.project_context import DEFAULT_LIMIT, DEFAULT_MAX_CHARS
from studio_contracts.start_work import (
    StartWorkCandidate,
    StartWorkRequest,
    StartWorkResult,
)
from studio_contracts.tasks import TaskStatus


def _ids() -> dict[str, str]:
    return {"project_id": str(uuid4()), "agent_id": str(uuid4())}


def test_request_defaults_match_prepare_bounds() -> None:
    request = StartWorkRequest(**_ids())
    assert request.task_id is None
    assert request.objective is None
    assert request.agent_stable_key is None
    assert request.files is None
    assert request.limit == DEFAULT_LIMIT
    assert request.max_chars == DEFAULT_MAX_CHARS


def test_request_requires_project_and_agent() -> None:
    with pytest.raises(ValidationError):
        StartWorkRequest(agent_id=uuid4())
    with pytest.raises(ValidationError):
        StartWorkRequest(project_id=uuid4())


def test_request_forbids_foreign_fields() -> None:
    with pytest.raises(ValidationError):
        StartWorkRequest(**_ids(), machine_id=str(uuid4()))


def test_request_enforces_prepare_bounds() -> None:
    with pytest.raises(ValidationError):
        StartWorkRequest(**_ids(), objective="x" * 1001)
    with pytest.raises(ValidationError):
        StartWorkRequest(**_ids(), files=[f"f{n}.py" for n in range(21)])
    assert StartWorkRequest(**_ids(), files=[f"f{n}.py" for n in range(20)]).files is not None


def test_candidate_is_compact() -> None:
    candidate = StartWorkCandidate(task_id=uuid4(), title="Do it", status=TaskStatus.CREATED)
    assert candidate.model_dump() == {
        "task_id": candidate.task_id,
        "title": "Do it",
        "status": TaskStatus.CREATED,
    }
    with pytest.raises(ValidationError):
        StartWorkCandidate(task_id=uuid4(), title="Do it", status="created", description="x")


def test_result_defaults_to_no_task_path() -> None:
    result = StartWorkResult()
    assert result.task is None
    assert result.session is None
    assert result.claimed is False
    assert result.resumed is False
    assert result.prepared_context is None
    assert result.candidates == []


def test_result_json_round_trip_with_candidates() -> None:
    result = StartWorkResult(
        candidates=[StartWorkCandidate(task_id=uuid4(), title="Next", status=TaskStatus.CREATED)]
    )
    assert StartWorkResult.model_validate_json(result.model_dump_json()).candidates == (
        result.candidates
    )


def _descriptions(schema: dict) -> list[str]:
    found = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "description" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_descriptions(value) if isinstance(value, (dict, list)) else [])
    elif isinstance(schema, list):
        for item in schema:
            found.extend(_descriptions(item) if isinstance(item, (dict, list)) else [])
    return found


@pytest.mark.parametrize("shape", [StartWorkRequest, StartWorkCandidate, StartWorkResult])
def test_no_numbered_decision_leaks_into_schema(shape: type) -> None:
    for description in _descriptions(shape.model_json_schema()):
        assert not re.search(r"dec-\d", description.lower()), description
