//! Typed local bridge: envelope validation and error construction for
//! `studio.local/v1`.
//!
//! The renderer sends a `BridgeRequest`. The shell does not interpret payloads:
//! it checks the envelope against the closed P1 allowlist (command, protocol,
//! identifiers, size), forwards allowlisted read-only commands to the local
//! peer and relays its `BridgeResponse`/`BridgeErrorMessage`. The full payload
//! validation is the peer's job (pydantic, the P1 contracts) and the
//! renderer's (targeted validators generated from the same export).

use crate::allowlist::{self, PROTOCOL};
use serde_json::{json, Map, Value};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

const REQUEST_KEYS: &[&str] = &[
    "kind",
    "protocol",
    "message_id",
    "correlation_id",
    "sent_at",
    "command",
    "payload",
    "deadline_ms",
];
const ENVELOPE_OVERHEAD_BYTES: usize = 4096;

/// A request that passed the envelope checks.
#[derive(Debug)]
pub struct ValidRequest {
    pub command: String,
    pub message_id: String,
    pub correlation_id: String,
}

/// Failure of the envelope checks, already shaped as a P1 error.
#[derive(Debug)]
pub struct Rejection {
    pub code: &'static str,
    pub message: &'static str,
}

fn is_identifier(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 64
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b':' | b'-'))
}

pub fn validate_request(raw: &Value) -> Result<ValidRequest, Rejection> {
    let obj = raw.as_object().ok_or(Rejection {
        code: "invalid_request",
        message: "The request must be a JSON object.",
    })?;
    if obj.keys().any(|k| !REQUEST_KEYS.contains(&k.as_str())) {
        return Err(Rejection {
            code: "invalid_request",
            message: "The request carries a field the protocol does not define.",
        });
    }
    if obj.get("kind").and_then(Value::as_str) != Some("request") {
        return Err(Rejection {
            code: "invalid_request",
            message: "Only request messages may be sent to the bridge.",
        });
    }
    if obj.get("protocol").and_then(Value::as_str) != Some(PROTOCOL) {
        return Err(Rejection {
            code: "protocol_incompatible",
            message: "Unsupported local protocol.",
        });
    }
    let command = obj.get("command").and_then(Value::as_str).unwrap_or("");
    let spec = allowlist::lookup(command).ok_or(Rejection {
        code: "unknown_command",
        message: "The command is not part of the local protocol allowlist.",
    })?;
    let message_id = obj.get("message_id").and_then(Value::as_str).unwrap_or("");
    let correlation_id = obj.get("correlation_id").and_then(Value::as_str).unwrap_or("");
    if !is_identifier(message_id) || !is_identifier(correlation_id) {
        return Err(Rejection {
            code: "invalid_request",
            message: "The request identifiers are missing or malformed.",
        });
    }
    if !obj.get("sent_at").is_some_and(Value::is_string)
        || !obj.get("payload").is_some_and(Value::is_object)
    {
        return Err(Rejection {
            code: "invalid_request",
            message: "The request timestamp or payload is missing.",
        });
    }
    let size = serde_json::to_vec(raw).map(|v| v.len()).unwrap_or(usize::MAX);
    if size > spec.max_request_bytes + ENVELOPE_OVERHEAD_BYTES {
        return Err(Rejection {
            code: "payload_too_large",
            message: "The request exceeds the size allowed for this command.",
        });
    }
    Ok(ValidRequest {
        command: spec.command.clone(),
        message_id: message_id.to_owned(),
        correlation_id: correlation_id.to_owned(),
    })
}

/// `YYYY-MM-DDTHH:MM:SSZ` for "now" without a date crate.
pub fn utc_now() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format_utc(secs)
}

pub fn format_utc(secs: u64) -> String {
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    // Howard Hinnant's civil-from-days.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z",
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

fn next_message_id() -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(1);
    format!("desktop-err-{}", COUNTER.fetch_add(1, Ordering::Relaxed))
}

/// Build a `BridgeErrorMessage` (P1 shape). `message` must be static text:
/// never a path, secret or renderer-supplied string.
pub fn error_message(
    request_id: Option<&str>,
    correlation_id: Option<&str>,
    code: &str,
    message: &str,
    retryable: bool,
    details: Map<String, Value>,
) -> Value {
    let corr = correlation_id
        .filter(|c| is_identifier(c))
        .unwrap_or("unknown")
        .to_owned();
    json!({
        "kind": "error",
        "protocol": PROTOCOL,
        "message_id": next_message_id(),
        "correlation_id": corr,
        "request_id": request_id.filter(|r| is_identifier(r)),
        "sent_at": utc_now(),
        "error": {
            "code": code,
            "component": "bridge",
            "correlation_id": corr,
            "details": details,
            "message": message,
            "retryable": retryable,
        }
    })
}

