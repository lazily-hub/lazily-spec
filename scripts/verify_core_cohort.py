#!/usr/bin/env python3
"""Validate an immutable Lazily Core cohort bill of materials.

The JSON Schema owns the document shape.  This module owns relationships that a
schema cannot express: exact tag/version and spec pins, compatible API ranges,
unique identities, content digests, and optional local Git source verification.
It intentionally performs no publishing and makes no registry credentials
available to a release job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker


EXPECTED_BINDINGS = {
    "rust",
    "javascript",
    "python",
    "go",
    "kotlin",
    "cpp",
    "csharp",
    "dart",
    "zig",
}
REQUIRED_GATES = {
    "profile",
    "api",
    "fixture",
    "package",
    "pre_publish_consumer",
    "published_consumer",
}
PRE_PUBLISH_GATES = REQUIRED_GATES - {"published_consumer"}
FLOATING_VALUES = {
    "head",
    "main",
    "master",
    "latest",
    "stable",
    "nightly",
    "current",
    "tip",
    "trunk",
}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_path(parts: Iterable[Any]) -> str:
    rendered = "$"
    for part in parts:
        rendered += f"[{part}]" if isinstance(part, int) else f".{part}"
    return rendered


def is_floating(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        normalized in FLOATING_VALUES
        or normalized.startswith("refs/heads/")
        or "*" in normalized
        or normalized.endswith(".x")
    )


def repository_name(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")


def safe_evidence_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"evidence path escapes root: {relative}")
    return candidate


def verify_digest(
    root: Path,
    relative: str,
    expected: str,
    label: str,
    errors: list[str],
) -> None:
    try:
        path = safe_evidence_path(root, relative)
    except ValueError as error:
        errors.append(f"{label}: {error}")
        return
    if not path.is_file():
        errors.append(f"{label}: missing evidence file {relative}")
        return
    actual = sha256_file(path)
    if actual != expected:
        errors.append(
            f"{label}: sha256 mismatch for {relative}: expected {expected}, got {actual}"
        )


def git_output(repo: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.returncode, result.stdout.strip()


def verify_source_pin(
    source: dict[str, Any],
    repo_root: Path,
    label: str,
    errors: list[str],
    *,
    checkout_commit: str | None = None,
) -> None:
    repo = repo_root / repository_name(source["repository"])
    if not (repo / ".git").exists() and not (repo / ".git").is_file():
        errors.append(f"{label}: missing source checkout {repo}")
        return

    if checkout_commit is not None:
        code, head = git_output(repo, "rev-parse", "HEAD")
        if code != 0:
            errors.append(f"{label}: cannot read HEAD for {repo}: {head}")
        elif head != checkout_commit:
            errors.append(
                f"{label}: qualification checkout mismatch: "
                f"expected {checkout_commit}, got {head}"
            )

    code, peeled = git_output(repo, "rev-parse", f"refs/tags/{source['tag']}^{{}}")
    if code != 0:
        code, peeled = git_output(repo, "rev-parse", f"refs/tags/{source['tag']}")
    if code != 0:
        errors.append(f"{label}: tag {source['tag']} is missing from {repo}")
    elif peeled != source["commit"]:
        errors.append(
            f"{label}: peeled tag {source['tag']} is {peeled}, not {source['commit']}"
        )


def validate_schema(
    manifest: dict[str, Any], schema: dict[str, Any]
) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{json_path(error.absolute_path)}: {error.message}"
        for error in sorted(
            validator.iter_errors(manifest), key=lambda item: json_path(item.absolute_path)
        )
    ]


def validate_semantics(
    manifest: dict[str, Any],
    *,
    artifact_root: Path | None = None,
    repo_root: Path | None = None,
    spec_root: Path | None = None,
    require_publish_ready: bool = False,
    require_final: bool = False,
    expected_spec_commit: str | None = None,
    expected_binding: str | None = None,
    expected_commit: str | None = None,
    expected_tag: str | None = None,
    expected_qualification_commit: str | None = None,
) -> list[str]:
    errors: list[str] = []
    spec = manifest["spec"]
    bindings = manifest["bindings"]
    spec_revision = manifest["conformance_revision"]
    api_generation = manifest["core_api_generation"]
    wire_version = manifest["wire_version"]

    if spec["commit"] != spec_revision:
        errors.append("$.spec.commit must equal $.conformance_revision")
    if expected_spec_commit is not None and spec["commit"] != expected_spec_commit:
        errors.append(
            f"$.spec.commit {spec['commit']} does not match "
            f"--expected-spec-commit {expected_spec_commit}"
        )
    if is_floating(spec["tag"]):
        errors.append("$.spec.tag is floating")

    binding_ids = [binding["id"] for binding in bindings]
    duplicates = sorted({item for item in binding_ids if binding_ids.count(item) > 1})
    if duplicates:
        errors.append(f"$.bindings contains duplicate ids: {', '.join(duplicates)}")

    if require_final:
        if manifest["state"] != "final":
            errors.append("$.state must be final when --require-final is used")
        present = set(binding_ids)
        if present != EXPECTED_BINDINGS:
            missing = sorted(EXPECTED_BINDINGS - present)
            extra = sorted(present - EXPECTED_BINDINGS)
            errors.append(
                "$.bindings must contain the complete nine-binding cohort"
                f" (missing={missing}, extra={extra})"
            )
        if manifest["profile"]["status"] != "beta":
            errors.append("$.profile.status must be beta for a final cohort")

    matched_expected_binding = False
    seen_coordinates: set[tuple[str, str]] = set()
    seen_artifacts: set[str] = set()

    for index, binding in enumerate(bindings):
        label = f"$.bindings[{index}] ({binding['id']})"
        source = binding["source"]
        if is_floating(source["tag"]):
            errors.append(f"{label}.source.tag is floating")
        if binding["spec_revision"] != spec_revision:
            errors.append(f"{label}.spec_revision does not match the cohort spec revision")
        if binding["fixture_revision"] != spec_revision:
            errors.append(f"{label}.fixture_revision does not match the cohort spec revision")

        if binding["profile"] != "preview":
            if binding["core_api_generation"] != api_generation:
                errors.append(f"{label}.core_api_generation does not match the cohort")
            if binding["wire_version"] != wire_version:
                errors.append(f"{label}.wire_version does not match the cohort")

        core_range = binding["compatibility"]["core_api"]
        if core_range["minimum"] > core_range["maximum"]:
            errors.append(f"{label}.compatibility.core_api has an inverted range")
        if not core_range["minimum"] <= api_generation <= core_range["maximum"]:
            errors.append(
                f"{label}.compatibility.core_api does not include generation {api_generation}"
            )
        for module_index, module in enumerate(binding["compatibility"]["modules"]):
            module_label = f"{label}.compatibility.modules[{module_index}]"
            if module["minimum_core_api"] > module["maximum_core_api"]:
                errors.append(f"{module_label} has an inverted Core API range")
            if not (
                module["minimum_core_api"]
                <= api_generation
                <= module["maximum_core_api"]
            ):
                errors.append(
                    f"{module_label} does not include generation {api_generation}"
                )

        toolchain_names: set[str] = set()
        for toolchain_index, toolchain in enumerate(binding["toolchains"]):
            toolchain_label = f"{label}.toolchains[{toolchain_index}]"
            if toolchain["name"] in toolchain_names:
                errors.append(f"{toolchain_label} repeats toolchain {toolchain['name']}")
            toolchain_names.add(toolchain["name"])
            if is_floating(toolchain["minimum"]):
                errors.append(f"{toolchain_label}.minimum is floating")
            if is_floating(toolchain["current"]):
                errors.append(f"{toolchain_label}.current is floating")

        package_versions = {package["version"] for package in binding["packages"]}
        expected_tags = {f"v{version}" for version in package_versions}
        if expected_tags != {source["tag"]}:
            errors.append(
                f"{label}.source.tag {source['tag']} does not exactly match package versions "
                f"{sorted(package_versions)}"
            )

        for package_index, package in enumerate(binding["packages"]):
            package_label = f"{label}.packages[{package_index}]"
            coordinate_key = (package["ecosystem"], package["coordinate"])
            if coordinate_key in seen_coordinates:
                errors.append(
                    f"{package_label} repeats package coordinate "
                    f"{package['ecosystem']}:{package['coordinate']}"
                )
            seen_coordinates.add(coordinate_key)
            for artifact_index, artifact in enumerate(package["artifacts"]):
                artifact_label = f"{package_label}.artifacts[{artifact_index}]"
                if artifact["file"] in seen_artifacts:
                    errors.append(f"{artifact_label} repeats artifact file {artifact['file']}")
                seen_artifacts.add(artifact["file"])
                if require_final and artifact["registry"]["status"] != "available":
                    errors.append(f"{artifact_label}.registry.status must be available")
                if artifact_root is not None:
                    verify_digest(
                        artifact_root,
                        artifact["file"],
                        artifact["sha256"],
                        artifact_label,
                        errors,
                    )
                    provenance = artifact["provenance"]
                    verify_digest(
                        artifact_root,
                        provenance["file"],
                        provenance["sha256"],
                        f"{artifact_label}.provenance",
                        errors,
                    )
                    registry = artifact["registry"]
                    verify_digest(
                        artifact_root,
                        registry["metadata_file"],
                        registry["metadata_sha256"],
                        f"{artifact_label}.registry",
                        errors,
                    )

        gate_names = [gate["name"] for gate in binding["gates"]]
        duplicate_gates = sorted({name for name in gate_names if gate_names.count(name) > 1})
        missing_gates = sorted(REQUIRED_GATES - set(gate_names))
        extra_gates = sorted(set(gate_names) - REQUIRED_GATES)
        if duplicate_gates:
            errors.append(f"{label}.gates contains duplicates: {', '.join(duplicate_gates)}")
        if missing_gates or extra_gates:
            errors.append(
                f"{label}.gates must contain the exact gate set"
                f" (missing={missing_gates}, extra={extra_gates})"
            )

        for gate_index, gate in enumerate(binding["gates"]):
            gate_label = f"{label}.gates[{gate_index}] ({gate['name']})"
            required_to_pass = require_final or (
                require_publish_ready and gate["name"] in PRE_PUBLISH_GATES
            )
            if required_to_pass and gate["status"] != "passed":
                errors.append(f"{gate_label}.status must be passed")
            if artifact_root is not None:
                verify_digest(
                    artifact_root,
                    gate["evidence_file"],
                    gate["evidence_sha256"],
                    gate_label,
                    errors,
                )

        if repo_root is not None:
            verify_source_pin(
                source,
                repo_root,
                label,
                errors,
                checkout_commit=binding["qualification_commit"],
            )

        if expected_binding == binding["id"]:
            matched_expected_binding = True
            if expected_commit is not None and source["commit"] != expected_commit:
                errors.append(
                    f"{label}.source.commit {source['commit']} does not match "
                    f"--expected-commit {expected_commit}"
                )
            if expected_tag is not None and source["tag"] != expected_tag:
                errors.append(
                    f"{label}.source.tag {source['tag']} does not match "
                    f"--expected-tag {expected_tag}"
                )
            if (
                expected_qualification_commit is not None
                and binding["qualification_commit"] != expected_qualification_commit
            ):
                errors.append(
                    f"{label}.qualification_commit {binding['qualification_commit']} "
                    "does not match --expected-qualification-commit "
                    f"{expected_qualification_commit}"
                )

    if expected_binding is not None and not matched_expected_binding:
        errors.append(f"--expected-binding {expected_binding} is absent from the cohort")

    if repo_root is not None:
        verify_source_pin(spec, repo_root, "$.spec", errors)
    if spec_root is not None:
        verify_digest(
            spec_root,
            manifest["profile"]["registry_path"],
            manifest["profile"]["sha256"],
            "$.profile",
            errors,
        )

    return errors


def build_report(manifest: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    root = manifest if isinstance(manifest, dict) else {}
    bindings = []
    raw_bindings = root.get("bindings", [])
    if not isinstance(raw_bindings, list):
        raw_bindings = []
    for raw_binding in raw_bindings:
        binding = raw_binding if isinstance(raw_binding, dict) else {}
        raw_gates = binding.get("gates", [])
        if not isinstance(raw_gates, list):
            raw_gates = []
        gate_status = {
            gate.get("name"): gate.get("status")
            for gate in raw_gates
            if isinstance(gate, dict)
        }
        raw_packages = binding.get("packages", [])
        if not isinstance(raw_packages, list):
            raw_packages = []
        bindings.append(
            {
                "id": binding.get("id"),
                "profile": binding.get("profile"),
                "core_api_generation": binding.get("core_api_generation"),
                "fixture_revision": binding.get("fixture_revision"),
                "packages": [
                    {
                        "ecosystem": package.get("ecosystem"),
                        "coordinate": package.get("coordinate"),
                        "version": package.get("version"),
                        "registry_statuses": [
                            artifact.get("registry", {}).get("status")
                            for artifact in package.get("artifacts", [])
                            if isinstance(artifact, dict)
                        ],
                    }
                    for package in raw_packages
                    if isinstance(package, dict)
                ],
                "api_status": gate_status.get("api", "missing"),
                "fixture_status": gate_status.get("fixture", "missing"),
                "package_status": gate_status.get("package", "missing"),
                "published_consumer_status": gate_status.get(
                    "published_consumer", "missing"
                ),
            }
        )
    return {
        "cohort_id": root.get("cohort_id"),
        "state": root.get("state"),
        "spec_revision": root.get("conformance_revision"),
        "status": "passed" if not errors else "failed",
        "bindings": bindings,
        "errors": errors,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Lazily Core cohort `{report['cohort_id']}`",
        "",
        f"Status: **{report['status']}**  ",
        f"State: `{report['state']}`  ",
        f"Spec revision: `{report['spec_revision']}`",
        "",
        "| Binding | Profile | API | Fixture | Package | Published consumer | Packages |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for binding in report["bindings"]:
        packages = ", ".join(
            f"{item['ecosystem']}:{item['coordinate']}@{item['version']}"
            for item in binding["packages"]
        )
        lines.append(
            "| {id} | {profile} | {api_status} | {fixture_status} | "
            "{package_status} | {published_consumer_status} | {packages} |".format(
                id=binding["id"],
                profile=binding["profile"],
                api_status=binding["api_status"],
                fixture_status=binding["fixture_status"],
                package_status=binding["package_status"],
                published_consumer_status=binding["published_consumer_status"],
                packages=packages,
            )
        )
    if report["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in report["errors"])
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "schemas" / "core-cohort.json",
    )
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--spec-root", type=Path)
    parser.add_argument("--require-publish-ready", action="store_true")
    parser.add_argument("--require-final", action="store_true")
    parser.add_argument("--expected-spec-commit")
    parser.add_argument("--expected-binding", choices=sorted(EXPECTED_BINDINGS))
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-tag")
    parser.add_argument("--expected-qualification-commit")
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--report-markdown", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = load_json(args.manifest)
        schema = load_json(args.schema)
    except (OSError, json.JSONDecodeError) as error:
        print(f"cohort verification failed: {error}", file=sys.stderr)
        return 2

    errors = validate_schema(manifest, schema)
    if not errors:
        errors.extend(
            validate_semantics(
                manifest,
                artifact_root=args.artifact_root,
                repo_root=args.repo_root,
                spec_root=args.spec_root,
                require_publish_ready=args.require_publish_ready,
                require_final=args.require_final,
                expected_spec_commit=args.expected_spec_commit,
                expected_binding=args.expected_binding,
                expected_commit=args.expected_commit,
                expected_tag=args.expected_tag,
                expected_qualification_commit=args.expected_qualification_commit,
            )
        )

    report = build_report(manifest, errors)
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.report_markdown:
        args.report_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.report_markdown.write_text(render_markdown(report), encoding="utf-8")

    if errors:
        print("cohort verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        f"cohort {manifest['cohort_id']} passed "
        f"({len(manifest['bindings'])} bindings, state={manifest['state']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
