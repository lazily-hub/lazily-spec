# Conformance Fixtures

The `conformance/` directory contains canonical test fixtures that all IPC-capable bindings must
validate against. Each binding's CI should deserialize the `wire` field, run the assertions, and
re-serialize to confirm round-trip fidelity.

## Fixture schema

```json
{
  "description": "Human-readable summary",
  "protocol_version": 1,
  "kind": "Snapshot" | "Delta" | "Receipt",
  "assertions": {
    "prose": ["…keys below that are PARAGRAPHS, not comparable values…"],
    "…language-agnostic field checks…": "…"
  },
  "wire": { "…canonical protocol JSON…" }
}
```

`assertions.prose` declares which sibling keys state an obligation in English rather than
carrying a comparable value. A runner discharges those by naming the executable keys that
prove them — see [Prose assertion keys](#prose-assertion-keys-lzprosekeyconvention).

## Fixture discriminability (`#lzfixturediscrim`)

Opening a fixture, consuming every key, and comparing every executable value still does not
prove that the fixture data can distinguish the behavior it names. For example, every ordering
predicate returns `true` for an empty or singleton roster. A runner can faithfully assert
`roster_sorted_ascending: true` while a library that reverses its roster order remains green.

`scripts/check-fixture-discriminability.mjs` audits this fourth rung:

1. Non-boolean routes are exact-value oracles. A changed observation differs from the canonical
   value.
2. Boolean routes carrying both `true` and `false` somewhere at the same normalized fixture
   pointer have an in-corpus control that rejects either constant mutant.
3. Every remaining single-valued boolean route must appear in
   `audits/fixture-discriminability.json`. A claim is either `mutation-killed`, with the binding,
   library-source mutation, command, observed failure, and a fixture witness, or `untested` with
   a reason. Missing and stale ledger entries fail CI.

`untested` is deliberately not a weaker spelling of pass. It records that the corpus claim has
no registered library mutation proof, so coverage reports and follow-up audits cannot silently
treat an asserted predicate as behavior-discriminating.

The signaling transcript is the first recorded proof. Three peers join; the third welcome
must carry the two-element roster `[1, 2]`. Reversing `SignalingRoom.roster` in `lazily-js`
now fails the canonical replay with actual `[2, 1]`, while removing self-filtering and stamping `from` with
the target rather than the registered sender fail the other two signaling assertions.

To initialize ledger entries after intentionally adding claims:

```sh
node scripts/check-fixture-discriminability.mjs --write-initial-ledger
```

The initializer preserves existing evidence and creates new entries as explicit `untested`
claims. Replace that status only after running the cited library-source mutant and confirming
that a canonical fixture—not merely an independent unit test—reddens.

## Custom assertion callback consumption (`#lzassertwithseam`)

Every binding exposes a custom assertion helper for relations that plain equality cannot
express: tolerances, containment, decoding, and derived projections. The helper passes the
fixture value to a callback. Calling the callback is not itself proof that the callback used
that value: an ignored parameter previously marked the key asserted while comparing nothing.

A binding MUST therefore:

1. require the callback to expose and syntactically read its fixture-value parameter;
2. record the key as asserted only after the callback completes successfully; and
3. keep extraction explicit by using a projection helper (for example Python's
   `assert_key_into`) when the caller performs the comparison after the helper returns.

`scripts/check-assert-with-consumption.py` enforces rule 1 for every maintained binding.
`scripts/check-assertion-ordering.py` runs it as part of the existing binding conformance
gate, so comments and string literals do not count as reads and unsupported callback forms
fail closed. Its self-test includes an accepted and an ignored callback for every supported
language. The runtime helper ordering enforces rule 2: a callback that throws, rejects, or
returns a failing verdict cannot leave the assertion ledger green.

## Current fixtures

| Fixture | Kind | Description |
|---------|------|-------------|
| `snapshot_minimal.json` | Snapshot | One payload node, no edges |
| `snapshot_multi_node.json` | Snapshot | Multiple nodes and edges |
| `snapshot_shared_blob.json` | Snapshot | SharedBlob node state |
| `delta_sequential.json` | Delta | All 7 DeltaOp variants, sequential |
| `delta_non_sequential.json` | Delta | Non-sequential delta with gap |
| `delta_shared_blob.json` | Delta | CellSet/SlotValue with SharedBlob |
| `receipts/causal_receipts.json` | Receipt | Causal receipt projection with non-terminal and terminal outcomes |

## Publishing a corpus change (`#lzspecpushbeforebindings`)

**Push the corpus change to `lazily-spec` FIRST, then verify and push the bindings.**
Never the other way round, however green the bindings look locally.

The asymmetry is the whole reason. Local verification resolves the corpus through the
**sibling working tree** (`../lazily-spec/conformance/...`), so it sees your change the
moment you save it. Every binding's CI instead **clones published `main`** — for example
`lazily-cs/.github/workflows/ci.yml` runs
`git clone --depth 1 https://github.com/lazily-hub/lazily-spec.git ../lazily-spec`.
So a corpus change that is green in nine local checkouts is invisible to all nine CI runs
until it is pushed, and any binding that pins a scenario or fixture count fails on the
mismatch.

That is not hypothetical. Landing the SeqCrdt fork-clock scenarios
(`#lzspecforkclockfixture`) in the wrong order turned `lazily-cs` red with
`Expected: 8 / Actual: 6` — its runner census correctly counted the eight scenarios in the
working tree while CI replayed the published six — and forced `lazily-cpp` to pin
`MIN_SCENARIOS` to the published `144` rather than the local `146`, then raise it again in
a second commit once the push landed.

The order that works:

1. Fix the bindings' **behaviour** first if the new fixture would otherwise redden them,
   but do not push a binding whose *census* (scenario counts, coverage floors) encodes the
   new corpus.
2. Commit and push the `lazily-spec` change, including any vendored mirrors re-synced by
   `scripts/sync-conformance-fixtures.mjs --sync`.
3. Only then push binding changes that assume the new corpus, and re-run any CI that
   failed against the old one.

A floor or count in a binding must always describe **what CI's clone guarantees**, never
what your working tree happens to hold. `make check` here warns when the local corpus is
ahead of `origin/main`, which is the moment this rule applies — see
`scripts/check-corpus-published.mjs`.

## Adding a new binding

Copy the fixture-loading pattern from `lazily-rs/tests/conformance.rs`. Each test should:

1. Load the fixture.
2. Parse the `wire` field into the binding's native `IpcMessage` type.
3. Assert the `assertions` fields.
4. Re-serialize and compare for byte-for-byte round-trip fidelity, subject to the
   equivalence exemptions below.

### Round-trip equivalence exemptions

Byte-for-byte comparison is the default, but it is **not** the contract for a field whose
schema declares two encodings equivalent. Where the schema says a field may be omitted *or*
sent in some canonical empty form, a binding MUST NOT be required to reproduce the sender's
choice: both encodings decode to the same value, so a binding is free to emit either one.

For such fields the round-trip comparison is **semantic**: normalize the fixture's `wire` and
the binding's re-serialized output to the same canonical form (fill in the declared default for
an absent field) before comparing. All other fields remain byte-for-byte.

