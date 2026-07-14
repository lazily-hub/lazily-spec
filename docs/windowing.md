# Stream windowing (`#lzwindow`)

Phase 5 of the realtime + distributed primitives plan. Lifts the relay plane's
`WindowPolicy` (`#lzrateshape`) into real **stream-window** primitives over a
stream, emitting window **aggregates**. Window aggregation *is* a merge, so the
`MergePolicy` algebra (`Sum` / `Max` / `SetUnion` / custom — `#relaycell`)
composes without new code: the aggregate of a window equals the associative fold
of its elements.

Each primitive is a pure compute **core** (the window bookkeeping + a
`MergePolicy` fold — `BytesPayload` when the aggregate is bytes-eligible) split
from a reactive **cell** projecting the last emitted aggregate onto a `Cell`
(invalidates on each emit).

## `TumblingWindow` — fixed, non-overlapping

- **Count** (`TumblingWindow::count(n)`) — accumulate `n` elements under the
  merge; on the `n`-th, emit the window aggregate and reset.
- **Time** (`TumblingWindow::time(period)`) — accumulate into the current
  window; at each period boundary (`tick(now)` with `now ≥ next`) emit the
  window aggregate and open the next window. An empty window emits nothing.

## `SlidingWindow(size, slide)` — overlapping

Retains the last `size` elements; every `slide` pushes, emit the merge-fold over
the current window. (Fold-recompute, so it is correct for **any** associative
merge, not only invertible ones.)

## `SessionWindow` — gap-based

Sessionizes by idle gap: accumulate consecutive elements into a session; when a
new element arrives more than `gap` after the previous one, **close** the current
session (emit its aggregate) and open a new one with the arriving element. A
`flush(now)` closes the open session once it has been idle longer than `gap`. The
`gap` threshold is a reactive cell (adaptive).

## Aggregate = windowed merge

Because merge is associative, regrouping a run of elements into windows never
changes the per-window fold: the emitted aggregate is exactly the left-fold of
the window's elements under `⊕`. This is the correctness core (`Sum`/`Max`/
`SetUnion` windows compose for free).

## Conformance

`conformance/windowing/` uses `Sum` (u64) aggregates for determinism.

| Fixture | Model | Checks |
|---------|-------|--------|
| `tumbling_count.json` | `TumblingWindow` (count) | emit the fold every `n` elements; reset between windows |
| `tumbling_time.json` | `TumblingWindow` (time) | emit the window fold at each period boundary; empty window emits nothing |
| `sliding_count.json` | `SlidingWindow` | emit the fold over the last `size` on every `slide` |
| `session.json` | `SessionWindow` | accumulate within `gap`; a larger gap closes+emits and opens a new session; `flush` closes an idle session |

Ops are `{ "type": "push", "now"?, "value" }` / `{ "type": "tick"|"flush",
"now" }`; `returns` is the emitted aggregate (or `null`); `expected.output` is
the last emitted aggregate and `expected.invalidates.output` whether it changed.

## Formal model

`lazily-formal/LazilyFormal/Windowing.lean`: the window aggregate equals the fold
of its elements, and regrouping (windowing) preserves the total fold under an
associative merge (`window_fold_regroup`, `tumbling_emits_fold`).
