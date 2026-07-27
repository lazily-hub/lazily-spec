#!/usr/bin/env python3
"""Check the async-v2 public naming contract across sibling bindings."""

from __future__ import annotations

import re
import sys
from pathlib import Path


SPEC_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_SRC = SPEC_ROOT.parent

BINDINGS = {
    "lazily-rs": (
        "src/async_context.rs",
        r"\bpub\s+struct\s+AsyncSource\b",
        r"\bpub\s+struct\s+AsyncComputed\b",
    ),
    "lazily-js": (
        "src/reactive-async.d.ts",
        r"\bexport\s+class\s+AsyncSource\b",
        r"\bexport\s+class\s+AsyncComputed\b",
    ),
    "lazily-kt": (
        "src/main/kotlin/io/github/lazily/AsyncContext.kt",
        r"\bclass\s+AsyncSource\b",
        r"\bclass\s+AsyncComputed\b",
    ),
    "lazily-cs": (
        "src/Lazily/AsyncContext.cs",
        r"\bclass\s+AsyncSource\b",
        r"\bclass\s+AsyncComputed\b",
    ),
    "lazily-cpp": (
        "include/lazily/async_context.hpp",
        r"\bstruct\s+AsyncSource\b",
        r"\bstruct\s+AsyncComputed\b",
    ),
    "lazily-go": (
        "async_context.go",
        r"\btype\s+AsyncSource\[",
        r"\btype\s+AsyncComputed\[",
    ),
    "lazily-py": (
        "src/lazily/async_context.py",
        r"\bclass\s+AsyncSource\[",
        r"\bclass\s+AsyncComputed\[",
    ),
    "lazily-zig": (
        "src/lazily/async_context.zig",
        r"\bpub\s+fn\s+AsyncSource\b",
        r"\bpub\s+fn\s+AsyncComputed\b",
    ),
}

LEGACY_NAMES = ("AsyncCellHandle", "AsyncSlotHandle")
LEGACY_DECLARATION = re.compile(
    r"\b(class|const|type|using)\b"
    r"|^\s*(?:export\s+)?(?:AsyncCellHandle|AsyncSlotHandle)\s*="
)


def fail(message: str) -> None:
    print(f"async-v2-names: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_binding(name: str, relative: str, source_pat: str, computed_pat: str) -> None:
    path = WORKSPACE_SRC / name / relative
    if not path.exists():
        print(f"async-v2-names: SKIP {name} (sibling checkout absent)")
        return

    text = path.read_text(encoding="utf-8")
    if re.search(source_pat, text) is None:
        fail(f"{name}: no canonical AsyncSource declaration in {relative}")
    if re.search(computed_pat, text) is None:
        fail(f"{name}: no canonical AsyncComputed declaration in {relative}")

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not any(legacy in line for legacy in LEGACY_NAMES):
            continue
        if LEGACY_DECLARATION.search(line) is None:
            continue
        window = "\n".join(lines[max(0, index - 3) : min(len(lines), index + 4)])
        if re.search(r"\b(deprecated|compatibility)\b", window, re.IGNORECASE) is None:
            fail(
                f"{name}:{relative}:{index + 1}: legacy declaration lacks "
                "an explicit deprecated/compatibility marker"
            )

    print(f"async-v2-names: OK {name}")


def main() -> None:
    async_doc = (SPEC_ROOT / "docs/async.md").read_text(encoding="utf-8")
    for required in ("AsyncSource", "AsyncComputed", "AsyncComputedState"):
        if required not in async_doc:
            fail(f"docs/async.md does not define {required}")

    for name, values in BINDINGS.items():
        check_binding(name, *values)


if __name__ == "__main__":
    main()
