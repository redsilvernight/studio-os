import { describe, expect, it } from "vitest";
import { md5Base64, md5Bytes } from "./md5";

function hex(bytes: Uint8Array): string {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function utf8(value: string): Uint8Array<ArrayBuffer> {
  return new TextEncoder().encode(value);
}

describe("md5Bytes", () => {
  it("matches the RFC 1321 vectors", () => {
    expect(hex(md5Bytes(utf8("")))).toBe("d41d8cd98f00b204e9800998ecf8427e");
    expect(hex(md5Bytes(utf8("abc")))).toBe("900150983cd24fb0d6963f7d28e17f72");
    expect(hex(md5Bytes(utf8("message digest")))).toBe("f96b697d7cb7938d525a2f31aaf161d0");
    expect(hex(md5Bytes(utf8("The quick brown fox jumps over the lazy dog")))).toBe(
      "9e107d9d372bb6826bd81d3542a419d6",
    );
  });

  it("pads a message longer than one block without truncating", () => {
    const long = utf8("abcdefghijklmnopqrstuvwxyz".repeat(4));
    expect(hex(md5Bytes(long))).toBe("44077f4856c7d6c519fce5dfc0fb1fcf");
  });
});

describe("md5Base64", () => {
  it("returns the base64 form the transfer API expects", () => {
    expect(md5Base64(utf8("abc"))).toBe("kAFQmDzST7DWlj99KOF/cg==");
  });
});