Exempt fields:

| Field | Equivalent encodings | Declared by |
|-------|----------------------|-------------|
| `CrdtSync.frontier` | omitted ≡ `[]` — "unchanged since the last accepted frame" (`#lzspecfrontiersuppress`) | [`schemas/distributed.json`](../schemas/distributed.json) (`required` is `["ops"]` only) |

A binding MUST accept an omitted `frontier` on decode and treat it as empty. Rejecting the
absent form is a conformance failure; re-emitting it as `[]` is not.

## Prose assertion keys (`#lzprosekeyconvention`)

An `assertions` block mixes two kinds of key. Most carry a value a runner can compare
against observed behaviour — a list, a count, a vocabulary. A few carry an English
paragraph that states an obligation and nothing comparable: `clause`, `anti_vacuity`,
`null_form`, `theorem`, `note`. This section says what a runner MUST do with the second
kind, because nothing did, and the nine bindings each decided.

### The failure this closes

Replaying `blob_backend_discriminator.json` v2 — which added four new paragraphs
(`backend_form_vocabulary`, `null_form`, `non_string_form`, `epoch_disambiguation`) —
produced **four different treatments of the same four keys**:

| Binding | Treatment |
|---|---|
| lazily-js | excused all four, its own `assert-key.js` warning against comparing an English paragraph to a literal |
| lazily-py, lazily-dart, lazily-go, lazily-kt, lazily-cs, lazily-zig | excused them with individually-worded reasons naming the assertion that discharges each — falsifiable in principle, checked by nothing |
| lazily-rs | marked them `Expect::prose`, a third tracker state exempt from every check, which requires a reason and then discards it |
| lazily-cpp | **asserted** all four against tallies computed from the run |

Every one is defensible alone. That is the point: this is the same shape as the 5-2 split
the blob-backend clause itself came from — an undocumented default and a deliberate choice
are indistinguishable from the outside, and so are four deliberate ones.

### Definition

A **prose key** is a key of a fixture's top-level `assertions` block whose value is a
natural-language paragraph: it states an obligation and carries no value a runner can
compare against observed behaviour.

The **corpus** declares which keys those are, in `assertions.prose` — an array of sibling
key names. A binding MUST NOT decide for itself. The declaration is itself a key of the
block, so the existing consumption guards see it: a runner that ignores it fails with an
unconsumed key, which is what makes the rollout self-enforcing.

Prose nested inside a data key is **not** a prose key. `assertions.outcomes` maps a
vocabulary to English glosses; the assertion is the key set, and the parent key's own
assertion discharges it.

### The rule

A prose key is **discharged**, never asserted and never excused. To discharge it a runner
names the executable assertion keys that carry its obligation, and its assertion-key
tracker verifies the naming. A binding's tracker MUST fail the run when:

1. a key listed in `assertions.prose` is **asserted** — comparing a paragraph, or a tally
   derived from one, to an English string pins wording, not behaviour. A copy-edit reddens
   the run and a library regression does not. `reject_obligation` says exactly this about
   error message formats; it applies no less to the paragraph stating it;
2. a key listed in `assertions.prose` is **excused with free text** — an unfalsifiable
   reason ("prose", "explains why the wire is text/hex") is indistinguishable from the
   undocumented default this clause exists to remove;
3. a key **not** listed in `assertions.prose` is discharged;
4. the set of discharged keys differs from `assertions.prose` — this is the comparison that
   consumes `prose` itself, and it is what makes a forgotten key fail rather than vanish;
5. a discharge names **no** keys;
6. a discharge names a key that the same fixture's run **did not assert**;
7. a discharge names a key that is itself prose, **or names `prose`**. The second half is
   not redundant: `prose` never lists itself, so without it rule 7 misses
   `dischargedBy: ["prose"]` — and rule 4's own comparison marks `prose` asserted, so
   rule 6 would wave it through. A paragraph discharged by the declaration that it is a
   paragraph proves nothing. Seed the prose-name set with `prose` itself.

8. an opened fixture whose block declares `prose` never reaches verification. Rules 1-7 are
   all satisfied over an empty population, so a fixture that is opened and then never
   replayed passes every one of them while proving nothing — the vacuity the corpus's own
   `anti_vacuity` keys exist to name, reappearing in the guard meant to enforce them.
   Derive the required verifications from the corpus, never from a hand-kept count.

