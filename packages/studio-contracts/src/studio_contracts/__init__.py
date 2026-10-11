"""Shared Studio OS contracts (TECH/02-05_*.md). No FastAPI/SQLAlchemy dependency."""

API_CONTRACT_VERSION = 2
EVENT_SCHEMA_VERSION = 1
PROFILE_CONTRACT_VERSION = 1
"""Execution profile contract version (P04-profile-contract, DEC-0198).

N; N-1 is accepted on read (`studio_contracts.profiles.PROFILE_MIN_COMPATIBLE_VERSION`)."""
