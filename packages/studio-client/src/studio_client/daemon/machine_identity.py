from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from studio_contracts.local.daemon_control import instance_lock_key
from studio_contracts.local.identity import ProfileRef

from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.tokens import KeyringTokenStore, TokenStore, origin_of

_LOGGER = logging.getLogger(__name__)

MachineResolver = Callable[[ClientConfig, Path], UUID | None]


def _cache_path(config: ClientConfig, data_root: Path) -> Path:
    profile = ProfileRef(profile_id=config.profile_id, server_origin=origin_of(config.api_base_url))
    return data_root / "identity" / f"{instance_lock_key(profile)}.json"


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _read_cache(path: Path, fingerprint: str) -> UUID | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("credential_sha256") != fingerprint:
            return None
        return UUID(data["machine_id"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _write_cache(path: Path, fingerprint: str, machine_id: UUID) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"credential_sha256": fingerprint, "machine_id": str(machine_id)}),
            encoding="utf-8",
        )
    except OSError:
        _LOGGER.warning("machine identity cache not writable", exc_info=True)


async def _fetch(config: ClientConfig, token_store: TokenStore) -> UUID:
    async with StudioApiClient(config, token_store) as client:
        return (await client.get_own_machine()).id


def resolve_machine_id(
    config: ClientConfig,
    data_root: Path,
    *,
    token_store: TokenStore | None = None,
) -> UUID | None:
    store = token_store or KeyringTokenStore()
    token = store.get_token(origin_of(config.api_base_url))
    if not token:
        return None
    fingerprint = _fingerprint(token)
    path = _cache_path(config, data_root)
    cached = _read_cache(path, fingerprint)
    if cached is not None:
        return cached
    try:
        machine_id = asyncio.run(_fetch(config, store))
    except Exception:  # noqa: BLE001
        _LOGGER.warning("own machine identity could not be fetched", exc_info=True)
        return None
    _write_cache(path, fingerprint, machine_id)
    return machine_id
