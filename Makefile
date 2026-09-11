.RECIPEPREFIX := >

LAKE ?= lake
LEAN_DIR ?= formal/lean

.PHONY: \
check \
test-schemas \
test-lean-formal \
coverage-check \
coverage-claims-check \
coverage-sync \
fixture-copies-check \
fixture-copies-check-all \
fixture-copies-sync \
async-v2-names-check \
scenario-identity-check \
prose-keys-check \
assertion-block-schema-check \
assertion-ordering-check \
fixture-discriminability-check \
corpus-published-check \
corpus-floors-check \
corpus-counts-sync \
corpus-blocks-report

check: assertion-block-schema-check test-schemas test-lean-formal coverage-check coverage-claims-check fixture-copies-check async-v2-names-check scenario-identity-check prose-keys-check assertion-ordering-check fixture-discriminability-check corpus-floors-check corpus-published-check

# Fixture-discriminability guard (#lzfixturediscrim). Exact-value assertions and
# boolean routes with both outcomes carry their own controls. Every remaining
# single-valued boolean claim must either cite a killed library-source mutant or
# remain explicitly `untested` with a reason in the fail-closed audit ledger.
fixture-discriminability-check:
>node scripts/check-fixture-discriminability.mjs

# Canonical assertion-block schema guard (#lzassertionblockschema). The
# generated schema routes every assertions/expect/expected object by fixture and
# normalized JSON pointer, so all fixture families get fail-closed keys without
# pretending Protobuf unknown-field handling is validation.
assertion-block-schema-check:
>python3 scripts/gen_assertion_block_schema.py --check

# Assertion-observation ordering guard (#lzassertordering). The binding-side
# invocations check real runner anchors; this self-test proves the guard itself
# rejects the two reversed shapes it is meant to make unreachable.
assertion-ordering-check:
>python3 scripts/check-assertion-ordering.py --self-test

# Prose-key declaration guard (#lzprosekeyconvention). An assertion key carrying
# an English paragraph states an obligation and carries nothing comparable, and
# nothing said which keys those were — so nine bindings each decided and landed
# on FOUR different treatments of the same four keys. The corpus now declares the
# set in `assertions.prose`; this is the corpus-side half (every paragraph
# declared, no stale entries, no obligation hiding in a reserved annotation
# name). The binding-side half — a declared key is DISCHARGED by naming
# executable keys the same run asserted — lives in each binding's tracker,
# because only the run knows what it asserted.
prose-keys-check:
>node scripts/check-prose-keys.mjs

# Scenario-identity guard (#lzspecscenarioids). Every scenario in the corpus must
# carry a stable `id` or `name`. Nine bindings resolve scenario identity the same
# way, and a scenario with neither key falls back to its POSITIONAL index — so
# inserting one ahead of it silently rebinds every ledger entry and every excuse
# that names it, with nothing turning red. This is the corpus-side half; the
# bindings turn their fallback into a hard error.
scenario-identity-check:
>node scripts/check-scenario-identity.mjs

# API-shape-only guard. Missing sibling checkouts are reported as staged/skipped;
# every sibling that is present must expose the canonical async value pair.
async-v2-names-check:
>python3 scripts/check_async_v2_names.py

# Feature-matrix single-source guard: docs/coverage.md (and every sibling binding
# README, when checked out) must match the canonical coverage.json. Edit
# coverage.json, then run `make coverage-sync`.
coverage-check:
>node scripts/sync-coverage.mjs --check

# Coverage-CLAIM guard: a shipped mark on a fixture-bearing row must be backed by
# a fixture the binding actually replays, read from that binding's own ledger.
# `sync-coverage` above only proves the rendered tables match coverage.json — it
# has nothing to say about whether coverage.json is TRUE. Sibling checkouts are
# reported when absent rather than silently skipped.
coverage-claims-check:
>node scripts/check-coverage-claims.mjs --check

coverage-sync:
>node scripts/sync-coverage.mjs

# Selected fixture subsets are vendored for standalone Python, Dart, Rust, and
# Go CI. The canonical corpus remains authoritative.
fixture-copies-check:
>node scripts/sync-conformance-fixtures.mjs --check

fixture-copies-check-all:
>node scripts/sync-conformance-fixtures.mjs --check --require-all

fixture-copies-sync:
>node scripts/sync-conformance-fixtures.mjs --sync

# JSON Schema drift-prevention: every conformance fixture validates against its
# schema, and the stale (slot_id / base64 / "type"-discriminant) form is rejected.
test-schemas:
>uv run --group dev pytest tests/ -q

test-lean-formal:
>cd "$(LEAN_DIR)" && $(LAKE) build

# Corpus-publication advisory (#lzspecpushbeforebindings). Bindings verify against
# this working tree; their CI clones published main. This fires at the moment the
# ordering rule applies — when `conformance/` is ahead of origin/main — names the
# fixtures, and says what CI will see. It ADVISES rather than gates: a corpus
# ahead of main is the normal state while a fixture change is being authored, so
# failing here would gate the ordinary workflow to catch a mistake made in a
# different repo. See docs/conformance.md § Publishing a corpus change.
corpus-published-check:
>node scripts/check-corpus-published.mjs

# Corpus-floor guard (#lzcorpusfloorguard). A new FIXTURE reddens ten repos in
# minutes; a new STEP inside an existing fixture reddened nothing, and eight of
# nine bindings' per-fixture step floors were slack enough to swallow three new
# rows without executing them. Two directions, one idea — a count something else
# depends on must move deliberately: `corpus-counts.json` pins the corpus's own
# per-fixture step counts so a SHRINK is visible (a runner that asserts it ran
# every step it loaded stays green over a shorter fixture), and each binding's
# declared MIN_FIXTURES / MIN_SCENARIOS is re-derived from the corpus plus that
# binding's own KNOWN_UNCOVERED / KNOWN_UNREPLAYED_SCENARIOS ledger and must
# match EXACTLY. Slack has stopped guarding; a floor above reality is
# unsatisfiable and names the red binding in one line.
corpus-floors-check:
>node scripts/check-corpus-floors.mjs

# Re-pin `corpus-counts.json` after a deliberate corpus change. Commit the
# result in the same change as the fixture edit — that pairing is the review.
corpus-counts-sync:
>node scripts/check-corpus-floors.mjs --write

# The assertion-block population each binding should DERIVE rather than type
# (#lzblockfloorpin). Four bindings floored this dimension on a hand-maintained
# constant — lazily-cs MIN_BLOCKS=743, lazily-js 638, lazily-py
# MIN_DECLARED_BLOCKS=620, lazily-zig 31 — and the first three are reproduced to
# the unit by the corpus plus that binding's own ledger. Read the row matching
# your walk (block-name set, and whether an array-valued block counts its
# elements) and assert EQUALITY against it instead of a floor.
corpus-blocks-report:
>node scripts/check-corpus-floors.mjs --report-blocks

