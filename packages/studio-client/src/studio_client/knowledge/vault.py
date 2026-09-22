from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from studio_client.knowledge.errors import KnowledgeError

VAULT_SCHEMA_VERSION = 1
VAULT_METADATA_DIR = ".studio"
VAULT_METADATA_FILE = "vault.json"
VAULT_README = "README.md"

CANONICAL_DIRECTORIES: tuple[str, ...] = ("projects", "global", "conventions", "templates")
"""Structure canonique minimale du Vault. `projects/<slug>/` porte la mémoire
projet, `global/` et `conventions/` la mémoire studio (DEC-0042), `templates/`
est un échafaudage jamais exposé par défaut. Rien de propriétaire : ce sont des
dossiers Markdown ordinaires, et un Vault existant n'est jamais réorganisé."""

DEFAULT_EXPOSED_PREFIXES: tuple[str, ...] = ("projects/", "global/", "conventions/")
"""Portée par défaut d'un Vault Studi'OS, alignée sur DEC-0042. Un Vault
connecté mais non Studi'OS garde la portée fermée par défaut (`()`)."""

INDEX_IGNORED_DIRECTORIES: frozenset[str] = frozenset(
    {
        VAULT_METADATA_DIR,
        ".obsidian",
        ".git",
        ".trash",
        "node_modules",
        "__pycache__",
    }
)
"""Dossiers jamais indexés : métadonnées Studi'OS, configuration de l'éditeur
Markdown optionnel, VCS, corbeilles et caches. Un dossier caché est ignoré
par défaut, jamais supprimé ni modifié."""

DEFAULT_INCLUDE_GLOBS: tuple[str, ...] = ("**/*.md",)
DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = ()

_README_CONTENT = (
    "# Vault\n"
    "\n"
    "Ce dossier contient de la mémoire au format Markdown. Studi'OS le lit et\n"
    "l'indexe localement ; il ne le réécrit jamais et n'envoie rien au serveur.\n"
    "Les fichiers restent utilisables sans Studi'OS et sans éditeur particulier.\n"
)


class VaultState(StrEnum):
    MISSING = "missing"
    NOT_A_DIRECTORY = "not_a_directory"
    INACCESSIBLE = "inaccessible"
    EMPTY = "empty"
    MARKDOWN_EXISTING = "markdown_existing"
    STUDIOS_VAULT = "studios_vault"


@dataclass(frozen=True)
class VaultFile:
    relative_path: str
    absolute_path: Path
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class VaultInitReport:
    """Résultat d'une initialisation. `created` et `skipped` disent exactement
    ce qui a été écrit ; rien n'est jamais écrasé."""

    root: Path
    state_before: VaultState
    created: tuple[str, ...]
    skipped: tuple[str, ...]


