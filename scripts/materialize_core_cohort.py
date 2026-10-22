#!/usr/bin/env python3
"""Materialize and verify every byte named by a Core cohort manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    resolved_root = root.resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise ValueError(f"path escapes materialization root: {relative}")
    return target


def entries(manifest: dict[str, Any]) -> Iterable[tuple[str, str, str]]:
    for binding in manifest["bindings"]:
        for package in binding["packages"]:
            for artifact in package["artifacts"]:
                yield artifact["file"], artifact["sha256"], artifact["uri"]
                provenance = artifact["provenance"]
                yield provenance["file"], provenance["sha256"], provenance["uri"]
                registry = artifact["registry"]
                yield (
                    registry["metadata_file"],
                    registry["metadata_sha256"],
                    registry["url"],
                )
        for gate in binding["gates"]:
            yield gate["evidence_file"], gate["evidence_sha256"], ""


def request(url: str) -> urllib.request.Request:
    headers = {"User-Agent": "lazily-core-cohort-materializer/1"}
    actor = os.environ.get("GITHUB_ACTOR")
    token = os.environ.get("GITHUB_TOKEN")
    if "maven.pkg.github.com" in url:
        if not actor or not token:
            raise RuntimeError(
                "GITHUB_ACTOR and GITHUB_TOKEN are required for GitHub Packages"
            )
        encoded = base64.b64encode(f"{actor}:{token}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
    return urllib.request.Request(url, headers=headers)


def materialize(
    manifest: dict[str, Any], output: Path, seed_root: Path | None
) -> list[str]:
    output.mkdir(parents=True, exist_ok=True)
    seen: dict[str, str] = {}
    written: list[str] = []
    for relative, expected, url in entries(manifest):
        if relative in seen:
            if seen[relative] != expected:
                raise ValueError(f"conflicting digests for {relative}")
            continue
        seen[relative] = expected
        target = safe_path(output, relative)
        source = safe_path(seed_root, relative) if seed_root is not None else None
        target.parent.mkdir(parents=True, exist_ok=True)
        if source is not None and source.is_file():
            shutil.copyfile(source, target)
        elif url:
            with urllib.request.urlopen(request(url)) as response, target.open("wb") as stream:
                shutil.copyfileobj(response, stream)
        else:
            raise FileNotFoundError(f"no seed file or download URI for {relative}")
        actual = sha256_file(target)
        if actual != expected:
            target.unlink(missing_ok=True)
            raise ValueError(
                f"sha256 mismatch for {relative}: expected {expected}, got {actual}"
            )
        written.append(relative)
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    try:
        written = materialize(manifest, args.output, args.seed_root)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"cohort materialization failed: {error}")
        return 1
    print(f"materialized {len(written)} immutable cohort files in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
