# View

A **view** is a host-neutral compute document. It is the same class of artifact
as a [state chart](state-charts.md): declarative data a binding installs onto
one reactive context. It is not a Snapshot, not a Delta, and not a wire
message. It is not a widget tree and not a pixel layout.

The normative schema is [`schemas/view.json`](../schemas/view.json)
(`$id` `https://lazily.dev/schemas/view.json`, title `View`).

## Document

| Field | Required | Meaning |
|-------|----------|---------|
| `id` | yes | Stable document id. Non-empty string. |
| `root` | yes | Id of the root node. |
| `signals` | yes | Map of signal id → `{initial}`. May be empty. |
| `nodes` | yes | Map of node id → node. At least one node. |
| `chart` | no | A whole [`statechart.json`](../schemas/statechart.json) document. |

`additionalProperties` is false on the document and on every object it
defines. Unknown fields are malformed. That is what rejects widget names,
pixel fields (`x`, `y`, `width`, `height`, `pixels`), and host event names
(`onClick`, `onPressed`).

### Signals

`initial` is required. It may be null, a boolean, an integer, or a string.
Objects, arrays, and non-integer numbers are rejected. Install creates one `Source` per signal,
seeded with `initial`.

### Nodes

`role` is `text`, `button`, `field`, `list`, or `region`. No other role is a
node.

`children` is an ordered array of node ids. Child order is this array. Object
key order is not significant. Every node except the root has exactly one
parent. The root reaches every node. Cycles, diamonds, duplicate children, and
orphans are malformed.

`layout` is abstract:

- `flow`: `row`, `column`, or `stack`
- `align`: `start`, `center`, `end`, or `stretch`
- `grow`: an integer ≥ 0

No pixel, point, or host unit is representable.

`text` is either a string or an expression. `hidden` and `disabled` are either
a boolean or an expression. `bind` is a signal id and must name a declared
signal. `bind` does not write the signal. A `change` effect writes it, if the
document says so.

### Expressions

An expression is `{op, args}`. A bare null, boolean, integer, or string in an
argument position is a literal. There are no host closures.

| `op` | `args` | Result |
|------|--------|--------|
| `lit` | one literal | That literal. |
| `ref` | one string, a signal id | The signal's current value. The id must be declared. |
| `call` | a name, then arguments | One of the closed calls below. |
| `if` | condition, then, else | The condition must evaluate to a boolean. |
| `eq` | left, right | Boolean. Integers compare as integers. Different kinds are not equal. |
| `concat` | zero or more values | Each value stringified, then concatenated. |
| `trim` | one value | That value stringified, then trimmed of leading and trailing Unicode whitespace. |

Stringify: null → `""`, boolean → `true` or `false`, integer → its decimal
digits, string → itself.

Closed calls:

| Name | Args | Result |
|------|------|--------|
| `event` | none | The value delivered with the event currently being dispatched. Illegal outside an effect. Absent payload is null. |
| `not` | one boolean | Its negation. |
| `add` | two or more integers | Their sum. |
| `len` | one string | Its Unicode scalar count, as an integer. |

Any other call name, or the wrong arity, or the wrong kind of value, is
malformed. `event` inside `text`, `hidden`, or `disabled` is malformed: those
expressions are not effects.

Each expression installs as a guarded `Computed`.

### Effects

`effects` maps a semantic event to one effect. The only event names are
`activate`, `change`, and `submit`.

| `op` | `args` | Behavior |
|------|--------|----------|
| `set` | signal id, value expression | Write the signal. |
| `send` | event name, optional payload expression | Deliver that event to the chart cell. Requires `chart`. |
| `batch` | one or more effects | Run them in order. |

Dispatch of an event the node does not handle is a no-op: signals stay put and
the trace is empty. Dispatch of an unknown node or an unknown event name is
malformed.

The conformance trace is the `set` and `send` operations that ran, in order.
`batch` does not appear in the trace. A `set` record is
`{"op":"set","signal":"<id>","value":<value>}`. A `send` record is
`{"op":"send","event":"<name>"}` plus `"payload"` when the effect passed one.
`send` is recorded whether or not the chart accepts the event. The chart's
active leaves are a separate observation.

An effect installs as an `Effect`. The reference interpreter also subscribes
one host `Effect` to the expression computeds so a value change has a
subscriber that is not a host toolkit.

### Chart

When `chart` is present it is a state chart, installed as one cell on the same
context (the chart's configuration source). `send` calls that chart with an
empty guard map. A named guard therefore fails. An otherwise enabled
unguarded ancestor transition may still run. When `chart` is absent, any `send` is malformed.

## Install

Install is not part of the document.

1. One context per host.
2. Each signal becomes a `Source`.
3. Each expression becomes a guarded `Computed`.
4. Each effect becomes an `Effect`, run when its semantic event is dispatched.
5. The chart, if any, becomes one cell.

After install, hosts exchange values. A Snapshot cannot rebuild the view.

## What conformance asserts

Fixtures in [`conformance/view/`](../conformance/view/) are replayed the same
way as [`conformance/statechart/`](../conformance/statechart/). Each fixture
asserts:

- resolved signal values
- expression values, keyed `nodeId.text`, `nodeId.hidden`, and `nodeId.disabled` for fields the node has
- the effect trace (`set` / `send`)
- the abstract layout: preorder from the root, each node `{id, role, children, flow}` with `flow` null when the node sets none

`chart` in a fixture is the chart's active leaves (sorted), or null when the
document has no chart.

Conformance does not assert pixels, focus, IME, caret, gestures, list
virtualization, the accessibility tree, or a host patch list. A host library
may separately assert its own patch list (text, attribute, children, semantic
event) for a lowering that library already has. That assertion is not this
document.

## Fixtures

| Fixture | Covers |
|---------|--------|
| `counter.json` | Explicit null signal, `column` layout, `concat` / `ref` / `lit`, `call add`, `activate` → `set` |
| `field_change.json` | `row` layout, `field` `bind`, `change` → `trim` / `event`, `if` / `eq` / `not` |
| `batch_send.json` | `stack` layout, `list`, `call len`, `submit` → `batch` of `set` and `send`, chart cell and fail-closed guards |
| `malformed_rejected.json` | Missing signal map or initial, fractional initial, widget role, pixel field, host event name, unknown ops, dangling ids, `event` outside an effect, bad arity, cycle, orphan, unknown call, bad `bind`, `send` without a chart |
