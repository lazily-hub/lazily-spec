"""Machine-checkable durable capability hierarchy."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = json.loads((ROOT / "durable-tiers.json").read_text())
SCHEMA = json.loads((ROOT / "schemas" / "durable-tiers.json").read_text())


def test_registry_validates() -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(REGISTRY)


def test_tiers_are_exact_monotone_chain() -> None:
    tiers = REGISTRY["tiers"]
    assert [(tier["id"], tier["rank"], tier["requires"]) for tier in tiers] == [
        ("core", 0, []),
        ("client", 1, ["core"]),
        ("durable_host", 2, ["client"]),
        ("distributed_host", 3, ["durable_host"]),
        ("accelerated_host", 4, ["distributed_host"]),
    ]


def test_client_never_claims_owner_authority() -> None:
    tiers = {tier["id"]: tier for tier in REGISTRY["tiers"]}
    assert tiers["core"]["transition_authority"] == "none"
    assert tiers["client"]["transition_authority"] == "none"
    assert "injected_compatible_transport" in tiers["client"]["required_capabilities"]


def test_native_host_tiers_require_real_dependency_and_failure_evidence() -> None:
    tiers = {tier["id"]: tier for tier in REGISTRY["tiers"]}
    assert "mature_transactional_database_client" in tiers["durable_host"]["required_capabilities"]
    assert "shared_crash_replay_corpus" in tiers["durable_host"]["required_capabilities"]
    assert "mature_broker_client" in tiers["distributed_host"]["required_capabilities"]
    assert "commit_before_ack_recovery" in tiers["distributed_host"]["required_capabilities"]
    assert tiers["accelerated_host"]["required_capabilities"] == [
        "bypassable_valkey_acceleration",
        "cache_loss_equivalence",
    ]
