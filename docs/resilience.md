# Fault-tolerance primitives (`#lzresilience`)

Phase 6 of the realtime + distributed primitives plan. Composes with
`CommandTransport` / `CommandPolicy` so RPCs degrade gracefully. Each primitive
is a pure compute **core** (a state machine / counter over the logical clock —
`BytesPayload`) split from a reactive **cell** projecting the salient reader.

## `CircuitBreakerCell` — Closed / Open / HalfOpen

A reactive state machine driven by the success/failure rate over a sliding
window. Gates `CommandTransport::send`: a **closed** circuit is passthrough, an
**open** one fast-fails.

- **Closed** — calls pass; record outcomes into a sliding window of the last `N`
  calls. When failures in the window reach `failure_threshold`, trip to **Open**
  (`open_until = now + reset_timeout`).
- **Open** — fast-fail (`allow(now) = false`) until `now ≥ open_until`, then
  transition to **HalfOpen** on the next `allow`.
- **HalfOpen** — allow a single probe: a success closes the breaker (clears the
  window), a failure re-opens it.

`allow(now)` returns whether a call is permitted (and performs the
Open→HalfOpen transition at the deadline); `record(success, now)` feeds an
outcome. The `state` reader invalidates on a state change.

## `RetryPolicyCell` — exponential backoff

An exponential-backoff source: `delay(attempt) = min(cap, base · 2^attempt)`,
saturating to `cap` (a shift overflow clamps to `cap`). `next()` yields the delay
for the current attempt and advances; `reset()` returns to attempt 0. Optional
**decorrelated jitter** takes an injectable RNG (deterministic under a seed);
conformance pins the un-jittered exponential schedule.

## `BulkheadCell` — bounded isolation pool

A bounded permit pool isolating a downstream (per-tenant / per-shard): `capacity`
permits, `acquire()` succeeds while `in_use < capacity` (returns `false`
otherwise), `release()` frees one. `permits_in_use` is the reactive reader.
Invariant: `0 ≤ in_use ≤ capacity`.

## `TimeoutCell` — deadline-bounded call

Wraps a call with a deadline: `arm(now, timeout)` starts the clock
(`deadline = now + timeout`); `tick(now)` fast-fails when `now ≥ deadline`
(returns the timeout edge, once). `is_timed_out` is the reactive reader. Composes
the `#lztime` deadline discipline.

## Conformance

| Fixture | Model | Checks |
|---------|-------|--------|
| `circuit_breaker.json` | `CircuitBreakerCell` | trip Closed→Open at threshold; Open fast-fails; Open→HalfOpen at deadline; HalfOpen success→Closed |
| `retry.json` | `RetryPolicyCell` | exponential delays saturating at `cap`; delay reader invalidation |
| `bulkhead.json` | `BulkheadCell` | acquire to capacity then reject; release; permits_in_use invalidation; boundedness |
| `timeout.json` | `TimeoutCell` | arm; tick fast-fails at the deadline (edge once); idempotent thereafter |

## Formal model

`lazily-formal/LazilyFormal/Resilience.lean`: circuit-breaker transition safety
(`open_fast_fails`, `halfopen_success_closes`, `halfopen_failure_reopens`),
retry backoff bounded by `cap` (`retry_bounded`) and monotone up to the cap
(`retry_monotone`), bulkhead boundedness (`bulkhead_bounded`), and timeout
monotonicity (`timeout_monotone`).
