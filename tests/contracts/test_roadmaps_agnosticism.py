"""Roadmaps P10 - provider/model/harness agnosticism (DEC-0043, DEC-0085).

The Roadmap domain describes work, never who or what performs it. Provider, model
and harness identity belong to the Agent/Runtime layers (joinable through
`agent_id`). Two cheap, stable guards: no Roadmap contract field carries that
identity, and no Roadmap domain source names a vendor or product."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from pydantic import BaseModel
from studio_contracts import initialization, roadmaps

ROOT = Path(__file__).resolve().parents[2]

DOMAIN_SOURCES = (
    "packages/studio-contracts/src/studio_contracts/roadmaps.py",
    "packages/studio-contracts/src/studio_contracts/initialization.py",
    "services/api/src/studio_api/db/models/roadmap.py",
    "services/api/src/studio_api/routers/roadmaps.py",
    "services/api/src/studio_api/routers/initialization.py",
    "services/api/src/studio_api/services/roadmaps.py",
    "services/api/src/studio_api/services/roadmap_support.py",
    "services/api/src/studio_api/services/roadmap_structure.py",
    "services/api/src/studio_api/services/roadmap_hydration.py",
    "services/api/src/studio_api/services/roadmap_port.py",
    "services/api/src/studio_api/services/project_context_roadmap.py",
    "services/api/src/studio_api/services/initialization.py",
    "services/mcp/src/studio_mcp/tools/roadmaps.py",
    "services/mcp/src/studio_mcp/tools/initialization.py",
    "dashboard/src/roadmapApi.ts",
    "dashboard/src/roadmapData.ts",
    "dashboard/src/roadmapFormat.ts",
    "dashboard/src/roadmapTypes.ts",
    "dashboard/src/views/roadmap.ts",
)

VENDORS = re.compile(
    r"claude|anthropic|openai|chatgpt|\bgpt[-\d]|codex|opencode|qwen|gemini|kimi|mistral|"
    r"llama|ollama|copilot|cursor",
    re.IGNORECASE,
)
IDENTITY_FIELDS = {"harness", "provider", "model", "model_ref", "provider_ref", "harness_ref"}


def test_no_roadmap_domain_source_names_a_vendor_or_product() -> None:
    offenders = [
        f"{path}:{number}: {line.strip()}"
        for path in DOMAIN_SOURCES
        for number, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1)
        if VENDORS.search(line)
    ]
    assert offenders == []


def test_no_roadmap_contract_field_carries_provider_model_or_harness_identity() -> None:
    models = [
        obj
        for module in (roadmaps, initialization)
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BaseModel) and obj.__module__ == module.__name__
    ]
    assert len(models) > 20  # the scan really covered the contract surface
    # `RuntimeTarget` is the one place a *binding* legitimately names a runtime: a
    # Library binding of the initialization plan, not a Roadmap concept.
    allowed = {"InitializationBindingRef"}
    leaks = [
        f"{model.__name__}.{name}"
        for model in models
        if model.__name__ not in allowed
        for name in model.model_fields
        if name in IDENTITY_FIELDS
    ]
    assert leaks == []


def test_the_roadmap_document_rejects_agent_identity_smuggled_into_the_plan() -> None:
    document = {
        "format": "studio.roadmap/v1",
        "title": "Plan",
        "model": "any-model",
        "phases": [],
    }
    try:
        roadmaps.RoadmapDocument.model_validate(document)
    except ValueError:
        return
    raise AssertionError("an unknown `model` field must be rejected (extra=forbid)")
