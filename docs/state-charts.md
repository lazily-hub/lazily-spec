# State Charts

A **state chart** is a Harel/SCXML hierarchical state machine. This chapter
specifies the **full** cross-language subset all lazily bindings implement:
compound (nested) states, orthogonal (**parallel / AND**) regions, **history**
states (shallow and deep), entry/exit/run **actions**, internal/external
transitions, **guards**, and **extended state** (`context`). It also fixes the
declarative chart form the conformance fixtures use and how a chart relates to
the reactive [Cell Model](cell-model.md) and the flat FSM kernel in the [Lean
Formal Model](formal-model.md).

A state chart is **compute, not protocol**. It is never serialized over the wire
as a distinct kind — only its converged active **configuration** crosses
IPC/FFI as an ordinary cell `Payload`. Each binding implements the chart
natively; this chapter fixes the *behavior* so a chart defined in one language
means the same thing in another (validated by the [conformance fixtures](#conformance-fixtures)).

The declarative chart form is normatively defined by
[`schemas/statechart.json`](../schemas/statechart.json) (JSON Schema, Draft
2020-12). The prose below fixes its semantics.

## Why a chart reduces to existing machinery

The Lean kernel (`formal/lean/LazilyFormal/StateMachine.lean`) defines a pure
transition `State → Event → Option State`. A single-region chart compiles to
exactly this kernel: the chart's **active leaf** is the `State`, the **event**
is the `Event`, and the chart's transition logic (walk-up + LCA +
descend-initial) is a pure function returning `Some(new_leaf)` or `None`.

Orthogonal regions generalize `State` from a single leaf to an active
**configuration** (a set of leaves, one per region). The transition is still a
pure `Configuration → Event → Option Configuration`: enabled transitions,
conflict resolution, and exit/enter-set computation are all deterministic
functions of the chart definition and the current configuration. Because of
this, a chart cell is **single-writer** by the [Cell Model](cell-model.md)
rules — it is either a direct cell (reactive bindings) or a derived cell keyed
off event cells. It is therefore **never multi-write**: replicas converge on
the event stream, and each replica's chart recomputes deterministically. No
`merge:` mechanism is defined or needed for charts.

## Reactive vs. projection bindings

| Binding | Chart backing | Why |
|---------|---------------|-----|
| lazily-rs, lazily-py, lazily-zig, lazily-dart | reactive `Cell` (active configuration) | these run their own reactive graph; the chart composes with slots/signals/effects |
| lazily-kt, lazily-js | pure native (no reactive graph) | these are state-projection **consumers**; a chart is plugin-local compute. If a chart's state must be authoritative/shared, the chart runs in lazily-rs and these bindings observe it via the existing snapshot/delta projection — never via chart FFI |

A chart is **never** exposed over FFI. lazily-kt and lazily-js implement it
natively because the transition is pure logic with zero system dependencies;
routing it through JNA/koffi to a Rust `Context` would be circular (the only
thing FFI buys them is an authoritative projection, which a local chart is not).

## Declarative chart form

Conformance fixtures and cross-language chart definitions use a flat id map.
States form a tree via `parent`. The full form:

```json
{
  "initial": "<state-id>",
  "context"?: { … },
  "states": {
    "<id>": {
      "parent"?: "<id>",
      "kind"?: "atomic" | "compound" | "parallel" | "history" | "final",
      "initial"?: "<child-id>",          // compound only
      "parallel"?: true,                  // AND-state: children are concurrent regions
      "history"?: "shallow" | "deep",     // history pseudo-state
      "default"?: "<target-id>",          // history: resume target before any recording
      "on"?: { "<event>": <transition>, … },
      "entry"?: [<action>, …],
      "exit"?:  [<action>, …],
      "run"?:    [<action>, …]
    }
  }
}
```

`kind` is optional and inferred: `history` when `history` is set; `parallel`
when `parallel` is true; `compound` when the state has children; otherwise
`atomic`. A `<transition>` is a bare target-id string (shorthand for
`{"target": id}`) or an object:

```json
{ "target": "<id>", "guard"?: <guard>, "action"?: [<action>], "internal"?: false }
```

**Structural rules**

- Exactly one state has no `parent` — the **root**.
- A **compound** state (one with children) MUST declare `initial`, which MUST
  resolve to a leaf by descending compound `initial`s.
- A **parallel** state MUST NOT declare `initial`; its children are the
  concurrent regions, and all of them are active whenever the parallel state is.
- A **history** state MUST NOT declare `initial` or `parallel`; it MUST declare
  `history` and SHOULD declare `default`. Its `parent` is the region whose
  configuration it records.
- An **atomic** state has no children, no `initial`, and no `parallel`.
- A `final` state signals completion of its parent region (see
  [Completion](#completion)).

## Active configuration

The **active configuration** is the set of states that are currently active:

- A state is active if any of its children is active (compound), or **all** of
  its region children are active (parallel), or it is an active leaf.
- For a single-region chart, the configuration is the path **root → active
  leaf** and contains exactly one leaf.
- For a chart with parallel regions, the configuration contains **one leaf per
  region** plus all their ancestors (including the parallel state itself).

The set of **active leaves** is the subset of atomic active states.

## Transition selection

`send(event)` runs **run-to-completion**: it computes the next configuration
from the current one with no interleaving of external events.

### 1. Enabled transitions

For each **active leaf**, walk **up** its ancestor chain. At each ancestor,
collect every transition whose `on[event]` matches `event` and whose `guard`
passes. A guard passes when it is absent, resolves `true` (see [Guards](#guards)),
or — for a context-expression guard — evaluates `true` against `context`. A
single event may enable transitions in **more than one region** (parallel
charts fire concurrently).

### 2. Conflict resolution

Two enabled transitions **conflict** if their exit sets (computed next)
intersect — i.e. one would exit a state the other needs. Resolve conflicts by:

1. If one transition's source is a descendant of the other's source, keep the
   **descendant** (innermost wins).
2. Otherwise keep the one that appears **first in document order** (the order
   states and their `on` entries are declared).

The surviving set is taken atomically.

### 3. Exit and enter sets

For each taken transition with source `s` and target `t`:

- `lca` = the lowest state that is an ancestor of **both** the active leaf in
  `s`'s region and `t`. (For a transition internal to one parallel region, the
  `lca` stays inside that region and the sibling regions are untouched.)
- **Exit set** = active states strictly below `lca`, restricted to `s`'s region
  subtree.
- **Enter set** = the path `lca → t`, then:
  - if `t` is **compound**, descend via `initial` to a leaf;
  - if `t` is **parallel**, enter **every** region child and descend each;
  - if entering a region whose recorded **history** exists, descend via the
    recorded configuration instead of `initial` (see [History](#history));
  - if `t` is a **history** state, resume its parent region per its recorded
    configuration (or `default` if none).

The total exit set is the union over taken transitions; the total enter set is
the union, plus any parallel siblings forced active by entering a parallel
state. Exit actions run **innermost-first** (reverse document order within the
exit set); then transition `action`s run; then entry actions run
**outermost-first** (document order within the enter set).

**Internal vs external.** A transition with `internal: true` whose target is
the source or a descendant of it does **not** exit/re-enter the source — only
its `action` runs and descendants below the target are reconfigured. The
default is **external** (exit/re-enter the source).

### 4. Apply

The new configuration is the old one minus the total exit set plus the total
enter set. If no transition was enabled, the event is **rejected**: return
`false`, state unchanged.

### Single-region specialization

With no parallel regions the algorithm collapses to the SCXML single-region
rule: walk up from the one active leaf, take the first passing transition, and
compute exit/enter through the `lca`. `lca` makes sibling-substate transitions
(e.g. `a.x → a.y`) cheap (exit only `x`, enter `y`) and cross-subtree
transitions (`a.x → b.y`) correct (exit `a.x…`, enter `b.y…`).

## Queries

- `active()` → the active leaf id. Defined for single-region charts; for charts
  with parallel regions it is **undefined** (use `configuration()`).
- `configuration()` → the full set of active state ids (leaves plus all active
  ancestors).
- `activeLeaves()` → the set of active atomic state ids (one per region).
- `matches(id)` → `true` iff `id` is in `configuration()` (the hierarchical
  "state-in" predicate).

## History

A history pseudo-state records its parent region's active configuration
whenever that region is exited, and resumes it when the region is re-entered by
a transition targeting the history state.

- **Shallow** (`"history": "shallow"`): records/restores the **direct child**
  of the parent region that was active. Nested configuration below that child
  is re-derived from the child's own `initial`.
- **Deep** (`"history": "deep"`): records/restores the **full nested leaf
  configuration** of the parent region, across all descendant compound and
  parallel levels.
- **First entry:** when a region with a history child has never been exited
  (no recording), a transition targeting the history state enters `default`
  instead. `default` SHOULD be declared; if absent, the region's `initial` is
  used.

A region records history on **every** exit, including exits caused by a
transition that leaves the region without targeting its history, so a later
re-entry via history resumes the most recent configuration.

## Actions

Actions are **host-resolved side effects**, never part of the configuration.
A binding accepts an action handler `name → effect`; for conformance replay,
each step asserts the ordered trace of action names that fired.

- `entry` — fired when the state enters, after its ancestors' entries.
- `exit` — fired when the state exits, before its ancestors' exits.
- `run` — ongoing (do) actions: started on entry, cancelled on exit.
  Host-managed; not part of conformance replay.
- transition `action` — fired after the exit set and before the enter set.

Order, restated: **exit actions (innermost-first) → transition action → entry
actions (outermost-first)**, per the [exit/enter set computation](#3-exit-and-enter-sets).

## Guards

A transition may name a guard. A guard is either:

- a **bare string** — a named guard resolved by the caller's guard resolver
  (`name → bool`); when no resolver is supplied or the name is unknown it is
  treated as `false` (**fail-closed**); or
- an object `{"expr": "…"}` — an extended-state expression the host evaluates
  against `context`.

Guards are pure predicates over caller-supplied state, never over the chart's
own configuration. For conformance replay, each step supplies its guard outcomes
explicitly by name, so every binding reproduces identical behavior without
shipping a guard evaluator.

## Extended state

`context` is optional host-resolved caller state over which context-expression
guards evaluate. It is never serialized as part of the active configuration; it
lives outside the chart. A binding that supports `context` exposes it to guard
expressions and transition/entry actions; a binding that does not MUST reject
charts that use `{"expr": …}` guards explicitly rather than silently treating
them as passing.

## Completion

A `final` state marks its parent region complete. When every region of a
parallel state reaches a `final` child, the parallel state itself is complete
and a completion (`done`) event is raised for the parent. This is the SCXML
automatic transition on completion. (Bindings MAY defer `final`/completion to a
later revision, but MUST reject `final` explicitly if unsupported.)

## Reactive binding

In reactive bindings the active configuration lives in a `Cell`. On
`send(event)` the pure transition produces a new configuration; the cell's
`!=` (PartialEq) guard suppresses downstream invalidation when the
configuration is unchanged (e.g. a no-op self-transition or a parallel-region
transition that doesn't change the leaf set). Any `Slot` / `Signal` /
subscriber reading `active()`, `configuration()`, or `matches()` is
invalidated on a real transition.

## Self-transitions

A transition whose resulting configuration equals the current one is a no-op:
accepted (`true`) but the cell's `PartialEq` guard suppresses downstream
invalidation, identical to the flat `StateMachine` self-transition rule. (For
an external self-transition that must re-run `entry`/`exit`, the configuration
object is still replaced; whether that invalidates dependents is the binding's
documented choice — conformance asserts the action trace, not invalidation
counts.)

## Conformance fixtures

Canonical charts live in
[`conformance/statechart/`](../conformance/statechart/). Each binding loads
them, asserts `initial_active` (and `initial_actions` when present), replays
the `steps`, and asserts `accepted`, `active`, `matches`, and (when present)
`actions` after each step. For parallel charts `active` is an array of active
leaves (sorted); for single-region charts it is a single leaf id.

**Fixture schema**

```json
{
  "description": "…",
  "kind": "StateChart",
  "initial_active": "leaf" | ["leaf", …],
  "initial_actions"?: ["action", …],
  "chart": { …per schemas/statechart.json… },
  "steps": [
    {
      "event": "START",
      "guards"?: { "name": true },
      "accepted": true,
      "active": "leaf" | ["leaf", …],
      "matches"?: { "state-id": true },
      "actions"?: ["action", …]
    }
  ]
}
```

- `initial_active` — expected active leaf (or leaves for parallel) after
  descending `chart.initial`, asserted once before any step.
- `initial_actions` (optional) — ordered action names fired during initial
  entry.
- `event` — the event sent.
- `guards` (optional) — per-step named guard outcomes for this send.
- `accepted` — expected `send` return value.
- `active` — expected active leaf (single) or active-leaf set (parallel) after
  the step.
- `matches` (optional) — `{ state-id: bool }` expectations for `matches()`.
- `actions` (optional) — ordered action names fired during the step (exit →
  transition → entry).

Current fixtures:

| Fixture | Covers |
|---------|--------|
| `flat_cycle.json` | flat (single-level) transitions, rejection, cycle |
| `hierarchical_player.json` | nesting, walk-up transition resolution, LCA across levels, `matches()` |
| `guarded_door.json` | named guards, fail-closed rejection, guard pass |
| `parallel_regions.json` | orthogonal (AND) regions: per-region transitions, `matches()` across regions, exiting all regions |
| `history_shallow.json` | shallow history: resume last direct child on re-entry; first-entry `default` |
| `history_deep.json` | deep history: resume full nested leaf configuration; sticky across cycles |
| `entry_exit_actions.json` | entry/exit/transition action ordering across LCA boundaries |

## Implementation status

The single-region subset (compound states, walk-up resolution, LCA, guards,
self-transitions) is required of all bindings. Orthogonal regions, history,
actions, and extended state are specified here in full; a binding MAY implement
a subset, but MUST reject any feature it does not implement **explicitly**
(never silently ignore a `parallel`, `history`, `entry/exit/run`, or
`{"expr": …}` guard). Each binding's conformance run selects the fixtures that
match its implemented subset.
