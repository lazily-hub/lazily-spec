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
async-v2-names-check

check: test-schemas test-lean-formal coverage-check coverage-claims-check fixture-copies-check async-v2-names-check

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
