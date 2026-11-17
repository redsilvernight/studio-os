"""Three-way Library merge for local client consumers."""

from studio_contracts.library_merge import (
    CONFLICT_END,
    CONFLICT_SEPARATOR,
    CONFLICT_START,
    MergeConflict,
    MergeResult,
    merge_texts,
)

__all__ = [
    "CONFLICT_END",
    "CONFLICT_SEPARATOR",
    "CONFLICT_START",
    "MergeConflict",
    "MergeResult",
    "merge_texts",
]
