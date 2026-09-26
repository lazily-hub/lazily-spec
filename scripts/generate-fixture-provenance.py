#!/usr/bin/env python3
"""Generate exact Apache-2.0 provenance for canonical and vendored fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
GO_ROOT = ROOT.parent / "lazily-go"
OUTPUT = ROOT / "provenance" / "fixtures.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_simulation_metadata(path: Path) -> None:
    relative = path.relative_to(ROOT).as_posix()
    if not relative.startswith("conformance/simulation/"):
        return
    value = json.loads(path.read_text())
    required = {"schema_version", "origin", "license", "generator", "seed"}
    missing = sorted(required - set(value))
    if missing:
        raise SystemExit(f"{relative}: generated simulation fixture missing {missing}")
    generator = value["generator"]
    if not isinstance(generator, dict) or not {"path", "version"} <= set(generator):
        raise SystemExit(f"{relative}: generator needs path and version")
    if value["license"] != "Apache-2.0":
        raise SystemExit(f"{relative}: license must be Apache-2.0")


def inventory() -> dict:
    canonical_paths = sorted((ROOT / "conformance").rglob("*.json"))
    canonical = []
    for path in canonical_paths:
        validate_simulation_metadata(path)
        canonical.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": digest(path),
            "origin": "first-party-lazily-spec",
            "license": "Apache-2.0",
        })

    vendored = []
    vendored_root = GO_ROOT / "test" / "conformance"
    if vendored_root.exists():
        for path in sorted(vendored_root.rglob("*.json")):
            relative = path.relative_to(GO_ROOT).as_posix()
            canonical_path = "conformance/" + path.relative_to(vendored_root).as_posix()
            source = ROOT / canonical_path
            if not source.exists() or source.read_bytes() != path.read_bytes():
                raise SystemExit(f"{relative}: vendored bytes differ from {canonical_path}")
            vendored.append({
                "repository": "lazily-go",
                "path": relative,
                "canonical_path": canonical_path,
                "sha256": digest(path),
                "license": "Apache-2.0",
            })
    elif OUTPUT.exists():
        vendored = json.loads(OUTPUT.read_text())["vendored_copies"]

    return {
        "schema_version": 1,
        "repository_license": "Apache-2.0",
        "fixture_reuse_terms": "Apache-2.0",
        "canonical_fixtures": canonical,
        "vendored_copies": vendored,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(inventory(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
            print(f"{OUTPUT.relative_to(ROOT)} is stale; regenerate it", file=sys.stderr)
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
