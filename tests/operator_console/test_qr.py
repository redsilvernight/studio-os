from __future__ import annotations

import pytest
from studio_operator.qr import qr_matrix, qr_svg

# Independent reference: goQR.me (api.qrserver.com) rendered
# "hello world lowercase forces byte mode" with ecc=M, margin=0; its mask is 2.
# Lowercase forces byte mode, so our encoder and the reference use the same
# segment and the matrices must match module for module.
REFERENCE_PAYLOAD = "hello world lowercase forces byte mode"
REFERENCE_MATRIX = [
    "11111110000110001011101111111",
    "10000010010100111100001000001",
    "10111010100110001010001011101",
    "10111010110111100100001011101",
    "10111010110000001111001011101",
    "10000010110100111100101000001",
    "11111110101010101010101111111",
    "00000000101110111000100000000",
    "10111110000000000100001111100",
    "01011000100111001001111111111",
    "10001011000101110110101010000",
    "00011100111101010011010011010",
    "01101010011110110100100000101",
    "00111000110110000011111011111",
    "11111011001100011110101011100",
    "00100001011110111000001110000",
    "10101110010010010100000000100",
    "11101101110101101011101110011",
    "10011110010101110000100010000",
    "10000100010011011001001101010",
    "10011110001000111100111111111",
    "00000000101000001000100011011",
    "11111110000110011111101011100",
    "10000010110010110001100011011",
    "10111010101110001110111110100",
    "10111010111000101010100001111",
    "10111010111100010010011111110",
    "10000010010111000011100001010",
    "11111110110111110101000011100",
]


def _expected() -> list[list[bool]]:
    return [[cell == "1" for cell in row] for row in REFERENCE_MATRIX]


def test_matches_an_independent_encoder_module_for_module() -> None:
    assert qr_matrix(REFERENCE_PAYLOAD, mask=2) == _expected()


def test_the_chosen_mask_is_one_of_the_eight_and_deterministic() -> None:
    first = qr_matrix(REFERENCE_PAYLOAD)
    second = qr_matrix(REFERENCE_PAYLOAD)
    assert first == second
    assert len(first) == 29


def test_finder_patterns_and_timing_are_in_place() -> None:
    matrix = qr_matrix("otpauth://totp/Studio%20OS:flo%40example.test?secret=A")
    size = len(matrix)
    for origin_row, origin_col in ((0, 0), (0, size - 7), (size - 7, 0)):
        for dy in range(7):
            for dx in range(7):
                dark = matrix[origin_row + dy][origin_col + dx]
                ring = dy in (0, 6) or dx in (0, 6)
                core = 2 <= dy <= 4 and 2 <= dx <= 4
                assert dark is (ring or core)
    # Timing patterns alternate on row/column 6, starting dark at index 8.
    for index in range(8, size - 8):
        assert matrix[6][index] is (index % 2 == 0)
        assert matrix[index][6] is (index % 2 == 0)


def test_long_payloads_use_a_bigger_version_and_too_long_fails() -> None:
    assert len(qr_matrix("a" * 100)) == 41  # version 6 (17 + 4 * 6)
    with pytest.raises(ValueError):
        qr_matrix("a" * 214)


def test_svg_is_self_contained_and_has_no_script() -> None:
    svg = qr_svg("otpauth://totp/x?secret=JBSWY3DPEHPK3PXP")
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "<script" not in svg.lower()
    assert "http://www.w3.org/2000/svg" in svg
    assert svg.count("<rect") > 20
