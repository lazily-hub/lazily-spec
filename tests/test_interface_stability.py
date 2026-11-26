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


def _marked(text: str, name: str) -> str:
    start = f"<!-- {name}:start -->"
    end = f"<!-- {name}:end -->"
    assert start in text and end in text, name
    section = text.split(start, 1)[1].split(end, 1)[0]
    assert section.strip(), name
    return section


def _assert_points_at_registry(text: str, registry: dict) -> None:
    symbols = ", ".join(f"`{item}`" for item in registry["beta_contract"]["abstract_symbols"])
    modules = ", ".join(f"`{item['id']}`" for item in registry["unstable_modules"])
    assert "profiles/interface-stability.json" in text
    assert "candidate" in text
    assert "does not promote" in text
    assert "beta contract" in text
    assert "unstable" in text
    assert "unstable_modules" in text
    assert "not_candidate_bindings" in text
    assert "reactive_graph_outside_core_closure" in text
    assert "beta_contract_reexports" in text
    assert symbols not in text
    assert modules not in text


def test_reader_docs_explain_stability_from_the_registry() -> None:
    registry = json.loads(REGISTRY_PATH.read_text())
    readme = _marked((ROOT / "README.md").read_text(), "beta-stability")
    introduction = _marked((ROOT / "docs" / "introduction.md").read_text(), "beta-stability")
    core_beta = (ROOT / "docs" / "core-beta.md").read_text()
    core_support = (ROOT / "docs" / "core-support.md").read_text()
    for text in (readme, introduction, core_beta, core_support):
        _assert_points_at_registry(text, registry)


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
