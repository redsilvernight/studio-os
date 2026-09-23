from __future__ import annotations

import ast
import re
from pathlib import Path

import studio_code_graph

PACKAGE = Path(studio_code_graph.__file__).parent
ADAPTER = PACKAGE / "graphify"
NETWORK_MODULES = {
    "socket",
    "http",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "websockets",
}


def sources(exclude: Path | None = None) -> list[Path]:
    return [
        path
        for path in sorted(PACKAGE.rglob("*.py"))
        if exclude is None or exclude not in path.parents
    ]


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_graphify_is_confined_to_the_adapter_package() -> None:
    for path in sources(exclude=ADAPTER):
        text = path.read_text(encoding="utf-8")
        assert "graphify" not in imported_roots(path), path.name
        assert not re.search(r"studio_code_graph\.graphify", text), path.name
        assert "graph.json" not in text, path.name


def test_only_the_package_init_reexports_the_adapter() -> None:
    importers = [
        path.name
        for path in sources(exclude=ADAPTER)
        if "from studio_code_graph.graphify" in path.read_text(encoding="utf-8")
    ]
    assert importers == []


def test_the_adapter_never_imports_the_graphify_library() -> None:
    for path in ADAPTER.rglob("*.py"):
        assert "graphify" not in imported_roots(path), path.name


def test_the_provider_contract_does_not_mention_a_vendor() -> None:
    for name in ("provider.py", "service.py", "index.py", "store.py", "gitstate.py", "fixtures.py"):
        text = (PACKAGE / name).read_text(encoding="utf-8").lower()
        assert "graphify" not in text, name


def test_no_network_module_is_imported_anywhere() -> None:
    for path in sources():
        assert not imported_roots(path) & NETWORK_MODULES, path.name


def test_no_shell_is_ever_spawned() -> None:
    for path in sources():
        text = path.read_text(encoding="utf-8")
        assert "shell=True" not in text and "os.system" not in text, path.name
        assert "create_subprocess_shell" not in text, path.name


def test_the_package_has_no_developer_machine_path() -> None:
    for path in sources():
        text = path.read_text(encoding="utf-8")
        assert "E:\\" not in text and "E:/" not in text and "Graphify\\Studio" not in text, (
            path.name
        )


def test_only_the_adapter_runner_locator_and_git_state_spawn_processes() -> None:
    spawners = {
        path.name
        for path in sources()
        if imported_roots(path) & {"subprocess"}
        or "create_subprocess_exec" in path.read_text("utf-8")
    }
    assert spawners <= {"runner.py", "locator.py", "gitstate.py"}


def test_the_service_only_depends_on_the_provider_protocol() -> None:
    roots = imported_roots(PACKAGE / "service.py")
    assert "studio_client" not in roots
    text = (PACKAGE / "service.py").read_text(encoding="utf-8")
    for name in ("adapter", "locator", "runner", "translate"):
        assert name not in text
