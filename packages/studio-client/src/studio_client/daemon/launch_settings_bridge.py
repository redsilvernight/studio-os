"""``launch.get_settings`` / ``launch.save_settings`` bridge commands.

The machine owner decides, locally, whether remote launches are honoured
(AIB-J): an explicit opt-in, a concurrency cap and an explicit list of allowed
harnesses. The choice lives in ``launch_settings.json`` under the daemon data
root, written atomically; ``ClientConfig`` only provides the defaults, so a
missing or unreadable file fails closed (no opt-in, no harness).

Neither a path nor a harness inventory beyond identifiers leaves this module.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError
from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.launch import (
    MAX_LAUNCH_CONCURRENCY,
    LaunchSettings,
    LaunchSettingsSaveRequest,
    LaunchSettingsView,
)

from studio_client.capabilities import neutral_context
from studio_client.config import ClientConfig
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.harness.base import DetectionState, HarnessContext
from studio_client.harness.registry import HarnessRegistry, default_adapters

_LOGGER = logging.getLogger("studio_client.daemon.launch_settings_bridge")

SETTINGS_FILE = "launch_settings.json"


def _invalid(message: str) -> LocalFeatureError:
    return LocalFeatureError(
        LocalError(
            code=LocalErrorCode.INVALID_REQUEST,
            message=message,
            component=ComponentId.DAEMON,
            retryable=False,
        )
    )


def _defaults(config: ClientConfig) -> LaunchSettings:
    return LaunchSettings(
        opt_in=config.launch_opt_in,
        max_concurrent=min(max(config.max_concurrent_launches, 1), MAX_LAUNCH_CONCURRENCY),
        allowed_harnesses=list(dict.fromkeys(config.launch_allowed_harnesses)),
    )


def load_launch_settings(config: ClientConfig, data_root: Path) -> LaunchSettings:
    """Stored settings, else the configured defaults. An unreadable or invalid
    file never opts the machine in: it falls back to the safe defaults."""
    path = data_root / SETTINGS_FILE
    try:
        return LaunchSettings.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _defaults(config)
    except (OSError, ValidationError, ValueError) as exc:
        _LOGGER.warning("launch settings unreadable (%s); using safe defaults", type(exc).__name__)
        return _defaults(config).model_copy(update={"opt_in": False, "allowed_harnesses": []})


def effective_launch_config(config: ClientConfig, data_root: Path) -> ClientConfig:
    """`config` with the owner's stored launch settings applied."""
    settings = load_launch_settings(config, data_root)
    return config.model_copy(
        update={
            "launch_opt_in": settings.opt_in,
            "max_concurrent_launches": settings.max_concurrent,
            "launch_allowed_harnesses": tuple(settings.allowed_harnesses),
        }
    )


def _write_atomic(path: Path, settings: LaunchSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        settings.model_dump(mode="json", exclude={"detected_harnesses"}), sort_keys=True
    )
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".launch_settings.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _detected(registry: HarnessRegistry, ctx: HarnessContext) -> list[str]:
    return sorted(
        adapter.harness_id
        for adapter, detection in registry.detect_all(ctx)
        if detection.state not in (DetectionState.NOT_INSTALLED, DetectionState.UNAVAILABLE)
    )


def _view(settings: LaunchSettings, detected: list[str]) -> LaunchSettingsView:
    return LaunchSettingsView(
        opt_in=settings.opt_in,
        max_concurrent=settings.max_concurrent,
        allowed_harnesses=settings.allowed_harnesses,
        detected_harnesses=detected,
    )


def get_launch_settings(
    config: ClientConfig,
    data_root: Path,
    *,
    registry: HarnessRegistry | None = None,
    ctx: HarnessContext | None = None,
) -> LaunchSettingsView:
    active = registry if registry is not None else HarnessRegistry(default_adapters())
    context = ctx if ctx is not None else neutral_context(config)
    return _view(load_launch_settings(config, data_root), _detected(active, context))


def save_launch_settings(
    config: ClientConfig,
    data_root: Path,
    request: LaunchSettingsSaveRequest,
    *,
    registry: HarnessRegistry | None = None,
    ctx: HarnessContext | None = None,
) -> LaunchSettingsView:
    """Persist the owner's choice. Only harnesses this daemon knows are
    accepted; whether one is installed is checked at launch time, not here."""
    active = registry if registry is not None else HarnessRegistry(default_adapters())
    known = {adapter.harness_id for adapter in active.adapters()}
    if any(harness not in known for harness in request.allowed_harnesses):
        raise _invalid("A harness is not known to this machine.")
    settings = LaunchSettings(
        opt_in=request.opt_in,
        max_concurrent=request.max_concurrent,
        allowed_harnesses=request.allowed_harnesses,
    )
    try:
        _write_atomic(data_root / SETTINGS_FILE, settings)
    except OSError as exc:
        _LOGGER.warning("launch settings not saved (%s)", type(exc).__name__)
        raise LocalFeatureError(
            LocalError(
                code=LocalErrorCode.INTERNAL_ERROR,
                message="The launch settings could not be saved.",
                component=ComponentId.DAEMON,
                retryable=True,
            )
        ) from exc
    context = ctx if ctx is not None else neutral_context(config)
    return _view(settings, _detected(active, context))
