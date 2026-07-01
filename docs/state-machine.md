# State Machine

A **state machine** is the flat finite-state-machine primitive — a reactive cell
holding the current state plus a pure transition function. It is the kernel a
single-region [State Chart](state-charts.md) compiles down to, and the Lean
formal model in [`lazily-formal`](https://github.com/lazily-hub/lazily-formal)
(`LazilyFormal/StateMachine.lean`) fixes its semantics normatively.

A state machine is **compute, not protocol**. Like a chart, it is never
serialized as a distinct wire kind — only its current state crosses
IPC/FFI as an ordinary cell `Payload` (a `CellSet` op on the active-state cell).
Each binding implements it natively; this chapter fixes the *behavior* so a
machine defined in one language means the same thing in another.

## The kernel

The pure transition core is:

```
Transition : State -> Event -> Option State
Machine    = { current: State, transition: Transition }
send(m, e) = match m.transition(m.current, e) of
             | Some next => { current: next, ... }   // accepted
             | None      => m                         // rejected (guard)
```

A binding wraps the current `State` in a reactive cell and exposes `send` as the
mutator. The transition function is pure: given the current state and an event
it returns the next state (`Some`) or rejects the event (`None`, a guard).

## API surface

| Method | Description |
|--------|-------------|
| `new(ctx, initial, transition_fn)` | Create with an initial state and a pure transition function |
| `send(ctx, event) -> bool` | Evaluate the transition; `true` if accepted, `false` if rejected (`None`) |
| `state(ctx) -> State` | Read the current state |
| `state_handle() -> CellHandle<State>` | The underlying active-state cell, for reactive dependencies |
| `on_transition(ctx, old_new_callback) -> EffectHandle` | Observer firing on each state change with `(old, new)` |
| `state_is(ctx, target) -> SignalHandle<bool>` | Eager signal: `true` while in `target` |

## Semantics

- **PartialEq guard (no-op suppression):** a transition to an equal state is
  *accepted* (`send` returns `true`) but does **not** invalidate dependents —
  the active-state cell's equality guard suppresses the no-op update. This is
  the flat analogue of the chart [self-transition](state-charts.md#self-transitions)
  rule. To force re-entry, clear the cell's dependents before `send`.
- **Reactive integration:** any computed/memo/signal/effect that reads
  `state_handle()` automatically recomputes or reruns on a real transition.
- **On-enter / on-exit:** model with an effect that has a cleanup closure — the
  body is on-enter, the returned cleanup is on-exit (runs before the next rerun).
  `on_transition` provides a single `(old, new)` observer instead.
- **Batch atomicity:** a batch coalesces multiple `send` calls — effects fire
  once after the batch settles.
- **Deterministic transition function:** the transition function MUST be pure and
  deterministic. `send` never changes the transition function — a machine is
  fully described by its transition function and current state.

## Proven invariants

The Lean kernel (`lazily-formal/LazilyFormal/StateMachine.lean`) proves the
properties that are easiest to blur across bindings:

- **Guard rejection preserves state** — a rejected event (`None`) leaves
  `current` unchanged.
- **Accepted transitions advance state** — an accepted `Some(next)` sets
  `current = next`.
- **Self-transitions are no-ops** — `Some(current)` leaves `current` unchanged
  and `sends` returns `false`.
- **Changed transitions send `true`** — `Some(next)` with `next != current`
  reports a real change.
- **`send` preserves the transition function.**

## Relationship to state charts

A single-region chart refines this `send`: the chart's active leaf is the
`State`, the chart event is the `Event`, and the chart's walk-up + LCA +
descend-initial logic is a pure function returning `Some(new_leaf)` or `None`.
The confluence/determinism of a single-region chart is inherited from this kernel
(see [`single_region_refines_flat_machine`](state-charts.md) in
`lazily-formal/LazilyFormal/StateChart.lean`). A flat `StateMachine` is the
degenerate chart with no nesting.

## Context layers

The flat kernel is context-agnostic. A binding offers it over each reactive
context layer it implements, with identical semantics:

- **Single-threaded** — backed by the single-threaded reactive context.
- **Thread-safe** — a lock-backed counterpart over the thread-safe context; the
  transition function and state are `Send + Sync`, the machine is a clonable
  handle to the same state cell, and observers fire synchronously within the
  invalidating `send`/`batch` call preserving glitch-free pull-based ordering.
- **Async** — backed by the [async context](async.md); `send` and `state` stay
  synchronous (cells are the synchronous input layer), while reactive observers
  use the async effect/signal APIs and settle on the runtime rather than within
  `send`.

## Implementation status

The flat machine is required of all bindings that ship a reactive graph. A
binding MAY omit the thread-safe or async counterparts if it does not implement
those context layers, but the single-threaded machine and its PartialEq no-op
suppression MUST be present wherever a chart is supported (a chart depends on
this kernel). lazily-rs, lazily-zig, and lazily-py implement it; the Lean model
is the executable reference.
