from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from studio_code_graph.graphify.translate import TranslationContext, translate_graph
from studio_code_graph.provider import BuildFailure, CodeGraphBuildError
from studio_contracts.local.graph import Confidence, NodeKind, RelationKind

from .support import WORKSPACE_ID


def context(tmp_path: Path, **overrides: Any) -> TranslationContext:
    values: dict[str, Any] = {
        "workspace_id": WORKSPACE_ID,
        "repo_name": "app",
        "repo_root": tmp_path,
        "source_id": "code.graphify",
        "provider_id": "graphify",
    }
    values.update(overrides)
    return TranslationContext(**values)


def node(
    node_id: str, label: str, path: str, *, kind: str | None = None, line: str | None = None
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": node_id,
        "label": label,
        "file_type": "code",
        "source_file": path,
        "source_location": line,
    }
    if kind == "class":
        raw["_callable_class"] = True
    elif kind == "function":
        raw["_callable"] = True
    return raw


def link(source: str, target: str, relation: str, confidence: str = "EXTRACTED") -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "confidence": confidence,
        "source_location": "L4",
    }


def sample() -> dict[str, Any]:
    return {
        "nodes": [
            node("f_main", "main.py", "src/main.py"),
            node("f_util", "util.py", "src/util.py"),
            node("c_greeter", "Greeter", "src/util.py", kind="class", line="L1"),
            node("m_greet", ".greet()", "src/util.py", kind="function", line="L2"),
            node("fn_helper", "helper()", "src/util.py", kind="function", line="L5"),
            node("fn_main", "main()", "src/main.py", kind="function", line="L3"),
        ],
        "links": [
            link("f_util", "c_greeter", "contains"),
            link("c_greeter", "m_greet", "method"),
            link("f_util", "fn_helper", "contains"),
            link("f_main", "fn_main", "contains"),
            link("f_main", "f_util", "imports_from"),
            link("fn_main", "fn_helper", "calls"),
            link("fn_main", "m_greet", "calls", "INFERRED"),
        ],
    }


def test_kinds_relations_and_provenance(tmp_path: Path) -> None:
    result = translate_graph(sample(), context(tmp_path))
    kinds = sorted(item.kind.value for item in result.nodes)
    assert kinds == ["class", "file", "file", "function", "function", "function"]
    assert {edge.kind for edge in result.edges} == {
        RelationKind.CONTAINS,
        RelationKind.IMPORTS,
        RelationKind.CALLS,
    }
    assert all(item.provenance.source_id == "code.graphify" for item in result.nodes)
    assert all(item.provenance.confidence is Confidence.EXTRACTED for item in result.nodes)
    assert all(item.provenance.extractor.startswith("graphify.") for item in result.nodes)
    assert result.languages == ("python",) and result.dropped == {}


def test_methods_are_qualified_and_uris_local(tmp_path: Path) -> None:
    result = translate_graph(sample(), context(tmp_path))
    labels = {item.label for item in result.nodes}
    assert {"Greeter", "Greeter.greet", "helper", "main", "src/main.py"} <= labels
    for item in result.nodes:
        assert item.uri is not None and item.uri.startswith("studio-local://code/")
        assert str(tmp_path) not in item.uri


def test_inferred_edges_carry_evidence_and_native_relation_is_kept(tmp_path: Path) -> None:
    result = translate_graph(sample(), context(tmp_path))
    inferred = [edge for edge in result.edges if edge.provenance.confidence is Confidence.INFERRED]
    assert len(inferred) == 1 and inferred[0].provenance.evidence
    imports = next(edge for edge in result.edges if edge.kind is RelationKind.IMPORTS)
    assert imports.metadata["native_relation"] == "imports_from"


def test_ids_are_stable_and_input_order_independent(tmp_path: Path) -> None:
    graph = sample()
    first = translate_graph(graph, context(tmp_path))
    graph["nodes"].reverse()
    graph["links"].reverse()
    second = translate_graph(graph, context(tmp_path))
    assert [n.node_id for n in first.nodes] == [n.node_id for n in second.nodes]
    assert [e.edge_id for e in first.edges] == [e.edge_id for e in second.edges]


def test_ids_survive_a_line_shift_of_an_unrelated_symbol(tmp_path: Path) -> None:
    first = translate_graph(sample(), context(tmp_path))
    graph = sample()
    for raw in graph["nodes"]:
        if raw["id"] == "fn_helper":
            raw["source_location"] = "L40"
    second = translate_graph(graph, context(tmp_path))
    assert {n.node_id for n in first.nodes} == {n.node_id for n in second.nodes}


