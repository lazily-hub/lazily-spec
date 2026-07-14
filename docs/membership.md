# Membership + failure detection (`#lzmemb`)

Phase 2 of the realtime + distributed primitives plan. The load-bearing
primitive for any peer topology: a **reactive view of the live peer set**. Every
coordination primitive downstream (`#lzcoord` lease/leader/lock, `#lzpresence`)
reads it. It lives *below* the CRDT plane — it tells the CRDT plane which peers
are valid sync targets.

## Primitives

- **`MembershipCell`** — reactive membership keyed by peer id. Backed by
  SWIM-style heartbeats + a **Phi-accrual** failure detector, so join / leave /
  suspect / dead are reactive signals. Per-peer state:
  `Alive | Suspect | Dead | Left`.
- **`PeerSet`** — derived `Reactive<Set<PeerId>>` over the membership cell: only
  the `Alive` peers. Invalidates only when the alive set changes (PartialEq
  guard).
- **`PeerChangeEvent`** — the diff stream over the membership cell:
  `Joined(peer)`, `Left(peer)`, `StateChanged { peer, from, to }`.

The peer id is generic (`P: Ord + Clone`); the distributed plane plugs in
`PeerId` (`distributed.rs`). SWIM/gossip packets ride the existing
`RelayTransport` / `Transport` — **no new transport**.

## Compute-core split (backend portability)

The pure, C++-eligible core is the **Phi-accrual math + the SWIM state machine**
over plain state; the reactive signal emission (the alive-set `Cell` and the
event stream) is the thin glue. Payload class: heartbeat / membership frames are
**`BytesPayload`**.

## Phi-accrual failure detector

Each peer has a detector over a sliding window (`max_samples`) of heartbeat
inter-arrival times. `phi(now)` is the negative log-likelihood that a heartbeat
has not yet been seen — a peer is *suspected* when `phi > phi_threshold`.

To make phi **bit-portable across bindings**, every binding computes phi with the
identical Akka-style logistic approximation of the normal CDF:

```
mean = average(window);  std = max(stddev(window), min_std)
y = (elapsed - mean) / std
e = exp(-y * (1.5976 + 0.070566 * y * y))
phi = if elapsed > mean then -log10(e / (1 + e))
                        else -log10(1 - 1 / (1 + e))
```

`phi = 0` when the window is empty (no estimate yet) or `elapsed = 0`.

## SWIM state machine

Per-peer transitions driven by heartbeats and the logical clock:

- `join(peer, now)` — insert `Alive` with a fresh detector; emit `Joined`.
- `heartbeat(peer, now)` — record the arrival; a `Suspect`/`Dead` peer returns
  to `Alive` (SWIM refutation); emit `StateChanged` if the state changed.
  A heartbeat for an unknown peer is a join.
- `tick(now)` — recompute liveness: an `Alive` peer with `phi(now) >
  phi_threshold` becomes `Suspect` (records `suspect_since`); a `Suspect` peer
  with `now - suspect_since ≥ suspect_timeout` becomes `Dead`.
- `leave(peer, now)` — mark `Left` (graceful departure); emit `Left`.

`PeerSet` = the peers whose state is `Alive`. `Suspect`/`Dead`/`Left` peers are
**not** valid sync targets.

## Conformance

`conformance/membership/membership_lifecycle.json` drives a peer through its full
lifecycle. Ops are `{ "type": "join"|"heartbeat"|"leave"|"tick", "peer": id,
"now": N }`; each step asserts the acted peer's `state`, the `alive_set`, and
whether the `PeerSet` reader `invalidates`. To stay bit-portable the fixture
probes phi only far from the threshold (a regular-heartbeat cadence keeps a peer
`Alive`; a large clock gap makes phi astronomically large → `Suspect`), so
floating-point differences never change a transition.

| Fixture | Checks |
|---------|--------|
| `membership_lifecycle.json` | join→Alive & set grows; regular heartbeats keep Alive with no set churn; clock gap → Suspect (leaves the set); suspect_timeout → Dead (no further set change); join/leave a second peer; PeerSet invalidates only on set change |

## Formal model

`lazily-formal/LazilyFormal/Membership.lean` models the SWIM state machine as a
transition function and proves the safety invariants: `Suspect` is only entered
from `Alive` (`suspect_from_alive`), `Dead` only from `Suspect`
(`dead_from_suspect`), a heartbeat always yields `Alive`
(`heartbeat_revives`), `Left` is reached only by `leave` (`left_only_by_leave`),
and a peer is in the alive set iff its state is `Alive` (`alive_set_iff`).
Phi-accrual arithmetic is abstracted as the `suspect` signal predicate.
