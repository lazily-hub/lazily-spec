"""Executable and mutation-checked boundary-ingress reference model."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


FIXTURE = (
    Path(__file__).parents[1]
    / "conformance"
    / "ingress"
    / "boundary_ingress_adapter.json"
)


@dataclass
class Delivery:
    receipt_id: str
    targets: set[str] = field(default_factory=set)
    acked: set[str] = field(default_factory=set)

    @property
    def converged(self) -> bool:
        return bool(self.targets) and self.targets <= self.acked


@dataclass
class Event:
    cursor: int
    stamped_at: int
    action: str
    key: str | None = None
    validation: str | None = None


class Model:
    """The pure transition owner; adapters only publish inputs and run effects."""

    def __init__(
        self,
        *,
        max_buffered: int,
        freshness_horizon: int,
        mutations: frozenset[str] = frozenset(),
    ) -> None:
        self.max_buffered = max_buffered
        self.freshness_horizon = freshness_horizon
        self.mutations = mutations
        self.phase = "detached"
        self.generation = 0
        self.cursor: int | None = None
        self.buffered: dict[int, Event] = {}
        self.source_keys: set[str] = set()
        self.members: set[str] = set()
        self.validation = "valid"
        self.replay_from: int | None = None
        self.stale_events = 0
        self.delivery: Delivery | None = None
        self.last_stamped_at: int | None = None
        self.now = 0
        self.revision = 0

    def _changed(self) -> None:
        self.revision += 1

    def _apply_event(self, event: Event) -> None:
        if event.action == "upsert":
            assert event.key is not None
            self.source_keys.add(event.key)
        elif event.action == "remove":
            assert event.key is not None
            self.source_keys.discard(event.key)
        elif event.action == "validate":
            assert event.validation in {"valid", "invalid"}
            self.validation = event.validation
        else:
            raise AssertionError(f"unknown action {event.action!r}")
        self.cursor = event.cursor
        self.last_stamped_at = event.stamped_at
        self.phase = "live" if self.validation == "valid" else "invalid"
        self.replay_from = None

    def _drain_contiguous(self) -> None:
        assert self.cursor is not None
        while self.cursor + 1 in self.buffered:
            event = self.buffered.pop(self.cursor + 1)
            self._apply_event(event)
        if self.buffered:
            self.phase = "replay_required"
            self.replay_from = self.cursor + 1

    def apply(self, op: dict[str, Any]) -> None:
        kind = op["type"]
        if kind == "subscribe":
            generation = op["generation"]
            if (
                "restart_keeps_old_buffer" in self.mutations
                and self.phase == "bootstrapping"
            ):
                old_buffer = self.buffered
            else:
                old_buffer = {}
            self.generation = generation
            self.cursor = None
            self.buffered = old_buffer
            self.source_keys.clear()
            self.members.clear()
            self.replay_from = None
            self.phase = "bootstrapping"
            self._changed()
            return

        if kind == "snapshot":
            generation = op["generation"]
            if generation < self.generation:
                self.stale_events += 1
                self._changed()
                return
            if generation > self.generation:
                self.generation = generation
                self.buffered.clear()
            self.cursor = op["cursor"]
            self.last_stamped_at = op["stamped_at"]
            self.source_keys = set(op["source_keys"])
            self.members = set(op["members"])
            self.validation = op["validation"]
            self.phase = "live" if self.validation == "valid" else "invalid"
            self.replay_from = None
            self.buffered = {
                cursor: event
                for cursor, event in self.buffered.items()
                if cursor > self.cursor
            }
            if "snapshot_does_not_drain_buffer" not in self.mutations:
                self._drain_contiguous()
            self._changed()
            return

        if kind == "event":
            generation = op["generation"]
            event = Event(
                cursor=op["cursor"],
                stamped_at=op["stamped_at"],
                action=op["action"],
                key=op.get("key"),
                validation=op.get("validation"),
            )
            if (
                generation < self.generation
                and "accepts_stale_generation" not in self.mutations
            ):
                self.stale_events += 1
                self._changed()
                return
            if generation > self.generation:
                self.generation = generation
                self.cursor = None
                self.buffered.clear()
                self.phase = "bootstrapping"
            if self.cursor is None:
                if (
                    len(self.buffered) >= self.max_buffered
                    and event.cursor not in self.buffered
                ):
                    if "ignores_backpressure" not in self.mutations:
                        self.phase = "backpressured"
                        self.replay_from = 0
                        self._changed()
                        return
                self.buffered.setdefault(event.cursor, event)
                self._changed()
                return
            if event.cursor <= self.cursor:
                return
            if event.cursor == self.cursor + 1:
                self._apply_event(event)
                self._drain_contiguous()
                self._changed()
                return
            if len(self.buffered) >= self.max_buffered:
                self.phase = "backpressured"
                self.replay_from = self.cursor + 1
                self._changed()
                return
            self.buffered[event.cursor] = event
            self.phase = "replay_required"
            self.replay_from = self.cursor + 1
            self._changed()
            return

        if kind == "member_join":
            member = op["member"]
            before = (set(self.members), copy.deepcopy(self.delivery))
            self.members.add(member)
            if (
                self.delivery is not None
                and not self.delivery.targets
                and "zero_members_converges" not in self.mutations
            ):
                self.delivery.targets.add(member)
            if before != (self.members, self.delivery):
                self._changed()
            return

        if kind == "member_leave":
            member = op["member"]
            if member in self.members:
                self.members.remove(member)
                if (
                    "forget_receipt_targets_on_leave" in self.mutations
                    and self.delivery is not None
                ):
                    self.delivery.targets.discard(member)
                self._changed()
            return

        if kind == "open_receipt":
            self.delivery = Delivery(op["receipt_id"], set(self.members))
            self._changed()
            return

        if kind == "ack":
            if self.delivery is None or self.delivery.receipt_id != op["receipt_id"]:
                return
            member = op["member"]
            if member in self.delivery.targets and member not in self.delivery.acked:
                self.delivery.acked.add(member)
                self._changed()
            elif "duplicate_ack_churns" in self.mutations:
                self._changed()
            return

        if kind == "tick":
            was_fresh = self.fresh
            self.now = op["now"]
            if self.fresh != was_fresh:
                self._changed()
            return

        raise AssertionError(f"unknown op {kind!r}")

    @property
    def ready(self) -> bool:
        return self.phase == "live" and self.validation == "valid"

    @property
    def fresh(self) -> bool:
        if self.last_stamped_at is None:
            return False
        if "freshness_inclusive_bug" in self.mutations:
            return self.now - self.last_stamped_at < self.freshness_horizon
        return self.now - self.last_stamped_at <= self.freshness_horizon

    def projection(self) -> dict[str, Any]:
        delivery = None
        if self.delivery is not None:
            delivery = {
                "receipt_id": self.delivery.receipt_id,
                "targets": sorted(self.delivery.targets),
                "acked": sorted(self.delivery.acked),
                "converged": (
                    True
                    if "zero_members_converges" in self.mutations
                    and not self.delivery.targets
                    else self.delivery.converged
                ),
            }
        return {
            "phase": self.phase,
            "generation": self.generation,
            "cursor": self.cursor,
            "buffered_cursors": sorted(self.buffered),
            "source_keys": sorted(self.source_keys),
            "members": sorted(self.members),
            "validation": self.validation,
            "replay_from": self.replay_from,
            "stale_events": self.stale_events,
            "delivery": delivery,
            "ready": self.ready,
            "fresh": self.fresh,
            "observation_revision": self.revision,
            "revision": self.revision,
        }


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def replay(mutations: frozenset[str] = frozenset()) -> list[str]:
    fixture = load_fixture()
    failures: list[str] = []
    for scenario in fixture["scenarios"]:
        policy = fixture["policy"] | scenario.get("policy", {})
        model = Model(
            max_buffered=policy["max_buffered"],
            freshness_horizon=policy["freshness_horizon"],
            mutations=mutations,
        )
        for index, step in enumerate(scenario["steps"]):
            model.apply(step["op"])
            actual = model.projection()
            for key, expected in step["expected"].items():
                if actual[key] != expected:
                    failures.append(
                        f"{scenario['id']} step {index} {key}: "
                        f"{actual[key]!r} != {expected!r}"
                    )
    return failures


def test_boundary_ingress_reference_replays_canonical_fixture() -> None:
    assert replay() == []


@pytest.mark.parametrize(
    "mutation",
    [
        "restart_keeps_old_buffer",
        "snapshot_does_not_drain_buffer",
        "accepts_stale_generation",
        "zero_members_converges",
        "forget_receipt_targets_on_leave",
        "duplicate_ack_churns",
        "ignores_backpressure",
        "freshness_inclusive_bug",
    ],
)
def test_boundary_ingress_mutation_is_killed(mutation: str) -> None:
    assert replay(frozenset({mutation})), f"mutation {mutation!r} survived"
