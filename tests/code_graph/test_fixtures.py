from __future__ import annotations

import pytest
from studio_code_graph import FIXTURE_NAMES, all_fixtures, build_fixture
from studio_contracts.local.common import ComponentState, LocalErrorCode
from studio_contracts.local.graph import NodeKind, RelationKind
from studio_contracts.local.provider import IndexState

REQUIRED = {
    "empty",
    "small",
    "files",
    "functions",
    "imports",
    "calls",
    "contains",
    "partial",
    "stale",
    "indexing",
    "provider_absent",
    "error",
    "corrupt",
}


def test_every_required_fixture_exists() -> None:
    assert REQUIRED <= set(FIXTURE_NAMES)
    assert list(all_fixtures()) == list(FIXTURE_NAMES)


def test_unknown_fixture_is_rejected() -> None:
    with pytest.raises(KeyError):
        build_fixture("nope")


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_is_deterministic_and_contract_valid(name: str) -> None:
    first, second = build_fixture(name), build_fixture(name)
    assert first == second
    assert first.status.model_dump_json() == second.status.model_dump_json()
    if first.page is not None:
        type(first.page).model_validate_json(first.page.model_dump_json())
    type(first.symbols).model_validate_json(first.symbols.model_dump_json())


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_data_is_code_sourced_with_provenance(name: str) -> None:
    fixture = build_fixture(name)
    if fixture.page is None:
        return
    for node in fixture.page.nodes:
        assert node.uri and node.provenance.source_id and node.node_id
    for edge in fixture.page.edges:
        assert edge.provenance.source_id and edge.edge_id


def test_states_are_the_declared_ones() -> None:
    expected = {
        "empty": ComponentState.READY,
        "small": ComponentState.READY,
        "partial": ComponentState.READY,
        "stale": ComponentState.STALE,
        "indexing": ComponentState.INDEXING,
        "provider_absent": ComponentState.NOT_INSTALLED,
        "error": ComponentState.ERROR,
        "corrupt": ComponentState.ERROR,
    }
    for name, state in expected.items():
        assert build_fixture(name).status.state is state, name


def test_error_fixtures_carry_the_matching_codes() -> None:
    absent = build_fixture("provider_absent").status.error
    assert absent is not None and absent.code is LocalErrorCode.PROVIDER_NOT_INSTALLED
    corrupt = build_fixture("corrupt").status
    assert corrupt.error is not None and corrupt.error.code is LocalErrorCode.INDEX_CORRUPT


def test_empty_and_small_content() -> None:
    assert build_fixture("empty").page is not None
    assert build_fixture("empty").page.nodes == []  # type: ignore[union-attr]
    small = build_fixture("small").page
    assert small is not None
    kinds = {node.kind for node in small.nodes}
    assert {NodeKind.FILE, NodeKind.CLASS, NodeKind.FUNCTION} <= kinds
    assert {edge.kind for edge in small.edges} >= {
        RelationKind.CONTAINS,
        RelationKind.IMPORTS,
        RelationKind.CALLS,
    }


def test_relation_specific_fixtures_hold_only_their_relation() -> None:
    for name, relation in (
        ("imports", RelationKind.IMPORTS),
        ("calls", RelationKind.CALLS),
        ("contains", RelationKind.CONTAINS),
    ):
        page = build_fixture(name).page
        assert page is not None and page.edges
        assert {edge.kind for edge in page.edges} == {relation}, name


def test_symbols_of_incomplete_indexes_are_marked_incomplete() -> None:
    for name in ("stale", "indexing", "provider_absent", "error", "corrupt"):
        fixture = build_fixture(name)
        if fixture.symbols.index_state is not IndexState.READY:
            assert fixture.symbols.complete is False, name
