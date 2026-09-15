/**
 * Minimal MD5 (RFC 1321) over raw bytes.
 *
 * Needed for the transfer single-PUT path: `POST /transfers/{id}/upload/
 * initiate` requires the file's base64 MD5 (`content_md5`) and storage itself
 * rejects a mismatch (`422 missing_content_md5` when omitted, DEC-0025).
 * WebCrypto deliberately has no MD5, so this is a local implementation; it is
 * unit-tested against RFC 1321 vectors.
 */

const SHIFTS = [
  7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
  5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
  4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
  6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
] as const;

const SINE = new Uint32Array(64);
for (let i = 0; i < 64; i += 1) {
  SINE[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296);
}

function rotl(value: number, count: number): number {
  return (value << count) | (value >>> (32 - count));
}

export function md5Bytes(input: Uint8Array): Uint8Array {
  const originalLength = input.length;
  const bitLength = originalLength * 8;
  const paddedLength = (((originalLength + 8) >> 6) + 1) << 6;
  const bytes = new Uint8Array(paddedLength);
  bytes.set(input);
  bytes[originalLength] = 0x80;
  const padded = new DataView(bytes.buffer);
  padded.setUint32(paddedLength - 8, bitLength >>> 0, true);
  padded.setUint32(paddedLength - 4, Math.floor(bitLength / 4294967296), true);

  let a0 = 0x67452301;
  let b0 = 0xefcdab89;
  let c0 = 0x98badcfe;
  let d0 = 0x10325476;
  const words = new Uint32Array(16);

  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let i = 0; i < 16; i += 1) words[i] = padded.getUint32(offset + i * 4, true);
    let a = a0;
    let b = b0;
    let c = c0;
    let d = d0;
    for (let i = 0; i < 64; i += 1) {
      let f: number;
      let g: number;
      if (i < 16) {
        f = (b & c) | (~b & d);
        g = i;
      } else if (i < 32) {
        f = (d & b) | (~d & c);
        g = (5 * i + 1) & 15;
      } else if (i < 48) {
        f = b ^ c ^ d;
        g = (3 * i + 5) & 15;
      } else {
        f = c ^ (b | ~d);
        g = (7 * i) & 15;
      }
      const sum = (f + a + SINE[i]! + words[g]!) | 0;
      a = d;
      d = c;
      c = b;
      b = (b + rotl(sum, SHIFTS[i]!)) | 0;
    }
    a0 = (a0 + a) | 0;
    b0 = (b0 + b) | 0;
    c0 = (c0 + c) | 0;
    d0 = (d0 + d) | 0;
  }

  const out = new Uint8Array(16);
  const view = new DataView(out.buffer);
  view.setUint32(0, a0 >>> 0, true);
  view.setUint32(4, b0 >>> 0, true);
  view.setUint32(8, c0 >>> 0, true);
  view.setUint32(12, d0 >>> 0, true);
  return out;
}

/** base64 (RFC 1864) of the MD5 digest, the exact form `content_md5` expects. */
export function md5Base64(input: Uint8Array): string {
  let binary = "";
  for (const byte of md5Bytes(input)) binary += String.fromCharCode(byte);
  return btoa(binary);
}
