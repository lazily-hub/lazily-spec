#!/usr/bin/env python3
"""Check every binding against the SQLite store contract (#lazilysqlitestoreopen).

``sqlite-stores.json`` is the contract and the ledger in one file: the contract
(an explicit busy timeout, no deferred read-then-write transactions) plus one
declaration per binding saying whether it ships a SQLite store and, if it does,
where the busy timeout is declared, which two-writer regression tests exercise
it, and which guard bans deferred transactions.

This script verifies those declarations against the sibling binding checkouts:

* a binding declared ``"none"`` has no SQLite driver use anywhere under its
  ``scan_roots`` -- a new SQLite path cannot land without declaring the contract;
* a binding that OWNS its connection uses a driver only in its declared
  ``driver_files``; its declared busy timeout equals the contract's, and the
  declaration text appears verbatim in the declared file; every declared
  two-writer test and the timeout test exist; the deferred-transaction guard
  carries every declared token;
* a binding over a HOST-owned connection (it opens none itself) states the
  host's obligation, carrying the contract marker, in the declared file.

The checks are static on purpose. Behaviour -- the second writer waiting and
then landing, failing at timeout zero -- is each binding's own two-writer test;
this guard makes those tests and the shared value impossible to drop silently.

Without ``--require-all`` a missing sibling is skipped (local checkouts);
spec CI passes ``--require-all`` after cloning every sibling.
``--sparse-paths BINDING`` prints the paths a sparse clone needs for the check.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "sqlite-stores.json"

CODE_SUFFIXES = {
    ".rs", ".py", ".pyx", ".go", ".kt", ".kts", ".java", ".js", ".mjs", ".cjs",
    ".ts", ".mts", ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".cs",
    ".dart", ".zig", ".gd",
}
SKIP_DIRS = {
    ".git", "node_modules", "target", "build", "dist", "vendor", "bin", "obj",
    ".zig-cache", "zig-out", "zig-cache", ".gradle", ".venv", "__pycache__",
    ".dart_tool", ".godot",
}


def load_registry(path: Path = REGISTRY) -> dict:
    return json.loads(path.read_text())


def _scan_files(repo: Path, scan_roots: list[str]) -> list[Path]:
    files: list[Path] = []
    for root in scan_roots:
        base = repo if root == "." else repo / root
        if not base.is_dir():
            continue
        # "." is the repository's top level only (Go keeps its package there);
        # every other root is walked recursively.
        candidates = base.iterdir() if root == "." else base.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix not in CODE_SUFFIXES:
                continue
            rel_parts = path.relative_to(repo).parts
            if any(part in SKIP_DIRS for part in rel_parts[:-1]):
                continue
            if path.name.endswith("_test.go"):
                continue
            files.append(path)
    return sorted(files)


def driver_hits(repo: Path, scan_roots: list[str], drivers: list[dict]) -> dict[str, set[str]]:
    """Map each scanned file (repo-relative) to the driver ids it uses."""
    compiled = [(d["id"], re.compile(d["pattern"], re.MULTILINE)) for d in drivers]
    hits: dict[str, set[str]] = {}
    for path in _scan_files(repo, scan_roots):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        found = {driver_id for driver_id, rx in compiled if rx.search(text)}
        if found:
            hits[path.relative_to(repo).as_posix()] = found
    return hits


def _read(repo: Path, rel: str, binding: str, problems: list[str]) -> str | None:
    path = repo / rel
    if not path.is_file():
        problems.append(f"{binding}: declared file {rel} does not exist")
        return None
    return path.read_text(errors="replace")


def _has_identifier(text: str, name: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text) is not None


def registry_problems(registry: dict, expected_bindings: list[str] | None = None) -> list[str]:
    """Self-consistency of the registry alone (no sibling checkouts needed)."""
    problems: list[str] = []
    contract_ms = registry["contract"]["busy_timeout_ms"]
    names = [entry["binding"] for entry in registry["bindings"]]
    if len(names) != len(set(names)):
        problems.append(f"bindings listed more than once: {sorted(n for n in names if names.count(n) > 1)}")
    if expected_bindings is not None and sorted(names) != sorted(expected_bindings):
        problems.append(
            f"registry bindings {sorted(names)} != the binding set {sorted(expected_bindings)}: "
            "every binding must declare its SQLite store, or \"none\""
        )
    for entry in registry["bindings"]:
        if entry["repo"] != f"lazily-{entry['binding']}":
            problems.append(f"{entry['binding']}: repo {entry['repo']!r} != lazily-{entry['binding']}")
        sqlite = entry["sqlite"]
        if isinstance(sqlite, dict) and sqlite["connection"] == "owned":
            if sqlite["busy_timeout"]["ms"] != contract_ms:
                problems.append(
                    f"{entry['binding']}: busy timeout {sqlite['busy_timeout']['ms']} ms "
                    f"!= the contract's {contract_ms} ms"
                )
    for driver in registry["drivers"]:
        try:
            re.compile(driver["pattern"])
        except re.error as exc:
            problems.append(f"driver {driver['id']}: invalid pattern: {exc}")
    return problems


def binding_problems(entry: dict, repo: Path, drivers: list[dict]) -> list[str]:
    """Verify one binding's declaration against its checkout at ``repo``."""
    binding = entry["binding"]
    problems: list[str] = []
    scanned = _scan_files(repo, entry["scan_roots"])
    if not scanned:
        problems.append(
            f"{binding}: scan_roots {entry['scan_roots']} hold no source files under {repo} "
            "(a scan of nothing proves nothing)"
        )
    hits = driver_hits(repo, entry["scan_roots"], drivers)
    sqlite = entry["sqlite"]
    if sqlite == "none":
        for rel, ids in sorted(hits.items()):
            problems.append(
                f"{binding}: declared sqlite \"none\" but {rel} uses {sorted(ids)}; "
                "declare the store and its contract evidence in sqlite-stores.json"
            )
        return problems

    if sqlite["connection"] == "host":
        for rel, ids in sorted(hits.items()):
            problems.append(
                f"{binding}: declared a host-owned connection but {rel} uses {sorted(ids)} itself"
            )
        obligation = sqlite["obligation"]
        text = _read(repo, obligation["file"], binding, problems)
        if text is not None and obligation["marker"] not in text:
            problems.append(f"{binding}: {obligation['file']} does not state the host obligation {obligation['marker']}")
        if text is not None and not _has_identifier(text, sqlite["store"]):
            problems.append(f"{binding}: {obligation['file']} does not define {sqlite['store']}")
        return problems

    allowed = set(sqlite["driver_files"])
    for rel, ids in sorted(hits.items()):
        if rel not in allowed:
            problems.append(f"{binding}: {rel} uses {sorted(ids)} but is not a declared driver file")
    for rel in sorted(allowed - set(hits)):
        problems.append(f"{binding}: declared driver file {rel} uses no SQLite driver (stale declaration)")

    timeout = sqlite["busy_timeout"]
    text = _read(repo, timeout["file"], binding, problems)
    if text is not None:
        if timeout["declaration"] not in text:
            problems.append(f"{binding}: {timeout['file']} lacks the declared busy timeout `{timeout['declaration']}`")
        if not _has_identifier(text, sqlite["store"]):
            problems.append(f"{binding}: {timeout['file']} does not define {sqlite['store']}")

    # The busy-timeout test lives beside the two-writer tests.
    two_writer = sqlite["two_writer_tests"]
    text = _read(repo, two_writer["file"], binding, problems)
    if text is not None:
        for name in [*two_writer["names"], timeout["test"]]:
            if not _has_identifier(text, name):
                problems.append(f"{binding}: {two_writer['file']} has no test {name}")

    guard = sqlite["deferred_transaction_guard"]
    text = _read(repo, guard["file"], binding, problems)
    if text is not None:
        for token in guard["tokens"]:
            if token not in text:
                problems.append(f"{binding}: deferred-transaction guard {guard['file']} lacks `{token}`")
    return problems


