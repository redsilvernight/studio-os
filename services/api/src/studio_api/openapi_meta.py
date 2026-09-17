from __future__ import annotations

from typing import Any

from fastapi.security import HTTPBearer

# Machine Bearer authentication, as the OpenAPI `securityScheme` every
# protected operation references. The runtime behavior is unchanged: the
# credential is an opaque machine token provisioned out of band, sent as
# `Authorization: Bearer <machine-token>` on every request under `/api/v1`.
# A missing, invalid or revoked credential returns 401. `auto_error=False`
# keeps the 401 shapes raised by `deps.get_current_machine` as the single
# source of truth — the scheme only describes the mechanism, it never
# accepts or rejects a request by itself. Known immaterial nuance: an empty
# bearer value (`Authorization: Bearer` with no token) now answers 401
# "missing bearer token" where the hand-rolled parser answered 401
# "invalid or revoked machine token" — same status, same documented 401
# shape, no consumer can distinguish a usable signal either way.
machine_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="MachineBearer",
    description=(
        "Machine credential provisioned out of band. Send it as "
        "`Authorization: Bearer <machine-token>` on every request under "
        "`/api/v1`. The token is opaque: a missing, invalid or revoked "
        "credential returns 401. Unauthenticated operations are "
        "`GET /healthz`, `GET /metrics`, the human dashboard login "
        "`POST /auth/token`, and the HMAC-signed GitHub ingress "
        "`POST /github/webhook` (etape 9.1: signed, never Bearer)."
    ),
)

IDEMPOTENCY_KEY_DESCRIPTION = (
    "Optional replay key for safe retries (timeouts, reconnects, offline "
    "queue replay). Send a caller-generated unique value per intended "
    "resource: replaying the same key with the identical body returns the "
    "original response instead of creating a duplicate, even under "
    "concurrent retries. Replaying the same key with a different body is a "
    "client error (`409 idempotency_key_payload_mismatch`) — always resend "
    "the exact same body when retrying. A key whose creation never "
    "completed may briefly answer `409 idempotency_key_in_progress`; retry "
    "identically. `POST /events` does not use this header (the "
    "client-generated `event_id` plays that role instead), and neither do "
    "`POST /machines` and `POST /users`."
)

IF_MATCH_VERSION_DESCRIPTION = (
    "Optimistic concurrency guard, required. Send the `version` value last "
    "read for the object (from any GET response). If another writer changed "
    "the object first, the update is rejected with `409 version_conflict` "
    "carrying the current server version — re-read, merge, and retry. "
    "Updates never overwrite silently."
)


ErrorResponses = dict[int | str, Any]


def _json_response(description: str, example: Any) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"example": example}},
    }


def merge_status(status_code: int, *variants: ErrorResponses) -> ErrorResponses:
    """Combine several variants sharing one status code into the single
    response object OpenAPI allows per status code. Descriptions
    concatenate; the first variant's example illustrates the shape (all
    share the `{"detail": {"error_code", ...}}` envelope)."""
    descriptions = [variant[status_code]["description"] for variant in variants]
    example = variants[0][status_code]["content"]["application/json"]["example"]
    return {status_code: _json_response(" ".join(descriptions), example)}


def merge_conflict(*variants: ErrorResponses) -> ErrorResponses:
    """Combine several 409 variants into the single response object OpenAPI
    allows per status code. Descriptions concatenate; the first variant's
    example illustrates the shape (all share the `{"detail":
    {"error_code", ...}}` envelope)."""
    return merge_status(409, *variants)


RESP_401_UNAUTHORIZED: ErrorResponses = {
    401: _json_response(
        "Missing, invalid or revoked credential. Send "
        "`Authorization: Bearer <machine-token>` for a machine, or "
        "`Authorization: Bearer <jwt>` obtained from `POST /auth/token` "
        "for a human dashboard user; provision the machine token out "
        "of band before calling.",
        {"detail": "missing bearer token"},
    )
}

RESP_403_FORBIDDEN: ErrorResponses = {
    403: _json_response(
        "Authenticated but not allowed. The caller's role or resource "
        "ownership does not permit this action (`resource` names the "
        "object kind, `action` the attempted operation). A 403 is final: "
        "retrying the same call changes nothing, and a queued offline "
        "operation that replays into a 403 is dead-lettered, never "
        "retried. Reads stay fully available; only the listed write "
        "operations can return this.",
        {"detail": {"error_code": "forbidden", "resource": "task", "action": "write"}},
    )
}

