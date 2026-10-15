from __future__ import annotations

import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas/core-artifact-consumers.schema.json").read_text())
CONTRACT = json.loads((ROOT / "profiles/core-artifact-consumers.json").read_text())


def test_schema_is_meta_valid() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_contract_validates() -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(CONTRACT)


def test_schema_rejects_a_vacuous_consumer() -> None:
    invalid = json.loads(json.dumps(CONTRACT))
    invalid["bindings"][0]["consumer"]["scenarios"] = ["source-computed-effect"]
    errors = list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(invalid))
    assert errors


def test_schema_rejects_short_deprecation_window() -> None:
    invalid = json.loads(json.dumps(CONTRACT))
    invalid["policy"]["deprecation"]["minimum_days"] = 89
    errors = list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(invalid))
    assert errors
