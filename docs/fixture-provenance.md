# Fixture provenance and licensing

The owner selected Apache License 2.0 for the Lazily package family. The
`lazily-spec` repository, its independently authored specifications, schemas,
and canonical conformance fixtures are available under `Apache-2.0` unless a
file says otherwise. Copying a canonical fixture into a binding preserves that
source license and provenance; a destination repository license does not erase
it.

[`provenance/fixtures.json`](../provenance/fixtures.json) records every current
canonical fixture by path and SHA-256 digest and every byte-identical vendored
Go copy with its canonical source path. The generated ledger is checked against
the filesystem by `scripts/generate-fixture-provenance.py --check`; additions,
deletions, byte drift, or an unreviewed copy make `make check` fail.

New generated simulation fixtures MUST live under `conformance/simulation/` and
declare `schema_version`, `origin`, `license`, `seed`, and a `generator` object
with stable `path` and `version` fields. An imported artifact additionally MUST
record its exact upstream version or commit, source license, preserved notices,
and reviewer approval. Unknown provenance is a stop condition, not an invitation
to infer permission from public readability.

Development tooling is not redistributed as part of the specification.
[`third-party/uv-lock-licenses.json`](../third-party/uv-lock-licenses.json) is a
machine-readable inventory generated from the exact registry packages in
`uv.lock`, with reviewed SPDX expressions, dependency relationship, source URL,
and notice disposition. A lock change without a corresponding license review
fails closed.
