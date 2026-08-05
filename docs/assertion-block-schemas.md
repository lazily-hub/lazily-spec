# Assertion-block schemas

Canonical conformance claims use three historical object names:
`assertions`, `expect`, and `expected`. They are executable contract data, not
free-form fixture metadata.

`schemas/assertion-blocks.json` gives every such object a fail-closed Draft
2020-12 schema. Each route is identified by its fixture-relative path and a JSON
pointer whose array indexes are normalized to `*`. Route schemas:

- reject unknown keys with `additionalProperties: false`;
- require every key present in all examples at that route;
- validate scalar, array, object, and nested value shapes;
- cover every fixture area, including families without a whole-fixture schema;
- are checked in both directions, so an unvalidated block and a stale unused
  schema route both fail.

The file is generated from reviewed corpus state, but it is intentionally
checked in. A fixture edit therefore has to carry a visible schema diff:

```sh
python3 scripts/gen_assertion_block_schema.py
```

`make check` runs the generator in `--check` mode and mutation-checks unknown
keys, missing required keys, wrong value types, and unknown fixture routes. This
guard complements binding-side read/assert ledgers: JSON Schema constrains what
a fixture may say, while the runtime ledgers prove a binding actually consumed
and asserted what the fixture said.
