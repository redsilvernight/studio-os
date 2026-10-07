from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretFinding:
    field: str
    pattern: str


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "github_token",
        re.compile(
            r"\b(?:ghp_[A-Za-z0-9]{8,}|gho_[A-Za-z0-9]{8,}|ghu_[A-Za-z0-9]{8,}"
            r"|ghs_[A-Za-z0-9]{8,}|ghr_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})\b"
        ),
    ),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{10,}\b")),
    ("openai_key", re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9\-_]{10,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b")),
    ("stripe_key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\b")),
    ("pem_block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    (
        "url_credentials",
        re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s/@:]+:[^\s/@]+@[^\s/]+\b"),
    ),
    (
        "secret_assignment",
        re.compile(
            r"\b(password|passwd|secret|token|api[_-]?key|client_secret)\b"
            r"\s*[:=]\s*(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'"
            r"|(?P<bare>[^\s\"'`,;\)\]]+))",
            re.IGNORECASE,
        ),
    ),
)

_ASSIGNMENT_RE = SECRET_PATTERNS[-1][1]

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _is_placeholder(value: str) -> bool:
    text = value.strip().strip("\"'`,;).]}")
    if not text:
        return True
    lowered = text.lower()
    if set(lowered) <= {"x", "*", ".", "…", "-", "_", "#"}:
        return True
    # Low-diversity filler ("aaaa…", "abab…") is never a real credential.
    if len(set(lowered)) <= 2:
        return True
    if text.startswith(("<", "${", "{{", "$")):
        return True
    if lowered.startswith(("os.environ", "os.getenv", "process.env", "env(")):
        return True
    if _UUID_RE.fullmatch(text) is not None:
        return True
    return False


def _assignment_hit(text: str) -> bool:
    for match in _ASSIGNMENT_RE.finditer(text):
        candidate = match.group("dq")
        if candidate is None:
            candidate = match.group("sq")
        if candidate is None:
            candidate = match.group("bare") or ""
        candidate = candidate.strip().strip(",;).]}")
        if len(candidate) < 8:
            continue
        if _is_placeholder(candidate):
            continue
        return True
    return False


def scan(fields: dict[str, str]) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for field, value in fields.items():
        if not value:
            continue
        for pattern_id, rx in SECRET_PATTERNS:
            if pattern_id == "secret_assignment":
                if _assignment_hit(value):
                    findings.append(SecretFinding(field=field, pattern=pattern_id))
            elif rx.search(value) is not None:
                findings.append(SecretFinding(field=field, pattern=pattern_id))
    return findings
