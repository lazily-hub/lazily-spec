#!/usr/bin/env python3
"""Generate the first-party consumer simulation testkit fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "conformance" / "simulation" / "consumer_testkit.json"
SEED = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
PROTOCOL = "counter.protocol.v1"
PRODUCTION_REDUCER = "counter.reducer.v1"


def adapter(
    adapter_id: str,
    kind: str,
    *,
    service_id: str = "",
    external_port: str | None = None,
    reducer_id: str = PRODUCTION_REDUCER,
    production_reducer_id: str = PRODUCTION_REDUCER,
    clock_stub: str = "none",
    delta_bias: int = 0,
    history_mode: str = "exact",
    execution_mode: str = "real",
) -> dict:
    value = {
        "id": adapter_id,
        "kind": kind,
        "service_id": service_id,
        "reducer_id": reducer_id,
        "production_reducer_id": production_reducer_id,
        "protocol_id": PROTOCOL,
        "clock_stub": clock_stub,
        "delta_bias": delta_bias,
        "history_mode": history_mode,
        "execution_mode": execution_mode,
    }
    if external_port is not None:
        value["external_port"] = external_port
    return value


def memory(*, execution_mode: str = "sim_world") -> dict:
    return adapter(
        "memory",
        "in_memory",
        clock_stub="stubbed",
        history_mode="none",
        execution_mode=execution_mode,
    )


def external(adapter_id: str, port: str, *, history_mode: str = "exact") -> dict:
    return adapter(
        adapter_id,
        "external_process",
        service_id=f"{adapter_id}.service",
        external_port=port,
        reducer_id=f"{adapter_id}.reducer.v1",
        production_reducer_id="",
        history_mode=history_mode,
    )


def fixture() -> dict:
    return {
        "schema_version": 1,
        "origin": "first-party-lazily-spec",
        "license": "Apache-2.0",
        "seed": SEED,
        "generator": {
            "path": "scripts/generate-consumer-simulation-fixture.py",
            "version": "1",
        },
        "description": (
            "Consumer simulation testkit applies one materialized counter history "
            "through a SimWorld baseline and explicitly selected real or "
            "external-process adapters, checking exact history prefixes and "
            "canonical observations after every action."
        ),
        "kind": "ConsumerSimulationTestkit",
        "model": "CounterReducerV1",
        "protocol_id": PROTOCOL,
        "production_reducer_id": PRODUCTION_REDUCER,
        "ports": [
            {
                "id": "state.store",
                "kind": "storage",
                "determinism": "deterministic",
            },
            {
                "id": "event.stream",
                "kind": "messaging",
                "determinism": "nondeterministic",
            },
            {
                "id": "logical.clock",
                "kind": "clock",
                "determinism": "nondeterministic",
            },
        ],
        "actions": [
            {
                "id": f"increment.{index}",
                "actor_id": "consumer",
                "kind": "counter.increment",
                "version": "1",
                "payload": payload,
            }
            for index, payload in enumerate((1, 2, 3))
        ],
        "scenarios": [
            {
                "id": "selected_real_adapters_match_every_checkpoint",
                "simulation_adapter_id": "memory",
                "required_real_adapters": ["postgres", "nats"],
                "required_external_processes": [],
                "adapters": [
                    adapter(
                        "nats.integration",
                        "nats",
                        service_id="nats.integration.service",
                    ),
                    memory(),
                    adapter(
                        "postgres.integration",
                        "postgres",
                        service_id="postgres.integration.service",
                    ),
                ],
                "expected": {
                    "outcome": "success",
                    "adapter_ids": [
                        "memory",
                        "nats.integration",
                        "postgres.integration",
                    ],
                    "checkpoint_steps": [1, 2, 3],
                    "checkpoint_action_ids": [
                        "increment.0",
                        "increment.1",
                        "increment.2",
                    ],
                    "checkpoint_values": [1, 3, 6],
                    "observation_relation": "all_equal_at_every_checkpoint",
                    "materialized_history_relation": (
                        "exact_prefix_at_every_checkpoint"
                    ),
                    "probe_relation": "every_real_adapter_once",
                },
            },
            {
                "id": (
                    "selected_external_process_preserves_independent_reducer_identity"
                ),
                "simulation_adapter_id": "memory",
                "required_real_adapters": [],
                "required_external_processes": [
                    {"adapter_id": "sample.cli", "port": "cli"}
                ],
                "adapters": [memory(), external("sample.cli", "cli")],
                "expected": {
                    "outcome": "success",
                    "adapter_ids": ["memory", "sample.cli"],
                    "checkpoint_steps": [1, 2, 3],
                    "checkpoint_values": [1, 3, 6],
                    "external_adapter_id": "sample.cli",
                    "external_port": "cli",
                    "external_protocol_id": PROTOCOL,
                    "external_reducer_id": "sample.cli.reducer.v1",
                    "external_production_reducer_id": "",
                },
            },
            {
                "id": "real_adapter_divergence_is_localized_to_first_action",
                "simulation_adapter_id": "memory",
                "required_real_adapters": ["postgres"],
                "required_external_processes": [],
                "adapters": [
                    memory(),
                    adapter(
                        "postgres.mutant",
                        "postgres",
                        service_id="postgres.mutant.service",
                        delta_bias=1,
                    ),
                ],
                "expected": {
                    "outcome": "observation_divergence",
                    "step": 1,
                    "action_id": "increment.0",
                    "adapter_id": "postgres.mutant",
                    "observation_id": "consumer.value",
                },
            },
            {
                "id": "real_adapter_history_drift_fails_at_first_prefix",
                "simulation_adapter_id": "memory",
                "required_real_adapters": [],
                "required_external_processes": [
                    {"adapter_id": "sample.filesystem", "port": "filesystem"}
                ],
                "adapters": [
                    memory(),
                    external("sample.filesystem", "filesystem", history_mode="empty"),
                ],
                "expected": {
                    "outcome": "materialized_history_mismatch",
                    "step": 1,
                    "action_id": "increment.0",
                    "adapter_id": "sample.filesystem",
                    "expected_prefix_length": 1,
                    "actual_prefix_length": 0,
                },
            },
            {
                "id": "simulation_adapter_bypass_is_rejected",
                "simulation_adapter_id": "memory",
                "required_real_adapters": ["postgres"],
                "required_external_processes": [],
                "adapters": [
                    memory(execution_mode="bypass"),
                    adapter(
                        "postgres.integration",
                        "postgres",
                        service_id="postgres.integration.service",
                    ),
                ],
                "expected": {
                    "outcome": "simulation_world_bypass",
                    "step": 1,
                    "action_id": "increment.0",
                    "adapter_id": "memory",
                },
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(fixture(), indent=2) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
            print(f"{OUTPUT.relative_to(ROOT)} is stale; regenerate it")
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
