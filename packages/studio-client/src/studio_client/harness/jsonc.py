"""Minimal-diff editing of JSON / JSONC configuration files.

A harness configuration belongs to the user. Adding one entry must therefore
leave every other byte alone — key order, comments, indentation, line endings,
unknown properties. Re-serialising the document would lose all of that, so the
editor works on the *text*: it parses the document into spans, then splices
exactly one member in or out. `verify_edit` then re-parses the result and
proves that nothing but the managed member changed.

Vendor-neutral on purpose: it knows JSON, not Claude Code or OpenCode.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

MAX_DEPTH = 32
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_LITERALS = {"true": True, "false": False, "null": None}


class JsoncError(ValueError):
    """The document is not a JSON(C) document this editor can edit safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Node:
    kind: str  # "object" | "array" | "string" | "number" | "literal"
    start: int
    end: int
    value: Any = None
    members: list[Member] = field(default_factory=list)
    items: list[Node] = field(default_factory=list)


@dataclass
class Member:
    key: str
    start: int
    value: Node

    @property
    def end(self) -> int:
        return self.value.end


class _Parser:
    def __init__(self, text: str, *, comments: bool, trailing_commas: bool) -> None:
        self.text = text
        self.comments = comments
        self.trailing_commas = trailing_commas
        self.pos = 0

    def fail(self, code: str, message: str) -> JsoncError:
        return JsoncError(code, message)

    def skip(self) -> None:
        text = self.text
        while self.pos < len(text):
            char = text[self.pos]
            if char in " \t\r\n":
                self.pos += 1
            elif text.startswith("//", self.pos):
                if not self.comments:
                    raise self.fail("comment_not_allowed", "comments are not allowed here")
                end = text.find("\n", self.pos)
                self.pos = len(text) if end == -1 else end
            elif text.startswith("/*", self.pos):
                if not self.comments:
                    raise self.fail("comment_not_allowed", "comments are not allowed here")
                end = text.find("*/", self.pos + 2)
                if end == -1:
                    raise self.fail("syntax", "unterminated comment")
                self.pos = end + 2
            else:
                return

    def document(self) -> Node:
        self.skip()
        node = self.value(0)
        self.skip()
        if self.pos != len(self.text):
            raise self.fail("syntax", "unexpected content after the document")
        return node

    def value(self, depth: int) -> Node:
        if depth > MAX_DEPTH:
            raise self.fail("too_deep", "document is nested too deeply")
        if self.pos >= len(self.text):
            raise self.fail("syntax", "unexpected end of document")
        char = self.text[self.pos]
        if char == "{":
            return self.object(depth)
        if char == "[":
            return self.array(depth)
        if char == '"':
            start = self.pos
            value = self.string()
            return Node("string", start, self.pos, value)
        match = _NUMBER.match(self.text, self.pos)
        if match is not None:
            try:
                number = json.loads(match.group())
            except ValueError:
                raise self.fail("syntax", "number is out of range") from None
            self.pos = match.end()
            return Node("number", match.start(), match.end(), number)
        for word, literal in _LITERALS.items():
            if self.text.startswith(word, self.pos):
                start = self.pos
                self.pos += len(word)
                return Node("literal", start, self.pos, literal)
        raise self.fail("syntax", "unexpected token")

    def string(self) -> str:
        text = self.text
        start = self.pos
        index = start + 1
        while index < len(text):
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if char == '"':
                self.pos = index + 1
                try:
                    return str(json.loads(text[start : index + 1]))
                except json.JSONDecodeError as error:
                    raise self.fail("syntax", "invalid string") from error
            if char in "\r\n":
                break
            index += 1
        raise self.fail("syntax", "unterminated string")

    def object(self, depth: int) -> Node:
        node = Node("object", self.pos, self.pos)
        self.pos += 1
        seen: set[str] = set()
        while True:
            self.skip()
            if self.pos >= len(self.text):
                raise self.fail("syntax", "unterminated object")
            if self.text[self.pos] == "}":
                self.pos += 1
                break
            if self.text[self.pos] != '"':
                raise self.fail("syntax", "object keys must be strings")
            member_start = self.pos
            key = self.string()
            if key in seen:
                raise self.fail("duplicate_key", "duplicate key in object")
            seen.add(key)
            self.skip()
            if self.pos >= len(self.text) or self.text[self.pos] != ":":
                raise self.fail("syntax", "expected ':' after a key")
            self.pos += 1
            self.skip()
            node.members.append(Member(key, member_start, self.value(depth + 1)))
            self.skip()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1
                self.skip()
                if self.pos < len(self.text) and self.text[self.pos] == "}":
                    if not self.trailing_commas:
                        raise self.fail("trailing_comma", "trailing comma is not allowed")
                continue
            if self.pos < len(self.text) and self.text[self.pos] == "}":
                self.pos += 1
                break
            raise self.fail("syntax", "expected ',' or '}'")
        node.end = self.pos
        return node

    def array(self, depth: int) -> Node:
        node = Node("array", self.pos, self.pos)
        self.pos += 1
        while True:
            self.skip()
            if self.pos >= len(self.text):
                raise self.fail("syntax", "unterminated array")
            if self.text[self.pos] == "]":
                self.pos += 1
                break
            node.items.append(self.value(depth + 1))
            self.skip()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1
                self.skip()
                if self.pos < len(self.text) and self.text[self.pos] == "]":
                    if not self.trailing_commas:
                        raise self.fail("trailing_comma", "trailing comma is not allowed")
                continue
            if self.pos < len(self.text) and self.text[self.pos] == "]":
                self.pos += 1
                break
            raise self.fail("syntax", "expected ',' or ']'")
        node.end = self.pos
        return node


