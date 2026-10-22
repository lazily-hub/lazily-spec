#!/usr/bin/env python3
"""Generate the stale-handle disposal identity/kind matrix.

The generated fixture includes the Effect -> recycled Source reproduction for
btakita/agent-doc#354.  Keeping the cartesian product in code makes a missing
same-kind ABA row or cross-kind row visible instead of relying on hand-copying.

Run: python3 scripts/gen_stale_handle_disposal_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "conformance" / "reactive-graph" / "stale_effect_handle_cannot_remove_recycled_source.json"
KINDS = ("cell", "computed", "effect")


def _create(kind: str, node_id: str) -> dict:
    if kind == "cell":
        return {"op": {"type": "cell", "id": node_id, "value": 20}}
    if kind == "computed":
        return {
            "op": {
                "type": "computed",
                "id": node_id,
                "reads": ["driver"],
                "offset": 20,
            }
        }
    return {"op": {"type": "effect", "id": node_id, "reads": ["driver"]}}


def _prime(kind: str, node_id: str) -> list[dict]:
    if kind != "computed":
        return []
    return [
        {
            "op": {"type": "read", "id": node_id},
            "expect": {"value": 21},
        }
    ]


def _dispose_expect(stale_kind: str, successor_kind: str) -> dict:
    expect = {
        "recycled_id_confirmed": True,
        "readable": {"successor": True},
        "writable": {"successor": successor_kind == "cell"},
        "dependents_of": {"successor": 0},
        "dependencies_of": {"successor": 0 if successor_kind == "cell" else 1},
    }
    cleanups: dict[str, int] = {}
    if stale_kind == "effect":
        cleanups["stale"] = 1
    if successor_kind == "effect":
        cleanups["successor"] = 0
    if cleanups:
        expect["cleanups_of"] = cleanups
    return expect


def _survival_steps(successor_kind: str) -> list[dict]:
    if successor_kind == "cell":
        return [
            {
                "op": {"type": "set_cell", "id": "successor", "value": 21},
                "expect": {
                    "read": {"successor": 21},
                    "readable": {"successor": True},
                    "writable": {"successor": True},
                    "dependents_of": {"successor": 0},
                    "dependencies_of": {"successor": 0},
                },
            }
        ]
    if successor_kind == "computed":
        return [
            {"op": {"type": "set_cell", "id": "driver", "value": 2}},
            {
                "op": {"type": "read", "id": "successor"},
                "expect": {
                    "value": 22,
                    "readable": {"successor": True},
                    "writable": {"successor": False},
                    "dependents_of": {"successor": 0},
                    "dependencies_of": {"successor": 1},
                },
            },
        ]
    return [
        {
            "op": {"type": "set_cell", "id": "driver", "value": 2},
            "expect": {
                "observed_by": ["successor"],
                "observed_count": 1,
                "readable": {"successor": True},
                "writable": {"successor": False},
                "dependents_of": {"successor": 0},
                "dependencies_of": {"successor": 1},
                "cleanups_of": {"successor": 1},
            },
        },
        {
            "op": {"type": "dispose", "id": "successor"},
            "expect": {"cleanups_of": {"successor": 2}},
        },
    ]


def _scenario(stale_kind: str, successor_kind: str) -> dict:
    steps = [{"op": {"type": "cell", "id": "driver", "value": 1}}]
    steps.append(_create(stale_kind, "stale"))
    steps.extend(_prime(stale_kind, "stale"))
    steps.append({"op": {"type": "dispose", "id": "stale"}})
    steps.append(_create(successor_kind, "successor"))
    steps.extend(_prime(successor_kind, "successor"))
    steps.append(
        {
            "op": {
                "type": "dispose_stale_handle",
                "handle_of": "stale",
                "handle_kind": stale_kind,
                "successor": "successor",
                "successor_kind": successor_kind,
            },
            "expect": _dispose_expect(stale_kind, successor_kind),
        }
    )
    steps.extend(_survival_steps(successor_kind))
    scenario_id = f"stale_{stale_kind}_to_{successor_kind}"
    return {
        "id": scenario_id,
        "name": scenario_id,
        "requires": ["recycled_node_ids"],
        "steps": steps,
    }


def build() -> dict:
    return {
        "description": (
            "A stale handle is identified by allocator slot, generation, and node kind; "
            "disposing it MUST NOT remove the live occupant of a recycled slot "
            "(#lzspecedgeindex, btakita/agent-doc#354)."
        ),
        "kind": "ReactiveGraph",
        "model": "Context",
        "shape": "scenarios",
        "generator": "scripts/gen_stale_handle_disposal_fixture.py",
        "scenarios": [
            _scenario(stale_kind, successor_kind)
            for stale_kind in KINDS
            for successor_kind in KINDS
        ],
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