**Evaluate rule 7 before rule 6.** A paragraph can never be asserted — rule 1 forbids it — so
a discharge naming another paragraph *always* also violates rule 6. Check 6 first and rule 7
becomes dead code that never reports, and the run fails with "names a key this run never
asserted" when the real defect is "names a paragraph". The numbering is not the evaluation
order; this one pair is.

Rule 6 means ASSERTED, not merely satisfied: an excused key does not discharge anything,
because an excuse is precisely the absence of a comparison. A discharge naming a key the
fixture does not carry at all is a distinct failure — the discharge has rotted, exactly as a
stale excuse has. One executable key may discharge several paragraphs; `decoded_backend`
carries five in `blob_backend_discriminator.json`, and that is expected rather than a
collision.

Rule 6 is the whole convention: the excuse becomes falsifiable, because the tracker can
check it. "`epoch_disambiguation` is discharged by `frame_epoch` and `blob_epoch`" is a
claim about the run; "`epoch_disambiguation` is prose" is not.

A discharge may name a key that carries the obligation only by PROXY. `theorem` names a
Lean theorem in another repository; the run can only prove its consequence. Naming a proxy
is conforming. Naming a key that has nothing to do with the obligation is not, and no
tracker can tell the two apart — that judgement stays with review, which is why the
discharge is written at the call site where review sees it. `wire_encoding` is no longer a
proxy: every declaring scenario carries `expect.wire_input_fnv1a64`, and the runner hashes
the exact UTF-8 JSON bytes or decoded MessagePack bytes it passes to the library decoder.

### Scope of "the same fixture's run"

The discharge ledger is **fixture-scoped**, not block-scoped. An obligation stated in
`assertions` is routinely carried by a per-scenario `expect` key: `epoch_disambiguation` is
discharged by `expect.frame_epoch` and `expect.blob_epoch`, which are asserted long after
the `assertions` block itself is finished. A named key is therefore matched by **key name,
in any block of that fixture**, and verification happens when the fixture's replay is
finished. A runner that never verifies MUST fail — an unverified discharge claim is
reported by the ledger's own teardown, exactly as an unconsumed key is.

A block declaring `prose` MUST also carry at least one non-prose key. A block that is
entirely prose has nothing that could discharge it.

**A block is identified by its path in the fixture**, not by a human-written label. Rules 3
and 4 are block-local, so two blocks whose tracker labels happen to collide would merge
silently and each would satisfy the other's declaration. Key them on `assertions`,
`scenarios[3].expect`, `steps[7].expect` — something the fixture determines.

**Which rules are block-local and which are fixture-wide.** The declaration is block-local:
each block owns its own `prose` array, and rules 3 and 4 compare a block's discharged set
against that block's array. Only the NAME MATCHING of rules 6 and 7 is fixture-wide, because
that is the half that has to reach a per-scenario `expect` key.

**A "run" is one test, not one process.** Where a fixture is replayed by several tests, the
ledger is scoped to each and cleared at its verification. Unioning asserted keys across
tests would let a discharge in one test be satisfied by an assertion in another, which is
the same accident-of-collocation the fixture-scoped ledger exists to bound.

**Arming the verification net is a LIFO hazard.** Every cleanup mechanism the nine use —
`Drop`, `t.Cleanup`, `addTearDown`, `IDisposable`, a destructor — runs in reverse
registration order. A net armed by the first `prose_key` call therefore fires BEFORE a
verification the runner registered earlier in its body, and reports a false failure. Arm the
net from the same seam that already owns the block's consumption check, which is
structurally guaranteed to run last.

### Reserved annotation names

`note`, `description` and `reason` inside a per-step or per-scenario block are
**annotations**, exempt by name in every binding.

**A corpus declaration overrides the by-name exemption, and a tracker MUST apply it first.**
Both `frame_roundtrip_json.json` and `frame_roundtrip_msgpack.json` declare `note` prose. A
tracker that subtracts its reserved-name set before consulting `assertions.prose` makes that
declaration invisible to its consumption guards: the key is exempt from the unread guard and
exempt from the unasserted guard. Three of the nine hit this independently while
implementing the clause. Evaluate `prose` on the raw block, before any name-based exemption;
the exemption applies only to keys the block did not declare.

How bad the inversion is depends on where rule 4 reads from, and this is worth stating
precisely because one binding measured it rather than assuming. Where rule 4's comparison
reads the RAW block — the declared set kept separately, never subtracted from — the
inversion degrades to a worse error message: the forgotten `note` is still caught, just by
the set comparison rather than by the guard that would have named it. Where rule 4 reads
through the exempted view, nothing is left: both fixtures skip the convention entirely and
the binding still reports conforming. Keep the declared set independent of the exemption and
the inversion cannot be fatal — but evaluate in the stated order anyway, because the guard
that names the key is the one a reader acts on.

Inside a block that declares `prose`, the name exemption is off entirely: the corpus wins,
so a `note` sitting in a declaring block but absent from its array needs an assertion or an
excuse like any other key. Everywhere else the exemption stands as-is.

### Naming a discharge that discharges nothing

The tracker checks that a named key was asserted. It cannot check that the assertion
*proves* the paragraph, and three bindings found the gap the same way: a key that compares
the fixture to itself is asserted, satisfies rule 6, and discharges nothing. Two shapes
recur.

`scenario_count` asserted against `len(fixture["scenarios"])`, and `codecs` / `key_forms`
compared to hand-written literals, are green over a runner that decodes nothing — which is
the exact vacuity `anti_vacuity` exists to name. Compare them against what the run really
replayed before naming them.

