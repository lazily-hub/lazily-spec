# Contributing to lazily-spec

## Verify a change

Run the complete local gate, including the Lean formal model, with:

```bash
make check
```

The ordinary `make check` also verifies every sibling fixture mirror that is
currently checked out.

## Maintain vendored fixture subsets

Python, Dart, Rust, and Go vendor selected fixture subsets so their suites can
run without a sibling checkout. From this canonical repository:

```bash
make fixture-copies-check-all  # verify every tracked copy byte-for-byte
make fixture-copies-sync       # refresh the present mirrors
```
