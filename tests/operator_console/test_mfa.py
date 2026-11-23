from __future__ import annotations

import base64

import pytest
from studio_operator.mfa import totp, verify_totp

# RFC 6238 appendix B: ASCII secret "12345678901234567890", SHA-1 vectors.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    ("instant", "expected_six_digits"),
    [
        (59, "287082"),  # 8-digit vector 94287082
        (1_111_111_109, "081804"),  # 07081804
        (1_111_111_111, "050471"),  # 14050471
        (1_234_567_890, "005924"),  # 89005924
    ],
)
def test_totp_matches_rfc6238_vectors(instant: int, expected_six_digits: str) -> None:
    assert totp(RFC_SECRET, at=instant) == expected_six_digits


def test_verify_accepts_the_current_step_and_one_step_of_skew() -> None:
    code = totp(RFC_SECRET, at=59)
    assert verify_totp(RFC_SECRET, code, at=59)
    assert verify_totp(RFC_SECRET, code, at=59 + 30)
    assert verify_totp(RFC_SECRET, code, at=59 - 30)
    assert not verify_totp(RFC_SECRET, code, at=59 + 120)


def test_verify_rejects_malformed_or_foreign_codes() -> None:
    assert not verify_totp(RFC_SECRET, "12345", at=59)
    assert not verify_totp(RFC_SECRET, "abcdef", at=59)
    assert not verify_totp(RFC_SECRET, "000000", at=59)
    assert not verify_totp("not-base-32!", "287082", at=59)


def test_a_code_never_verifies_with_another_secret() -> None:
    other = base64.b32encode(b"another-secret-here").decode()
    code = totp(RFC_SECRET, at=1_700_000_000)
    assert not verify_totp(other, code, at=1_700_000_000)