Worse, `nodekey_null_leniency.json`'s `wire_encoding` obligation — that the ABSENT and
explicit-`null` wire forms stay distinguishable into the runner — was dischargeable by
nothing at all in at least one binding: `key ?? null` collapses the two the instant the
value is decoded, and every key in that fixture's `expect` blocks is identical for the
`omitted` and `null` families. The four `null` scenarios were the four `omitted` ones
wearing a different id. The fix is a control that reads the raw wire slot BEFORE the decoder
runs, which is what the sibling blob-backend runner already does for `backend`. Adding the
missing control is conforming; naming a key that merely happens to be asserted is not. That exemption is only safe while they
annotate; an annotation MUST NOT state an obligation, because a reserved name is a place no
runner can be made to discharge anything. `scripts/check-prose-keys.mjs` enforces this and
carries a both-directions allowlist of the instances that already do — five reactive-graph
step notes, each a real normative rule (`teardown is idempotent`, `a stale cell handle whose
id has been recycled MUST be a no-op`) that no binding checks today. New instances redden.

### Tracker API

The nine trackers differ in mechanism — a `Drop` guard, a global recorder plus a manifest
script, a `t.Cleanup`, an `IDisposable` — but the SPELLING is fixed here, because a
convention whose name drifts per binding is how four treatments of one rule went unnoticed
in the first place.

| Binding | Discharge | Fixture-end verification |
|---|---|---|
| lazily-rs | `exp.prose_key("clause", &["backends", "scenario_count"])` | `expect::verify_prose(fixture)`, armed by a `ProseLedger` guard |
| lazily-py | `prose_key(block, "clause", discharged_by=["backends"])` | `verify_prose(fixture)` |
| lazily-js | `proseKey(block, "clause", ["backends"])` | `verifyProse(fixture)` |
| lazily-go | `proseKey(t, block, "clause", "backends")` | `verifyProse(t, fixture)`, registered with `t.Cleanup` |
| lazily-dart | `proseKey(block, 'clause', dischargedBy: ['backends'])` | `verifyProse(fixture)`, registered with `addTearDown` |
| lazily-kt | `proseKey("clause", listOf("backends"))` | `verifyProse(fixture)` |
| lazily-cs | `ProseKey("clause", "backends")` | `VerifyProse(fixture)` |
| lazily-cpp | `block.prose_key("clause", {"backends"})` | `verify_prose(fixture)` |
| lazily-zig | `proseKey("clause", &.{"backends"})` | `verifyProse(fixture)` |

`prose_key` replaces whatever the binding did before — lazily-rs's third `prose()` state
goes away rather than gaining a sibling, and the free-text `excuse_key` reasons written for
these keys are deleted, not kept alongside. Two paths to satisfy one key is the ambiguity
this clause removes.

### What this does not check, and what is still open

**A discharge is checked for truth, not for sufficiency.** Rule 6 proves the named key was
asserted. Nothing proves it is *relevant*: discharging all nine of
`blob_backend_discriminator.json`'s paragraphs with `scenario_count` alone would satisfy
every rule. The excuse is now falsifiable, which it was not before, but it is not yet
load-bearing — that judgement stays with review, which is why the discharge is written at
the call site rather than in a table. Do not read a green run as "every paragraph is
proven"; read it as "no paragraph is discharged by a claim the run contradicts".

**`generator` is provenance metadata, not an assertion.** A generated fixture that records
its source script places the path in the top-level `generator` field. It MUST NOT place that
field under `assertions`: a replay cannot observe which script emitted its input, so an
assertion tracker would have nothing executable to compare. Binding runners do not consume
top-level provenance metadata.

The former `wire_encoding` gap is executable (`#lzwireencodingrunner`).
`check-prose-keys.mjs` requires every `wire_json` to be raw parseable text, every
`wire_msgpack_hex` to be even-length lowercase hex, both codecs to be represented, and
every scenario's `expect.wire_input_fnv1a64` to match those exact bytes. Each binding then
computes the same digest over the buffer it passes to its library decoder and asserts that
key before decoding. A re-serialized value therefore changes the decoder-input witness
instead of silently satisfying a proxy discharge.

### What is checked where

| Half | Where | What |
|---|---|---|
| Corpus | `scripts/check-prose-keys.mjs` (`make prose-keys-check`) | every paragraph declared, no stale or comparable entries, `prose` not self-listing, a declaring block carrying at least one non-prose key, no obligation hiding in a reserved annotation name |
| Binding | the binding's own assertion-key tracker, at runtime | rules 1-7 above |
| Binding | the binding's **coverage / ledger guard**, beside the fixture-open and scenario-replay rungs | rule 8 |

Rule 8's row is separate on purpose. It cannot live in the test host: a test that never runs
reports nothing, so the very run rule 8 exists to catch is the run that would have to report
itself. It belongs where the other "did the suite actually do this?" rungs already live — the
guard that reads the runtime manifest after the suite finishes.

The split is not arbitrary. Only the run knows which keys it asserted, so rule 6 cannot be
checked from this repo; and only the corpus can settle which keys are prose, so leaving that
to nine trackers is what produced four answers.

## Object-valued assertion keys (`#lzsubblockkeyset`)

An assertion key whose value is a JSON **object** carries two obligations, not one: the
value of each sub-field, and the sub-field **key set**. Bindings were discharging the first
and not the second, which makes the object the null form one level down — a field added to
it upstream is compared by nothing, and the fixture reports clean over the very change it
exists to catch.

### The failure this closes