def test_ids_differ_between_repos(tmp_path: Path) -> None:
    first = translate_graph(sample(), context(tmp_path, repo_name="one"))
    second = translate_graph(sample(), context(tmp_path, repo_name="two"))
    assert not {n.node_id for n in first.nodes} & {n.node_id for n in second.nodes}


def test_unsupported_facts_are_dropped_not_invented(tmp_path: Path) -> None:
    graph = sample()
    graph["nodes"] += [
        {"id": "ext", "label": "os.path", "file_type": "code", "source_file": ""},
        {"id": "doc", "label": "README", "file_type": "document", "source_file": "README.md"},
        {
            "id": "esc",
            "label": "x()",
            "file_type": "code",
            "source_file": "../x.py",
            "_callable": 1,
        },
        {
            "id": "hash",
            "label": "y()",
            "file_type": "code",
            "source_file": "a#b.py",
            "_callable": 1,
        },
        node("var", "CONSTANT", "src/util.py"),
        {"label": "no id"},
        "junk",
    ]
    graph["links"] += [
        link("fn_main", "ext", "calls"),
        link("fn_main", "fn_helper", "semantically_similar_to"),
        link("fn_main", "fn_helper", "references"),
        link("fn_main", "m_greet", "calls", "AMBIGUOUS"),
        link("fn_main", "fn_main", "contains"),
        link("f_main", "f_util", "imports_from"),
        "junk",
    ]
    result = translate_graph(graph, context(tmp_path))
    assert result.dropped == {
        "duplicate_edge": 1,
        "malformed_edge": 1,
        "malformed_node": 2,
        "non_code_node": 1,
        "self_containment": 1,
        "unreliable_edge": 1,
        "unresolved_external_edge": 1,
        "unresolved_external_node": 1,
        "unsafe_path": 2,
        "unsupported_node_kind": 1,
        "unsupported_relation": 2,
    }
    assert sum(1 for item in result.nodes if item.kind is NodeKind.FILE) == 2
    assert not any(item.label in {"x", "y", "CONSTANT", "os.path"} for item in result.nodes)


def test_language_and_glob_filters(tmp_path: Path) -> None:
    graph = sample()
    graph["nodes"].append(node("js", "app.js", "web/app.js"))
    only_python = translate_graph(graph, context(tmp_path, languages=("python",)))
    assert all(n.metadata["path"].endswith(".py") for n in only_python.nodes)
    assert only_python.dropped["excluded_by_config"] == 1
    excluded = translate_graph(graph, context(tmp_path, exclude_globs=("src/util.py",)))
    assert not any(n.metadata["path"] == "src/util.py" for n in excluded.nodes)
    included = translate_graph(graph, context(tmp_path, include_globs=("web/**",)))
    assert [n.metadata["path"] for n in included.nodes] == ["web/app.js"]


def test_dangling_edges_are_not_kept_after_filtering(tmp_path: Path) -> None:
    result = translate_graph(sample(), context(tmp_path, exclude_globs=("src/util.py",)))
    ids = {n.node_id for n in result.nodes}
    assert all(e.source.node_id in ids and e.target.node_id in ids for e in result.edges)


def test_duplicate_symbols_keep_distinct_ids(tmp_path: Path) -> None:
    graph = {
        "nodes": [
            node("a", "run()", "src/a.py", kind="function", line="L1"),
            node("b", "run()", "src/a.py", kind="function", line="L9"),
        ],
        "links": [],
    }
    result = translate_graph(graph, context(tmp_path))
    assert len({n.node_id for n in result.nodes}) == 2


@pytest.mark.parametrize("graph", [None, [], "text", 3, {"nodes": "x", "links": []}, {"nodes": []}])
def test_corrupt_shapes_are_refused(tmp_path: Path, graph: object) -> None:
    with pytest.raises(CodeGraphBuildError) as error:
        translate_graph(graph, context(tmp_path))
    assert error.value.failure is BuildFailure.OUTPUT_CORRUPT


def test_edges_key_is_accepted_as_an_alias_for_links(tmp_path: Path) -> None:
    graph = sample()
    graph["edges"] = graph.pop("links")
    assert translate_graph(graph, context(tmp_path)).edges


def test_empty_graph(tmp_path: Path) -> None:
    result = translate_graph({"nodes": [], "links": []}, context(tmp_path))
    assert result.nodes == [] and result.edges == [] and result.languages == ()
