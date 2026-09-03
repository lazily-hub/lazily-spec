"""Executable contract guard for the keyed latest durable projection fixture."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "conformance" / "egress" / "latest_durable_projection.json"


@dataclass
class Entry:
    desired: dict[str, Any] | None = None
    inflight: dict[str, Any] | None = None
    durable_through: int | None = None


class LatestDurableProjectionReference:
    """Small reference reducer used only to validate the language-neutral trace."""

    def __init__(self, generation: int) -> None:
        self.generation = generation
        self.entries: dict[str, Entry] = {}

    def entry(self, key: str) -> Entry:
        return self.entries.setdefault(key, Entry())

    def upsert_desired(self, op: dict[str, Any]) -> dict[str, Any]:
        entry = self.entry(op["key"])
        epoch = op["epoch"]
        value = op["value"]

        if entry.durable_through is not None and epoch <= entry.durable_through:
            return {"upsert": "already_durable", "durable_through": entry.durable_through}

        retained = [
            revision
            for revision in (entry.desired, entry.inflight)
            if revision is not None
        ]
        newest_epoch = max((revision["epoch"] for revision in retained), default=None)
        if newest_epoch is not None and epoch < newest_epoch:
            return {"upsert": "stale_epoch", "current": newest_epoch}
        if newest_epoch == epoch:
            current = next(revision for revision in retained if revision["epoch"] == epoch)
            if current["value"] == value:
                return {"upsert": "unchanged"}
            return {"upsert": "epoch_conflict"}

        entry.desired = {"epoch": epoch, "value": value}
        return {"upsert": "accepted"}

    def claim(self, op: dict[str, Any]) -> dict[str, Any]:
        if op["generation"] != self.generation:
            return {"claim": "stale_generation", "current": self.generation}
        entry = self.entry(op["key"])
        if entry.inflight is not None:
            return {"claim": "busy"}
        if entry.desired is None:
            return {"claim": "empty"}

        desired = entry.desired
        envelope = {
            "generation": self.generation,
            "key": op["key"],
            "epoch": desired["epoch"],
            "value": desired["value"],
        }
        entry.desired = None
        entry.inflight = envelope
        return {"claim": "claimed", "envelope": copy.deepcopy(envelope)}

    def ack_applied(self, op: dict[str, Any]) -> dict[str, Any]:
        if op["generation"] != self.generation:
            return {"ack": "stale_generation", "current": self.generation}
        entry = self.entry(op["key"])
        inflight = entry.inflight
        if inflight is None or inflight["epoch"] != op["epoch"]:
            if entry.durable_through is not None and op["epoch"] <= entry.durable_through:
                return {"ack": "unchanged", "durable_through": entry.durable_through}
            return {"ack": "unknown_epoch"}

        entry.inflight = None
        if entry.durable_through is None or op["epoch"] > entry.durable_through:
            entry.durable_through = op["epoch"]
            return {"ack": "advanced", "durable_through": entry.durable_through}
        return {"ack": "unchanged", "durable_through": entry.durable_through}

    def fail_retryable(self, op: dict[str, Any]) -> dict[str, Any]:
        if op["generation"] != self.generation:
            return {"failure": "stale_generation", "current": self.generation}
        entry = self.entry(op["key"])
        inflight = entry.inflight
        if inflight is None or inflight["epoch"] != op["epoch"]:
            return {"failure": "unknown_epoch"}

        entry.inflight = None
        if entry.desired is not None and entry.desired["epoch"] > inflight["epoch"]:
            return {"failure": "superseded"}
        entry.desired = {"epoch": inflight["epoch"], "value": inflight["value"]}
        return {"failure": "pending"}

    def reconnect(self, op: dict[str, Any]) -> dict[str, Any]:
        new_generation = op["generation"]
        if new_generation < self.generation:
            return {"reconnect": "stale_generation", "current": self.generation}
        if new_generation == self.generation:
            return {"reconnect": "unchanged", "generation": self.generation}

        requeued = 0
        superseded = 0
        for entry in self.entries.values():
            inflight = entry.inflight
            if inflight is None:
                continue
            if entry.desired is not None and entry.desired["epoch"] > inflight["epoch"]:
                superseded += 1
            else:
                entry.desired = {
                    "epoch": inflight["epoch"],
                    "value": inflight["value"],
                }
                requeued += 1
            entry.inflight = None
        self.generation = new_generation
        return {
            "reconnect": "advanced",
            "generation": new_generation,
            "requeued": requeued,
            "superseded": superseded,
        }

    def apply(self, op: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, op["type"])
        return handler(op)

    def projected_state(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "entries": [
                {
                    "key": key,
                    "desired": copy.deepcopy(entry.desired),
                    "inflight": copy.deepcopy(entry.inflight),
                    "durable_through": entry.durable_through,
                }
                for key, entry in sorted(self.entries.items())
            ],
        }


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def test_latest_durable_projection_fixture_replays_exactly() -> None:
    fixture = load_fixture()
    assert fixture["kind"] == "LatestDurableProjection"
    assert fixture["model"] == "LatestDurableProjectionCore"

    for scenario in fixture["scenarios"]:
        core = LatestDurableProjectionReference(scenario["generation"])
        for index, step in enumerate(scenario["steps"]):
            before = core.projected_state()
            actual_return = core.apply(step["op"])
            assert actual_return == step["returns"], (scenario["id"], index, before)
            assert core.projected_state() == step["expected"], (scenario["id"], index)


def test_fixture_pins_latest_projection_safety_and_liveness_seams() -> None:
    fixture = load_fixture()
    steps = [step for scenario in fixture["scenarios"] for step in scenario["steps"]]

    outcomes = {
        next(iter(step["returns"].values()))
        for step in steps
    }
    assert {"accepted", "claimed", "busy", "advanced", "pending", "stale_generation"} <= outcomes

    # Every projected state has at most one in-flight envelope per key by shape,
    # and an in-flight envelope is always fenced by the state's current generation.
    for step in steps:
        state = step["expected"]
        keys = [entry["key"] for entry in state["entries"]]
        assert len(keys) == len(set(keys))
        for entry in state["entries"]:
            if entry["inflight"] is not None:
                assert entry["inflight"]["generation"] == state["generation"]
                assert entry["inflight"]["key"] == entry["key"]

    superseding_upsert = next(
        step
        for step in steps
        if step["op"] == {
            "type": "upsert_desired",
            "key": "doc",
            "epoch": 2,
            "value": "B",
        }
    )
    assert superseding_upsert["expected"]["entries"][0]["durable_through"] is None

    stale_ack = next(
        step
        for step in steps
        if step["returns"].get("ack") == "stale_generation"
    )
    assert all(entry["durable_through"] is None for entry in stale_ack["expected"]["entries"])


def test_durable_frontier_never_regresses_in_fixture() -> None:
    fixture = load_fixture()
    for scenario in fixture["scenarios"]:
        durable_by_key: dict[str, int] = {}
        for step in scenario["steps"]:
            for entry in step["expected"]["entries"]:
                frontier = entry["durable_through"]
                if frontier is None:
                    continue
                assert frontier >= durable_by_key.get(entry["key"], frontier)
                durable_by_key[entry["key"]] = frontier
