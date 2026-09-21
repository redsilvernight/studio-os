from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError
from studio_contracts.local.common import (
    ComponentId,
    LocalError,
    LocalErrorCode,
    MetadataValue,
)

from studio_code_graph.provider import BuildFailure, CodeGraphBuildError

_FALLBACK_MESSAGE = "code graph operation failed"


def make_error(
    code: LocalErrorCode,
    message: str,
    *,
    retryable: bool = False,
    details: Mapping[str, MetadataValue] | None = None,
) -> LocalError:
    """A `LocalError` reported by the code graph. Text that the contract refuses
    (an absolute path, secret-looking material) is replaced by a neutral message
    rather than surfaced."""
    for candidate in (message, _FALLBACK_MESSAGE):
        for extra in (dict(details or {}), {}):
            try:
                return LocalError(
                    code=code,
                    message=candidate,
                    component=ComponentId.CODE_GRAPH,
                    retryable=retryable,
                    details=extra,
                )
            except ValidationError:
                continue
    raise RuntimeError("unreachable")


_BUILD_FAILURE_CODES: dict[BuildFailure, tuple[LocalErrorCode, bool]] = {
    BuildFailure.TIMEOUT: (LocalErrorCode.TIMEOUT, True),
    BuildFailure.CANCELLED: (LocalErrorCode.CANCELLED, True),
    BuildFailure.PROCESS_FAILED: (LocalErrorCode.INTERNAL_ERROR, True),
    BuildFailure.OUTPUT_MISSING: (LocalErrorCode.INTERNAL_ERROR, True),
    BuildFailure.OUTPUT_CORRUPT: (LocalErrorCode.INDEX_CORRUPT, True),
    BuildFailure.NOT_AVAILABLE: (LocalErrorCode.INTERNAL_ERROR, True),
}


def build_failure_error(error: CodeGraphBuildError, repo_name: str) -> LocalError:
    code, retryable = _BUILD_FAILURE_CODES[error.failure]
    message = f"code graph provider failed: {error.failure.value}"
    if error.detail:
        message = f"{message} ({error.detail})"
    return make_error(
        code,
        message,
        retryable=retryable,
        details={"repo": repo_name, "failure": error.failure.value},
    )


class CodeGraphQueryError(Exception):
    """A query the code graph cannot serve; carries the structured error the
    daemon returns to the caller."""

    def __init__(self, error: LocalError) -> None:
        super().__init__(error.message)
        self.error = error