pub fn reject(raw: &Value, rejection: &Rejection) -> Value {
    let get = |k: &str| raw.get(k).and_then(Value::as_str);
    error_message(
        get("message_id"),
        get("correlation_id"),
        rejection.code,
        rejection.message,
        false,
        Map::new(),
    )
}

/// A peer answer is only relayed if it is a response or error for *this*
/// request; anything else is an internal error, never passed through.
pub fn check_peer_answer(request: &ValidRequest, answer: &Value) -> Result<(), &'static str> {
    let obj = answer.as_object().ok_or("The local peer answered with a non-object.")?;
    let kind = obj.get("kind").and_then(Value::as_str);
    if !matches!(kind, Some("response") | Some("error")) {
        return Err("The local peer answered with an unexpected message kind.");
    }
    if obj.get("protocol").and_then(Value::as_str) != Some(PROTOCOL) {
        return Err("The local peer answered with another protocol.");
    }
    if obj.get("correlation_id").and_then(Value::as_str) != Some(request.correlation_id.as_str()) {
        return Err("The local peer answered a different correlation.");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;

    fn fixture(name: &str) -> Value {
        let path: PathBuf = [
            env!("CARGO_MANIFEST_DIR"),
            "..",
            "..",
            "contracts",
            "local",
            "fixtures",
            "valid",
            name,
        ]
        .iter()
        .collect();
        let doc: Value = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
        doc["data"].clone()
    }

    #[test]
    fn p1_handshake_request_fixture_is_accepted() {
        let req = fixture("bridge.request.handshake.json");
        let ok = validate_request(&req).expect("P1 fixture must pass the envelope check");
        assert_eq!(ok.command, "runtime.handshake");
    }

    #[test]
    fn p1_error_fixture_has_the_shape_the_shell_emits() {
        let fx = fixture("bridge.error.capability_missing.json");
        let built = error_message(
            Some("req-0001"),
            Some("corr-0001"),
            "capability_missing",
            "x",
            false,
            Map::new(),
        );
        let keys = |v: &Value| {
            let mut k: Vec<String> = v.as_object().unwrap().keys().cloned().collect();
            k.sort();
            k
        };
        assert_eq!(keys(&built), keys(&fx));
        assert_eq!(keys(&built["error"]), keys(&fx["error"]));
    }

    #[test]
    fn envelope_violations_are_rejected_with_p1_codes() {
        let good = fixture("bridge.request.handshake.json");
        let mutate = |f: &dyn Fn(&mut Map<String, Value>)| {
            let mut v = good.clone();
            f(v.as_object_mut().unwrap());
            validate_request(&v).unwrap_err().code
        };
        assert_eq!(mutate(&|o| { o.insert("command".into(), json!("execute_shell")); }), "unknown_command");
        assert_eq!(mutate(&|o| { o.insert("command".into(), json!("")); }), "unknown_command");
        assert_eq!(mutate(&|o| { o.insert("protocol".into(), json!("studio.local/v2")); }), "protocol_incompatible");
        assert_eq!(mutate(&|o| { o.insert("kind".into(), json!("cancel")); }), "invalid_request");
        assert_eq!(mutate(&|o| { o.insert("extra".into(), json!(1)); }), "invalid_request");
        assert_eq!(mutate(&|o| { o.insert("message_id".into(), json!("a b")); }), "invalid_request");
        assert_eq!(mutate(&|o| { o.remove("payload"); }), "invalid_request");
        assert_eq!(validate_request(&json!("x")).unwrap_err().code, "invalid_request");
        assert_eq!(validate_request(&json!(null)).unwrap_err().code, "invalid_request");
    }

    #[test]
    fn oversized_payload_is_rejected() {
        let mut v = fixture("bridge.request.handshake.json");
        v["payload"] = json!({ "blob": "x".repeat(200_000) });
        assert_eq!(validate_request(&v).unwrap_err().code, "payload_too_large");
    }

    #[test]
    fn peer_answers_must_match_the_request() {
        let req = validate_request(&fixture("bridge.request.handshake.json")).unwrap();
        let ok = json!({"kind":"response","protocol":PROTOCOL,"correlation_id":"corr-0001"});
        assert!(check_peer_answer(&req, &ok).is_ok());
        let other = json!({"kind":"response","protocol":PROTOCOL,"correlation_id":"other"});
        assert!(check_peer_answer(&req, &other).is_err());
        let event = json!({"kind":"event","protocol":PROTOCOL,"correlation_id":"corr-0001"});
        assert!(check_peer_answer(&req, &event).is_err());
        assert!(check_peer_answer(&req, &json!([1])).is_err());
    }

    #[test]
    fn utc_formatting_is_correct() {
        assert_eq!(format_utc(0), "1970-01-01T00:00:00Z");
        assert_eq!(format_utc(1_768_478_400), "2026-01-15T12:00:00Z");
        assert_eq!(format_utc(951_782_400), "2000-02-29T00:00:00Z");
    }
}
