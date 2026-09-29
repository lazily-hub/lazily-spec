"""Structural and discriminability checks for the consumer simulation fixture."""

from __future__ import annotations

import json
from pathlib import Path


FIXTURE = (
    Path(__file__).parents[1]
    / "conformance"
    / "simulation"
    / "consumer_testkit.json"
)


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_fixture_has_stable_first_party_provenance() -> None:
    fixture = load_fixture()
    assert fixture["schema_version"] == 1
    assert fixture["origin"] == "first-party-lazily-spec"
    assert fixture["license"] == "Apache-2.0"
    assert len(fixture["seed"]) == 64
    assert fixture["generator"] == {
        "path": "scripts/generate-consumer-simulation-fixture.py",
        "version": "1",
    }


def test_generated_fixture_is_current() -> None:
    import subprocess

    completed = subprocess.run(
        [
            "python3",
            str(
                Path(__file__).parents[1]
                / "scripts"
                / "generate-consumer-simulation-fixture.py"
            ),
            "--check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_fixture_carries_a_materialized_nontrivial_history() -> None:
    fixture = load_fixture()
    actions = fixture["actions"]
    assert [action["id"] for action in actions] == [
        "increment.0",
        "increment.1",
        "increment.2",
    ]
    assert [action["payload"] for action in actions] == [1, 2, 3]
    assert sum(action["payload"] for action in actions) == 6


def test_fixture_distinguishes_success_and_each_required_failure_boundary() -> None:
    fixture = load_fixture()
    scenarios = {scenario["id"]: scenario for scenario in fixture["scenarios"]}
    assert set(scenarios) == {
        "selected_real_adapters_match_every_checkpoint",
        "selected_external_process_preserves_independent_reducer_identity",
        "real_adapter_divergence_is_localized_to_first_action",
        "real_adapter_history_drift_fails_at_first_prefix",
        "simulation_adapter_bypass_is_rejected",
    }
    assert {
        scenario["expected"]["outcome"] for scenario in scenarios.values()
    } == {
        "success",
        "observation_divergence",
        "materialized_history_mismatch",
        "simulation_world_bypass",
    }
    assert scenarios[
        "real_adapter_divergence_is_localized_to_first_action"
    ]["expected"] == {
        "outcome": "observation_divergence",
        "step": 1,
        "action_id": "increment.0",
        "adapter_id": "postgres.mutant",
        "observation_id": "consumer.value",
    }


def test_every_scenario_selects_a_real_boundary_and_shares_ports() -> None:
    fixture = load_fixture()
    canonical_ports = {
        (port["id"], port["kind"], port["determinism"])
        for port in fixture["ports"]
    }
    assert canonical_ports == {
        ("state.store", "storage", "deterministic"),
        ("event.stream", "messaging", "nondeterministic"),
        ("logical.clock", "clock", "nondeterministic"),
    }
    for scenario in fixture["scenarios"]:
        assert scenario["required_real_adapters"] or scenario[
            "required_external_processes"
        ]
        adapters = {adapter["id"]: adapter for adapter in scenario["adapters"]}
        baseline = adapters[scenario["simulation_adapter_id"]]
        assert baseline["kind"] == "in_memory"
        assert baseline["execution_mode"] in {"sim_world", "bypass"}
        for selection in scenario["required_external_processes"]:
            adapter = adapters[selection["adapter_id"]]
            assert adapter["kind"] == "external_process"
            assert adapter["external_port"] == selection["port"]
            assert adapter["production_reducer_id"] == ""
