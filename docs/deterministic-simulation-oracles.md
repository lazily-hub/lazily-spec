# Deterministic simulation oracles (`#lzsimoracle`)

Deterministic execution makes a failure reproducible; it does not establish that
the execution was correct. A simulator therefore needs observations and oracles
whose authority is separate from the scheduling mechanism it is checking.

This contract complements [Replay-Equivalence Proof](replay-equivalence.md).
Replay equivalence asks whether a rebuilt graph reproduces one exact event log.
Simulation oracles ask whether every action in a generated or hand-authored
history preserved the subject's safety, model, differential, liveness, and
history obligations.

Status: **MAY** as a family feature. A binding that exposes deterministic
simulation and claims this feature **MUST** satisfy every requirement below.

## One checked boundary per executed action

The oracle runner **MUST** own the step boundary. After each executed action, and
before the next action runs, it **MUST**:

1. apply the exact action result to any reference model;
2. obtain a side-effect-free observation map from the simulated subject;
3. compare the subject with every reference and differential observation;
4. evaluate every safety and bounded-liveness assertion;
5. append the action to the operation history and evaluate every history
   assertion; and
6. retain canonical observation bytes for the step fingerprint.

The snapshot **MUST** name the executed step, logical time, action, and acceptance
outcome. Values exposed to assertions **MUST** be frozen or copied so an
assertion cannot mutate the simulated subject. A runner **MUST NOT** claim
stepwise checking when callers execute the world around this boundary; fingerprint
creation must reject a world whose executed-step count exceeds its checked-step
count.

Observation maps use the canonical equality classes from
[Replay-Equivalence Proof](replay-equivalence.md#3-the-observation-encoding-is-canonical-or-it-fails):
mapping and set iteration order are ignored, sequence order and type are
significant, members are framed, and unsupported values fail rather than falling
back to host rendering.

## Comparative authority must not be circular

Every reference model and differential subject **MUST** declare a stable source
identity and one of these provenance classes:

- `independent_model` — a separately authored executable specification;
- `production_reducer` — the production decision/reducer path, reused rather
  than reimplemented by the simulator;
- `real_adapter` — a selected real database, broker, network, or other external
  adapter used by a differential/conformance run; or
- `simulation_only` — another implementation that exists only inside the
  deterministic world.

A `simulation_only` witness **MAY** supplement other checks, but it **MUST NOT**
be the sole comparative oracle for the behavior it implements. Construction
**MUST** fail when every configured reference/differential witness is
`simulation_only`. This prevents two copies of the same simulator assumption
from certifying one another. Pure safety or history assertions remain useful
without a comparative witness, but they do not become a reference-model or
differential claim.

## Oracle classes

### Safety invariants

A safety assertion is a stable id plus a total check over one immutable step
snapshot. It runs after every action. Its first failure **MUST** stop execution
and remain the runner's stable failure; later calls must not overwrite the
earliest counterexample.

### Reference models

A reference model consumes the same ordered action results as the subject and
publishes its own observation map. The runner **MUST** compare every observation
key and canonical value after every action. A missing or additional key is a
failure, not an implicit default.

### Differential subjects

A differential subject independently observes an alternate implementation of
the same behavior. It receives or is driven by the same materialized history,
and its complete observation map is compared after every action. Real-adapter
differentials belong outside `SimWorld`; nondeterministic transport policy must
not leak back into the deterministic scheduler.

### Bounded liveness

A bounded-liveness assertion has a stable id, a trigger, a satisfaction
predicate, and a nonnegative bound measured in subsequently executed actions.
The trigger opens an obligation, satisfaction closes it, and reaching the bound
while it remains open fails. If a run becomes idle with an open obligation, the
run **MUST** fail even when the numeric bound has not yet been consumed: no
future simulated action can discharge it.

### History checks and linearizability

The runner **MUST** expose an immutable ordered history. Each operation names its
action and kind, invocation and return logical times, outcome, and any causal or
checkpoint identity. Explicit overlapping operations from modeled clients or
ports **MAY** be added alongside single-step operations.

History assertions run after every action and may check uniqueness, causality,
monotonicity, receipt pairing, or domain-specific sequential rules.
Linearizability is narrower: a checker **MUST NOT** run unless the tested surface
explicitly claims a named, versioned sequential specification and provides
operation intervals suitable for that checker. A generic simulator, eventual
projection, or surface that makes no linearizability claim must not acquire one
merely because a history checker exists.

## Exact-trace fingerprints

An oracle fingerprint **MUST** bind all of the following:

- the digest of the exact simulation trace, including logical timing and queue
  order;
- the digest of the exact replay log projected from that trace;
- the complete replay-harness fingerprint and its identity digest; and
- canonical observation bytes at every checked step, including step number and
  logical time.

Verification **MUST** validate the fingerprint's own identity and then the trace
and replay-log identities before comparing observation values. It **MUST** run
the `ReplayHarness` against that exact log rather than accepting an equal final
state. Timing, queue-order, log, replay-checkpoint, or observation mutations are
distinct failures; none may be normalized into a passing comparison.

## Mutation gate

A binding claiming this feature **MUST** carry seeded mutations that demonstrate
the oracle is discriminating. At minimum, the suite must turn red for:

- a reducer defect caught by a safety invariant;
- a subject defect caught by an independent reference model;
- an alternate-implementation defect caught by a differential comparison;
- a missing completion caught both at its action bound and at idle;
- trace timing or ordering drift caught by the exact-trace fingerprint;
- replay-log, replay-fingerprint, and step-observation identity drift;
- a malformed or duplicate operation caught by a history assertion; and
- an illegal sequential history caught only after an explicit linearizability
  capability claim.

Each mutation must name the assertion it is expected to trip. A test that only
proves the healthy execution passes is not evidence that the oracle observes the
claimed defect class.

## Scope

These oracles complement unit, contract, replay, and real-infrastructure tests.
They do not authorize real clocks, threads, sockets, databases, or brokers inside
the deterministic world; those remain behind narrow ports and are checked by
separate conformance runs. Determinism is the mechanism that preserves a
counterexample. Independent authority is what makes that counterexample mean
the implementation is wrong.
