from __future__ import annotations

from pydantic import BaseModel
from studio_contracts.ai_work import AIWorkLog
from studio_contracts.claims import ResourceClaim
from studio_contracts.decisions import Decision
from studio_contracts.events import EventEnvelope
from studio_contracts.projects import Project
from studio_contracts.tasks import Task
from studio_contracts.transfers import Transfer

from tests.conftest import load_fixture

FIXTURE_MODELS: dict[str, type[BaseModel]] = {
    "projects": Project,
    "tasks": Task,
    "claims": ResourceClaim,
    "decisions": Decision,
    "ai_work": AIWorkLog,
    "transfers": Transfer,
    "events": EventEnvelope,
}


def test_every_fixture_file_is_mapped() -> None:
    from tests.conftest import FIXTURES_DIR

    fixture_names = {p.stem for p in FIXTURES_DIR.glob("*.json")}
    assert fixture_names == set(FIXTURE_MODELS)


def test_fixtures_validate_against_contracts() -> None:
    for name, model in FIXTURE_MODELS.items():
        items = load_fixture(name)
        assert items, f"{name}.json is empty"
        for item in items:
            model.model_validate(item)
