from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_core_cohort.py"
SCHEMA = ROOT / "schemas" / "core-cohort.json"
SPEC = importlib.util.spec_from_file_location("verify_core_cohort", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_evidence(root: Path, binding_id: str) -> dict[str, str]:
    files = {
        "artifact": f"artifacts/{binding_id}.pkg",
        "provenance": f"provenance/{binding_id}.json",
        "registry": f"registry/{binding_id}.json",
        "gate": f"gates/{binding_id}.json",
    }
    payloads = {
        "artifact": f"package:{binding_id}\n".encode(),
        "provenance": f'{{"binding":"{binding_id}","signed":true}}\n'.encode(),
        "registry": f'{{"binding":"{binding_id}","available":false}}\n'.encode(),
        "gate": f'{{"binding":"{binding_id}","passed":true}}\n'.encode(),
    }
    result: dict[str, str] = {}
    for name, relative in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payloads[name])
        result[f"{name}_file"] = relative
        result[f"{name}_sha256"] = digest(payloads[name])
    return result


def make_binding(binding_id: str, evidence: dict[str, str]) -> dict:
    commit = "b" * 40
    gate = {
        "status": "passed",
        "evidence_file": evidence["gate_file"],
        "evidence_sha256": evidence["gate_sha256"],
    }
    return {
        "id": binding_id,
        "profile": "core-candidate",
        "source": {
            "repository": f"https://github.com/lazily-hub/lazily-{binding_id}",
            "commit": commit,
            "tag": "v1.2.3",
        },
        "spec_revision": "a" * 40,
        "fixture_revision": "a" * 40,
        "core_api_generation": 1,
        "wire_version": "1",
        "core_imports": [f"lazily_{binding_id}.core"],
        "toolchains": [{"name": "compiler", "minimum": "1.70.0", "current": "1.80.0"}],
        "compatibility": {
            "core_api": {"minimum": 1, "maximum": 1},
            "modules": [
                {
                    "coordinate": f"lazily-{binding_id}-module",
                    "minimum_core_api": 1,
                    "maximum_core_api": 1,
                }
            ],
        },
        "packages": [
            {
                "ecosystem": "cargo",
                "coordinate": f"lazily-{binding_id}",
                "version": "1.2.3",
                "artifacts": [
                    {
                        "file": evidence["artifact_file"],
                        "sha256": evidence["artifact_sha256"],
                        "provenance": {
                            "kind": "slsa",
                            "uri": f"https://example.invalid/{binding_id}/provenance",
                            "file": evidence["provenance_file"],
                            "sha256": evidence["provenance_sha256"],
                        },
                        "registry": {
                            "url": f"https://example.invalid/{binding_id}/1.2.3",
                            "status": "missing",
                            "checked_at": "2026-10-12T10:00:00Z",
                            "metadata_file": evidence["registry_file"],
                            "metadata_sha256": evidence["registry_sha256"],
                        },
                    }
                ],
            }
        ],
        "gates": [dict(gate, name=name) for name in sorted(VERIFIER.REQUIRED_GATES)],
    }


def make_manifest(tmp_path: Path, binding_ids: tuple[str, ...] = ("rust",)) -> dict:
    profile = b'{"profile":"core-candidate"}\n'
    profile_path = tmp_path / "profiles" / "core.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_bytes(profile)
    return {
        "schema_version": 1,
        "cohort_id": "2026-10-12.rc1",
        "state": "candidate",
        "created_at": "2026-10-12T10:00:00Z",
        "profile": {
            "status": "candidate",
            "registry_path": "profiles/core.json",
            "sha256": digest(profile),
        },
        "spec": {
            "repository": "https://github.com/lazily-hub/lazily-spec",
            "commit": "a" * 40,
            "tag": "v1.0.0",
        },
        "conformance_revision": "a" * 40,
        "core_api_generation": 1,
        "wire_version": "1",
        "bindings": [
            make_binding(binding_id, write_evidence(tmp_path, binding_id))
            for binding_id in binding_ids
        ],
    }


def schema_errors(manifest: dict) -> list[str]:
    return VERIFIER.validate_schema(manifest, json.loads(SCHEMA.read_text()))


def test_candidate_manifest_is_publish_ready_and_reportable(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)

    assert schema_errors(manifest) == []
    assert VERIFIER.validate_semantics(
        manifest,
        artifact_root=tmp_path,
        spec_root=tmp_path,
        require_publish_ready=True,
        expected_spec_commit="a" * 40,
        expected_binding="rust",
        expected_commit="b" * 40,
        expected_tag="v1.2.3",
    ) == []

    report = VERIFIER.build_report(manifest, [])
    rendered = VERIFIER.render_markdown(report)
    assert report["status"] == "passed"
    assert report["bindings"][0]["published_consumer_status"] == "passed"
    assert "cargo:lazily-rust@1.2.3" in rendered


