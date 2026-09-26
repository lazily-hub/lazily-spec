"""Portable durable-client conformance."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
ENVELOPE_SCHEMA = json.loads((ROOT / "schemas" / "durable-envelope.json").read_text())
CORPUS_SCHEMA = json.loads(
    (ROOT / "schemas" / "durable-client-conformance.json").read_text()
)
FIXTURE = json.loads(
    (ROOT / "conformance" / "durable-client" / "envelope_v1.json").read_text()
)
ENVELOPE_VALIDATOR = jsonschema.Draft202012Validator(ENVELOPE_SCHEMA)
REGISTRY = Registry().with_resource(
    ENVELOPE_SCHEMA["$id"], Resource.from_contents(ENVELOPE_SCHEMA, default_specification=DRAFT202012)
)
CORPUS_VALIDATOR = jsonschema.Draft202012Validator(CORPUS_SCHEMA, registry=REGISTRY)


def envelope_vector(vector_id: str) -> dict:
    return next(row for row in FIXTURE["envelope_vectors"] if row["id"] == vector_id)


def test_corpus_is_schema_valid_and_has_no_owner_authority() -> None:
    CORPUS_VALIDATOR.validate(FIXTURE)
    assert FIXTURE["owner_authority"] is False
    assert [row["id"] for row in FIXTURE["envelope_vectors"]] == [
        "envelope_v1_round_trip",
        "unknown_protocol_fails_before_payload_decode",
        "empty_identity_fails_closed",
        "zero_versions_fail_closed",
    ]


def test_envelope_acceptance_and_fail_closed_vectors() -> None:
    valid = envelope_vector("envelope_v1_round_trip")
    ENVELOPE_VALIDATOR.validate(valid["envelope"])
    assert json.loads(json.dumps(valid["envelope"])) == valid["envelope"]
    assert valid["expected"] == {
        "accepted": True,
        "reason": "accepted",
        "payload_decoded": True,
    }
    for vector_id in [
        "unknown_protocol_fails_before_payload_decode",
        "empty_identity_fails_closed",
        "zero_versions_fail_closed",
    ]:
        row = envelope_vector(vector_id)
        assert list(ENVELOPE_VALIDATOR.iter_errors(row["envelope"])), vector_id
        assert row["expected"]["accepted"] is False
        assert row["expected"]["payload_decoded"] is False


def test_ordering_is_observed_without_inventing_owner_order() -> None:
    row = FIXTURE["ordering_vectors"][0]
    assert row["observed_message_ids"] == row["expected_delivery_order"]
    assert row["owner_order_inferred"] is False


def test_advisory_projection_applies_source_order_across_gap_and_replay() -> None:
    row = FIXTURE["projection_ordering_vectors"][0]
    assert row["observed_source_positions"] == [2, 1, 2]
    assert row["expected_applied_positions"] == [1, 2]
    assert row["expected_delivery_classification"] == ["buffered", "applied", "duplicate"]
    assert row["broker_order_authoritative"] is False
    assert row["may_authorize_transition"] is False


def test_dedup_classifies_identity_and_content() -> None:
    row = FIXTURE["dedup_vectors"][0]
    first, duplicate, conflict = row["deliveries"]
    assert first == duplicate
    assert first["message_id"] == conflict["message_id"]
    assert first != conflict
    assert row["expected_classification"] == ["first", "duplicate", "conflict"]


def test_durable_receipt_is_not_a_transport_ack() -> None:
    row = FIXTURE["receipt_vectors"][0]
    assert row["receipt"] == row["expected_round_trip"]
    assert row["transport_ack_equivalent"] is False


def test_projection_fingerprint_equivalence_requires_source_and_digest() -> None:
    for row in FIXTURE["projection_fingerprint_vectors"]:
        same_source = row["left"]["source_position"] == row["right"]["source_position"]
        same_fingerprint = row["left"]["fingerprint"] == row["right"]["fingerprint"]
        same_completeness = row["left"]["completeness"] == row["right"]["completeness"]
        assert row["left"]["may_authorize_transition"] is False
        assert row["right"]["may_authorize_transition"] is False
        assert row["expected"] == {
            "same_source": same_source,
            "same_fingerprint": same_fingerprint,
            "same_completeness": same_completeness,
            "equivalent": same_source and same_fingerprint and same_completeness,
        }


def test_schema_rejects_authority_and_broker_metadata_fields() -> None:
    base = envelope_vector("envelope_v1_round_trip")["envelope"]
    for extra in ["owner_position", "fence", "stream_sequence", "owner_authority"]:
        candidate = {**base, extra: 1}
        assert list(ENVELOPE_VALIDATOR.iter_errors(candidate)), extra