RESP_404_NOT_FOUND: ErrorResponses = {
    404: _json_response(
        "No such resource. Unknown ids return 404; access to an existing "
        "but unauthorized transfer returns 403 instead, never 404.",
        {"detail": "task not found"},
    )
}

RESP_409_VERSION_CONFLICT: ErrorResponses = {
    409: _json_response(
        "Stale `If-Match-Version`: another writer changed the object "
        "first. `server_version` is the current version — re-read the "
        "object, merge, and retry with the new version.",
        {"detail": {"error_code": "version_conflict", "server_version": 3}},
    )
}

RESP_409_ACTOR_NOT_OWNED: ErrorResponses = {
    409: _json_response(
        "Provenance mismatch: the referenced agent identity is unknown or "
        "attached to another machine. Register an agent for the caller's "
        "own authenticated machine first (`POST /agents`), then reference "
        "it. Never silently attributed across machines.",
        {
            "detail": {
                "error_code": "actor_not_owned",
                "message": "agent_id must be an agent attached to the authenticated machine",
            }
        },
    )
}

RESP_409_MACHINE_ID_MISMATCH: ErrorResponses = {
    409: _json_response(
        "`machine_id` in the body must equal the authenticated machine's "
        "own id — it is never a free field. Send the caller's own id, "
        "never another machine's.",
        {
            "detail": {
                "error_code": "machine_id_mismatch",
                "message": "machine_id does not match the authenticated machine",
            }
        },
    )
}

RESP_409_EVENT_IDENTITY: ErrorResponses = {
    409: _json_response(
        "Event identity rejected before anything is stored: `machine_id` "
        "must be omitted (it is derived from the authenticated machine) "
        "or equal to it (`machine_id_mismatch`); `actor_type=user` "
        "requires `actor_id` equal to the machine owner's user id "
        "(`actor_id_mismatch`); `actor_type=agent` requires an agent "
        "attached to the caller's machine, and `actor_type=system` "
        "requires `actor_id` equal to the machine's own id "
        "(`actor_not_owned`). Replaying an already-stored `event_id` "
        "with a different identity never modifies the original.",
        {
            "detail": {
                "error_code": "machine_id_mismatch",
                "message": "machine_id does not match the authenticated machine",
            }
        },
    )
}

RESP_409_IDEMPOTENCY: ErrorResponses = {
    409: _json_response(
        "Replay key problem, no duplicate was created: either the same "
        "`Idempotency-Key` was reused with a different body "
        "(`idempotency_key_payload_mismatch` — resend the exact original "
        "body) or a previous creation with this key is still completing "
        "(`idempotency_key_in_progress` — retry identically after a "
        "short delay).",
        {"detail": {"error_code": "idempotency_key_payload_mismatch"}},
    )
}

RESP_409_REVIEW_TRANSITION: ErrorResponses = {
    409: _json_response(
        "Invalid review transition: resolving a work entry to "
        "`approved` (or requesting changes) requires a privileged role "
        "and is only possible from `review_requested` — nobody approves "
        "their own work. Move the entry to `review_requested` first, "
        "then have a privileged reviewer resolve it.",
        {"detail": {"error_code": "invalid_status_transition"}},
    )
}

RESP_409_ALREADY_CLAIMED: ErrorResponses = {
    409: _json_response(
        "Another machine already holds this task's claim (soft lock). "
        "Release by its owner, or pick another task — claims warn, they "
        "never queue.",
        {"detail": {"error_code": "already_claimed"}},
    )
}

RESP_409_LIBRARY: ErrorResponses = {
    409: _json_response(
        "Library reference conflict: the `stable_key` is already taken in "
        "this scope (`duplicate_stable_key`); a dependency pin names "
        "several visible resources (`pin_ambiguous` — disambiguate the "
        "pin); or a lock already exists for this `(project, resource)` "
        "pair (`already_locked`).",
        {"detail": {"error_code": "duplicate_stable_key"}},
    )
}