`arena_blob.json`'s `assertions.descriptor` carries five sub-fields. Every binding that
replayed it compared those five by name and stopped. Planting a sixth key inside the object
left lazily-zig's suite **green** while every scalar sibling in the same block reddened —
found only by the corpus perturbation pass, because no rung above it can see inside a key
it considers consumed. The consumption ledger saw `descriptor` read and asserted; the
read-but-not-asserted rung saw an assertion; the bind ledger saw a bound block. All three
were satisfied by a check that could not fail.

### The rule

A binding's assertion-key tracker MUST fail the run when an assertion key whose value is an
object is consumed without its key set being checked. The tracker owns this, not the call
site. Two ways to discharge it, and the tracker MUST recognise both:

1. **Descend.** The tracker hands the caller a CHILD tracker bound to the object. The child
   owns the same unconsumed-key teardown the parent has, so a sub-field nothing reads fails
   exactly as an unconsumed top-level key does. This is the form to prefer: the obligation
   moves down rather than being restated.
2. **Compare the key set.** The tracker compares the object's key set against the set the
   run actually produced, in **both** directions — a fixture token nothing replayed and a
   replayed token the fixture omits are each failures. This is the form for a key whose
   sub-fields are a vocabulary rather than data: `nodeid_exact_range.json`'s
   `assertions.outcomes` maps outcome tokens to English glosses, and the assertion is which
   tokens exist, not what the glosses say.

Anything else — a plain value comparison, a hand-written field-by-field check, a count of
sub-fields — leaves the run reporting nothing about a field the corpus grows later. **A
per-call-site field count is not conformance.** It relies on the next author remembering,
which is the property this rung exists to remove; it is at best a stopgap and MUST be
replaced by 1 or 2.

A key the corpus declares in `assertions.prose` is out of scope here: a paragraph is a
string, and prose nested inside a data key is not a prose key (see § Prose assertion keys).

### The rule is not scoped to top-level `assertions`

It applies to **every block a runner binds to its assertion-key tracker** — `expect`,
`expected`, per-step, per-scenario, per-frame — because the defect is identical wherever
an object value is compared field by field. This matters because it is the one thing about
this class that is consistently underestimated: a scan of top-level `assertions` blocks
finds exactly two object-valued keys in the whole corpus, and the guard, once landed,
found between 14 and 26 distinct key shapes per binding. Do not scope the audit from a
corpus scan; land the guard and let it name the sites.

The recurring shapes, for orientation rather than as a checklist: `invalidates`, `scopes`,
`receipts`, `reads`, `subscriptions`, `values`, `handle_stable`, `observe`, `states`,
`present`, `discovery`, `projection`, `frame`, `state_after`, `converged_nodes`, `text_on`,
`version_vector_on`, `order_on`, `get` / `get_on`, `final_state`, `after_publish`,
`authority`, `retry`, `dependents_of`, `readable`, `read`. The ingress fixtures nest four
levels deep (`invalidates.scopes.<key>.<reader kind>`), and every level is a key set.

### What is checked where

| Half | Where | What |
|---|---|---|
| Corpus | the fixture itself | which assertion keys have object values — the corpus decides, a binding never assumes |
| Binding | the binding's assertion-key tracker, at runtime | an object-valued key consumed by neither 1 nor 2 fails the run |

Neither half is provable from the other. The corpus cannot know whether a runner descended,
and a runner cannot be trusted to notice that a value it compared happened to be an object.

### Validating a tracker that claims to enforce this

The guard is only as good as its own falsifiability, and this whole rung exists because a
check that cannot fail reads identically to one that passes. Plant an extra key inside each
object-valued assertion value in a **scratch copy** of the corpus — never `lazily-spec` in
place, where a probe reddens every other binding concurrently — and confirm the suite goes
RED. A tracker that reports clean over a planted sub-field has not implemented this section,
whatever its code says.

## Assertion observation ordering (`#lzassertordering`)

An executable assertion has to remain reachable when the behavior it names is
wrong. Two ordering rules follow:

1. Fully evaluate and finish a fixture-owned assertion block, including its
   prose obligations, before applying runner-side coverage floors. A redundant
   floor may still guard the runner, but it must not preempt the fixture
   assertion that owns the falsifying corpus mutation.
2. Evaluate an assertion about a run only after performing that run, and compare
   the declared rule with an observed runtime outcome. Checking a label or
   literal before ingest, decode, replay, or dispatch is not an assertion of the
   behavior the label names.

The semantic priority is therefore fixture assertion first, runner floor second.
This matters for diagnostics as well as coverage: a mutated `scenario_count`
must fail as `scenario_count`, not disappear behind an earlier hard-coded count.

`scripts/check-assertion-ordering.py` is the cross-binding static guard. Every
binding invokes its own configured pass from `make check`; missing, duplicated,
or renamed anchors fail closed. The guard checks order and attachment, not the
sufficiency of the runtime comparison. Mutation probes remain required for the
runtime assertion itself.

For `distributed/anti_entropy_converge.json`, `resolution: max_stamp` is tied to
the runtime state selected after ingest. Its conflict witness delivers the
greatest-stamp operation before a lower-stamp tail, so arrival-order resolution
and max-stamp resolution produce different observations.

## Keyed cell collections conformance

