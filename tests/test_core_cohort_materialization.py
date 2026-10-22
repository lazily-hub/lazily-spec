from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATERIALIZER = load("materialize_core_cohort", ROOT / "scripts/materialize_core_cohort.py")
RUNNERS = load(
    "run_core_published_consumers", ROOT / "scripts/run_core_published_consumers.py"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest(binding_id: str, artifact: bytes) -> dict:
    evidence = b"evidence\n"
    artifact_entry = {
        "uri": "https://example.invalid/artifact",
        "file": f"artifacts/{binding_id}.pkg",
        "sha256": sha(artifact),
        "provenance": {
            "uri": "https://example.invalid/provenance",
            "file": f"evidence/{binding_id}.json",
            "sha256": sha(evidence),
        },
        "registry": {
            "url": "https://example.invalid/registry",
            "metadata_file": f"evidence/{binding_id}.json",
            "metadata_sha256": sha(evidence),
        },
    }
    return {
        "bindings": [
            {
                "id": binding_id,
                "packages": [
                    {
                        "coordinate": RUNNERS.CORE_COORDINATES[binding_id],
                        "version": "1.2.3",
                        "artifacts": [artifact_entry],
                    }
                ],
                "gates": [
                    {
                        "evidence_file": f"evidence/{binding_id}.json",
                        "evidence_sha256": sha(evidence),
                    }
                ],
            }
        ]
    }


def test_materializer_copies_seeded_bytes_and_rejects_tampering(tmp_path: Path) -> None:
    data = manifest("rust", b"artifact\n")
    seed = tmp_path / "seed"
    (seed / "artifacts").mkdir(parents=True)
    (seed / "evidence").mkdir()
    (seed / "artifacts/rust.pkg").write_bytes(b"artifact\n")
    (seed / "evidence/rust.json").write_bytes(b"evidence\n")

    written = MATERIALIZER.materialize(data, tmp_path / "out", seed)
    assert sorted(written) == ["artifacts/rust.pkg", "evidence/rust.json"]

    (seed / "artifacts/rust.pkg").write_bytes(b"tampered\n")
    try:
        MATERIALIZER.materialize(data, tmp_path / "bad", seed)
    except ValueError as error:
        assert "sha256 mismatch" in str(error)
    else:
        raise AssertionError("tampered artifact was accepted")


def test_published_runner_passes_exact_version_and_digest(tmp_path: Path) -> None:
    data = manifest("rust", b"artifact\n")
    repository = tmp_path / "lazily-rs"
    script = repository / "scripts/core-artifact-consumer-check.sh"
    script.parent.mkdir(parents=True)
    output = repository / "observed.json"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '{\"version\":\"%s\",\"sha256\":\"%s\"}\\n' "
        '"$LAZILY_CORE_ARTIFACT_VERSION" "$LAZILY_CORE_ARTIFACT_SHA256" '
        f"> {output}\n"
    )
    script.chmod(0o755)

    assert RUNNERS.run(data, tmp_path) == ["rust"]
    observed = json.loads(output.read_text())
    assert observed == {
        "version": "1.2.3",
        "sha256": sha(b"artifact\n"),
    }