def sparse_paths(entry: dict) -> list[str]:
    paths = {root for root in entry["scan_roots"] if root != "."}
    sqlite = entry["sqlite"]
    if isinstance(sqlite, dict):
        files = (
            [sqlite["obligation"]["file"]]
            if sqlite["connection"] == "host"
            else [
                *sqlite["driver_files"],
                sqlite["busy_timeout"]["file"],
                sqlite["two_writer_tests"]["file"],
                sqlite["deferred_transaction_guard"]["file"],
            ]
        )
        for rel in files:
            parent = Path(rel).parent.as_posix()
            if parent != ".":
                paths.add(parent)
    return sorted(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bindings-root", type=Path, default=ROOT.parent)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--sparse-paths", metavar="BINDING")
    args = parser.parse_args(argv)

    registry = load_registry(args.registry)
    if args.sparse_paths:
        (entry,) = [e for e in registry["bindings"] if e["binding"] == args.sparse_paths]
        print(" ".join(sparse_paths(entry)))
        return 0

    problems = registry_problems(registry)
    checked: list[str] = []
    skipped: list[str] = []
    for entry in registry["bindings"]:
        repo = args.bindings_root / entry["repo"]
        if not repo.is_dir():
            if args.require_all:
                problems.append(f"{entry['binding']}: sibling checkout {repo} is missing (--require-all)")
            else:
                skipped.append(entry["binding"])
            continue
        problems += binding_problems(entry, repo, registry["drivers"])
        checked.append(entry["binding"])

    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        print(f"sqlite-stores check FAILED: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    owned = [e["binding"] for e in registry["bindings"] if isinstance(e["sqlite"], dict) and e["sqlite"]["connection"] == "owned" and e["binding"] in checked]
    print(
        f"sqlite-stores check OK: {len(checked)} binding(s) checked "
        f"({', '.join(checked) or 'none'}); owned SQLite stores: {', '.join(owned) or 'none'}"
        + (f"; skipped (no sibling): {', '.join(skipped)}" if skipped else "")
    )
    if not checked:
        print("sqlite-stores check checked no binding at all", file=sys.stderr)
        return 1 if args.require_all else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
