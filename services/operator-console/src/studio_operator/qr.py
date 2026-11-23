"""Minimal QR Code encoder (byte mode, ECC level M, versions 1 to 10).

The console has to show an `otpauth://` enrollment code as a QR image without
pulling a new dependency into the deployment: this module implements the
ISO/IEC 18004 pipeline it needs — byte-mode segment, Reed-Solomon ECC over
GF(256), block interleaving, function patterns, data placement, the eight
masks and the penalty score that picks one — and renders an SVG.

Scope is deliberately narrow: UTF-8/ASCII bytes, ECC M, at most 213 bytes
(version 10), which covers every `otpauth://` URI this console emits. The
output was cross-checked module for module against an independent encoder
(goQR.me) for enrollment URIs; `tests/operator_console/test_qr.py` pins a
regression matrix.
"""

from __future__ import annotations

from dataclasses import dataclass

# Byte-mode capacity for ECC M, per version (data codewords minus the header).
_BYTE_CAPACITY_M = {
    1: 14,
    2: 26,
    3: 42,
    4: 62,
    5: 84,
    6: 106,
    7: 122,
    8: 152,
    9: 180,
    10: 213,
}

# ECC level M block structure: (group1 blocks, group1 data, group2 blocks,
# group2 data, ec codewords per block).
_BLOCKS_M = {
    1: (1, 16, 0, 0, 10),
    2: (1, 28, 0, 0, 16),
    3: (1, 44, 0, 0, 26),
    4: (2, 32, 0, 0, 18),
    5: (2, 43, 0, 0, 24),
    6: (4, 27, 0, 0, 16),
    7: (4, 31, 0, 0, 18),
    8: (2, 38, 2, 39, 22),
    9: (3, 36, 2, 37, 22),
    10: (4, 43, 1, 44, 26),
}

_ALIGNMENT_POSITIONS = {
    1: (),
    2: (6, 18),
    3: (6, 22),
    4: (6, 26),
    5: (6, 30),
    6: (6, 34),
    7: (6, 22, 38),
    8: (6, 24, 42),
    9: (6, 26, 46),
    10: (6, 28, 50),
}

# ECC level M is encoded as 0b00 in the format information.
_ECC_M_BITS = 0b00
_PENALTY_N1 = 3
_PENALTY_N2 = 3
_PENALTY_N3 = 40
_PENALTY_N4 = 10


def _gf_tables() -> tuple[list[int], list[int]]:
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for index in range(255):
        exp[index] = value
        log[value] = index
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for index in range(255, 512):
        exp[index] = exp[index - 255]
    return exp, log


_EXP, _LOG = _gf_tables()


