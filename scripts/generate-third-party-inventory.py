#!/usr/bin/env python3
"""Generate the reviewed SPDX inventory for registry packages in uv.lock."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "uv.lock"
OUTPUT = ROOT / "third-party" / "uv-lock-licenses.json"
PROJECT = "lazily-spec-schemas"
DIRECT = {"jsonschema", "pytest", "referencing"}
LICENSES = {
    "attrs": ("MIT", "https://pypi.org/project/attrs/"),
    "colorama": ("BSD-3-Clause", "https://github.com/tartley/colorama"),
    "iniconfig": ("MIT", "https://pypi.org/project/iniconfig/"),
    "jsonschema": ("MIT", "https://github.com/python-jsonschema/jsonschema"),
    "jsonschema-specifications": ("MIT", "https://github.com/python-jsonschema/jsonschema-specifications"),
    "packaging": ("Apache-2.0 OR BSD-2-Clause", "https://github.com/pypa/packaging"),
    "pluggy": ("MIT", "https://github.com/pytest-dev/pluggy"),
    "pygments": ("BSD-2-Clause", "https://github.com/pygments/pygments"),
    "pytest": ("MIT", "https://github.com/pytest-dev/pytest"),
    "referencing": ("MIT", "https://github.com/python-jsonschema/referencing"),
    "rpds-py": ("MIT", "https://github.com/crate-py/rpds"),
    "typing-extensions": ("PSF-2.0", "https://github.com/python/typing_extensions"),
}


def inventory() -> dict:
    lock_bytes = LOCK.read_bytes()
    lock = tomllib.loads(lock_bytes.decode())
    packages = {
        package["name"]: package
        for package in lock["package"]
        if package["name"] != PROJECT and "registry" in package.get("source", {})
    }
    if set(packages) != set(LICENSES):
        missing = sorted(set(packages) - set(LICENSES))
        stale = sorted(set(LICENSES) - set(packages))
        raise SystemExit(f"license review required: missing={missing} stale={stale}")
    return {
        "schema_version": 1,
        "source": "uv.lock",
        "source_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "packages": [
            {
                "name": name,
                "version": packages[name]["version"],
                "relationship": "direct-development" if name in DIRECT else "transitive-development",
                "license": LICENSES[name][0],
                "source_url": LICENSES[name][1],
                "notice_required": False,
            }
            for name in sorted(packages)
        ],
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
