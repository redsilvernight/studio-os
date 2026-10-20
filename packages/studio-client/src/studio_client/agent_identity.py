"""One agent identity per (machine, provider, model), harness-independent
(DEC-0225, supersedes DEC-0180). Every caller that registers a model agent —
session-start hooks of every harness and the daemon launcher — builds its
`AgentCreate` here, so the metadata is identical and `POST /agents/ensure`
returns the same row instead of a `409 idempotency_key_payload_mismatch`.
The machine scope comes from the authenticated credential, never from here.
The harness stays attributed to the execution (`ai_work.harness`)."""

from __future__ import annotations

from studio_contracts.auth import AgentCreate

MODEL_AGENT_KEY_PREFIX = "agent-model:"
UNKNOWN_PROVIDER = "unknown"


def normalize_model_ref(model: str | None, provider: str | None = None) -> tuple[str, str] | None:
    """`(provider, model)` normalized (trim + lowercase, `provider/model`
    split), or `None` when the model is unknown. No variant folding: dated or
    sized variants are different models and keep different identities."""
    mid = (model or "").strip().lower()
    prov = (provider or "").strip().lower()
    if "/" in mid:
        head, _, tail = mid.partition("/")
        if not prov:
            prov = head.strip()
        mid = tail.strip()
    if not mid:
        return None
    return (prov or UNKNOWN_PROVIDER, mid)


def model_agent_stable_key(provider: str, model: str) -> str:
    return f"{MODEL_AGENT_KEY_PREFIX}{provider}/{model}"


def model_agent_create(model: str | None, provider: str | None = None) -> AgentCreate | None:
    """The canonical model agent registration, or `None` for an unknown model
    (callers then fall back explicitly to the harness agent, DEC-0099)."""
    ref = normalize_model_ref(model, provider)
    if ref is None:
        return None
    prov, mid = ref
    return AgentCreate(
        display_name=mid,
        provider=None if prov == UNKNOWN_PROVIDER else prov,
        model=mid,
        stable_key=model_agent_stable_key(prov, mid),
    )


def is_legacy_model_key(stable_key: str | None) -> bool:
    """Per-harness model keys from DEC-0180 (`agents-ensure-<h>:<p>/<m>`) and
    the former launcher keys (`launch-agent-<sha>`): kept intact, shown as
    a former identity, never rewritten."""
    if not stable_key:
        return False
    return stable_key.startswith("launch-agent-") or (
        stable_key.startswith("agents-ensure-") and ":" in stable_key
    )
