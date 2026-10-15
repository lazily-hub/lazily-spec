"""Structural and semantic guards for the canonical Core candidate profile."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profiles" / "core-v1.json"
SCHEMA_PATH = ROOT / "schemas" / "core-profile.schema.json"


def _profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def test_core_profile_validates_against_schema() -> None:
    errors = sorted(_validator().iter_errors(_profile()), key=lambda error: list(error.path))
    assert not errors, "\n".join(f"{list(error.path)}: {error.message}" for error in errors)


def test_schema_fails_closed_on_unknown_binding_field() -> None:
    profile = copy.deepcopy(_profile())
    profile["bindings"][0]["invented_escape_hatch"] = True
    assert list(_validator().iter_errors(profile))


def test_schema_fails_closed_on_missing_symbol_mappings() -> None:
    profile = copy.deepcopy(_profile())
    del profile["bindings"][0]["symbol_mappings"]
    assert list(_validator().iter_errors(profile))


def test_c_abi_fixtureless_claim_matches_proven_cohort() -> None:
    claiming_bindings = {
        binding["id"]
        for binding in _profile()["bindings"]
        if any(claim["id"] == "c_abi_ffi_boundary" for claim in binding["fixtureless_claims"])
    }
    assert claiming_bindings == {"rust", "zig", "go", "cpp", "csharp"}


def test_semantic_checker_and_negative_self_tests() -> None:
    result = subprocess.run(
        ["node", "scripts/check-core-profile.mjs", "--self-test"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "11 negative cases rejected" in result.stdout
