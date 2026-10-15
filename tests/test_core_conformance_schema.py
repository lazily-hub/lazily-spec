"""Schema coverage for executable Lazily Core qualification evidence."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry
from referencing.jsonschema import DRAFT202012


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


DECLARATION_SCHEMA = load_schema("core-conformance-declaration.schema.json")
REPORT_SCHEMA = load_schema("core-conformance-report.schema.json")
REGISTRY = Registry().with_resources(
    [
        (DECLARATION_SCHEMA["$id"], DRAFT202012.create_resource(DECLARATION_SCHEMA)),
        (REPORT_SCHEMA["$id"], DRAFT202012.create_resource(REPORT_SCHEMA)),
    ]
)
DECLARATION_VALIDATOR = jsonschema.Draft202012Validator(
    DECLARATION_SCHEMA,
    registry=REGISTRY,
)
REPORT_VALIDATOR = jsonschema.Draft202012Validator(REPORT_SCHEMA, registry=REGISTRY)


def valid_declaration() -> dict:
    return {
        "schema_version": 1,
        "profile_id": "core-v1",
        "binding_id": "rust",
        "report_command": ["cargo", "test", "--test", "core_conformance_report"],
        "runtime_skips": [
            {
                "fixture": "reactive-graph/batch.json",
                "scenario": "nested_batch",
                "execution_flavor": "async",
                "reason": "unsupported execution flavor",
            }
        ],
        "fixtureless_claims": [
            {
                "id": "c_abi_ffi_boundary",
                "proof_classes": ["native_artifact_consumer"],
                "command": ["cargo", "test", "ffi_consumer"],
            }
        ],
    }


def valid_report() -> dict:
    return {
        "schema_version": 1,
        "profile_id": "core-v1",
        "binding_id": "rust",
        "fixture_corpus_digest": "a" * 64,
        "fixtures": [
            {
                "path": "reactive-graph/batch.json",
                "scenario_ids": ["nested_batch"],
                "proof_classes": ["fixture_replay"],
                "assertion_blocks": [
                    {
                        "id": "/scenarios/*/expect",
                        "consumed": True,
                        "discriminability_evidence": (
                            "audits/fixture-discriminability.json#/claims/"
                            "reactive-graph~1batch.json#~1scenarios~1*~1expect"
                        ),
                    }
                ],
                "status": "partial",
            }
        ],
        "runtime_skips": [
            {
                "fixture": "reactive-graph/batch.json",
                "scenario": "nested_batch",
                "execution_flavor": "async",
                "reason": "unsupported execution flavor",
            }
        ],
        "fixtureless_claims": [
            {
                "id": "c_abi_ffi_boundary",
                "proof_classes": ["native_artifact_consumer"],
                "passed": True,
                "evidence": "rust/native-consumer.json",
            }
        ],
    }


def test_core_conformance_schemas_accept_complete_documents() -> None:
    DECLARATION_VALIDATOR.validate(valid_declaration())
    REPORT_VALIDATOR.validate(valid_report())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(report_command=[]),
        lambda value: value["runtime_skips"][0].update(reason=""),
        lambda value: value["fixtureless_claims"][0].update(command=[]),
        lambda value: value["fixtureless_claims"][0]["command"].append(""),
        lambda value: value.update(unrecognized=True),
    ],
)
def test_core_declaration_schema_rejects_incomplete_or_open_claims(mutate) -> None:
    document = deepcopy(valid_declaration())
    mutate(document)
    assert list(DECLARATION_VALIDATOR.iter_errors(document))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["runtime_skips"][0].update(reason=""),
        lambda value: value["fixtures"][0]["assertion_blocks"][0].update(
            discriminability_evidence="audits/fixture-discriminability.json"
        ),
        lambda value: value["fixtures"][0]["assertion_blocks"][0].update(
            discriminability_evidence="../outside.json#/claim"
        ),
        lambda value: value["fixtures"][0].update(status="unknown"),
        lambda value: value["fixtureless_claims"][0].update(evidence="../outside.json"),
        lambda value: value["fixtureless_claims"][0].update(passed=False),
        lambda value: value.update(unrecognized=True),
    ],
)
def test_core_report_schema_rejects_non_evidence(mutate) -> None:
    document = deepcopy(valid_report())
    mutate(document)
    assert list(REPORT_VALIDATOR.iter_errors(document))


def test_skipped_fixture_cannot_claim_assertion_blocks() -> None:
    document = valid_report()
    document["fixtures"][0]["status"] = "skipped"
    assert list(REPORT_VALIDATOR.iter_errors(document))

    document["fixtures"][0]["assertion_blocks"] = []
    REPORT_VALIDATOR.validate(document)