def parse(text: str, *, comments: bool = False, trailing_commas: bool = False) -> Node:
    try:
        return _Parser(text, comments=comments, trailing_commas=trailing_commas).document()
    except RecursionError as error:  # defence in depth: MAX_DEPTH already bounds it
        raise JsoncError("too_deep", "document is nested too deeply") from error


def to_python(node: Node) -> Any:
    if node.kind == "object":
        return {member.key: to_python(member.value) for member in node.members}
    if node.kind == "array":
        return [to_python(item) for item in node.items]
    return node.value


def find_member(node: Node, key: str) -> Member | None:
    for member in node.members:
        if member.key == key:
            return member
    return None


def lookup(root: Node, path: Sequence[str]) -> Node | None:
    """The node at `path`, or None when a segment is missing. A segment that
    exists but is not an object is a shape error, not a miss."""
    node = root
    for key in path:
        if node.kind != "object":
            raise JsoncError("unexpected_shape", "expected an object along the path")
        member = find_member(node, key)
        if member is None:
            return None
        node = member.value
    return node


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _indent_unit(text: str) -> str:
    smallest: int | None = None
    for line in text.splitlines():
        stripped = line.lstrip(" \t")
        if not stripped or stripped.startswith(("//", "/*", "*")):
            continue
        lead = line[: len(line) - len(stripped)]
        if lead.startswith("\t"):
            return "\t"
        if lead and (smallest is None or len(lead) < smallest):
            smallest = len(lead)
    return " " * (smallest or 2)


def _line_indent(text: str, position: int) -> str:
    line_start = text.rfind("\n", 0, position) + 1
    line = text[line_start:position]
    return line[: len(line) - len(line.lstrip(" \t"))]


def _render(value: Any, indent: str, unit: str, newline: str) -> str:
    dumped = json.dumps(value, indent=unit, ensure_ascii=False)
    return dumped.replace("\n", newline + indent)


