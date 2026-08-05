#!/usr/bin/env python3
"""Reject custom fixture assertions whose callback ignores the fixture value.

`assertKeyWith` is the escape hatch for comparisons that cannot be expressed as
plain equality.  Merely invoking a callback is not evidence that the callback
used the fixture value: `assertKeyWith("k", |_| true)` used to mark `k`
asserted while proving nothing.  This guard parses the callback shape used by
each maintained binding and requires its fixture-value parameter to occur in
the callback body.  Comments and string literals do not count.

The parser is intentionally small and conservative.  Unsupported callback
shapes fail closed and should either be expressed as an inline callback or
added here with a self-test before use.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Token:
    value: str
    line: int


CALL_NAMES: dict[str, frozenset[str]] = {
    "cpp": frozenset({"assert_key_with", "assert_key_with_if_present"}),
    "cs": frozenset({"AssertKeyWith", "TryAssertKeyWith", "AssertKeyInto"}),
    "dart": frozenset({"assertKeyWith", "assertKeyIfPresent"}),
    "go": frozenset({"assertKeyWith"}),
    "js": frozenset({"assertKeyWith"}),
    "kt": frozenset({"assertKeyWith"}),
    "rs": frozenset({"assert_key_with", "assert_key_if_present"}),
    "zig": frozenset({"assertKeyWith", "assertKeyWithOpt"}),
}

SOURCE_GLOBS: dict[str, tuple[str, ...]] = {
    "cpp": ("tests/**/*.cpp", "tests/**/*.hpp"),
    "cs": ("tests/**/*.cs",),
    "dart": ("test/**/*.dart",),
    "go": ("**/*_test.go",),
    "js": ("test/**/*.js",),
    "kt": ("src/test/**/*.kt",),
    "py": ("tests/**/*.py",),
    "rs": ("tests/**/*.rs",),
    "zig": ("src/**/*.zig",),
}

SOURCE_EXCLUDES: dict[str, frozenset[str]] = {
    # This is the helper implementation itself. Its optional form delegates the
    # caller-supplied `check` variable to `assert_key_with`; runner callbacks
    # live in the other integration-test crates and are scanned there.
    "rs": frozenset({"tests/common/expect.rs"}),
}

IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}
CLOSE_TO_OPEN = {close: open_ for open_, close in OPEN_TO_CLOSE.items()}


def _lex(text: str, *, rust_lifetimes: bool = False) -> list[Token]:
    """Tokenize identifiers and delimiters while discarding prose."""

    out: list[Token] = []
    i = 0
    line = 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = n if end < 0 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                return out
            line += text.count("\n", i, end + 2)
            i = end + 2
            continue
        # C++ raw strings are common in fixture tests.
        if text.startswith('R"', i):
            open_paren = text.find("(", i + 2)
            if open_paren >= 0:
                delimiter = text[i + 2 : open_paren]
                close = ")" + delimiter + '"'
                end = text.find(close, open_paren + 1)
                if end >= 0:
                    end += len(close)
                    line += text.count("\n", i, end)
                    i = end
                    continue
        # Rust lifetimes (`'a`) are identifiers, not character literals. Treat
        # the apostrophe as punctuation unless a matching quote immediately
        # follows the one-character payload.
        if (
            rust_lifetimes
            and ch == "'"
            and i + 1 < n
            and (text[i + 1].isalpha() or text[i + 1] == "_")
            and (i + 2 >= n or text[i + 2] != "'")
        ):
            out.append(Token(ch, line))
            i += 1
            continue
        if ch in {'"', "'", "`"}:
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                if text[i] == "\n":
                    line += 1
                i += 1
            continue
        match = IDENT.match(text, i)
        if match:
            out.append(Token(match.group(0), line))
            i = match.end()
            continue
        if text.startswith("=>", i):
            out.append(Token("=>", line))
            i += 2
            continue
        if text.startswith("::", i):
            out.append(Token("::", line))
            i += 2
            continue
        out.append(Token(ch, line))
        i += 1
    return out


def _matching(tokens: Sequence[Token], start: int) -> int | None:
    opening = tokens[start].value
    closing = OPEN_TO_CLOSE.get(opening)
    if closing is None:
        return None
    stack = [opening]
    for at in range(start + 1, len(tokens)):
        value = tokens[at].value
        if value in OPEN_TO_CLOSE:
            stack.append(value)
        elif value in CLOSE_TO_OPEN:
            if not stack or stack[-1] != CLOSE_TO_OPEN[value]:
                return None
            stack.pop()
            if not stack:
                return at
    return None


def _split_top_level(tokens: Sequence[Token]) -> list[list[Token]]:
    parts: list[list[Token]] = [[]]
    stack: list[str] = []
    for token in tokens:
        value = token.value
        if value in OPEN_TO_CLOSE:
            stack.append(value)
        elif value in CLOSE_TO_OPEN:
            if stack and stack[-1] == CLOSE_TO_OPEN[value]:
                stack.pop()
        if value == "," and not stack:
            parts.append([])
        else:
            parts[-1].append(token)
    return parts


def _identifiers(tokens: Iterable[Token]) -> list[str]:
    return [token.value for token in tokens if IDENT.fullmatch(token.value)]


def _body_uses(tokens: Sequence[Token], name: str) -> bool:
    return any(token.value == name for token in tokens)


def _parameter_from_typed(tokens: Sequence[Token]) -> str | None:
    ids = _identifiers(tokens)
    if not ids:
        return None
    candidate = ids[-1]
    if candidate == "_":
        return None
    # An unnamed `const Json&` / `JsonElement` ends in punctuation or consists
    # only of a type.  Requiring at least two identifiers for typed forms keeps
    # the scanner fail-closed.
    if tokens and tokens[-1].value in {"&", "*"}:
        return None
    if len(ids) == 1 and candidate in {
        "Json",
        "Value",
        "JsonElement",
        "dynamic",
        "any",
        "Object",
    }:
        return None
    return candidate


def _arrow_callback(tokens: Sequence[Token]) -> tuple[str, Sequence[Token]] | None:
    try:
        arrow = next(i for i, token in enumerate(tokens) if token.value == "=>")
    except StopIteration:
        return None
    params = list(tokens[:arrow])
    while params and params[0].value in {"async", "("}:
        if params[0].value == "(":
            break
        params.pop(0)
    if params and params[0].value == "(":
        end = _matching(params, 0)
        if end is None:
            return None
        params = params[1:end]
    name = _parameter_from_typed(params)
    if name is None:
        return None
    return name, tokens[arrow + 1 :]


def _dart_block_callback(tokens: Sequence[Token]) -> tuple[str, Sequence[Token]] | None:
    if not tokens or tokens[0].value != "(":
        return None
    close = _matching(tokens, 0)
    if close is None or close + 1 >= len(tokens) or tokens[close + 1].value != "{":
        return None
    body_close = _matching(tokens, close + 1)
    if body_close is None:
        return None
    name = _parameter_from_typed(tokens[1:close])
    if name is None:
        return None
    return name, tokens[close + 2 : body_close]


def _go_callback(tokens: Sequence[Token]) -> tuple[str, Sequence[Token]] | None:
    if not tokens or tokens[0].value != "func":
        return None
    try:
        open_paren = next(i for i, token in enumerate(tokens) if token.value == "(")
    except StopIteration:
        return None
    close_paren = _matching(tokens, open_paren)
    if close_paren is None:
        return None
    fields = _split_top_level(tokens[open_paren + 1 : close_paren])
    if not fields:
        return None
    ids = _identifiers(fields[0])
    if len(ids) < 2 or ids[0] == "_":
        return None
    try:
        body_open = next(
            i for i in range(close_paren + 1, len(tokens)) if tokens[i].value == "{"
        )
    except StopIteration:
        return None
    body_close = _matching(tokens, body_open)
    if body_close is None:
        return None
    return ids[0], tokens[body_open + 1 : body_close]


def _cpp_callback(tokens: Sequence[Token]) -> tuple[str, Sequence[Token]] | None:
    try:
        capture = next(i for i, token in enumerate(tokens) if token.value == "[")
    except StopIteration:
        return None
    capture_close = _matching(tokens, capture)
    if capture_close is None:
        return None
    try:
        params_open = next(
            i for i in range(capture_close + 1, len(tokens)) if tokens[i].value == "("
        )
    except StopIteration:
        return None
    params_close = _matching(tokens, params_open)
    if params_close is None:
        return None
    name = _parameter_from_typed(tokens[params_open + 1 : params_close])
    if name is None:
        return None
    try:
        body_open = next(
            i for i in range(params_close + 1, len(tokens)) if tokens[i].value == "{"
        )
    except StopIteration:
        return None
    body_close = _matching(tokens, body_open)
    if body_close is None:
        return None
    return name, tokens[body_open + 1 : body_close]


def _rust_callback(tokens: Sequence[Token]) -> tuple[str, Sequence[Token]] | None:
    pipes = [i for i, token in enumerate(tokens) if token.value == "|"]
    if len(pipes) < 2:
        return None
    ids = _identifiers(tokens[pipes[0] + 1 : pipes[1]])
    if not ids or ids[0] == "_":
        return None
    return ids[0], tokens[pipes[1] + 1 :]


def _kotlin_callback(tokens: Sequence[Token]) -> tuple[str, Sequence[Token]] | None:
    if not tokens or tokens[0].value != "{":
        return None
    close = _matching(tokens, 0)
    if close is None:
        return None
    inner = tokens[1:close]
    arrows = [i for i, token in enumerate(inner) if token.value == "=>"]
    # Kotlin's lambda arrow was lexed as '-' and '>'; normalize that spelling.
    if not arrows:
        for i in range(len(inner) - 1):
            if inner[i].value == "-" and inner[i + 1].value == ">":
                params = inner[:i]
                ids = _identifiers(params)
                if not ids or ids[-1] == "_":
                    return None
                return ids[-1], inner[i + 2 :]
        return "it", inner
    return None


def _callback_for(
    binding: str, args: Sequence[Sequence[Token]], trailing: Sequence[Token]
) -> tuple[str, Sequence[Token]] | None:
    indexes = {
        "cpp": 1,
        "cs": 1,
        "dart": 2,
        "go": 3,
        "js": 2,
        "rs": 1,
    }
    if binding == "kt":
        return _kotlin_callback(trailing)
    index = indexes[binding]
    if len(args) <= index:
        return None
    callback = args[index]
    if binding == "cpp":
        return _cpp_callback(callback)
    if binding == "go":
        return _go_callback(callback)
    if binding == "rs":
        return _rust_callback(callback)
    if binding in {"cs", "js"}:
        return _arrow_callback(callback)
    if binding == "dart":
        # A block callback can contain arrows of its own (switch expressions,
        # nested map callbacks). Recognize the outer block before looking for an
        # expression-bodied arrow.
        return _dart_block_callback(callback) or _arrow_callback(callback)
    raise AssertionError(binding)


def _definition_call(binding: str, tokens: Sequence[Token], at: int) -> bool:
    previous = tokens[at - 1].value if at else ""
    if binding == "cs":
        return previous != "."
    lookback = {token.value for token in tokens[max(0, at - 6) : at]}
    if binding == "cpp":
        return previous in {"void", "bool"} or "template" in lookback
    if binding == "dart":
        return previous in {"T", "void", "dynamic"}
    return bool(lookback & {"def", "fn", "fun", "func", "function"})


def _resolve_named_callback(
    binding: str, name: str, tokens: Sequence[Token]
) -> list[tuple[str, Sequence[Token]]]:
    """Resolve the two named callback forms used today (JS locals, C# methods)."""

    found: list[tuple[str, Sequence[Token]]] = []
    if binding == "js":
        for at, token in enumerate(tokens):
            if token.value != name:
                continue
            # `const fold = (want) => { ... }`
            if (
                at >= 1
                and at + 2 < len(tokens)
                and tokens[at + 1].value == "="
            ):
                candidate = _arrow_callback(tokens[at + 2 :])
                if candidate is not None:
                    found.append(candidate)
            # `function fold(want) { ... }`
            if (
                at >= 1
                and tokens[at - 1].value == "function"
                and at + 1 < len(tokens)
                and tokens[at + 1].value == "("
            ):
                close = _matching(tokens, at + 1)
                if close is None or close + 1 >= len(tokens):
                    continue
                parameter = _parameter_from_typed(tokens[at + 2 : close])
                if parameter is None or tokens[close + 1].value != "{":
                    continue
                body_close = _matching(tokens, close + 1)
                if body_close is not None:
                    found.append(
                        (parameter, tokens[close + 2 : body_close])
                    )
    elif binding == "cs":
        for at, token in enumerate(tokens):
            if (
                token.value != name
                or at + 1 >= len(tokens)
                or tokens[at + 1].value != "("
                or (at and tokens[at - 1].value == ".")
            ):
                continue
            close = _matching(tokens, at + 1)
            if close is None:
                continue
            params = _split_top_level(tokens[at + 2 : close])
            if not params:
                continue
            parameter = _parameter_from_typed(params[0])
            if parameter is None or close + 1 >= len(tokens):
                continue
            if tokens[close + 1].value == "{":
                body_close = _matching(tokens, close + 1)
                if body_close is not None:
                    found.append(
                        (parameter, tokens[close + 2 : body_close])
                    )
            elif tokens[close + 1].value == "=>":
                found.append((parameter, tokens[close + 2 :]))
    return found


def _scan_c_like(binding: str, text: str, display: str) -> list[str]:
    tokens = _lex(text, rust_lifetimes=binding == "rs")
    errors: list[str] = []
    names = CALL_NAMES[binding]
    for at, token in enumerate(tokens):
        if token.value not in names or _definition_call(binding, tokens, at):
            continue
        if at + 1 >= len(tokens) or tokens[at + 1].value != "(":
            continue
        close = _matching(tokens, at + 1)
        if close is None:
            errors.append(f"{display}:{token.line}: {token.value}: unclosed call")
            continue
        args = _split_top_level(tokens[at + 2 : close])
        trailing: Sequence[Token] = ()
        if binding == "kt" and close + 1 < len(tokens) and tokens[close + 1].value == "{":
            trailing_close = _matching(tokens, close + 1)
            if trailing_close is not None:
                trailing = tokens[close + 1 : trailing_close + 1]
        callback = _callback_for(binding, args, trailing)
        if callback is None and binding in {"cs", "js"}:
            callback_index = 1 if binding == "cs" else 2
            if len(args) > callback_index:
                callback_ids = _identifiers(args[callback_index])
                if len(callback_ids) == 1:
                    candidates = _resolve_named_callback(
                        binding, callback_ids[0], tokens
                    )
                    if candidates and all(
                        _body_uses(body, name) for name, body in candidates
                    ):
                        callback = candidates[0]
        if callback is None:
            errors.append(
                f"{display}:{token.line}: {token.value}: callback must expose one named "
                "fixture-value parameter"
            )
            continue
        name, body = callback
        if not _body_uses(body, name):
            errors.append(
                f"{display}:{token.line}: {token.value}: callback parameter `{name}` "
                "is never read"
            )
    return errors


class _PythonDefinitions(ast.NodeVisitor):
    def __init__(self) -> None:
        self.by_name: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.by_name.setdefault(node.name, []).append(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.by_name.setdefault(node.name, []).append(node)
        self.generic_visit(node)


def _python_arg_used(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Load)
        and child.id == name
        for child in ast.walk(node)
    )


def _scan_python(text: str, display: str) -> list[str]:
    try:
        tree = ast.parse(text, filename=display)
    except SyntaxError as error:
        return [f"{display}:{error.lineno or 1}: cannot parse: {error.msg}"]
    definitions = _PythonDefinitions()
    definitions.visit(tree)
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if function_name not in {"assert_key_with", "assert_key_into"}:
            continue
        callback: ast.AST | None = node.args[2] if len(node.args) > 2 else None
        if callback is None:
            callback = next(
                (kw.value for kw in node.keywords if kw.arg == "check"), None
            )
        if callback is None:
            errors.append(
                f"{display}:{node.lineno}: {function_name}: callback is required; "
                "returning a raw fixture value marks it asserted before any comparison"
            )
            continue
        if isinstance(callback, ast.Lambda):
            if not callback.args.args:
                errors.append(
                    f"{display}:{node.lineno}: {function_name}: callback must expose "
                    "one named fixture-value parameter"
                )
                continue
            name = callback.args.args[0].arg
            if name == "_" or not _python_arg_used(callback.body, name):
                errors.append(
                    f"{display}:{node.lineno}: {function_name}: callback parameter "
                    f"`{name}` is never read"
                )
            continue
        if isinstance(callback, ast.Name):
            candidates = definitions.by_name.get(callback.id, [])
            if not candidates:
                errors.append(
                    f"{display}:{node.lineno}: {function_name}: cannot resolve callback "
                    f"`{callback.id}`"
                )
                continue
            for candidate in candidates:
                if not candidate.args.args:
                    errors.append(
                        f"{display}:{node.lineno}: {function_name}: callback "
                        f"`{callback.id}` has no fixture-value parameter"
                    )
                    continue
                name = candidate.args.args[0].arg
                if name == "_" or not any(
                    _python_arg_used(statement, name) for statement in candidate.body
                ):
                    errors.append(
                        f"{display}:{node.lineno}: {function_name}: callback "
                        f"`{callback.id}` never reads `{name}`"
                    )
            continue
        errors.append(
            f"{display}:{node.lineno}: {function_name}: unsupported callback shape "
            f"`{type(callback).__name__}`"
        )
    return errors


def _zig_definitions(tokens: Sequence[Token]) -> dict[str, list[tuple[str | None, Sequence[Token]]]]:
    definitions: dict[str, list[tuple[str | None, Sequence[Token]]]] = {}
    for at, token in enumerate(tokens):
        if token.value != "fn" or at + 2 >= len(tokens):
            continue
        name = tokens[at + 1].value
        if not IDENT.fullmatch(name) or tokens[at + 2].value != "(":
            continue
        close = _matching(tokens, at + 2)
        if close is None:
            continue
        params = _split_top_level(tokens[at + 3 : close])
        parameter: str | None = None
        if params:
            ids = _identifiers(params[-1])
            if ids and ids[0] != "_":
                parameter = ids[0]
        try:
            body_open = next(
                i for i in range(close + 1, len(tokens)) if tokens[i].value == "{"
            )
        except StopIteration:
            continue
        body_close = _matching(tokens, body_open)
        if body_close is None:
            continue
        definitions.setdefault(name, []).append(
            (parameter, tokens[body_open + 1 : body_close])
        )
    return definitions


def _scan_zig(text: str, display: str) -> list[str]:
    tokens = _lex(text)
    definitions = _zig_definitions(tokens)
    errors: list[str] = []
    for at, token in enumerate(tokens):
        if token.value not in CALL_NAMES["zig"] or _definition_call("zig", tokens, at):
            continue
        if at + 1 >= len(tokens) or tokens[at + 1].value != "(":
            continue
        close = _matching(tokens, at + 1)
        if close is None:
            errors.append(f"{display}:{token.line}: {token.value}: unclosed call")
            continue
        args = _split_top_level(tokens[at + 2 : close])
        if len(args) < 3:
            errors.append(
                f"{display}:{token.line}: {token.value}: missing callback argument"
            )
            continue
        callback_ids = _identifiers(args[2])
        callback_name = callback_ids[-1] if callback_ids else ""
        candidates = definitions.get(callback_name, [])
        if not candidates:
            errors.append(
                f"{display}:{token.line}: {token.value}: cannot resolve callback "
                f"`{callback_name or '<expression>'}`"
            )
            continue
        if not any(
            parameter is not None and _body_uses(body, parameter)
            for parameter, body in candidates
        ):
            errors.append(
                f"{display}:{token.line}: {token.value}: callback `{callback_name}` "
                "never reads its fixture-value parameter"
            )
    return errors


def scan_text(binding: str, text: str, display: str) -> list[str]:
    if binding == "py":
        return _scan_python(text, display)
    if binding == "zig":
        return _scan_zig(text, display)
    return _scan_c_like(binding, text, display)


def run_binding(binding: str, root: Path) -> list[str]:
    paths: set[Path] = set()
    for pattern in SOURCE_GLOBS[binding]:
        paths.update(root.glob(pattern))
    if not paths:
        return [f"{root}: no source files matched {SOURCE_GLOBS[binding]}"]
    errors: list[str] = []
    for path in sorted(paths):
        if not path.is_file():
            continue
        relative = str(path.relative_to(root))
        if relative in SOURCE_EXCLUDES.get(binding, frozenset()):
            continue
        errors.extend(
            scan_text(binding, path.read_text(encoding="utf-8"), relative)
        )
    return errors


SELF_TESTS: dict[str, tuple[str, str]] = {
    "cpp": (
        'keys.assert_key_with("k", [&](const Json& want) { return want.is_bool(); });',
        'keys.assert_key_with("k", [&](const Json& want) { return true; });',
    ),
    "cs": (
        'keys.AssertKeyWith("k", want => Assert.True(want.GetBoolean()));',
        'keys.AssertKeyWith("k", want => Assert.True(true));',
    ),
    "dart": (
        "assertKeyWith(block, 'k', (want) => expect(want, isTrue));",
        "assertKeyWith(block, 'k', (want) => expect(true, isTrue));",
    ),
    "go": (
        'assertKeyWith(t, block, "k", func(want any) { check(want) })',
        'assertKeyWith(t, block, "k", func(want any) { check(true) })',
    ),
    "js": (
        'assertKeyWith(block, "k", (want) => assert.equal(actual, want));',
        'assertKeyWith(block, "k", (want) => assert.equal(actual, true));',
    ),
    "kt": (
        'keys.assertKeyWith("k") { want -> assertEquals(want, actual) }',
        'keys.assertKeyWith("k") { want -> assertEquals(true, actual) }',
    ),
    "py": (
        'assert_key_with(block, "k", lambda want: actual == want)',
        'assert_key_with(block, "k", lambda want: actual == True)',
    ),
    "rs": (
        'keys.assert_key_with("k", |want| assert_eq!(actual, want));',
        'keys.assert_key_with("k", |want| assert!(actual));',
    ),
    "zig": (
        """
        fn check(_: void, want: Value) !void { try expect(want); }
        try keys.assertKeyWith("k", {}, check);
        """,
        """
        fn check(_: void, want: Value) !void { try expect(true); }
        try keys.assertKeyWith("k", {}, check);
        """,
    ),
}


def self_test() -> list[str]:
    failures: list[str] = []
    for binding, (accepted, ignored) in SELF_TESTS.items():
        accepted_errors = scan_text(binding, accepted, f"<{binding}:accepted>")
        ignored_errors = scan_text(binding, ignored, f"<{binding}:ignored>")
        if accepted_errors:
            failures.append(f"{binding}: accepted callback rejected: {accepted_errors}")
        if not ignored_errors:
            failures.append(f"{binding}: ignored callback was accepted")
        # Comments and strings are negative controls: spelling the parameter in
        # prose must not turn a vacuous callback green.
        prose_only = ignored.replace(
            "true", '"want is documented here"', 1
        )
        if binding not in {"py", "zig"} and not scan_text(
            binding, prose_only, f"<{binding}:prose-only>"
        ):
            failures.append(f"{binding}: string/comment text counted as a read")
        if binding == "py":
            projection_accepted = scan_text(
                binding,
                'assert_key_into(block, "k", lambda want: want)',
                "<py:projection-accepted>",
            )
            projection_ignored = scan_text(
                binding,
                'assert_key_into(block, "k", lambda want: True)',
                "<py:projection-ignored>",
            )
            if projection_accepted:
                failures.append(
                    f"py: accepted projection rejected: {projection_accepted}"
                )
            if not projection_ignored:
                failures.append("py: ignored projection was accepted")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", choices=sorted(SOURCE_GLOBS))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        errors = self_test()
        label = "self-test"
    elif args.binding:
        errors = run_binding(args.binding, args.root.resolve())
        label = args.binding
    else:
        parser.error("choose --self-test or --binding")

    if errors:
        for error in errors:
            print(f"assert-with consumption error: {error}", file=sys.stderr)
        return 1
    print(f"assert-with consumption OK: {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
