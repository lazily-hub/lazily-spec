"""Machine-checkable concurrency boundaries for public Lazily capabilities."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = json.loads((ROOT / "concurrency-scopes.json").read_text())
SCHEMA = json.loads((ROOT / "schemas" / "concurrency-scopes.json").read_text())


def test_concurrency_scope_registry_validates() -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(REGISTRY)


def test_scope_and_capability_identities_are_unique_and_complete() -> None:
    scopes = [entry["id"] for entry in REGISTRY["scopes"]]
    capabilities = [entry["id"] for entry in REGISTRY["capabilities"]]
    assert scopes == [
        "single_goroutine",
        "single_process_serialized",
        "durable_cross_process",
        "distributed_fenced",
    ]
    assert len(scopes) == len(set(scopes))
    assert len(capabilities) == len(set(capabilities))
    assert {entry["scope"] for entry in REGISTRY["capabilities"]} == set(scopes)


def test_in_process_capabilities_cannot_claim_database_barrier_semantics() -> None:
    in_process = {"single_goroutine", "single_process_serialized"}
    for capability in REGISTRY["capabilities"]:
        if capability["scope"] not in in_process:
            continue
        assert capability["database_atomic"] is False
        assert capability["cross_replica_exclusion"] is False
        assert capability["projection_maintenance_barrier"] is False


def test_projection_barrier_requires_database_atomic_cross_process_scope() -> None:
    barriers = [
        capability
        for capability in REGISTRY["capabilities"]
        if capability["projection_maintenance_barrier"]
    ]
    assert barriers == [
        {
            "id": "postgres_projection_barrier",
            "scope": "durable_cross_process",
            "database_atomic": True,
            "cross_replica_exclusion": True,
            "projection_maintenance_barrier": True,
        }
    ]