def _insert_member(text: str, obj: Node, key: str, value: Any) -> str:
    newline = _newline(text)
    unit = _indent_unit(text)
    base = _line_indent(text, obj.start)
    if obj.members:
        first = obj.members[0]
        line_start = text.rfind("\n", 0, first.start) + 1
        head = text[line_start : first.start]
        member_indent = head if head.strip(" \t") == "" else base + unit
    else:
        member_indent = base + unit
    member = (
        f"{json.dumps(key, ensure_ascii=False)}: {_render(value, member_indent, unit, newline)}"
    )
    if not obj.members:
        inner = text[obj.start + 1 : obj.end - 1]
        if inner.strip() == "":
            body = f"{newline}{member_indent}{member}{newline}{base}"
            return text[: obj.start + 1] + body + text[obj.end - 1 :]
        insertion = f"{newline}{member_indent}{member}"
        return text[: obj.start + 1] + insertion + text[obj.start + 1 :]
    last = obj.members[-1]
    anchor = last.end
    scan = _Parser(text, comments=True, trailing_commas=True)
    scan.pos = anchor
    scan.skip()
    has_comma = scan.pos < len(text) and text[scan.pos] == ","
    if has_comma:
        anchor = scan.pos + 1
    rest_start = anchor
    line_end = text.find("\n", rest_start)
    line_end = len(text) if line_end == -1 else line_end
    tail = text[rest_start:line_end].rstrip("\r")
    if tail.strip() == "" or tail.lstrip().startswith("//"):
        point = rest_start + len(tail)
    else:
        point = rest_start
    addition = f"{newline}{member_indent}{member}"
    result = text[:point] + addition + text[point:]
    if not has_comma:
        result = result[: last.end] + "," + result[last.end :]
    return result


def upsert(
    text: str,
    path: Sequence[str],
    value: Any,
    *,
    comments: bool = False,
    trailing_commas: bool = False,
) -> str:
    """Set the member at `path` to `value`, touching nothing else."""
    if not path:
        raise ValueError("path must not be empty")
    root = parse(text, comments=comments, trailing_commas=trailing_commas)
    if root.kind != "object":
        raise JsoncError("unexpected_shape", "the document root must be an object")
    node = root
    for index, key in enumerate(path[:-1]):
        member = find_member(node, key)
        if member is None:
            wrapped: Any = value
            for inner in reversed(path[index + 1 :]):
                wrapped = {inner: wrapped}
            return _insert_member(text, node, key, wrapped)
        if member.value.kind != "object":
            raise JsoncError("unexpected_shape", "expected an object along the path")
        node = member.value
    final = find_member(node, path[-1])
    if final is None:
        return _insert_member(text, node, path[-1], value)
    newline = _newline(text)
    unit = _indent_unit(text)
    indent = _line_indent(text, final.start)
    rendered = _render(value, indent, unit, newline)
    return text[: final.value.start] + rendered + text[final.value.end :]


def _without(value: Any, path: Sequence[str]) -> Any:
    if not path:
        return None
    if not isinstance(value, dict) or path[0] not in value:
        return value
    copy = dict(value)
    if len(path) == 1:
        del copy[path[0]]
    else:
        copy[path[0]] = _without(copy[path[0]], path[1:])
        if copy[path[0]] == {}:
            del copy[path[0]]
    return copy


def verify_edit(
    before: str | None,
    after: str,
    path: Sequence[str],
    expected: Any,
    *,
    comments: bool = False,
    trailing_commas: bool = False,
) -> None:
    """Prove that `after` is `before` plus exactly the managed member. Raises
    JsoncError otherwise — the caller then refuses to write."""
    edited = parse(after, comments=comments, trailing_commas=trailing_commas)
    landed = lookup(edited, path)
    if landed is None or to_python(landed) != expected:
        raise JsoncError("verify_failed", "the managed entry is not in the edited document")
    if before is None:
        return
    original = to_python(parse(before, comments=comments, trailing_commas=trailing_commas))
    if _without(to_python(edited), path) != _without(original, path):
        raise JsoncError("verify_failed", "the edit changed content outside the managed entry")
