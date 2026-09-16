from __future__ import annotations


class ContextError(Exception):
    """Structured failure for local Context Package composition (DEC-0057).

    Errors are machine-readable through `reason` and human-readable through
    `message`. No network error ever propagates as an untyped exception.
    """

    VAULT_MISSING = "vault_missing"
    GRAPH_MISSING = "graph_missing"
    SERVER_UNREACHABLE = "server_unreachable"
    INVALID_PROJECT = "invalid_project"
    BUDGET_EXCEEDED = "budget_exceeded"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
