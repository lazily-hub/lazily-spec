# Distributed coordination (`#lzcoord`)

Phase 3 of the realtime + distributed primitives plan. Reads `MembershipCell`
(`#lzmemb`) and the temporal sources (`#lztime`). These are the leader / lease /
lock / semaphore / barrier primitives every distributed control plane wants.
Each is a pure compute **core** (a state machine over plain integers / peer ids —
`BytesPayload`, C++-eligible) split from a reactive **cell** projecting the
salient reader (holder, role, is_locked, permits, is_open) onto a `Cell`.

Time is the logical clock; `expiry` is a tick value driven by the runtime.

## `LeaseCell` — single-writer authority

A reactive lease grant: `holder: Option<PeerId>`, `expiry: u64`, and a
**monotone fencing token** `fence: u64`. Renewed by a heartbeat, expired by the
clock.

- `acquire(peer, now, ttl)` — grant if free/expired (**increments** `fence`,
  sets `expiry = now + ttl`) returning the new fence; a renew by the current
  holder keeps the **same** fence; held by another → `None`.
- `renew(peer, now, ttl)` — extend `expiry` if `peer` is the live holder.
- `release(peer)` — drop the grant if `peer` holds it.
- `tick(now)` — expire the grant when `now ≥ expiry`.

**Fencing-token monotonicity**: `fence` never decreases and strictly increases on
every *new* grant, so a stale holder's token is always less than the current one
— the check that fences off stale-leader writes (wire into `CommandPolicy` /
`Receipt*`).

## `LeaderCell` — leader / follower / candidate

Wraps a `LeaseCell` + the local node id `me`. Role is derived from the holder:
`Leader` (holder = me), `Follower` (holder = another peer), `Candidate` (no
holder). `current_leader()` is the holder; it invalidates on re-election.
`campaign(now, ttl)` tries to acquire the lease for `me`.

## `LockCell` — distributed mutex + fencing

A mutex over a `LeaseCell`: `acquire(peer, now, ttl)` returns a fencing token,
`is_locked` is a reactive reader (blocks the same way `RelayCell::is_full`
does), `validate(fence)` rejects a stale token (`fence` ≠ current). Release on
`release(peer)` or lease expiry (membership loss).

## `SemaphoreCell` — bounded permit pool

`capacity` permits; `acquire()` succeeds while `permits_available > 0` (returns
`false` at capacity), `release()` returns a permit (saturating at `capacity`).
`permits_available` is the reactive reader. Invariant: `0 ≤ acquired ≤ capacity`.

## `BarrierCell` / `QuorumCell` — wait-for-N gate

A reactive gate that opens once enough distinct peers arrive:

- `BarrierCell(required)` — `arrive(peer)`; `is_open` once `|arrived| ≥
  required`.
- `QuorumCell(total)` — a barrier with `required = total / 2 + 1` (strict
  majority). `vote(peer)`; `has_quorum` (`is_open`) opens at `⌊total/2⌋ + 1`.

Duplicate arrivals/votes are idempotent (a set). `is_open` invalidates only when
it flips.

## Conformance

`conformance/coordination/` replays each primitive:

| Fixture | Model | Checks |
|---------|-------|--------|
| `lease.json` | `LeaseCell` | grant/renew/expire; other-peer rejected; fence monotone (renew keeps, new grant increments); holder invalidation |
| `leader.json` | `LeaderCell` | campaign → Leader; expiry → Candidate; another peer wins → Follower; current_leader invalidation |
| `lock.json` | `LockCell` | acquire/held-rejected; fencing `validate` rejects a stale token after re-grant; is_locked invalidation |
| `semaphore.json` | `SemaphoreCell` | acquire to capacity then reject; release; permits_available invalidation; boundedness |
| `quorum.json` | `QuorumCell` | opens at ⌊total/2⌋+1 distinct votes; duplicate votes idempotent; is_open flips once |

## Formal model

`lazily-formal/LazilyFormal/Coordination.lean`: lease fencing-token monotonicity
(`acquire_fence_monotone`, `renew_keeps_fence`), semaphore boundedness
(`semaphore_bounded`, `acquire_decrements`), and the quorum gate opening exactly
at strict majority (`quorum_opens_at_majority`).