def _gf_mul(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    return _EXP[_LOG[left] + _LOG[right]]


def _rs_generator(degree: int) -> list[int]:
    """Coefficients of the generator polynomial, highest degree first."""
    poly = [1]
    for index in range(degree):
        factor = _EXP[index]
        shifted = poly + [0]
        for position in range(len(poly)):
            shifted[position + 1] ^= _gf_mul(poly[position], factor)
        poly = shifted
    return poly


def _rs_remainder(data: bytes, degree: int) -> list[int]:
    generator = _rs_generator(degree)
    remainder = [0] * degree
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        for index in range(degree):
            remainder[index] ^= _gf_mul(generator[index + 1], factor)
    return remainder


def _pick_version(length: int) -> int:
    for version, capacity in _BYTE_CAPACITY_M.items():
        if length <= capacity:
            return version
    raise ValueError(f"data too long for a version 10-M QR code ({length} bytes)")


def _data_codewords(payload: bytes, version: int) -> list[int]:
    count_bits = 8 if version <= 9 else 16
    bits = ["0100", format(len(payload), f"0{count_bits}b")]
    bits.extend(format(byte, "08b") for byte in payload)
    stream = "".join(bits)

    group1, size1, group2, size2, _ec = _BLOCKS_M[version]
    total_codewords = group1 * size1 + group2 * size2
    capacity_bits = total_codewords * 8
    stream += "0" * min(4, capacity_bits - len(stream))
    while len(stream) % 8:
        stream += "0"
    codewords = [int(stream[index : index + 8], 2) for index in range(0, len(stream), 8)]
    pads = (0xEC, 0x11)
    pad_index = 0
    while len(codewords) < total_codewords:
        codewords.append(pads[pad_index % 2])
        pad_index += 1
    return codewords


def _interleave(codewords: list[int], version: int) -> list[int]:
    group1, size1, group2, size2, ec_size = _BLOCKS_M[version]
    blocks: list[list[int]] = []
    offset = 0
    for _ in range(group1):
        blocks.append(codewords[offset : offset + size1])
        offset += size1
    for _ in range(group2):
        blocks.append(codewords[offset : offset + size2])
        offset += size2

    result: list[int] = []
    for index in range(max(len(block) for block in blocks)):
        for block in blocks:
            if index < len(block):
                result.append(block[index])
    ecc_blocks = [_rs_remainder(bytes(block), ec_size) for block in blocks]
    for index in range(ec_size):
        for ecc in ecc_blocks:
            result.append(ecc[index])
    return result


@dataclass
class _Matrix:
    size: int
    modules: list[list[bool]]
    is_function: list[list[bool]]

    @classmethod
    def empty(cls, version: int) -> _Matrix:
        size = 17 + 4 * version
        return cls(
            size=size,
            modules=[[False] * size for _ in range(size)],
            is_function=[[False] * size for _ in range(size)],
        )

    def copy(self) -> _Matrix:
        return _Matrix(
            size=self.size,
            modules=[row[:] for row in self.modules],
            is_function=[row[:] for row in self.is_function],
        )

    def set_function(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self.is_function[y][x] = True

    def _draw_finder(self, x: int, y: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                xx, yy = x + dx, y + dy
                if 0 <= xx < self.size and 0 <= yy < self.size:
                    distance = max(abs(dx), abs(dy))
                    self.set_function(xx, yy, distance not in (2, 4))

    def _draw_alignment(self, x: int, y: int) -> None:
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self.set_function(x + dx, y + dy, max(abs(dx), abs(dy)) != 1)

    def _draw_format_bits(self, mask: int) -> None:
        data = (_ECC_M_BITS << 3) | mask
        remainder = data
        for _ in range(10):
            remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
        bits = ((data << 10) | remainder) ^ 0x5412

        def bit(index: int) -> bool:
            return ((bits >> index) & 1) != 0

        for index in range(6):
            self.set_function(8, index, bit(index))
        self.set_function(8, 7, bit(6))
        self.set_function(8, 8, bit(7))
        self.set_function(7, 8, bit(8))
        for index in range(9, 15):
            self.set_function(14 - index, 8, bit(index))
        for index in range(8):
            self.set_function(self.size - 1 - index, 8, bit(index))
        for index in range(8, 15):
            self.set_function(8, self.size - 15 + index, bit(index))
        self.set_function(8, self.size - 8, True)

    def _draw_version_bits(self, version: int) -> None:
        if version < 7:
            return
        remainder = version
        for _ in range(12):
            remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
        bits = (version << 12) | remainder
        for index in range(18):
            bit = ((bits >> index) & 1) != 0
            a = self.size - 11 + (index % 3)
            b = index // 3
            self.set_function(a, b, bit)
            self.set_function(b, a, bit)


def _draw_function_patterns(matrix: _Matrix, version: int) -> None:
    size = matrix.size
    for index in range(size):
        matrix.set_function(6, index, index % 2 == 0)
        matrix.set_function(index, 6, index % 2 == 0)

    matrix._draw_finder(3, 3)
    matrix._draw_finder(size - 4, 3)
    matrix._draw_finder(3, size - 4)

    positions = _ALIGNMENT_POSITIONS[version]
    last = len(positions) - 1
    for row_index, y in enumerate(positions):
        for column_index, x in enumerate(positions):
            if (row_index, column_index) in {(0, 0), (0, last), (last, 0)}:
                continue
            matrix._draw_alignment(x, y)

    matrix._draw_version_bits(version)


def _place_data(matrix: _Matrix, codewords: list[int]) -> None:
    size = matrix.size
    bit_index = 0
    total_bits = len(codewords) * 8
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vertical in range(size):
            for offset in range(2):
                x = right - offset
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vertical if upward else vertical
                if not matrix.is_function[y][x] and bit_index < total_bits:
                    byte = codewords[bit_index >> 3]
                    matrix.modules[y][x] = ((byte >> (7 - (bit_index & 7))) & 1) != 0
                    bit_index += 1
        right -= 2


def _mask_bit(mask: int, x: int, y: int) -> bool:
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:
        return (x * y) % 2 + (x * y) % 3 == 0
    if mask == 6:
        return ((x * y) % 2 + (x * y) % 3) % 2 == 0
    return ((x + y) % 2 + (x * y) % 3) % 2 == 0


def _apply_mask(matrix: _Matrix, mask: int) -> None:
    for y in range(matrix.size):
        for x in range(matrix.size):
            if not matrix.is_function[y][x] and _mask_bit(mask, x, y):
                matrix.modules[y][x] = not matrix.modules[y][x]


def _penalty(matrix: _Matrix) -> int:
    size = matrix.size
    score = 0

    def finder_like(line: list[bool]) -> int:
        bits = "".join("1" if cell else "0" for cell in line)
        return bits.count("10111010000") + bits.count("00001011101")

    # Rule 1 and rule 3, rows then columns.
    lines = list(matrix.modules) + [
        [matrix.modules[y][x] for y in range(size)] for x in range(size)
    ]
    for line in lines:
        run_length = 1
        for index in range(1, size):
            if line[index] == line[index - 1]:
                run_length += 1
                if run_length == 5:
                    score += _PENALTY_N1
                elif run_length > 5:
                    score += 1
            else:
                run_length = 1
        score += _PENALTY_N3 * finder_like(line)

    # Rule 2: 2x2 blocks of one colour.
    for y in range(size - 1):
        for x in range(size - 1):
            colour = matrix.modules[y][x]
            if (
                matrix.modules[y][x + 1] == colour
                and matrix.modules[y + 1][x] == colour
                and matrix.modules[y + 1][x + 1] == colour
            ):
                score += _PENALTY_N2

    # Rule 4: dark/light balance.
    dark = sum(sum(1 for cell in row if cell) for row in matrix.modules)
    total = size * size
    score += _PENALTY_N4 * (abs(dark * 20 - total * 10) // total)

    return score


def qr_matrix(payload: str | bytes, *, mask: int | None = None) -> list[list[bool]]:
    """QR modules, row by row (True = dark), for byte-mode ECC-M data.

    `mask` forces one of the eight masks (diagnostics and the reference test);
    left to None the lowest-penalty mask is chosen, as the specification asks.
    """
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    version = _pick_version(len(data))
    codewords = _interleave(_data_codewords(data, version), version)

    base = _Matrix.empty(version)
    _draw_function_patterns(base, version)
    # Reserve the format areas before data placement: they are function
    # modules, never data, and are redrawn with the winning mask afterwards.
    base._draw_format_bits(0)
    _place_data(base, codewords)

    if mask is not None:
        matrix = base.copy()
        _apply_mask(matrix, mask)
        matrix._draw_format_bits(mask)
        return matrix.modules

    best: _Matrix | None = None
    best_score = 0
    for candidate in range(8):
        matrix = base.copy()
        _apply_mask(matrix, candidate)
        matrix._draw_format_bits(candidate)
        score = _penalty(matrix)
        if best is None or score < best_score:
            best, best_score = matrix, score
    assert best is not None
    return best.modules


def qr_svg(payload: str, *, scale: int = 6, border: int = 4) -> str:
    """SVG rendering of `payload`, one `<rect>` per dark module."""
    modules = qr_matrix(payload)
    size = len(modules)
    dimension = (size + border * 2) * scale
    rects = [
        f'<rect x="{(x + border) * scale}" y="{(y + border) * scale}" '
        f'width="{scale}" height="{scale}"/>'
        for y, row in enumerate(modules)
        for x, dark in enumerate(row)
        if dark
    ]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{dimension}" height="{dimension}" '
        f'viewBox="0 0 {dimension} {dimension}" role="img" '
        f'aria-label="Code QR d\'enrôlement MFA" shape-rendering="crispEdges">'
        f'<rect width="{dimension}" height="{dimension}" fill="#ffffff"/>'
        f'<g fill="#000000">{"".join(rects)}</g></svg>'
    )
