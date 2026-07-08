#!/usr/bin/env python3
"""Generate conformance/message-passing/*.json fixtures.

Each fixture is a scenario the bindings replay through their CommandProjection
reducer. `frames` are validated against their named schema by
tests/test_schema_conformance.py; `expect.projection` is the reducer image every
binding must reproduce; `expect.rpc`, when present, pins the RPC facade's
terminal-only resolution rule.

Run from src/lazily-spec: `python scripts/gen_message_passing_fixtures.py`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "conformance" / "message-passing"


def inline(obj: dict) -> tuple[dict, str]:
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    payload = {"Inline": list(body)}
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    return payload, digest


def submit(
    command_id: str,
    name: str,
    payload_obj: dict,
    *,
    generation: int,
    payload_type: str,
    idempotency_key: str,
    source: str = "vscode-plugin",
    supersede: bool = False,
    deadline_ms: int = 120000,
    payload_override: dict | None = None,
    payload_hash_override: str | None = None,
) -> dict:
    payload, digest = inline(payload_obj)
    if payload_override is not None:
        payload = payload_override
    if payload_hash_override is not None:
        digest = payload_hash_override
    return {
        "CommandSubmit": {
            "command_id": command_id,
            "causation_id": command_id,
            "source": source,
            "target": "project-controller",
            "namespace": "agent-doc",
            "name": name,
            "authority_generation": generation,
            "idempotency_key": idempotency_key,
            "deadline_ms": deadline_ms,
            "policy": {
                "dedupe": "same_idempotency_key",
                "supersede": supersede,
                "cancel_on_preempt": True,
            },
            "payload_type": payload_type,
            "payload_hash": digest,
            "payload": payload,
            "required_features": ["causal-receipts", "command-events"],
        }
    }


def event(event_id: str, command_id: str, kind: str, generation: int, detail=None) -> dict:
    return {
        "event_id": event_id,
        "command_id": command_id,
        "kind": kind,
        "generation": generation,
        "detail": detail,
    }


def events(*evs: dict) -> dict:
    return {"CommandEvents": {"events": list(evs)}}


def receipt(receipt_id, causation_id, generation, outcome, reason=None, payload_hash=None) -> dict:
    return {
        "receipt_id": receipt_id,
        "causation_id": causation_id,
        "observer": "project-controller",
        "generation": generation,
        "outcome": outcome,
        "reason": reason,
        "payload_hash": payload_hash,
    }


def receipts(*rs: dict) -> dict:
    return {"CausalReceipts": {"receipts": list(rs)}}


def entry(
    command_id,
    status,
    terminal,
    generation,
    reason=None,
    terminal_receipt_id=None,
    last_event_id=None,
) -> dict:
    return {
        "command_id": command_id,
        "status": status,
        "terminal": terminal,
        "generation": generation,
        "reason": reason,
        "terminal_receipt_id": terminal_receipt_id,
        "last_event_id": last_event_id,
    }


def frame(schema: str, wire: dict) -> dict:
    return {"schema": schema, "wire": wire}


def write(name: str, obj: dict) -> None:
    obj = {"protocol_version": 1, "kind": "Command", **obj}
    (OUT / name).write_text(json.dumps(obj, indent=2) + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. editor_route_submit — full agent-doc Run payload over CommandSubmit.
    editor_payload = {
        "file": "/home/user/project/plan.md",
        "relative_path": "plan.md",
        "dispatch_only": False,
        "plain_trigger": False,
        "wait_budget_ms": 120000,
        "layout_args": {"columns": 2, "focus": True},
        "route_key": "project-root:plan.md:run",
        "editor_attempt_id": "attempt-7",
    }
    write(
        "editor_route_submit.json",
        {
            "model": "CommandSubmit",
            "description": "Full agent-doc Run Agent Doc payload carried over CommandSubmit. A bare submit is non-terminal: the projection lists it as submitted with terminal=false.",
            "frames": [
                frame(
                    "message-passing",
                    submit(
                        "cmd-run-1",
                        "editor_route",
                        editor_payload,
                        generation=42,
                        payload_type="agent-doc.editor_route.v1",
                        idempotency_key="project-root:plan.md:run",
                    ),
                )
            ],
            "expect": {
                "projection": {
                    "generation": 42,
                    "commands": [
                        entry("cmd-run-1", "submitted", False, 42, last_event_id=None)
                    ],
                }
            },
        },
    )

    # 2. sync_tmux_layout_submit — shared-blob capable payload fixture.
    write(
        "sync_tmux_layout_submit.json",
        {
            "model": "CommandSubmit",
            "description": "Sync Tmux Layout submit using a shared-memory blob payload (SharedBlob) rather than inline bytes; proves the envelope carries either IpcValue arm.",
            "frames": [
                frame(
                    "message-passing",
                    submit(
                        "cmd-sync-1",
                        "sync_tmux_layout",
                        {},
                        generation=42,
                        payload_type="agent-doc.sync_tmux_layout.v1",
                        idempotency_key="project-root:sync",
                        source="jetbrains-plugin",
                        payload_override={
                            "SharedBlob": {
                                "offset": 0,
                                "len": 96,
                                "generation": 1,
                                "epoch": 1,
                                "checksum": 4242,
                            }
                        },
                        payload_hash_override="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                    ),
                )
            ],
            "expect": {
                "projection": {
                    "generation": 42,
                    "commands": [
                        entry("cmd-sync-1", "submitted", False, 42, last_event_id=None)
                    ],
                }
            },
        },
    )

    # 3. accepted_then_applied_receipt — nonterminal progress then terminal applied.
    _, applied_hash = inline(editor_payload)
    write(
        "accepted_then_applied_receipt.json",
        {
            "model": "CommandProjection",
            "description": "observed/accepted events are progress only; the command becomes terminal ONLY when the applied CausalReceipt folds in.",
            "frames": [
                frame(
                    "message-passing",
                    submit(
                        "cmd-run-1",
                        "editor_route",
                        editor_payload,
                        generation=42,
                        payload_type="agent-doc.editor_route.v1",
                        idempotency_key="project-root:plan.md:run",
                    ),
                ),
                frame(
                    "message-passing",
                    events(
                        event("ev-1", "cmd-run-1", "observed", 42),
                        event("ev-2", "cmd-run-1", "accepted", 42, "queued at position 1"),
                        event("ev-3", "cmd-run-1", "started", 42),
                    ),
                ),
                frame(
                    "receipts",
                    receipts(
                        receipt("rcpt-1", "cmd-run-1", 42, "applied", payload_hash=applied_hash)
                    ),
                ),
            ],
            "expect": {
                "projection": {
                    "generation": 42,
                    "commands": [
                        entry(
                            "cmd-run-1",
                            "applied",
                            True,
                            42,
                            terminal_receipt_id="rcpt-1",
                            last_event_id="ev-3",
                        )
                    ],
                },
                "terminal_after_frame_index": 2,
            },
        },
    )

    # 4. stale_generation_ignored — stale receipt/event does not update projection.
    write(
        "stale_generation_ignored.json",
        {
            "model": "CommandProjection",
            "description": "An event and a receipt from an older authority generation are ignored by the current projection; the command stays non-terminal at the current generation.",
            "frames": [
                frame(
                    "message-passing",
                    submit(
                        "cmd-run-1",
                        "editor_route",
                        editor_payload,
                        generation=42,
                        payload_type="agent-doc.editor_route.v1",
                        idempotency_key="project-root:plan.md:run",
                    ),
                ),
                frame(
                    "message-passing",
                    events(event("ev-stale", "cmd-run-1", "started", 41, "from old generation")),
                ),
                frame(
                    "receipts",
                    receipts(
                        receipt(
                            "rcpt-stale",
                            "cmd-run-1",
                            41,
                            "applied",
                            reason="stale generation",
                        )
                    ),
                ),
            ],
            "expect": {
                "projection": {
                    "generation": 42,
                    "commands": [
                        entry("cmd-run-1", "submitted", False, 42, last_event_id=None)
                    ],
                },
                "ignored_frame_indices": [1, 2],
            },
        },
    )

    # 5. terminal_conflict_fail_closed — conflicting terminal receipts fail closed.
    write(
        "terminal_conflict_fail_closed.json",
        {
            "model": "CommandProjection",
            "description": "Two terminal receipts at the same generation with different outcomes (applied vs rejected) is a terminal conflict; the reducer fails closed instead of picking a winner.",
            "frames": [
                frame(
                    "message-passing",
                    submit(
                        "cmd-run-1",
                        "editor_route",
                        editor_payload,
                        generation=42,
                        payload_type="agent-doc.editor_route.v1",
                        idempotency_key="project-root:plan.md:run",
                    ),
                ),
                frame(
                    "receipts",
                    receipts(receipt("rcpt-applied", "cmd-run-1", 42, "applied")),
                ),
                frame(
                    "receipts",
                    receipts(
                        receipt(
                            "rcpt-rejected",
                            "cmd-run-1",
                            42,
                            "rejected",
                            reason="conflicting terminal",
                        )
                    ),
                ),
            ],
            "expect": {
                "conflict": True,
                "conflict_command_id": "cmd-run-1",
                "conflict_after_frame_index": 2,
                "projection_before_conflict": {
                    "generation": 42,
                    "commands": [
                        entry(
                            "cmd-run-1",
                            "applied",
                            True,
                            42,
                            terminal_receipt_id="rcpt-applied",
                        )
                    ],
                },
            },
        },
    )

    # 6. cancel_preempts_nonterminal — cancel rejects only before applied.
    write(
        "cancel_preempts_nonterminal.json",
        {
            "model": "CommandProjection",
            "description": "CommandCancel terminally rejects a still-non-terminal command (rejected receipt with reason 'cancelled'). A cancel arriving after applied is ignored — it never rewrites applied into rejected.",
            "scenarios": [
                {
                    "name": "cancel_before_terminal",
                    "frames": [
                        frame(
                            "message-passing",
                            submit(
                                "cmd-run-1",
                                "editor_route",
                                editor_payload,
                                generation=42,
                                payload_type="agent-doc.editor_route.v1",
                                idempotency_key="project-root:plan.md:run",
                            ),
                        ),
                        frame(
                            "message-passing",
                            events(event("ev-1", "cmd-run-1", "accepted", 42)),
                        ),
                        frame(
                            "message-passing",
                            {
                                "CommandCancel": {
                                    "command_id": "cmd-run-1",
                                    "causation_id": "cancel-1",
                                    "source": "vscode-plugin",
                                    "authority_generation": 42,
                                    "reason": "operator cleared run",
                                }
                            },
                        ),
                        frame(
                            "message-passing",
                            events(event("ev-2", "cmd-run-1", "cancelled", 42)),
                        ),
                        frame(
                            "receipts",
                            receipts(
                                receipt(
                                    "rcpt-cancel",
                                    "cmd-run-1",
                                    42,
                                    "rejected",
                                    reason="cancelled",
                                )
                            ),
                        ),
                    ],
                    "expect": {
                        "projection": {
                            "generation": 42,
                            "commands": [
                                entry(
                                    "cmd-run-1",
                                    "cancelled",
                                    True,
                                    42,
                                    reason="cancelled",
                                    terminal_receipt_id="rcpt-cancel",
                                    last_event_id="ev-2",
                                )
                            ],
                        }
                    },
                },
                {
                    "name": "cancel_after_applied_ignored",
                    "frames": [
                        frame(
                            "message-passing",
                            submit(
                                "cmd-run-1",
                                "editor_route",
                                editor_payload,
                                generation=42,
                                payload_type="agent-doc.editor_route.v1",
                                idempotency_key="project-root:plan.md:run",
                            ),
                        ),
                        frame(
                            "receipts",
                            receipts(receipt("rcpt-applied", "cmd-run-1", 42, "applied")),
                        ),
                        frame(
                            "message-passing",
                            {
                                "CommandCancel": {
                                    "command_id": "cmd-run-1",
                                    "causation_id": "cancel-late",
                                    "source": "vscode-plugin",
                                    "authority_generation": 42,
                                    "reason": "too late",
                                }
                            },
                        ),
                    ],
                    "expect": {
                        "projection": {
                            "generation": 42,
                            "commands": [
                                entry(
                                    "cmd-run-1",
                                    "applied",
                                    True,
                                    42,
                                    terminal_receipt_id="rcpt-applied",
                                )
                            ],
                        },
                        "ignored_frame_indices": [2],
                    },
                },
            ],
        },
    )

    # 7. reconnect_command_projection — resync image after reconnect.
    write(
        "reconnect_command_projection.json",
        {
            "model": "CommandProjection",
            "description": "After a controller handoff/recycle a plugin resyncs with a CommandProjection frame. Folding the projection directly is equivalent to having folded the underlying events+receipts.",
            "frames": [
                frame(
                    "message-passing",
                    {
                        "CommandProjection": {
                            "generation": 43,
                            "commands": [
                                entry(
                                    "cmd-run-1",
                                    "applied",
                                    True,
                                    43,
                                    terminal_receipt_id="rcpt-1",
                                    last_event_id="ev-3",
                                ),
                                entry("cmd-run-2", "running", False, 43, last_event_id="ev-9"),
                            ],
                        }
                    },
                )
            ],
            "expect": {
                "projection": {
                    "generation": 43,
                    "commands": [
                        entry(
                            "cmd-run-1",
                            "applied",
                            True,
                            43,
                            terminal_receipt_id="rcpt-1",
                            last_event_id="ev-3",
                        ),
                        entry("cmd-run-2", "running", False, 43, last_event_id="ev-9"),
                    ],
                }
            },
        },
    )

    # 8. rpc_call_waits_for_terminal — facade resolves only on terminal.
    write(
        "rpc_call_waits_for_terminal.json",
        {
            "model": "CommandProjection",
            "description": "A unary RPC call does NOT resolve on accepted/queued/started progress; it resolves only when a terminal CausalReceipt folds in. resolves_after_frame_index pins the exact fold at which call() may return.",
            "frames": [
                frame(
                    "message-passing",
                    submit(
                        "cmd-run-1",
                        "editor_route",
                        editor_payload,
                        generation=42,
                        payload_type="agent-doc.editor_route.v1",
                        idempotency_key="project-root:plan.md:run",
                    ),
                ),
                frame(
                    "message-passing",
                    events(
                        event("ev-1", "cmd-run-1", "observed", 42),
                        event("ev-2", "cmd-run-1", "accepted", 42, "queued"),
                        event("ev-3", "cmd-run-1", "started", 42),
                    ),
                ),
                frame(
                    "receipts",
                    receipts(receipt("rcpt-1", "cmd-run-1", 42, "applied")),
                ),
            ],
            "expect": {
                "rpc": {
                    "command_id": "cmd-run-1",
                    "resolves_after_frame_index": 2,
                    "unresolved_after_frame_indices": [0, 1],
                    "terminal_status": "applied",
                },
                "projection": {
                    "generation": 42,
                    "commands": [
                        entry(
                            "cmd-run-1",
                            "applied",
                            True,
                            42,
                            terminal_receipt_id="rcpt-1",
                            last_event_id="ev-3",
                        )
                    ],
                },
            },
        },
    )


if __name__ == "__main__":
    main()
    print("wrote fixtures to", OUT)