RESP_404_LIBRARY_PIN: ErrorResponses = {
    404: _json_response(
        "Library reference not found: unknown id, or no visible resource "
        "matches a dependency pin (`pin_not_found`), or the pinned "
        "version was never created (`pin_version_not_found` / "
        "`version_not_found`). Pins on another user's private resources "
        "answer the same 404, never a hint of their existence.",
        {"detail": {"error_code": "pin_not_found", "stable_key": "..."}},
    )
}

RESP_422_LIBRARY_SCOPE: ErrorResponses = {
    422: _json_response(
        "Library scope context rejected, nothing stored: project scope "
        "requires `project_id`, studio and user scopes forbid it "
        "(`invalid_scope_context`).",
        {"detail": {"error_code": "invalid_scope_context"}},
    )
}

RESP_422_LIBRARY_CONTENT: ErrorResponses = {
    422: _json_response(
        "Library semantic content rejected, nothing stored (P3 semantic "
        "content): "
        "the version `content` must match its per-kind schema "
        "(`content_schema: studio.library.<kind>/v1`, unknown fields "
        "forbidden, `rule`/`skill` prose bounded to 65_536 characters, "
        "`model_profile` carrying vendor-neutral `requirements` only, "
        "`agent_definition` descriptive only; `workflow` stays free-form "
        "until P11). Per-field `details` describe the caller's own "
        "payload only.",
        {
            "detail": {
                "error_code": "invalid_content",
                "details": [{"field": "text", "reason": "String should have at least 1 character"}],
            }
        },
    )
}

RESP_422_LIBRARY_BINDING: ErrorResponses = {
    422: _json_response(
        "Library binding rejected, nothing stored (P5 typed bindings): "
        "the dependency pin names a forbidden kind couple "
        "(`forbidden_kind_pair`), an explicit relation that does not match "
        "the couple (`relation_mismatch`), a second model profile on one "
        "agent definition (`too_many_model_profiles`), twice the same "
        "target (`duplicate_binding`), or a private user target from a "
        "shared definition (`forbidden_scope`). Raised only after the "
        "404/409 existence gates — never an oracle on invisible resources.",
        {"detail": {"error_code": "invalid_binding", "reason": "forbidden_kind_pair"}},
    )
}


RESP_404_RUNTIME: ErrorResponses = {
    404: _json_response(
        "Runtime reference not found: unknown runtime id (`runtime not "
        "found`, plain message — another user's runtime answers the same "
        "404, never a hint of its existence), unknown runtime binding id "
        "(`runtime binding not found`), a `runtime_id` reference naming "
        "no row (`runtime_not_found`), an attached/bound machine that "
        "does not exist (`runtime_target_not_found`), or a project "
        "context that does not exist (`project_not_found`).",
        {"detail": {"error_code": "runtime_not_found"}},
    )
}

RESP_409_RUNTIME_BINDING: ErrorResponses = {
    409: _json_response(
        "Runtime choice already stored for this `(level, scope, kind, "
        "stable_key)` key (`already_bound`) — release it first, then "
        "store the new choice. Bindings are set-once per key, never "
        "silently overwritten.",
        {"detail": {"error_code": "already_bound"}},
    )
}

RESP_422_RUNTIME: ErrorResponses = {
    422: _json_response(
        "Runtime choice rejected, nothing stored: a `session` level sent "
        "for persistence (`ephemeral_level_not_stored`), a kind outside "
        "`agent_definition`/`model_profile` (`unsupported_target_kind`), "
        "a `runtime_id` mixed with inline anchors "
        "(`runtime_id_must_be_exclusive`), or an update/register leaving "
        "no anchor at all (`invalid_runtime` / `no_anchor_left`). "
        "Secret-looking metadata keys are rejected by validation before "
        "anything is stored.",
        {
            "detail": {
                "error_code": "invalid_runtime_binding",
                "reason": "ephemeral_level_not_stored",
            }
        },
    )
}

