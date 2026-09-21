"""P2 context contract — canonical shape, budget semantics, neutrality.

Pure tests: only `studio_contracts` (pydantic) plus static source checks, so
they run without a database. Anything needing rows lives in
`tests/mcp/test_prepare_context_aiwork.py` (CI).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import studio_contracts.project_context as ctx

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "services/api/src/studio_api/services/project_context.py"
ROADMAP_SERVICE = ROOT / "services/api/src/studio_api/services/project_context_roadmap.py"


def test_canonical_module_defines_budget_constants():
    assert ctx.DEFAULT_MAX_CHARS == 12_000
    assert (ctx.MIN_MAX_CHARS, ctx.MAX_MAX_CHARS) == (1_000, 50_000)
    assert ctx.ITEM_TEXT_CAP == 1_500
    assert ctx.MIN_TEXT_CHARS == 200
    assert ctx.ROADMAP_BUDGET_SHARE == 0.25
    assert ctx.AIWORK_BUDGET_SHARE == 0.15
    assert ctx.AIWORK_LIST_CAP == 10
    assert ctx.DEFAULT_LIMIT == 5 and ctx.MAX_LIMIT == 20


def test_budget_counts_characters_not_bytes_or_tokens():
    text = "café 🎯" + "x" * 100
    assert len(text) == 106  # Unicode scalar values — the contract unit
    assert len(text.encode("utf-8")) > len(text)  # bytes differ: Bloc B's unit, not ours
    assert "tokenizer" in (ctx.__doc__ or "").lower()


def test_service_defines_no_competing_models():
    for path in (SERVICE, ROADMAP_SERVICE):
        src = path.read_text(encoding="utf-8")
        own = re.findall(r"^class \w+\(BaseModel\)", src, re.MULTILINE)
        assert own == [], f"{path.name} redefines models: {own}"


def test_service_reexports_canonical_names():
    src = SERVICE.read_text(encoding="utf-8")
    for name in (
        "PreparedContext",
        "AIWorkItem",
        "DEFAULT_LIMIT",
        "DEFAULT_MAX_CHARS",
        "prepare_project_context",
    ):
        assert name in src, f"service lost back-compat name: {name}"
    assert "__all__" in src


def test_why_reasons_unchanged():
    assert set(ctx.Reason.__args__) == {
        "requested",
        "linked_to_task",
        "task_claim",
        "path_conflict",
        "project_scope",
        "lexical",
        "active_roadmap",
    }


def test_prepared_context_additive_and_minimal():
    import uuid

    base = ctx.PreparedContext(
        project=ctx.ProjectRef(id=uuid.uuid4(), slug="s", name="n"),
        query_terms=["x"],
        returned={},
        additional_available={},
        limits=ctx.ContextLimits(limit=5, max_chars=12_000, chars_used=0, item_text_cap=1_500),
    )
    dumped = base.model_dump(mode="json")
    assert base.ai_work == []
    assert "roadmap" not in dumped and "unavailable" not in dumped

    item = ctx.AIWorkItem(
        id=uuid.uuid4(),
        status="completed",
        summary="DONE .. NEXT ..",
        started_at=datetime.now(UTC),
        why=ctx.Why(reason="linked_to_task"),
    )
    full = base.model_copy(update={"ai_work": [item]})
    assert full.model_dump(mode="json")["ai_work"][0]["why"]["reason"] == "linked_to_task"


def test_canonical_contract_names_no_vendor_or_model():
    contract = ROOT / "packages/studio-contracts/src/studio_contracts/project_context.py"
    lowered = contract.read_text(encoding="utf-8").lower()
    for token in ("opus", "sonnet", "gpt-", "kimi", "anthropic", "openai", "claude-code"):
        assert token not in lowered, f"contract leaks {token!r}"