def _compile_glob(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern.startswith("**/", index):
                parts.append("(?:.*/)?")
                index += 3
                continue
            if pattern.startswith("**", index):
                parts.append(".*")
                index += 2
                continue
            parts.append("[^/]*")
            index += 1
            continue
        if char == "?":
            parts.append("[^/]")
            index += 1
            continue
        parts.append(re.escape(char))
        index += 1
    return re.compile("^" + "".join(parts) + "$")


def matches_globs(relative_posix: str, patterns: Sequence[str]) -> bool:
    return any(_compile_glob(pattern).match(relative_posix) is not None for pattern in patterns)


def _is_hidden(relative_posix: str) -> bool:
    return any(part.startswith(".") for part in relative_posix.split("/"))


def iter_markdown(
    root: Path,
    *,
    include_globs: Sequence[str] = DEFAULT_INCLUDE_GLOBS,
    exclude_globs: Sequence[str] = DEFAULT_EXCLUDE_GLOBS,
) -> Iterator[VaultFile]:
    """Markdown files of the vault, sorted, minus ignored and excluded paths."""
    if not root.is_dir():
        return
    found: list[VaultFile] = []
    for directory, subdirectories, filenames in os.walk(root):
        current = Path(directory)
        subdirectories[:] = sorted(
            name
            for name in subdirectories
            if name not in INDEX_IGNORED_DIRECTORIES and not name.startswith(".")
        )
        for filename in sorted(filenames):
            if not filename.lower().endswith(".md"):
                continue
            absolute = current / filename
            try:
                relative = absolute.relative_to(root).as_posix()
            except ValueError:
                continue
            if _is_hidden(relative):
                continue
            if not matches_globs(relative, include_globs):
                continue
            if exclude_globs and matches_globs(relative, exclude_globs):
                continue
            try:
                stat = absolute.stat()
            except OSError:
                continue
            if not absolute.is_file():
                continue
            found.append(
                VaultFile(
                    relative_path=relative,
                    absolute_path=absolute,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                )
            )
    yield from sorted(found, key=lambda item: item.relative_path)


def vault_state(root: Path) -> VaultState:
    if not root.exists():
        return VaultState.MISSING
    if not root.is_dir():
        return VaultState.NOT_A_DIRECTORY
    try:
        entries = list(os.scandir(root))
    except OSError:
        return VaultState.INACCESSIBLE
    if (root / VAULT_METADATA_DIR / VAULT_METADATA_FILE).is_file():
        return VaultState.STUDIOS_VAULT
    if not entries:
        return VaultState.EMPTY
    if any(item.is_file() and item.name.lower().endswith(".md") for item in entries):
        return VaultState.MARKDOWN_EXISTING
    if any(item.is_dir() and item.name not in INDEX_IGNORED_DIRECTORIES for item in entries):
        return VaultState.MARKDOWN_EXISTING
    return VaultState.EMPTY


def is_readable_directory(root: Path) -> bool:
    try:
        with os.scandir(root):
            return True
    except OSError:
        return False


def _ensure_directory(root: Path, relative: str) -> tuple[bool, str]:
    target = root / relative
    if target.exists():
        return False, relative
    target.mkdir(parents=True, exist_ok=True)
    return True, relative


def _ensure_file(path: Path, content: str) -> bool:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    except FileExistsError:
        return False
    return True


def initialize_vault(
    root: Path,
    *,
    extra_directories: Sequence[str] = (),
    write_readme: bool = True,
) -> VaultInitReport:
    """Create the missing canonical scaffolding of a vault, never overwriting.

    A non-empty Markdown folder is connected as-is: only absent directories and
    files are created, an existing `README.md` or `vault.json` is left
    untouched. Existing user files are never reformatted, moved or deleted."""
    state_before = vault_state(root)
    if state_before is VaultState.NOT_A_DIRECTORY:
        raise KnowledgeError(
            KnowledgeError.VAULT_NOT_A_DIRECTORY, "the vault path is not a directory"
        )
    root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    skipped: list[str] = []
    for relative in (*CANONICAL_DIRECTORIES, *extra_directories):
        was_created, name = _ensure_directory(root, relative)
        (created if was_created else skipped).append(name)
    metadata_created, metadata_name = _ensure_directory(root, VAULT_METADATA_DIR)
    (created if metadata_created else skipped).append(metadata_name)
    metadata = root / VAULT_METADATA_DIR / VAULT_METADATA_FILE
    if _ensure_file(
        metadata, json.dumps({"schema_version": VAULT_SCHEMA_VERSION}, indent=2) + "\n"
    ):
        created.append(f"{VAULT_METADATA_DIR}/{VAULT_METADATA_FILE}")
    else:
        skipped.append(f"{VAULT_METADATA_DIR}/{VAULT_METADATA_FILE}")
    if write_readme:
        if _ensure_file(root / VAULT_README, _README_CONTENT):
            created.append(VAULT_README)
        else:
            skipped.append(VAULT_README)
    return VaultInitReport(
        root=root,
        state_before=state_before,
        created=tuple(sorted(created)),
        skipped=tuple(sorted(skipped)),
    )


def read_markdown(absolute_path: Path) -> str:
    return absolute_path.read_text(encoding="utf-8")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vault_fingerprint(
    root: Path,
    *,
    include_globs: Sequence[str] = DEFAULT_INCLUDE_GLOBS,
    exclude_globs: Sequence[str] = DEFAULT_EXCLUDE_GLOBS,
) -> str:
    """Cheap freshness fingerprint: sorted (path, size, mtime_ns) of the vault.

    Content hashes are used per document during a reindex; the fingerprint only
    answers "did anything change since the index was built" without reading every
    file on each status call."""
    digest = hashlib.sha256()
    for item in iter_markdown(root, include_globs=include_globs, exclude_globs=exclude_globs):
        digest.update(item.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.size_bytes).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item.mtime_ns).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()