RESP_422_RESOLUTION: ErrorResponses = {
    422: _json_response(
        "Resolution refused, nothing stored (pure read): the winning "
        "runtime choice does not satisfy the linked model profile "
        "requirements (`runtime_incompatible`, with `level`, "
        "`matched_kind`, `matched_stable_key` and `unsatisfied` — never "
        "a silent fallback to another runtime), or the loaded snapshot "
        "is internally inconsistent (`invalid_resolution_input`, "
        "including a duplicated session override key). "
        "Missing or invisible definitions answer 404 "
        "`definition_not_found` instead, never a hint of their existence.",
        {
            "detail": {
                "error_code": "runtime_incompatible",
                "level": "user",
                "matched_kind": "agent_definition",
                "matched_stable_key": "...",
                "unsatisfied": ["coding: required"],
            }
        },
    )
}


RESP_409_TRANSFER_STATE: ErrorResponses = {
    409: _json_response(
        "Upload state conflict: the transfer is already `ready` "
        "(`transfer_already_ready`, uploads are never replaceable), the "
        "multipart `upload_id` is unknown for this transfer "
        "(`unknown_upload_id` — discard local upload state and start over "
        "with `upload/initiate`), or the resumed part size differs from "
        "the server constant (`part_size_mismatch`).",
        {"detail": {"error_code": "transfer_already_ready"}},
    )
}

RESP_413_TRANSFER_TOO_LARGE: ErrorResponses = {
    413: _json_response(
        "Transfer size exceeds the per-transfer maximum. Split the file "
        "or use the multipart upload path; `max_size_bytes` is the limit "
        "that applied.",
        {
            "detail": {
                "error_code": "transfer_too_large",
                "size_bytes": 1073741824,
                "max_size_bytes": 536870912,
            }
        },
    )
}

RESP_507_QUOTA_EXCEEDED: ErrorResponses = {
    507: _json_response(
        "Project (or unscoped) storage quota exceeded. Check "
        "`GET /transfers/consumption` for `remaining_bytes` before a "
        "large upload; between the check and the creation another upload "
        "may still win the race.",
        {
            "detail": {
                "error_code": "quota_exceeded",
                "project_id": "00000000-0000-0000-0000-000000000000",
                "consumed_bytes": 900,
                "requested_bytes": 200,
                "quota_bytes": 1000,
            }
        },
    )
}

RESP_422_TRANSFER_INTEGRITY: ErrorResponses = {
    422: _json_response(
        "Upload integrity or shape rejected, nothing marked ready: small "
        "uploads require `content_md5` at initiate "
        "(`missing_content_md5`); the completed size must equal the size "
        "declared at creation (`size_mismatch` / `object_not_found`); on "
        "the single-upload path the stored bytes are re-verified against "
        "the presigned checksum (`content_md5_mismatch`). Part numbers "
        "outside the multipart bounds fail as `invalid_part_number`.",
        {"detail": {"error_code": "missing_content_md5"}},
    )
}

RESP_401_WEBHOOK_SIGNATURE: ErrorResponses = {
    401: _json_response(
        "Invalid or missing GitHub webhook signature. The `X-Hub-Signature-256` "
        "HMAC over the raw body did not verify — deliberately a plain message "
        "with no machine-readable code, so a prober learns nothing. Retry "
        "with the correct `STUDIO_GITHUB_WEBHOOK_SECRET`.",
        {"detail": "invalid webhook signature"},
    )
}

RESP_503_WEBHOOK_NOT_CONFIGURED: ErrorResponses = {
    503: _json_response(
        "GitHub webhook ingress is not configured on this server "
        "(`STUDIO_GITHUB_WEBHOOK_SECRET` unset).",
        {"detail": {"error_code": "webhook_not_configured"}},
    )
}

RESP_413_WEBHOOK_TOO_LARGE: ErrorResponses = {
    413: _json_response(
        "Webhook body exceeds the bounded ingress size (`STUDIO_GITHUB_WEBHOOK_MAX_BODY_BYTES`).",
        {"detail": {"error_code": "webhook_body_too_large"}},
    )
}

RESP_400_WEBHOOK_MALFORMED: ErrorResponses = {
    400: _json_response(
        "Webhook delivery malformed: missing `X-GitHub-Event`/`X-GitHub-Delivery` "
        "headers (`webhook_missing_headers`) or unparsable JSON "
        "(`webhook_invalid_json`).",
        {"detail": {"error_code": "webhook_missing_headers"}},
    )
}
