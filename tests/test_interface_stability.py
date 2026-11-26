"""The beta-contract set stays equal to the core profile, and everything else stays unstable."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "profiles" / "interface-stability.json"
SCHEMA_PATH = ROOT / "schemas" / "interface-stability.schema.json"


def test_interface_stability_registry_matches_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    registry = json.loads(REGISTRY_PATH.read_text())
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(registry), key=lambda error: list(error.path))
    assert not errors, "\n".join(f"{list(error.path)}: {error.message}" for error in errors)


def test_interface_stability_checker_rejects_drift() -> None:
    result = subprocess.run(
        ["node", "scripts/check-interface-stability.mjs", "--self-test"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "6 negative cases rejected" in result.stdout
    document = (ROOT / "docs" / "interface-stability.md").read_text()
    assert "explicitly unstable" in document
    assert "**candidate**" in document