def test_rejects_manifest_from_a_different_spec_commit(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)

    errors = VERIFIER.validate_semantics(
        manifest,
        expected_spec_commit="c" * 40,
    )

    assert any("does not match --expected-spec-commit" in error for error in errors)


def test_schema_failure_can_still_produce_a_failure_report() -> None:
    malformed = {"cohort_id": "bad", "bindings": "not-an-array"}
    errors = schema_errors(malformed)

    report = VERIFIER.build_report(malformed, errors)

    assert errors
    assert report["status"] == "failed"
    assert report["bindings"] == []


def test_rejects_floating_toolchain_and_tag_version_mismatch(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    binding = manifest["bindings"][0]
    binding["toolchains"][0]["current"] = "latest"
    binding["packages"][0]["version"] = "1.2.4"

    errors = VERIFIER.validate_semantics(manifest)

    assert any("current is floating" in error for error in errors)
    assert any("does not exactly match package versions" in error for error in errors)


def test_rejects_wrong_spec_revision_and_incompatible_ranges(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    binding = manifest["bindings"][0]
    binding["fixture_revision"] = "c" * 40
    binding["compatibility"]["core_api"] = {"minimum": 2, "maximum": 3}
    binding["compatibility"]["modules"][0] = {
        "coordinate": "bad-module",
        "minimum_core_api": 3,
        "maximum_core_api": 2,
    }

    errors = VERIFIER.validate_semantics(manifest)

    assert any("fixture_revision does not match" in error for error in errors)
    assert any("core_api does not include generation 1" in error for error in errors)
    assert any("inverted Core API range" in error for error in errors)


def test_rejects_missing_or_wrong_artifact_evidence(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    artifact = manifest["bindings"][0]["packages"][0]["artifacts"][0]
    (tmp_path / artifact["file"]).write_bytes(b"tampered")
    (tmp_path / artifact["provenance"]["file"]).unlink()

    errors = VERIFIER.validate_semantics(manifest, artifact_root=tmp_path)

    assert any("sha256 mismatch" in error for error in errors)
    assert any("missing evidence file" in error for error in errors)


def test_final_cohort_requires_all_bindings_beta_and_available(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    manifest["state"] = "final"
    failed_gate = next(
        gate
        for gate in manifest["bindings"][0]["gates"]
        if gate["name"] == "published_consumer"
    )
    failed_gate["status"] = "pending"

    errors = VERIFIER.validate_semantics(manifest, require_final=True)

    assert any("complete nine-binding cohort" in error for error in errors)
    assert any("profile.status must be beta" in error for error in errors)
    assert any("registry.status must be available" in error for error in errors)
    assert any("published_consumer" in error and "must be passed" in error for error in errors)


def test_complete_final_cohort_passes_semantics(tmp_path: Path) -> None:
    binding_ids = tuple(sorted(VERIFIER.EXPECTED_BINDINGS))
    manifest = make_manifest(tmp_path, binding_ids)
    manifest["state"] = "final"
    manifest["profile"]["status"] = "beta"
    for binding in manifest["bindings"]:
        binding["profile"] = "core-beta"
        binding["packages"][0]["artifacts"][0]["registry"]["status"] = "available"

    assert schema_errors(manifest) == []
    assert VERIFIER.validate_semantics(
        manifest,
        artifact_root=tmp_path,
        spec_root=tmp_path,
        require_final=True,
    ) == []


def test_schema_rejects_evidence_path_traversal(tmp_path: Path) -> None:
    manifest = deepcopy(make_manifest(tmp_path))
    artifact = manifest["bindings"][0]["packages"][0]["artifacts"][0]
    artifact["file"] = "../outside.pkg"

    assert any("does not match" in error for error in schema_errors(manifest))


def test_source_verification_requires_tag_to_peel_to_checkout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repos"
    repo = repo_root / "lazily-rust"
    repo.mkdir(parents=True)

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()

    git("init", "-q")
    git("config", "user.name", "Cohort Test")
    git("config", "user.email", "cohort@example.invalid")
    (repo / "payload").write_text("first\n")
    git("add", "payload")
    git("commit", "-q", "-m", "first")
    tagged_commit = git("rev-parse", "HEAD")
    git("tag", "v1.2.3")
    source = {
        "repository": "https://github.com/lazily-hub/lazily-rust",
        "commit": tagged_commit,
        "tag": "v1.2.3",
    }
    errors: list[str] = []
    VERIFIER.verify_source_pin(source, repo_root, "binding", errors)
    assert errors == []

    (repo / "payload").write_text("second\n")
    git("add", "payload")
    git("commit", "-q", "-m", "second")
    source["commit"] = git("rev-parse", "HEAD")
    errors = []
    VERIFIER.verify_source_pin(source, repo_root, "binding", errors)
    assert any("peeled tag v1.2.3" in error for error in errors)
