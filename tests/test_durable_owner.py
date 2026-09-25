"""Independent guards for the durable-owner Phase 0 corpus."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "conformance" / "durable-owner"
SCHEMA = json.loads((ROOT / "schemas" / "durable-owner.json").read_text())


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize(
    "name",
    [
        "atomic_crash_boundary.json",
        "ordered_replay.json",
        "inbox_outbox_deduplication.json",
        "projection_fingerprint.json",
    ],
)
def test_fixture_validates_strict_schema(name: str) -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(load(name))


def payload_key(payload: dict) -> tuple[int, int, str]:
    return (
        payload["schema_version"],
        payload["codec_version"],
        payload["bytes"],
    )


def assert_image_invariants(image: dict, mode: str) -> None:
    history = image["history"]
    snapshot = image["snapshot"]
    if mode == "event_history":
        assert snapshot is None
        assert [record["position"] for record in history] == list(
            range(1, image["position"] + 1)
        )
    else:
        assert history == []
        if image["position"] == 0:
            assert snapshot is None
        else:
            assert snapshot["position"] == image["position"]

    inbox_ids = [record["id"] for record in image["inbox"]]
    effect_ids = [record["id"] for record in image["outbox"]]
    receipt_ids = [record["id"] for record in image["receipts"]]
    assert len(inbox_ids) == len(set(inbox_ids))
    assert len(effect_ids) == len(set(effect_ids))
    assert len(receipt_ids) == len(set(receipt_ids))

    receipted_effects = {record["effect_id"] for record in image["receipts"]}
    assert receipted_effects <= set(effect_ids)
    assert image["pending_effect_ids"] == [
        effect_id for effect_id in effect_ids if effect_id not in receipted_effects
    ]

    for record in history:
        assert record["payload"]["schema_version"] > 0
        assert record["payload"]["codec_version"] > 0
    if snapshot is not None:
        assert snapshot["payload"]["schema_version"] > 0
        assert snapshot["payload"]["codec_version"] > 0


@pytest.mark.parametrize(
    "name",
    [
        "atomic_crash_boundary.json",
        "ordered_replay.json",
        "inbox_outbox_deduplication.json",
    ],
)
def test_expected_images_prove_atomicity_and_no_mutation_on_refusal(name: str) -> None:
    fixture = load(name)
    refusal = {
        "aborted",
        "position_conflict",
        "stale_fence",
        "inbox_identity_conflict",
        "effect_identity_conflict",
        "receipt_identity_conflict",
        "effect_already_receipted",
    }
    for scenario in fixture["scenarios"]:
        previous = None
        for step in scenario["steps"]:
            result = step["expect"]["result"]
            image = step["expect"]["image"]
            assert_image_invariants(image, scenario["mode"])
            outcome = result["outcome"]

            if outcome in refusal and previous is not None:
                assert image == previous
            if outcome == "committed":
                assert result["through"] == image["position"]
                assert result["ack"] == "safe"
            if outcome == "duplicate":
                assert result["through"] == image["position"]
                assert result["ack"] == "safe"
                assert image == previous
            if result.get("ack") == "withhold":
                assert outcome not in {"committed", "duplicate"}
            previous = copy.deepcopy(image)


def history_key(records: list[dict]) -> tuple:
    return tuple((record["position"], payload_key(record["payload"])) for record in records)


def fingerprint_key(payload: dict) -> tuple[int, int, str]:
    return payload_key(payload)


def relation(left: object, right: object) -> str:
    return "equal" if left == right else "different"


def test_projection_and_history_fingerprint_equality_classes_are_independent() -> None:
    fixture = load("projection_fingerprint.json")
    seen_relations: set[str] = set()
    for scenario in fixture["scenarios"]:
        case = scenario["fingerprint_case"]
        expected = case["expect"]
        actual_projection = relation(
            fingerprint_key(case["left_projection"]),
            fingerprint_key(case["right_projection"]),
        )
        actual_history = relation(
            history_key(case["left_history"]), history_key(case["right_history"])
        )
        actual_latest = relation(
            fingerprint_key(case["left_latest"]),
            fingerprint_key(case["right_latest"]),
        )
        assert actual_projection == expected["projection_fingerprint_relation"]
        assert actual_history == expected["history_fingerprint_relation"]
        assert actual_latest == expected["latest_fingerprint_relation"]
        assert expected["history_capability"] == "complete_history"
        assert expected["latest_capability"] == "latest_state_only"
        seen_relations.update({actual_projection, actual_history})
    assert seen_relations == {"equal", "different"}


def test_schema_rejects_unknown_contract_fields_and_zero_versions() -> None:
    fixture = load("ordered_replay.json")
    unknown = copy.deepcopy(fixture)
    unknown["scenarios"][0]["steps"][0]["expect"]["image"]["surprise"] = 1
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(unknown))

    zero = copy.deepcopy(fixture)
    zero["scenarios"][0]["steps"][0]["op"]["commit"]["state"]["append_events"][0][
        "schema_version"
    ] = 0
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(zero))
