"""Executable reference model for the generic effect-CAS corpus."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "conformance" / "egress" / "effect_cas.json"
SCHEMA = ROOT / "schemas" / "effect-cas.json"


class EffectCasReference:
    def __init__(self, generation: int) -> None:
        self.generation = generation
        self.entries: dict[str, dict[str, Any]] = {}
        self.attempts: dict[str, dict[str, Any]] = {}

    def entry(self, key: str) -> dict[str, Any]:
        return self.entries.setdefault(
            key,
            {
                "pending": None,
                "inflight": None,
                "retry": None,
                "applied_through": None,
                "terminal": None,
            },
        )

    @staticmethod
    def intent(op: dict[str, Any]) -> dict[str, Any]:
        """The immutable intent as submitted; plan steps never rewrite it."""
        return {
            "identity": op["identity"],
            "key": op["key"],
            "epoch": op["epoch"],
            "expected": op["expected"],
            "plan": copy.deepcopy(op["plan"]),
        }

    @classmethod
    def pending(cls, op: dict[str, Any]) -> dict[str, Any]:
        return {
            "intent": cls.intent(op),
            "identity": op["identity"],
            "key": op["key"],
            "epoch": op["epoch"],
            "expected": op["expected"],
            "plan": op["plan"],
            "next_step": 0,
            "next_attempt": 1,
            "receipts": [],
            "ready_at": None,
        }

    @staticmethod
    def terminal(kind: str, pending: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": kind,
            "intent": copy.deepcopy(pending["intent"]),
            "identity": pending["identity"],
            "epoch": pending["epoch"],
            "receipts": copy.deepcopy(pending["receipts"]),
        }

    def upsert(self, op: dict[str, Any]) -> dict[str, Any]:
        entry = self.entry(op["key"])
        applied = entry["applied_through"]
        if applied is not None and op["epoch"] <= applied:
            return {"upsert": "already_applied", "applied_through": applied}
        retained = [
            value
            for value in (
                entry["pending"],
                None if entry["inflight"] is None else entry["inflight"]["retained"],
            )
            if value is not None
        ]
        if entry["terminal"] is not None:
            retained.append(entry["terminal"])
        current = max((value["epoch"] for value in retained), default=None)
        if current is not None and op["epoch"] < current:
            return {"upsert": "stale_epoch", "current": current}
        if current == op["epoch"]:
            # Compare the ORIGINAL immutable intent. A completed plan step
            # advances the retained work's next expected authority, but a
            # re-send of the same intent at the same epoch is still idempotent.
            intent = self.intent(op)
            same = any(value["intent"] == intent for value in retained)
            return {"upsert": "unchanged" if same else "epoch_conflict"}
        if entry["pending"] is not None:
            entry["terminal"] = self.terminal("superseded", entry["pending"])
        entry["pending"] = self.pending(op)
        entry["retry"] = None
        return {"upsert": "accepted"}

    def claim(self, op: dict[str, Any], save: str | None) -> dict[str, Any]:
        if op["generation"] != self.generation:
            return {"claim": "stale_generation", "current": self.generation}
        entry = self.entry(op["key"])
        if entry["inflight"] is not None:
            return {"claim": "busy"}
        pending = entry["pending"]
        if pending is None:
            return {"claim": "empty"}
        if pending["ready_at"] is not None and op["now"] < pending["ready_at"]:
            return {"claim": "waiting", "retry_at": pending["ready_at"]}
        attempt = {
            "identity": pending["identity"],
            "generation": self.generation,
            "epoch": pending["epoch"],
            "step": pending["next_step"],
            "attempt": pending["next_attempt"],
            "expected": pending["expected"],
            "payload": pending["plan"][pending["next_step"]],
            "key": pending["key"],
        }
        entry["pending"] = None
        entry["inflight"] = {"attempt": attempt, "retained": pending}
        if save is not None:
            self.attempts[save] = copy.deepcopy(attempt)
        return {
            "claim": "claimed",
            **{key: attempt[key] for key in ("identity", "step", "attempt", "expected", "payload")},
        }

    def resolve(self, name: str) -> dict[str, Any]:
        return self.attempts[name]

    def applied(self, op: dict[str, Any]) -> dict[str, Any]:
        attempt = self.resolve(op["attempt"])
        if attempt["generation"] != self.generation:
            return {"applied": "stale_generation", "current": self.generation}
        entry = self.entry(op["key"])
        terminal = entry["terminal"]
        if terminal is not None and any(
            receipt["attempt"] == attempt and receipt["receipt"] == op["receipt"]
            for receipt in terminal["receipts"]
        ):
            return {"applied": "duplicate"}
        inflight = entry["inflight"]
        if inflight is None or inflight["attempt"] != attempt:
            return {"applied": "unknown_attempt"}
        entry["inflight"] = None
        retained = inflight["retained"]
        retained["receipts"].append(
            {
                "attempt": attempt,
                "receipt": op["receipt"],
                "authority": op["authority"],
            }
        )
        entry["retry"] = None
        if entry["pending"] is not None and entry["pending"]["epoch"] > retained["epoch"]:
            entry["terminal"] = self.terminal("superseded", retained)
            return {"applied": "superseded"}
        next_step = retained["next_step"] + 1
        if next_step < len(retained["plan"]):
            retained["next_step"] = next_step
            retained["next_attempt"] = 1
            retained["expected"] = op["authority"]
            retained["ready_at"] = None
            entry["pending"] = retained
            return {"applied": "step_applied", "next_step": next_step}
        frontier = max(entry["applied_through"] or 0, retained["epoch"])
        entry["applied_through"] = frontier
        entry["terminal"] = self.terminal("applied", retained)
        return {"applied": "completed", "applied_through": frontier}

    def failed(self, op: dict[str, Any], kind: str) -> dict[str, Any]:
        attempt = self.resolve(op["attempt"])
        if attempt["generation"] != self.generation:
            return {"failure": "stale_generation", "current": self.generation}
        entry = self.entry(op["key"])
        inflight = entry["inflight"]
        if inflight is None or inflight["attempt"] != attempt:
            return {"failure": "unknown_attempt"}
        entry["inflight"] = None
        retained = inflight["retained"]
        newer = entry["pending"] is not None and entry["pending"]["epoch"] > retained["epoch"]
        if kind == "retryable" and not newer:
            entry["retry"] = {
                "attempt": attempt,
                "error": op["error"],
                "retry_at": op["retry_at"],
            }
            retained["next_attempt"] += 1
            retained["ready_at"] = op["retry_at"]
            entry["pending"] = retained
            return {"failure": "retrying", "retry_at": op["retry_at"]}
        if kind == "rejected":
            entry["retry"] = None
            entry["terminal"] = self.terminal("rejected", retained)
            return {"failure": "rejected"}
        entry["retry"] = None
        entry["terminal"] = self.terminal("superseded", retained)
        if kind == "superseded":
            assert op["backend_before"] == op["backend_after"], "failed CAS mutated backend"
        return {"failure": "superseded"}

    def reconnect(self, op: dict[str, Any]) -> dict[str, Any]:
        generation = op["generation"]
        if generation < self.generation:
            return {"reconnect": "stale_generation", "current": self.generation}
        if generation == self.generation:
            return {"reconnect": "unchanged", "generation": generation}
        requeued = 0
        superseded = 0
        for entry in self.entries.values():
            inflight = entry["inflight"]
            if inflight is None:
                continue
            entry["inflight"] = None
            retained = inflight["retained"]
            if entry["pending"] is not None and entry["pending"]["epoch"] > retained["epoch"]:
                entry["terminal"] = self.terminal("superseded", retained)
                superseded += 1
            else:
                retained["next_attempt"] += 1
                retained["ready_at"] = None
                entry["pending"] = retained
                requeued += 1
        self.generation = generation
        return {
            "reconnect": "advanced",
            "generation": generation,
            "requeued": requeued,
            "superseded": superseded,
        }

    def apply(self, step: dict[str, Any]) -> dict[str, Any]:
        op = step["op"]
        match op["type"]:
            case "upsert":
                return self.upsert(op)
            case "claim":
                return self.claim(op, step.get("save"))
            case "applied":
                return self.applied(op)
            case "superseded" | "retryable" | "rejected" as kind:
                return self.failed(op, kind)
            case "reconnect":
                return self.reconnect(op)
            case other:
                raise AssertionError(f"unknown effect-CAS op: {other}")

    def projected_final(self) -> dict[str, Any]:
        final: dict[str, Any] = {}
        for key, entry in sorted(self.entries.items()):
            pending = entry["pending"]
            inflight = entry["inflight"]
            terminal = entry["terminal"]
            final[key] = {
                "pending_identity": None if pending is None else pending["identity"],
                "inflight_identity": None if inflight is None else inflight["attempt"]["identity"],
                "applied_through": entry["applied_through"],
                "terminal": None if terminal is None else terminal["kind"],
                "receipt_count": 0 if terminal is None else len(terminal["receipts"]),
                "retry_at": None if entry["retry"] is None else entry["retry"]["retry_at"],
            }
        return final


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def test_effect_cas_schema_and_reference_replay() -> None:
    schema = json.loads(SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    fixture = load_fixture()
    jsonschema.Draft202012Validator(schema).validate(fixture)

    for scenario in fixture["scenarios"]:
        core = EffectCasReference(scenario["generation"])
        for index, step in enumerate(scenario["steps"]):
            assert core.apply(step) == step["returns"], (scenario["id"], index)
        assert core.projected_final() == scenario["final"], scenario["id"]


def test_effect_cas_corpus_covers_required_outcomes() -> None:
    fixture = load_fixture()
    scenario_ids = {scenario["id"] for scenario in fixture["scenarios"]}
    assert scenario_ids == {
        "exact_apply_and_duplicate_receipt",
        "authority_mismatch_has_zero_mutation",
        "newer_desired_supersedes_inflight_retry",
        "stale_generation_receipt_changes_no_state",
        "independent_keys_progress_concurrently",
        "reconnect_replays_same_effect_identity",
        "ordered_plan_resumes_after_partial_success",
        "supersession_between_plan_steps",
        "permanent_rejection_is_distinct_from_retry",
    }
    outcomes = {
        next(iter(step["returns"].values()))
        for scenario in fixture["scenarios"]
        for step in scenario["steps"]
    }
    assert {
        "completed",
        "duplicate",
        "superseded",
        "retrying",
        "rejected",
        "stale_generation",
        "unchanged",
    } <= outcomes


def test_effect_cas_resend_after_plan_step_compares_original_intent() -> None:
    """A re-sent intent is idempotent even after a plan step advanced the
    retained work's expected authority (the comparison is against the original
    immutable intent, never the advanced cursor state)."""
    fixture = load_fixture()
    scenario = next(
        s for s in fixture["scenarios"] if s["id"] == "ordered_plan_resumes_after_partial_success"
    )
    upserts = [step for step in scenario["steps"] if step["op"]["type"] == "upsert"]
    first, *resends = upserts
    assert len(resends) >= 2
    for resend in resends:
        assert resend["op"] == first["op"]
        assert resend["returns"] == {"upsert": "unchanged"}
    core = EffectCasReference(scenario["generation"])
    for step in scenario["steps"]:
        if step["op"]["type"] == "upsert" and step is not first:
            # Same epoch, advanced expected authority: still a conflict.
            changed = {**step["op"], "expected": step["op"]["expected"] + 1}
            assert core.upsert(changed) == {"upsert": "epoch_conflict"}
        assert core.apply(step) == step["returns"]
