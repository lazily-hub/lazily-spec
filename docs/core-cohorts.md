# Reproducible Core cohorts

A Core cohort is an immutable bill of materials (BOM), not a list of moving
branches. Its schema is [`schemas/core-cohort.json`](../schemas/core-cohort.json),
and `scripts/verify_core_cohort.py` is the semantic verifier.

The candidate manifest is deliberately not checked in yet. A truthful candidate
can only be cut after the Core profile, capability claims, API compatibility,
packaged-consumer gates, release pins, and Rust publication path are green. Until
then, inventing tags, artifact hashes, or registry evidence would make the BOM
look reproducible while pointing at artifacts that were never qualified.

## Evidence layout

The manifest names every byte used to qualify a cohort:

- the exact Lazily Spec repository, tag, peeled 40-hex commit, conformance
  revision, and Core profile digest;
- each binding's exact repository, tag, peeled commit, Core API generation, wire
  version, Core imports, toolchain bounds, and module compatibility ranges;
- every package coordinate and version, artifact digest, provenance statement,
  and captured registry response;
- evidence digests for profile, API, fixture, package, pre-publish consumer, and
  installed published-consumer gates.

Paths are relative to an evidence directory. The verifier rejects absolute or
parent-traversing paths, missing evidence, and digest mismatches. Registry
responses are captured as evidence because a later rerun must be able to explain
whether a package was present or yanked when the cohort was finalized.

## Verification modes

Validate a candidate before publishing one binding:

```sh
uv run python scripts/verify_core_cohort.py cohorts/2026-10-12.rc1.json \
  --artifact-root .cohort-evidence \
  --spec-root . \
  --require-publish-ready \
  --expected-spec-commit "$SPEC_COMMIT" \
  --expected-binding rust \
  --expected-commit "$GITHUB_SHA" \
  --expected-tag "$GITHUB_REF_NAME"
```

`--require-publish-ready` requires the profile, API, fixture, package, and
pre-publish installed-consumer gates to have passed. The published-consumer gate
may still be pending. A binding release job must depend on this gate; merely
running it alongside a publish job is not sufficient.

After registry propagation, download every released artifact, provenance
statement, registry response, and gate record into the evidence directory, then
finalize the manifest and run:

```sh
uv run python scripts/verify_core_cohort.py cohorts/2026-10-12.beta1.json \
  --artifact-root .cohort-evidence \
  --repo-root .. \
  --spec-root . \
  --require-final \
  --report-json out/core-cohort.json \
  --report-markdown out/core-cohort.md
```

Final verification requires the complete nine-binding set, an available (not
missing or yanked) registry status for every artifact, and all six gates to pass.
With `--repo-root`, every source tag must exist locally, peel to the manifest
commit, and match the checked-out `HEAD`.

## Reusable release gate

`.github/workflows/core-cohort-publish-gate.yml` is a reusable, non-publishing
workflow. A binding's release workflow calls it with:

- a 40-hex `spec_commit` (never `main` or another floating ref);
- the candidate manifest path at that commit;
- the calling binding id, exact commit, and version tag; and
- the name of an artifact containing the candidate packages and evidence.

The publish job then declares `needs: cohort-gate`. The reusable workflow checks
that the caller's commit and tag equal the manifest entry before it returns
green, and that the manifest's Spec commit equals the revision the workflow
checked out. It has read-only permissions and contains no registry credentials
or publish step.

Once the pending release-pin work has established the final manifest location
and evidence artifact name, each publishing repository must adopt this gate and
pin the reusable workflow itself by commit. Rust adoption additionally waits for
the Rust publication path to be green. Those cross-repository edits are part of
the release-pin integration, not something this scaffold can truthfully mark
complete in advance.
