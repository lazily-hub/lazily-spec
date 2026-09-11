# Replay-equivalence proof (`#lzreplayproof`)

[replay-safety.md](replay-safety.md) draws the line: the pure cores are
replay-safe, the reactive layer's *command ordering* is not, and cell **values**
are replay-stable either way. This page is the other half of that statement — it
says how a binding **proves** the stable half, instead of asserting it.

Status: **MAY**. A binding without a replay-equivalence harness is conformant.
It is a verification facility, not a runtime feature, and it is scored as an
optional row so declining it is not a gap. But a host that re-executes your code
from an event log — Temporal.io workflow replay, an event-sourced aggregate, a
deterministic simulation — should not be given a reactive graph without this
proof, and having it is what lets you.

## The contract

> Given the same event log, a **rebuilt** graph observes the same values at
> every checkpoint. Any deviation is a defect in the graph, not a tolerance.

Three obligations follow from it, and they are what the fixtures check.

### 1. The fingerprint is bound to the log that produced it

This is taken from `tsift`, whose cached excerpts are trustworthy because every
one records a body hash and *revalidates it against the source bytes* before the
excerpt is returned: a stale body deterministically suppresses the cached answer
rather than returning a plausible-looking one. Here the event log is the source
bytes.

A recorded fingerprint **MUST** carry a digest of its log, and a verify **MUST**
compare that digest *before* comparing any observed value. A fingerprint
recorded against a different log **MUST** be refused as a distinct outcome
(`log_mismatch`) and **MUST NOT** be compared.

Both halves matter. Two different logs can settle to the same final values —
`[+1, +2, +3]` and `[+3, +2, +1]` both sum to 6 — so a value comparison would
*pass*, and a harness that only compared values would certify a fingerprint that
proves nothing about the log in front of it. And a harness that compared anyway
and reported the difference as a divergence would blame the graph for a stale
test artifact.

The non-raising reporting form (`check`) is the same: it may collect value
divergences instead of failing, but a log mismatch is still refused there. A
stale fingerprint is an unanswerable question, not a report.

### 2. Divergence is localized to the first diverging checkpoint

A fingerprint that covers only the final state says the graph is wrong but not
where. A harness **MUST** checkpoint every event (`stride = 1`) by default, and
**MUST** report the first diverging checkpoint's sequence number and the label of
the cell that differed. Later checkpoints are almost always the same defect
carried forward and **MAY** be omitted from the report.

A harness **MAY** offer a coarser `stride` for long logs, and the initial state
(before any event) and the final state are always checkpointed. `stride` is part
of the fingerprint: a fingerprint recorded at one stride **MUST** be refused
against a harness sampling at another (`stride_mismatch`), because equal log
digest plus equal stride is what makes the two checkpoint sequences comparable
at all.

### 3. The observation encoding is canonical, or it fails

A fingerprint hashes observed values, so the encoding decides which differences
are differences. A binding **MAY** choose its own hash and its own byte layout —
fingerprints are pinned next to a test in one language and are not exchanged
between bindings, so there is nothing to agree on at the byte level and
demanding a shared hash would buy a dependency in five bindings for nothing.

What a binding **MUST** agree on is the **equality classes**:

| Property | Requirement |
|---|---|
| Mapping order | `{a:1, b:2}` and `{b:2, a:1}` are the same value |
| Set order | `{1,2,3}` and `{3,1,2}` are the same value |
| Sequence order | `[1,2]` and `[2,1]` are different values |
| Type tagging | `1`, `"1"`, `1.0`, `true` and the byte string `1` are five different values |
| Member framing | `["a","bc"]` and `["ab","c"]` are different values |

The last row is the one that is easy to get wrong: concatenating member
encodings without a length or delimiter makes those two sequences identical, and
a harness that cannot tell them apart certifies a graph that reshaped its own
output.

It is also the row whose obvious fixture does not prove it (`#lzreplayframing`).
`["a","bc"]` and `["ab","c"]` state a real equality class, but with a type tag in
front of every member they already differ as byte strings, so an encoder that
drops the length prefix **entirely** still passes that pair. Four bindings met
this independently while landing their harnesses and two of them ran the
length-dropping mutation, watched it survive, and ruled it benign. A pair that
merely differs is not a pair that pins the length. Three rows are needed, and the
corpus now carries all three:

