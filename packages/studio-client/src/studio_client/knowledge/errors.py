from __future__ import annotations


class KnowledgeError(Exception):
    """Typed failure for the local knowledge providers (`memory`, `graph`).

    `reason` is machine-readable and stable; `message` is human detail.
    Degraded states (missing vault/graph, stale graph) are reported, never
    a bare `OSError`/`ValueError` leaking to the daemon or an agent.
    """

    VAULT_MISSING = "vault_missing"
    VAULT_NOT_A_DIRECTORY = "vault_not_a_directory"
    OUT_OF_SCOPE = "out_of_scope"
    NOT_FOUND = "not_found"
    NOT_A_FILE = "not_a_file"
    INVALID_FRONTMATTER = "invalid_frontmatter"
    GRAPH_MISSING = "graph_missing"
    GRAPH_INVALID = "graph_invalid"
    REFRESH_UNSUPPORTED = "refresh_unsupported"
    WRITE_UNSUPPORTED = "write_unsupported"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.message = message
