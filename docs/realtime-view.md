# Realtime View v1

Realtime View is an optional extension of the [View compute document](view.md).
It carries a full, versioned definition and pairs it with the standard Lazily
[Snapshot and Delta](../protocol.md#ipc) stream for reactive values. The host
owns rendering, input state, transport, and action authorization.

## Full revisions

A [revision](../schemas/realtime-view.json) consists of `version: 1`,
`view_instance`, `revision`, a complete View `definition`, a `bindings` map
from View signal IDs to graph node IDs, and an `actions` map from View node
IDs and semantic events to opaque host action IDs. The View document ID stays
constant within an instance. Revisions are positive safe integers (at most
2^53 − 1), increase monotonically, and may skip numbers. A host can replace a
definition without replaying the missed structural revisions.

Apply a definition only after validating the entire View with the View rules,
including semantic references and the tree, and evaluating its standing
expressions against the available values. Every binding must name a declared
signal and every action must name an existing node. Multiple signals may read
the same graph node. Bound graph nodes use type tag `lazily.view.scalar.v1`
and inline UTF-8 JSON payloads containing exactly one scalar (null, boolean,
safe integer, or string). Unbound signals read their declared initial value. Realtime expressions reject
integer intermediates outside the safe range, including an overflowing partial
sum. Hidden and disabled expressions must produce booleans.
The current projection remains available after invalid input. A newer
definition cannot change the document ID. A duplicate revision with the same
definition, bindings, and actions is ignored. An equal revision with different
content is invalid, and an older revision is ignored.

Use node IDs as identity keys throughout the View instance. A child of a
`list` node is a row keyed by that child's node ID. For immediately successive
applied revisions, a node whose ID, role, and `bind` match keeps its identity
even when its parent, sibling order, label, layout, or actions change.
Removal retires that identity. Reintroduction creates a new identity. A role
or binding change replaces the identity. A host preserves retained input
controls and their editing state, including the caret, selection, composition,
and any unsubmitted draft, while changing surrounding rows or labels.

## Attach and reconnect

An attach consists of the current full revision and a graph Snapshot from the
same instance. Publish them to the renderer together after both validate.
Attach is required before standalone revisions or Deltas. A reconnect to a
known instance applies the same validation, preserves retained identities and
the event ledger, and requires a Snapshot at or above the last applied graph
epoch. An older Snapshot is ignored. A new instance uses an independent
receiver, a fresh event ledger, and fresh node identities.

A standalone revision may refer only to bound values currently available in
the receiver's graph. If a new revision needs new graph nodes, the producer
can deliver those values before the revision, or attach the revision and a
Snapshot together. The same rule applies to removing nodes still read by an
older definition. A malformed frame or a missing/invalid bound value does
not advance the accepted graph epoch or structural revision. The receiver
returns the last accepted graph epoch with a snapshot request on the first
Delta gap and suppresses repeated requests while one is outstanding. A
matching Delta may fill the gap before the Snapshot arrives. Use the existing
[reliable sync decision rules](../protocol.md#resync--gap-handling) for
duplicates and multi-epoch spans. Graph epochs and View revisions advance
independently. Replacing or reconnecting a View never replays its actions.

## Semantic events

A [View event](../schemas/realtime-view.json) carries `version: 1`,
`view_instance`, `displayed_revision`, `node_id`, `event_id`, `event`, and
`payload`. The types are:

| Event | Payload |
|-------|---------|
| `activate` | null |
| `change` | null, boolean, safe integer, or string |
| `submit` | null, boolean, safe integer, or string |

The receiver checks the instance, then the accepted event ledger, then the
displayed revision. For a previously unseen event ID, only the current
displayed revision is eligible. A moved target, a changed action, a removed
target, and an unrelated revision update all require the host to obtain a new
gesture against the current revision. A current event whose node or action is
absent, hidden, or disabled is unavailable. The producer resolves the action
from its own revision and applies its own authorization. Action IDs are
routing data. Sending a View event confers no action authority.

Serialize receiver operations and keep the host authorization predicate
side-effect free. For an accepted event, reserve the event ID before exposing the authorized
action to host application code. An exact repeat is a duplicate, including
after a revision change or reconnect, and must not execute again. Reusing an
accepted ID with a different revision, node, event, or payload is a conflict.
An unaccepted ID does not enter the ledger. Only the accepted outcome may
cause action dispatch. This reference ledger has instance lifetime. A host
that keeps an instance across process restart must keep an equivalent durable
receipt or rotate the instance ID. Durability and idempotency of outward
host effects are the host's responsibility.

Standalone View `effects` retain their existing meaning in the compute
interpreter. A realtime renderer evaluates standing expressions and routes
only declared host actions at the trusted boundary. It does not execute
portable View effects on receipt of a definition or graph update.

## Conformance

Shared [fixtures](../conformance-extensions/realtime-view/explorer.json) exercise identity through
insertion, removal and reordering, invalid or reordered full revisions,
Delta gaps and Snapshot recovery, and stale, duplicate, or conflicting
events. Host tests separately verify focus, caret, IME, drafts, and action
authorization on the real renderer path. Structural deltas can be evaluated
using the pilot's observed revision sizes and frequency of change.
