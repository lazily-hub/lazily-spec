"""Executable oracle and mutation gates for the portable stdlib corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "conformance" / "stdlib"
SCHEMA = json.loads((ROOT / "schemas" / "stdlib-fixture.schema.json").read_text())
FIXTURES = tuple(sorted(FIXTURE_DIR.glob("*.json")))
U64_MAX = 2**64 - 1


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def terminal_observation(
    state: dict[str, Any], *, adapter_counts: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {"outcome": state["status"]}
    for key in ("fired_at", "value", "reason", "revision", "generation"):
        if key in state:
            result[key] = state[key]
    if adapter_counts:
        result["operation_calls"] = 0
        result["cancellation_calls"] = 0
    return result


def run_timer(
    state: dict[str, Any] | None, step: dict[str, Any], mutation: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if step["op"] == "start":
        now = step["now"]
        duration = step["duration"]
        if duration > U64_MAX - now:
            state = {"status": "unavailable", "reason": "deadline_overflow"}
            return state, terminal_observation(state)
        state = {
            "status": "pending",
            "deadline": now + duration,
            "last_now": now,
        }
        return state, {"outcome": "pending", "deadline": state["deadline"]}

    assert state is not None
    if mutation == "fixture_bookkeeping":
        return state, {"outcome": "pending", "deadline": state.get("deadline")}
    if state["status"] != "pending":
        if mutation != "terminal_not_latched":
            return state, terminal_observation(state)
        state = {
            "status": "pending",
            "deadline": state["deadline"],
            "last_now": state["last_now"],
        }

    now = step["now"]
    if now < state["last_now"]:
        return state, {
            "outcome": "unavailable",
            "reason": "clock_regression",
            "deadline": state["deadline"],
        }
    state["last_now"] = now
    reached = (
        now > state["deadline"]
        if mutation == "deadline_strict_greater"
        else now >= state["deadline"]
    )
    if reached:
        state["status"] = "fired"
        state["fired_at"] = now
        return state, {"outcome": "fired", "fired_at": now}
    return state, {"outcome": "pending", "deadline": state["deadline"]}


def run_timeout(
    state: dict[str, Any] | None, step: dict[str, Any], mutation: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if step["op"] == "start":
        now = step["now"]
        duration = step["duration"]
        if duration > U64_MAX - now:
            state = {"status": "unavailable", "reason": "deadline_overflow"}
            return state, terminal_observation(state)
        state = {
            "status": "pending",
            "deadline": now + duration,
            "last_now": now,
        }
        return state, {"outcome": "pending", "deadline": state["deadline"]}

    assert state is not None
    if mutation == "fixture_bookkeeping":
        return state, {
            "outcome": "pending",
            "deadline": state.get("deadline"),
            "operation_calls": 0,
            "cancellation_calls": 0,
        }
    if state["status"] != "pending":
        if mutation != "terminal_not_latched":
            return state, terminal_observation(state, adapter_counts=True)
        state = {
            "status": "pending",
            "deadline": state["deadline"],
            "last_now": state["last_now"],
        }

    now = step["now"]
    if now < state["last_now"]:
        state = {
            **state,
            "status": "unavailable",
            "reason": "clock_regression",
        }
        return state, {
            "outcome": "unavailable",
            "reason": "clock_regression",
            "operation_calls": 0,
            "cancellation_calls": 0,
        }
    state["last_now"] = now
    reached = (
        now > state["deadline"]
        if mutation == "deadline_strict_greater"
        else now >= state["deadline"]
    )
    if reached:
        state["status"] = "timed_out"
        return state, {
            "outcome": "timed_out",
            "operation_calls": 0,
            "cancellation_calls": 0,
        }

    operation = step["operation"]
    cancellation = step["cancellation"]
    counts = {"operation_calls": 1, "cancellation_calls": 1}
    if mutation == "cancellation_before_completion" and cancellation == "cancelled":
        state["status"] = "cancelled"
        return state, {"outcome": "cancelled", **counts}
    if operation == "completed":
        state["status"] = "completed"
        state["value"] = step["value"]
        return state, {"outcome": "completed", "value": step["value"], **counts}
    if operation == "unavailable":
        state["status"] = "unavailable"
        state["reason"] = "operation_unavailable"
        return state, {
            "outcome": "unavailable",
            "reason": "operation_unavailable",
            **counts,
        }
    if cancellation == "cancelled":
        state["status"] = "cancelled"
        return state, {"outcome": "cancelled", **counts}
    if cancellation == "unavailable":
        state["status"] = "unavailable"
        state["reason"] = "cancellation_unavailable"
        return state, {
            "outcome": "unavailable",
            "reason": "cancellation_unavailable",
            **counts,
        }
    return state, {
        "outcome": "pending",
        "deadline": state["deadline"],
        **counts,
    }


def barrier_observation(state: dict[str, Any]) -> dict[str, Any]:
    result = {
        "outcome": state["status"],
        "revision": state["revision"],
        "generation": state["generation"],
    }
    if "reason" in state:
        result["reason"] = state["reason"]
    return result


def run_barrier(
    state: dict[str, Any] | None, step: dict[str, Any], mutation: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    op = step["op"]
    if op == "start":
        state = {
            "status": "pending",
            "revision": step["revision"],
            "generation": 0,
            "required_revision": step["required_revision"],
            "deadline": step["deadline"],
            "last_now": None,
        }
        return state, barrier_observation(state)

    assert state is not None
    if mutation == "fixture_bookkeeping":
        state["status"] = "pending"
        return state, barrier_observation(state)
    if state["status"] != "pending":
        if mutation != "terminal_not_latched":
            observation = barrier_observation(state)
            if op == "observe":
                observation["cancellation_calls"] = 0
            return state, observation
        state["status"] = "pending"

    if op == "dispose":
        state["status"] = "disposed"
        return state, barrier_observation(state)

    if op == "receipt":
        if mutation == "receipt_is_authority":
            state["revision"] = max(state["revision"], state["required_revision"])
            state["generation"] += 1
            state["status"] = "satisfied"
        return state, barrier_observation(state)

    if op == "advance":
        state["revision"] = max(state["revision"], step["revision"])
        state["generation"] += 1
        if (
            state["revision"] >= state["required_revision"]
            and step["predicate"]
        ):
            state["status"] = "satisfied"
        return state, barrier_observation(state)

    if op in {"register_recheck", "observe"}:
        now = step["now"]
        if (
            state["last_now"] is not None
            and now < state["last_now"]
            and mutation != "barrier_accept_clock_regression"
        ):
            state["status"] = "unavailable"
            state["reason"] = "clock_regression"
            observation = barrier_observation(state)
            if op == "observe":
                observation["cancellation_calls"] = 0
            return state, observation
        state["last_now"] = now

    if op == "register_recheck":
        state["generation"] += 1
        if mutation == "barrier_skip_post_registration_recheck":
            return state, barrier_observation(state)
        state["revision"] = max(state["revision"], step["observed_revision"])
        if (
            state["revision"] >= state["required_revision"]
            and step["predicate"]
        ):
            state["status"] = "satisfied"
        return state, barrier_observation(state)

    assert op == "observe"
    now = step["now"]
    deadline = state["deadline"]
    reached = deadline is not None and (
        now > deadline
        if mutation == "deadline_strict_greater"
        else now >= deadline
    )
    if reached:
        state["status"] = "timed_out"
        return state, {**barrier_observation(state), "cancellation_calls": 0}
    if state["revision"] >= state["required_revision"] and step["predicate"]:
        state["status"] = "satisfied"
        return state, {**barrier_observation(state), "cancellation_calls": 0}
    if step["cancellation"] == "cancelled":
        state["status"] = "cancelled"
    elif step["cancellation"] == "unavailable":
        state["status"] = "unavailable"
        state["reason"] = "cancellation_unavailable"
    return state, {**barrier_observation(state), "cancellation_calls": 1}


RUNNERS = {
    "stdlib_timer_v1": run_timer,
    "stdlib_timeout_v1": run_timeout,
    "stdlib_revision_barrier_v1": run_barrier,
}


def replay(
    fixture: dict[str, Any], mutation: str | None = None
) -> dict[str, list[str]]:
    failures: dict[str, list[str]] = {}
    runner = RUNNERS[fixture["feature"]]
    for scenario in fixture["scenarios"]:
        state = None
        mismatches = []
        for index, step in enumerate(scenario["steps"]):
            state, actual = runner(state, step, mutation)
            if actual != step["expect"]:
                mismatches.append(
                    f"step {index}: expected {step['expect']!r}, got {actual!r}"
                )
        if mismatches:
            failures[scenario["id"]] = mismatches
    return failures


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_fixture_schema_and_floors(path: Path) -> None:
    fixture = load_fixture(path)
    jsonschema.Draft202012Validator(SCHEMA).validate(fixture)
    scenario_ids = [scenario["id"] for scenario in fixture["scenarios"]]
    assertion_count = sum(
        len(step["expect"])
        for scenario in fixture["scenarios"]
        for step in scenario["steps"]
    )
    assert len(scenario_ids) == len(set(scenario_ids))
    assert len(scenario_ids) >= fixture["scenario_floor"]
    assert assertion_count >= fixture["assertion_floor"]
    assert len(fixture["mutations"]) >= fixture["mutation_floor"]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_canonical_fixture_oracle(path: Path) -> None:
    assert replay(load_fixture(path)) == {}


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_every_declared_mutation_is_observed(path: Path) -> None:
    fixture = load_fixture(path)
    scenario_ids = {scenario["id"] for scenario in fixture["scenarios"]}
    for mutation in fixture["mutations"]:
        expected_failures = set(mutation["must_fail"])
        assert expected_failures <= scenario_ids
        actual_failures = set(replay(fixture, mutation["operator"]))
        assert expected_failures <= actual_failures, (
            f"{path.name}: mutation {mutation['operator']!r} was not observed by "
            f"{sorted(expected_failures - actual_failures)!r}"
        )


def test_corpus_contains_all_three_versioned_features() -> None:
    assert {load_fixture(path)["feature"] for path in FIXTURES} == set(RUNNERS)