| Row | What it pins | Layout |
|---|---|---|
| `["a","bc"]` vs `["ab","c"]` | the equality class | any |
| `["a","sbc"]` vs `["as","bc"]`, and `{"a":"sb"}` vs `{"as":"b"}` | the member length, by letting one member's content spell the next member's tag | one whose string tag is the byte `s` |
| `[["a"],"b"]` vs `[["a","b"]]` | the container length, by moving a member across a nested boundary | **any** |

The nested row is the layout-independent one: a nested container's boundary has
no tag to hide behind, so dropping its length or count makes both sides
concatenate to the same bytes whatever the tags are. The second row is not
layout-independent and cannot be — the colliding content has to spell the tag,
and a binding **MAY** choose its tags. So a binding whose layout differs from the
reference **MUST** construct the pair that collides in *its own* bytes and assert
it next to its encoder, and **MUST** prove it by removing the length and watching
that assertion go red. Only the binding knows its own layout; the corpus cannot
ask this question for it.

A value the encoding does not define **MUST** fail loudly rather than fall back
on the host's default string conversion. Most languages' default rendering of an
object embeds an address or identity hash, so such a fallback reports a *false*
divergence on every run — the exact failure a replay proof exists to make
impossible, arriving as a flaky test instead of a real one.

## The canonical subject

A fixture cannot carry a reactive graph, so the corpus declares two trivial
subjects by name and every binding implements them the same way.

`accumulator` — state is `sum` (a signed integer, initially `0`) and `names` (an
ordered list of strings, initially empty).

- `apply(event)`: `sum += event.payload`, then append `event.name` to `names`.
- `observe()`: `{"sum": sum, "names": names}`.

`drifting_accumulator(drift_at, drift)` — `accumulator`, plus: after applying an
event whose `seq` equals `drift_at`, `sum += drift`. It stands in for the one
thing a replay proof is looking for — a graph that takes a value from outside its
log — with `drift = 0` as the honest run and a non-zero `drift` as the defect.

An event is `{seq, name, payload}`. Sequence numbers **MUST** strictly increase
and **MAY** be non-contiguous: an ack-truncated durable outbox replays real
epochs (see [durable-outbox.md](durable-outbox.md)), and renumbering them would
hide a truncated prefix that the log digest otherwise catches.

## What the fingerprint covers, and what it cannot

Checkpoint **values** only. Per [replay-safety.md](replay-safety.md) clause 3,
sibling effect order is deliberately free across the family, so the *sequence of
effects a replay fires* is not a stable thing to fingerprint and this contract
does not ask a binding to. A harness that fingerprinted effect order would be
asserting a guarantee the family does not make, and would fail on lazily-py for
conformant reasons (its dependent fan-out is a `set` keyed by object identity).

The obligation is therefore narrower than "the replay is identical" and stronger
than "the values converge": at every checkpoint, the same labels carry the same
values, and the first place that stops being true is named.

## Reference implementation

`lazily-py`'s `lazily.replay` (`ReplayHarness` / `ReplayLog` /
`ReplayFingerprint`, BLAKE2b-256 over a type-tagged, length-framed encoding).
Its `replay_log_from_outbox` also shows the intended source of a real log: a
reliable-sync `DurableOutbox.replay_from` already *is* a replay source, and
pointing the harness at it is what turns retained frames into a fingerprinted
log.

## Fixtures

- `conformance/replay/fingerprint_log_binding.json` — obligation 1, including
  the two-logs-same-sum case a value comparison would wrongly accept.
- `conformance/replay/divergence_localization.json` — obligation 2, including
  the stride binding.
- `conformance/replay/canonical_encoding_equality.json` — obligation 3, as
  same/different digest pairs. It asserts equality *classes*, never a hex
  digest, so a binding's choice of hash stays free. Its three member-framing
  rows are described above; the binding-local colliding pair the second row
  cannot carry is the binding's own obligation, not the corpus's.
