import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, test } from "node:test";
import { spawnSync } from "node:child_process";

const HERE = dirname(fileURLToPath(import.meta.url));
const CHECKER = join(HERE, "..", "scripts", "check-coverage-claims.mjs");
const scratch = [];

afterEach(() => {
  while (scratch.length > 0) rmSync(scratch.pop(), { recursive: true, force: true });
});

function fixture(body) {
  return `${JSON.stringify(body, null, 2)}\n`;
}

function setup({
  capabilityMark = "—",
  leakCapabilityFixtureIntoBase = false,
  oneLineCapabilityLedger = false,
} = {}) {
  const suite = mkdtempSync(join(tmpdir(), "lazily-coverage-claims-"));
  scratch.push(suite);
  const spec = join(suite, "lazily-spec");
  const binding = join(suite, "lazily-rs");
  mkdirSync(join(spec, "conformance", "reactive-graph"), { recursive: true });
  mkdirSync(join(binding, "scripts"), { recursive: true });

  const baseFixtures = ["reactive-graph/base.json"];
  if (leakCapabilityFixtureIntoBase) {
    baseFixtures.push("reactive-graph/recycled.json");
  }
  writeFileSync(
    join(spec, "coverage.json"),
    fixture({
      languages: ["Rust"],
      rows: [
        {
          id: "reactive-graph",
          feature: "Reactive graph",
          fixtures: baseFixtures,
          marks: ["✅"],
        },
        {
          id: "recycled-node-id-stale-handle-fencing",
          feature: "Recycled-node-id stale-handle fencing",
          optional: true,
          requires: ["recycled_node_ids"],
          fixtures: [
            "reactive-graph/recycled.json",
            "reactive-graph/stale-matrix.json",
          ],
          marks: [capabilityMark],
        },
      ],
    }),
  );
  writeFileSync(
    join(spec, "conformance", "reactive-graph", "base.json"),
    fixture({ kind: "ReactiveGraph", steps: [] }),
  );
  writeFileSync(
    join(spec, "conformance", "reactive-graph", "recycled.json"),
    fixture({ kind: "ReactiveGraph", requires: ["recycled_node_ids"], steps: [] }),
  );
  writeFileSync(
    join(spec, "conformance", "reactive-graph", "stale-matrix.json"),
    fixture({
      kind: "ReactiveGraph",
      scenarios: [
        { id: "same_kind", requires: ["recycled_node_ids"] },
        { id: "cross_kind", requires: ["recycled_node_ids"] },
      ],
    }),
  );
  writeFileSync(
    join(binding, "scripts", "check-conformance-coverage.sh"),
    oneLineCapabilityLedger
      ? `#!/usr/bin/env bash
KNOWN_UNCOVERED=(
)
UNSUPPORTED_CAPABILITIES=("recycled_node_ids")
`
      : `#!/usr/bin/env bash
KNOWN_UNCOVERED=(
)
UNSUPPORTED_CAPABILITIES=(
  "recycled_node_ids"
)
`,
  );
  return spec;
}

function run(spec) {
  return spawnSync(process.execPath, [CHECKER, "--check"], {
    encoding: "utf8",
    env: {
      ...process.env,
      LAZILY_COVERAGE_CLAIMS_ROOT: spec,
      LAZILY_COVERAGE_BINDINGS_ROOT: dirname(spec),
    },
  });
}

test("an exact optional-capability exclusion does not weaken the broad row", () => {
  const result = run(setup());
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /coverage claims OK/);
  assert.match(result.stdout, /1 shipped mark\(s\) checked/);
});

test("a shipped capability row conflicts with an exact capability exclusion", () => {
  const result = run(setup({ capabilityMark: "✅" }));
  assert.equal(result.status, 1);
  assert.match(result.stderr, /declares recycled_node_ids in UNSUPPORTED_CAPABILITIES/);
});

test("a capability-gated fixture cannot leak back into the broad row", () => {
  const result = run(setup({ leakCapabilityFixtureIntoBase: true }));
  assert.equal(result.status, 1);
  assert.match(
    result.stderr,
    /row "reactive-graph" declares no capability, but reactive-graph\/recycled\.json requires recycled_node_ids/,
  );
});

test("a capability exclusion must use the auditable multiline ledger shape", () => {
  const result = run(setup({ oneLineCapabilityLedger: true }));
  assert.equal(result.status, 1);
  assert.match(result.stderr, /ledger is not a multiline bash array/);
});
