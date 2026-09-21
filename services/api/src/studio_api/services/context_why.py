"""Selection provenance shared by every `studio_prepare_context` section (DEC-0080).

Kept apart from `project_context` so the Roadmap section (DEC-0088) can carry
the same `why` without a circular import.

Canonical home since P2: `studio_contracts.project_context`. Re-exported here
so existing importers keep working; new code should import from the contract.
"""

from __future__ import annotations

from studio_contracts.project_context import Reason, Why

__all__ = ["Reason", "Why"]
