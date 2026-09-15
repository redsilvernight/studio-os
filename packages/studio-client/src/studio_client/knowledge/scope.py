from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from studio_client.knowledge.errors import KnowledgeError


@dataclass(frozen=True)
class ScopePolicy:
    """Closed-by-default exposure policy for the local vault (DEC-0042).

    `allowed_prefixes` holds vault-relative directory prefixes
    (`"projects/my-slug/"`, `"conventions/"`, ...). The default — empty —
    exposes nothing: privacy of the developer's memory holds by
    construction, not by convention. `TECH/09` levels map as:
    `project` ↔ `projects/<slug>/`, `studio` ↔ `global/` + `conventions/`,
    `private` ↔ anything unlisted (see DEC-0042 for the full table).
    """

    allowed_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(self._normalize(prefix) for prefix in self.allowed_prefixes)
        object.__setattr__(self, "allowed_prefixes", normalized)

    @staticmethod
    def _normalize(prefix: str) -> str:
        cleaned = prefix.strip().replace("\\", "/").strip("/")
        return f"{cleaned}/" if cleaned else ""

    def _active(self) -> tuple[str, ...]:
        return tuple(p for p in self.allowed_prefixes if p)

    def is_exposed(self, relative_posix: str) -> bool:
        """True when a vault-relative posix path sits under an allowed prefix."""
        rel = relative_posix.strip().replace("\\", "/").lstrip("/")
        return any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in self._active())

    def resolve(self, vault_root: Path, requested: str) -> Path:
        """Resolve a caller-supplied path to an in-scope absolute path.

        `..` escapes, absolute paths and symlinks resolving outside the
        vault or outside the allowed prefixes raise
        `KnowledgeError(OUT_OF_SCOPE)`. Resolution is lexical plus symlink
        resolution (`Path.resolve()`), so a symlink planted inside an
        allowed directory but pointing at private memory is refused, not
        followed. Missing files resolve fine — existence is the caller's
        check (`NOT_FOUND`), scope is this method's.
        """
        if Path(requested).is_absolute():
            raise KnowledgeError(
                KnowledgeError.OUT_OF_SCOPE, f"absolute path refused: {requested!r}"
            )
        root = vault_root.resolve()
        candidate = (root / requested).resolve()
        if candidate != root and root not in candidate.parents:
            raise KnowledgeError(
                KnowledgeError.OUT_OF_SCOPE, f"path escapes the vault: {requested!r}"
            )
        rel = candidate.relative_to(root).as_posix()
        if rel != "." and not self.is_exposed(rel):
            raise KnowledgeError(
                KnowledgeError.OUT_OF_SCOPE, f"path outside the exposed scope: {requested!r}"
            )
        return candidate

    def exposed_files(self, vault_root: Path, suffix: str = ".md") -> list[Path]:
        """All in-scope files under the vault, sorted for determinism.

        Symlink escapes are skipped silently (search degrades, never leaks);
        a refusal here means "not exposable", not "caller error".
        """
        root = vault_root.resolve()
        found: set[Path] = set()
        for prefix in self._active():
            base = (root / prefix.rstrip("/")).resolve()
            if base != root and root not in base.parents:
                continue
            if not base.is_dir():
                continue
            for path in sorted(base.rglob(f"*{suffix}")):
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if resolved != root and root not in resolved.parents:
                    continue
                if self.is_exposed(resolved.relative_to(root).as_posix()) and resolved.is_file():
                    found.add(resolved)
        return sorted(found)
