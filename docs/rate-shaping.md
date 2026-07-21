# Rate-shaping source primitives (`#lzrateshape`)

Phase 0 of the realtime + distributed primitives plan. Debounce / throttle /
time-sampling already exist *algorithmically* inside the relay plane — they are
trapped behind `RelayCell::egress` as `WindowPolicy` / `ExpiryPolicy` /
`RatePolicy`. This phase **lifts** those policies into a standalone `rateshape`
home (relay policies re-export them, semantics unchanged) and adds four
source-level operators so **any** `Cell<T, K>` source can be rate-shaped, not
just a relay.

All four are logical-clock driven (a monotone `now`), like every temporal
primitive (`#lztime`). Each is a pure compute **core** — the emit/drop decision
over plain state (the C++-eligible part) — split from a thin reactive cell that
projects the emitted value onto a `Cell` (so a dropped input never invalidates
dependents). Payload class: the value passes through, so these are
**`PyObjectPayload`** unless `T` is a canonical `BytesPayload`; the decision core
is bytes-eligible.

## `DebounceCell<T>` — emit latest after a quiet period

Coalesces inputs (KeepLatest) and emits the latest value once **no input has
arrived for `quiet` ticks** — every input resets the quiet deadline. Composed
from a KeepLatest fold + a lifted deadline (`WindowPolicy::tick` over a
per-input `fire_at`).

- `input(now, v)` — `pending = v` (KeepLatest); `fire_at = now + quiet`.
- `tick(now)` — if there is pending input and `now ≥ fire_at`, emit the pending
  value and clear it (one emit per quiet period); else nothing.
- **Emits only the latest**, **only after the quiet period**, and the emit edge
  is the only reader invalidation.

## `ThrottleCell<T>` — one emit per window

Two edge variants over a fixed `window`:

- **Leading** — the first input of a window passes immediately; the rest are
  dropped (`DropNewest`) until the window elapses. `input(now, v)`: emit `v` and
  open a window `[now, now+window)` if none is active or the active one elapsed;
  else drop.
- **Trailing** — the first input opens a window but does not emit; inputs
  coalesce (KeepLatest); at the window boundary (`tick(now)` with
  `now ≥ window_start + window`) the latest is emitted and the window closes.

**At most one emit per window** in both variants.

## `SampleCell<T>` — deterministic sampling

Two modes:

- **Count** (`every_n`) — emit every `n`-th input: `input(v)` increments a
  counter, emits `v` iff `counter mod n == 0`.
- **Time** (`every_t`) — hold the latest input and emit it at each period
  boundary (`period, 2·period, …`), one emit per boundary crossed (interval
  semantics from `#lztime`). The held value persists across emits (sampling the
  signal's current value).

Deterministic: identical input/clock sequences produce identical emit sequences.

## `ProbabilisticSampleCell<T>` — tail sampling (NEW algorithm)

The only new algorithm in the plan (not in `RatePolicy`). Each input passes with
probability `rate ∈ [0, 1]`, driven by an **injectable** RNG so it is
deterministic under a fixed seed. The pure decision core is
`should_sample(draw) = draw < rate` over a random `draw ∈ [0, 1)`; the reactive
cell owns the RNG and feeds `should_sample(rng.next())`. Use case: trace
sampling, hot-path observability.

- **Threshold monotone in `rate`**: a higher `rate` passes a superset of draws
  (`rate₁ ≤ rate₂ ⇒ should_sample` at `rate₁` implies at `rate₂`).
- `rate = 0` drops all; `rate = 1` passes all (`draw < 1` always for `draw ∈ [0,1)`).

## Conformance

`conformance/rateshape/` replays each operator under a logical clock. Ops are
`{ "type": "input", "now": N, "value": v [, "draw": d] }` or
`{ "type": "tick", "now": N }`; `returns` is the emitted value (or `null` when
the op drops / holds); `expected.output` is the last emitted value and
`expected.invalidates.output` is whether the emit edge fired.

| Fixture | Model | Checks |
|---------|-------|--------|
| `debounce.json` | `DebounceCell` | resets on input; emits latest only after quiet; one emit per quiet period |
| `throttle_leading.json` | `ThrottleCell` (Leading) | first-in-window passes, rest dropped, re-opens after window |
| `throttle_trailing.json` | `ThrottleCell` (Trailing) | coalesce latest, emit at window boundary |
| `sample_count.json` | `SampleCell` (Count) | emit every n-th input |
| `sample_time.json` | `SampleCell` (Time) | emit held latest at each period boundary |
| `probabilistic_sample.json` | `ProbabilisticSampleCell` | pass iff `draw < rate` (injected draws) |

## Refactor

`WindowPolicy` / `ExpiryPolicy` / `RatePolicy` move out of `relay_policy` into a
new `rateshape` module; relay policies **re-export** them so the relay plane and
its conformance are unchanged (a regression guard: the existing relay-policy
tests must pass unmodified).

## Formal model

`lazily-formal/LazilyFormal/RateShape.lean`: debounce emits only after the
deadline and only the latest (`debounce_no_emit_before`, `debounce_emits_latest`);
leading throttle emits at most once per window (`throttle_leading_one_per_window`);
count sampling emits exactly on multiples of `n` (`sample_count_on_multiples`);
probabilistic threshold is monotone in `rate` (`prob_sample_monotone`) with the
`rate = 0` / `rate = 1` endpoints.