The `conformance/collections/` directory contains canonical fixtures for the
[keyed cell collections](cell-model.md#keyed-cell-collections) layer, which is **required
of every binding** (see the [Binding Conformance Matrix](protocol.md#binding-conformance-matrix)).
These are **compute** fixtures, not wire fixtures: a binding loads the `initial` state,
replays each `step`'s `op`, and asserts the `expected` effects (resulting `order`,
`values`, `membership`, and which reader classes — `value` / `membership` / `order` —
invalidate). The reconciliation fixture is declarative: diff `prior` → `target` and
assert the emitted minimal op set.

| Fixture | Covers |
|---------|--------|
| `collections/cellmap_independence.json` | value / set-membership / order reactivity independence |
| `collections/cellmap_atomic_move.json` | atomic ordered move keeps handle, bumps order once |
| `collections/dependency_reactive_availability.json` | exact-key observation before publication, unrelated-key isolation, stable unavailable/available identity |
| `collections/keyed_reconciliation_lis.json` | LIS move-minimized reconciliation; stable entries not invalidated |
| `collections/semtree_incremental.json` | memoized semantic tree: ancestor-chain-only recompute, sibling isolation, memo guard |
| `collections/seqcrdt_convergence.json` | move-aware sequence CRDT: single-LWW move, concurrent-move/value-edit independence, tombstone convergence, commutativity |
| `collections/mergecell_algebra.json` | `Source<T, M>` merge algebra (`#relaycell`): KeepLatest/Sum/Max policies; per-op converged value + whether `⊕(old,op)==old` suppresses the cascade (idempotent/identity no-op = free dedup); `Cell ≡ Source<KeepLatest>` |
| `collections/textcrdt_convergence.json` | Fugue/RGA character CRDT: concurrent same-point inserts, sticky tombstone, commutative/idempotent merge, GC |
| `collections/textcrdt_delta_sync.json` | `TextCrdt` delta sync (`#lztextsync`): `version_vector` (insert + tombstone ids), `delta_since` / `apply_delta`; bidirectional exchange convergence, whole-snapshot fork identity preservation, idempotent apply |
| `collections/stableid_alignment.json` | manufactured text identity: anchors / content hashes / word-LCS similarity alignment |
| `collections/workqueue_competing_delivery.json` | competing-consumer exclusive FIFO claims, delivery ownership, ack/nack, identity-preserving redelivery |
| `collections/workqueue_lease_deadletter.json` | strict visibility-timeout boundary, at-least-once requeue, max-delivery poison routing to DLQ |

## ComputedMap materialization conformance

The `conformance/materialization/` directory pins the eager-vs-lazy
[materialization behavior](cell-model.md#materialization-a-caller-provided-recipe) (`#lzmatmode`) of a
[`ComputedMap`](cell-model.md#keyed-cell-collections) — eager is a pre-mint loop over the
keyset; lazy is `get_or_insert_with` mint-on-access — proved in
[lazily-formal](formal-model.md)'s `Materialization` module. These are **compute**
fixtures: a binding reads the `spec` (each key's canonical value, and — for the
mixed fixture — its cell/slot entry kind), builds the keyed map under *both*
strategies, replays the `reads` sequence against the lazy build, and asserts
observational transparency plus the memory / entry-kind laws. Because
materialization is *not observable on the value axis*, there is no wire schema —
only the compute effects below.

| Fixture | Covers |
|---------|--------|
| `materialization/observational_transparency.json` | identical `observe` values under eager vs. lazy; eager materializes all keys; lazy materializes only read keys; default mode eager (`observe_canonical`, `eager_materializes_all`, `lazy_defers_slots`, `default_mode_eager`) |
| `materialization/deferral_not_deallocation.json` | lazy present set grows monotonically and is unchanged by re-reads; final lazy set is a subset of the eager set; no churn from allocation (`materialize_present_monotone`, `lazy_present_subset_eager`, `materialize_preserves_observe`) |
| `materialization/entry_kind_orthogonal_to_mode.json` | entry kind ⟂ mode: cell (input) entries are present under either mode; slot (derived) entries are deferred under lazy until read (`cell_entries_materialized_in_every_mode`, `slot_entries_deferred_under_lazy`) |

## Reactive graph disposal conformance

The `conformance/reactive-graph/` directory pins
[disposal and teardown scopes](reactive-graph.md#semantics) (`#lzspecedgeindex`) — the
explicit-lifetime half of the graph contract, whose scope law is proved as
`disposeScope_eq_disposeAll` in [lazily-formal](formal-model.md)'s `Reactive` module.
These are **compute** fixtures: a binding builds the graph by replaying each `step`'s
`op` against a fresh `Context` and asserts that step's `expect`. Disposal is not
observable on the wire — it changes what a context holds and what a publish reaches,
never a serialized frame — so there is no wire schema, only the compute effects below.

Every assertion is on **observable** state: dependent/dependency-set *sizes*, whether a
node is readable, a read's value or error, and which effects ran on a publish. Nothing
here fixes a promotion threshold, a hash strategy, or an index layout — those are
explicitly implementation-free per the
[implementation note](reactive-graph.md#semantics), and a binding that dedups edges by
linear scan at every degree conforms exactly as well as one that promotes to a hash
index.

Op vocabulary (all ids are fixture-local labels, never a binding's internal id):

| Op | Meaning |
|---|---|
| `cell {id, value}` | Create a source cell |
| `computed {id, reads[], offset, scope?}` | Create a derived, guarded `Computed` whose value is `sum(reads) + offset`; owned by `scope` when named |
| `effect {id, reads[], scope?}` | Register an effect over `reads`; runs on creation and on each flush after a tracked invalidation |
| `read {id}` | Read a node — `expect.value`, or `expect.error` for a disposed one |
| `set {id, value}` | Publish; `expect.observed_by` names the effects that ran, `expect.observed_count` their number |
| `dispose {id}` | Dispose one node, dispatching on its own kind |
| `fanout {id_prefix, reads[], count, read_each}` / `dispose_fanout {id_prefix, count}` | Create / dispose `count` sibling readers, for widths a literal step list would bloat |
| `churn {source, id_prefix, live_width, cycles, mode, read_each}` | Run `cycles` subscribe/unsubscribe cycles holding `live_width` subscribers live (`mode`: `dispose_then_create` or `scope_per_cycle`) |
| `begin_scope {scope}` / `end_scope {scope}` | Open / end a teardown scope |
| `disarm {scope}` | Cancel the scope's teardown — ending it then disposes nothing |
| `dispose_stale_handle {handle_of, handle_kind}` | Dispose through a handle whose id may have been recycled; a no-op unless the id still names a node of `handle_kind` |
| `subscribe {id, cell, callback?, on_notify?, on_notify_once?}` | Register a `Cell` observer labelled `id` on `cell`. `callback` names a *shared* callable, so two registrations naming the same `callback` subscribe the same function (default: the callback is unique to `id`). `on_notify` is a list of `subscribe`/`unsubscribe` ops the callback performs reentrantly when it runs; `on_notify_once` restricts them to the first invocation. A reentrant `subscribe` may use `id_prefix` instead of `id`, minting `<prefix>_0`, `<prefix>_1`, … per invocation |
| `unsubscribe {id, times?}` | Invoke the disposer returned by `subscribe {id}`, `times` times (default 1) — repeat calls exercise idempotency |

A fixture uses top-level `steps`, or `scenarios` plus `expected` when the claim is that
two differently-built runs agree (`expected.observationally_equal`).

| Fixture | Covers |
|---------|--------|
| `reactive-graph/dispose_detaches_edges_both_directions.json` | disposal detaches upstream *and* downstream edges; a publish to a former source does not reach the disposed node; the surviving source is unaffected |
| `reactive-graph/read_after_dispose_is_an_error.json` | reading a disposed `Computed`, a disposed source cell, or through a live reader that names one is an error — never a stale or default value; double-dispose is an idempotent no-op |
| `reactive-graph/recycled_id_inherits_nothing.json` | a node minted on a recycled id starts with an empty edge set in both directions — the owner-keyed-side-table aliasing hazard; a stale cross-kind handle disposes nothing |
| `reactive-graph/scope_teardown_equals_fold_of_disposals.json` | ending a scope is observationally equal to disposing each member individually (`disposeScope_eq_disposeAll`), including reverse-creation-order cleanup |
| `reactive-graph/scoping_bounds_teardown_not_visibility.json` | a scope's nodes read parent- and sibling-owned nodes freely in every direction; propagation crosses scope boundaries unchanged |
| `reactive-graph/disarm_disposes_nothing.json` | `disarm()` leaves node state untouched — the nodes stay readable, keep propagating, and stay individually disposable; ending the scope disposes nothing |
| `reactive-graph/cross_scope_teardown_hazard.json` | ending a scope tears down its nodes even when a node outside still reads them (**required** failure — a binding that keeps them alive is non-conforming); the mirror case is symmetric |
| `reactive-graph/churn_returns_to_baseline.json` | a subscribe/unsubscribe cycle that disposes what it creates leaves the source's dependent set at its starting size, under both individual disposal and one scope per cycle |

### Cell observer conformance (`#lzdartobservercow`)

The same directory pins
[observer semantics](reactive-graph.md#observer-semantics-cellsubscribe-lzdartobservercow) —
the hand-registered `Cell.subscribe` callbacks, which are a separate mechanism from the
tracked dependency edges above. Same compute-fixture shape, same op replay, two further
assertion keys:

| Assertion | Meaning |
|---|---|
| `observed_order` | The **exact sequence** of observer labels invoked by this step |
| `observed_counts` | Per-observer invocation counts for this step, where a shared callback runs more than once |

`observed_order` is deliberately a sequence and not a set. An unordered observer
collection satisfies a set-valued `observed_by` while firing in a fresh order on every
notification, which is precisely how the family's divergence went unnoticed — so an
observer fixture that asserts only `observed_by` is rejected by the structural guard.

**These fixtures fail against some bindings today, by design.** The observer contract was
unwritten until now and four bindings answered it differently; the fixtures encode the
family position, and the gaps are listed as
[known divergences](reactive-graph.md#observer-semantics-cellsubscribe-lzdartobservercow)
with migrations. A red result here is a binding bug, not a fixture bug.

| Fixture | Covers |
|---------|--------|
| `reactive-graph/observer_order_is_registration_order.json` | observers fire in registration order, stably across notifications; a removal closes the gap without reordering survivors; a re-registered callback appends rather than resuming its old position; the `==` guard still suppresses the notification entirely (**fails**: py, zig) |
| `reactive-graph/observer_duplicate_registrations_are_independent.json` | subscribing one callback twice yields two registrations that both fire and dispose independently — no dedup by identity or by equality (**fails**: py, zig) |
| `reactive-graph/observer_subscribe_during_notify_is_deferred.json` | an observer registered mid-notification first runs on the next one, including when observers registered earlier are still unvisited; a self-feeding subscriber terminates because the pass is bounded by the pre-callback count |
| `reactive-graph/observer_unsubscribe_during_notify_takes_effect_immediately.json` | an observer disposed mid-notification does not run in that pass even when unvisited; an already-visited observer's invocation stands; self-unsubscribe completes the call it is in; the tail observer still runs, catching a swap-remove under a live cursor (**fails**: dart, go) |
| `reactive-graph/observer_disposer_is_idempotent.json` | a disposer latches — repeat calls are silent no-ops that remove nothing else, and a spent disposer never reaches a later registration of an equal callable; cell teardown drops observers without invoking them, and a disposer outliving its cell is a no-op |

## Signaling conformance

The `conformance/signaling/` directory pins the WebSocket signaling wire protocol
(see [protocol.md § Signaling Protocol](protocol.md#signaling-protocol-websocket)),
the cross-language contract shared by every distributed-plane binding and the
reference TypeScript signaling server.

- `signaling/frames.json` is a **wire** fixture: each entry's `wire` field is the
  canonical JSON for one `ClientMessage` / `ServerMessage` variant and validates
  against `schemas/signaling.json`. A binding encodes its typed message to the same
  JSON and decodes the JSON back. Tags are kebab-case (`peer-joined`, `peer-left`);
  `peer` ids are bare numbers ≤ 2⁵³−1. Client-directed frames carry `to`;
  server-forwarded frames carry a server-stamped `from`.
- `signaling/anti_spoof_session.json` is a **compute** fixture: a binding that
  implements the server room replays each `input` and asserts the emitted `expect`
  frames. It pins the load-bearing invariants — the `welcome` roster excludes the
  joining peer, a forwarded frame's `from` is the sender's server-registered id
  (never client-supplied), and an unknown target yields an `error` frame. Its
  three-peer join makes roster sorting observable: the third welcome must be
  `[1, 2]`, not reverse order `[2, 1]`. Peer-joined broadcast order remains outside
  this fixture's claim.

## Distributed (CRDT plane) conformance

The `conformance/distributed/` directory pins the CRDT anti-entropy plane
(see [protocol.md § Distributed](protocol.md#distributed-crdt-cell-plane)).

- `distributed/crdt_sync_frames.json` is a **wire** fixture: each `wire` is a
  `{"CrdtSync": {frontier, ops}}` envelope validating against
  `schemas/distributed.json` (empty, keyed+keyless ops, and a multi-peer frontier).
- `distributed/anti_entropy_converge.json` is a **compute** fixture: a binding
  replays each scenario's `ops` through its `CrdtPlaneRuntime` and asserts
  convergence to `expect.converged` independent of delivery order, plus state-based
  idempotence (re-ingesting a seen frame applies 0 new ops). It models LWW cells
  where the plane `WireStamp` is the decisive stamp under lexicographic
  `(wall_time, logical, peer)` order.

## Lossless tree conformance

The `conformance/lossless-tree/` directory pins the lossless full-document tree
CRDT (see [Lossless Tree CRDT](lossless-tree-crdt.md), `#lzlosstree`). These are
**compute** fixtures with the same `{scenarios: [{seed, steps, expect}]}` shape as
the collections fixtures: a binding builds the `seed.tree` on replica `a`
(addressing nodes by stable string `label`s), replays each `step` (`fork` /
`clone` / `sync` / `deliver` an op subset / `on` a replica an op — `create`,
`edit_leaf`, `split`, `merge_leaves`, `reorder`, `tombstone`), and asserts the
`expect` fields: `render` / `render_on` (exact rendered text per replica),
`live_nodes` (live element+leaf count, excluding the root), and `converged` (a set
of replicas that must render identically). Byte offsets in ops (`at_byte`) are
**UTF-8** and must land on a char boundary.

| Fixture | Covers |
|---------|--------|
| `lossless-tree/exact_roundtrip.json` | Token/Trivia/Raw/Error leaves incl. an invalid span + multi-byte text; `render == source` |
| `lossless-tree/one_leaf_edit_delta.json` | one-leaf edit at a UTF-8 byte offset in multi-byte text, delivered by anti-entropy |
| `lossless-tree/split_merge.json` | split a leaf then merge back; render preserved; live-node count grows then restores |
| `lossless-tree/concurrent_insert_same_parent.json` | two replicas insert into the same gap; both survive, deterministic order, converge |
| `lossless-tree/concurrent_reorder_and_leaf_edit.json` | concurrent reorder + text edit both apply (position/text are independent registers) |
| `lossless-tree/non_contiguous_anti_entropy.json` | a delivery hole is representable in the dotted frontier, re-requested, and converges |
| `lossless-tree/token_trivia_preservation.json` | a leaf edit leaves adjacent Token/Trivia leaves byte-for-byte unchanged |
| `lossless-tree/invalid_source_roundtrip.json` | unclosed fence/comment kept as Error leaves round-trips exactly; editing an adjacent Raw leaf keeps the Error spans |
| `lossless-tree/concurrent_conflict_preserves_text.json` | incompatible concurrent shapes both survive with no bytes dropped (text preservation wins over semantic shape) |

The op-delta **wire** form additionally validates against `schemas/lossless-tree.json`
(vocabulary) + `schemas/lossless-tree-delta.json` (the `TreeUpdate` message); the
Rust reference and each port validate their serialized `TreeUpdate` against these.

## Causal receipt conformance

The `conformance/receipts/` directory pins lazily's generic outcome vocabulary
for commands and effect requests (see
[protocol.md § Causal Receipts](protocol.md#causal-receipts)).

- `receipts/causal_receipts.json` is a **wire + compute** fixture: its `wire`
  field validates against `schemas/receipts.json`, and bindings replay the
  receipts into their projection. The stale-generation receipt is ignored by the
  current projection; `observed` / `accepted` remain non-terminal; `applied` is
  the terminal outcome.

## Examples

### `snapshot_minimal.json`

```json
{{#include ../conformance/snapshot_minimal.json}}
```

### `snapshot_multi_node.json`

```json
{{#include ../conformance/snapshot_multi_node.json}}
```

### `snapshot_shared_blob.json`

```json
{{#include ../conformance/snapshot_shared_blob.json}}
```

### `delta_sequential.json`

```json
{{#include ../conformance/delta_sequential.json}}
```

### `delta_non_sequential.json`

```json
{{#include ../conformance/delta_non_sequential.json}}
```

### `delta_shared_blob.json`

```json
{{#include ../conformance/delta_shared_blob.json}}
```
