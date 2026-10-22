#!/usr/bin/env python3
"""Run every cohort binding's clean consumer against its published version."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any


REPOSITORIES = {
    "rust": "lazily-rs",
    "javascript": "lazily-js",
    "python": "lazily-py",
    "go": "lazily-go",
    "kotlin": "lazily-kt",
    "cpp": "lazily-cpp",
    "csharp": "lazily-cs",
    "dart": "lazily-dart",
    "zig": "lazily-zig",
}

CORE_COORDINATES = {
    "rust": "lazily",
    "javascript": "@lazily-hub/lazily-js",
    "python": "lazily",
    "go": "github.com/lazily-hub/lazily-go",
    "kotlin": "io.github.lazily:lazily",
    "cpp": "lazily-hub/lazily-cpp",
    "csharp": "Lazily",
    "dart": "lazily",
    "zig": "lazily-hub/lazily-zig",
}


def run(manifest: dict[str, Any], bindings_root: Path) -> list[str]:
    completed: list[str] = []
    for binding in manifest["bindings"]:
        binding_id = binding["id"]
        packages = [
            package
            for package in binding["packages"]
            if package["coordinate"] == CORE_COORDINATES[binding_id]
        ]
        if len(packages) != 1 or len(packages[0]["artifacts"]) != 1:
            raise ValueError(f"{binding_id} must name exactly one Core package artifact")
        package = packages[0]
        artifact = package["artifacts"][0]
        repository = bindings_root / REPOSITORIES[binding_id]
        script = repository / "scripts" / "core-artifact-consumer-check.sh"
        if not script.is_file():
            raise FileNotFoundError(f"missing published consumer for {binding_id}: {script}")
        environment = os.environ.copy()
        environment["LAZILY_CORE_ARTIFACT_VERSION"] = package["version"]
        environment["LAZILY_CORE_ARTIFACT_SHA256"] = artifact["sha256"]
        subprocess.run([str(script)], cwd=repository, env=environment, check=True)
        completed.append(binding_id)
    return completed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--bindings-root", type=Path, default=Path(".."))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    try:
        completed = run(manifest, args.bindings_root)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"published consumer qualification failed: {error}")
        return 1
    print(f"published consumers passed: {', '.join(completed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
