import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { renderSupportPolicy, runConsumers, validateContract } from "../scripts/core-support.mjs";

function fixture() {
  const scenarios = [
    ["source-computed-effect", "source to computed to effect"],
    ["batch-coalescing", "one settled rerun"],
    ["scoped-disposal", "scope teardown"],
    ["typed-context", "typed identity"],
  ];
  const profile = {
    profile_id: "core-v1",
    status: "candidate",
    core_api_generation: 1,
    bindings: [
      {
        id: "rust",
        language: "Rust",
        maturity: "candidate",
        execution_flavors: ["single-threaded"],
        imports: [{ id: "core", path: "lazily::core", kind: "module" }],
        toolchains: {
          minimum: { name: "Rust", version: "1.88" },
          current: { name: "Rust", version: "stable" },
        },
      },
      {
        id: "gdscript",
        language: "GDScript",
        maturity: "preview",
        execution_flavors: ["single-threaded"],
        imports: [{ id: "root", path: "Lazily", kind: "class" }],
        toolchains: {
          minimum: { name: "Godot", version: "4.4" },
          current: { name: "Godot", version: "4.5" },
        },
      },
    ],
  };
  const contract = {
    schema_version: 1,
    profile: "core-v1",
    policy: {
      pre_1_0_compatibility: "Compatibility is intentional before 1.0.",
      deprecation: { minimum_compatible_cohorts: 2, minimum_days: 90 },
      preview_disclaimer: "Non-Core exports remain Preview.",
    },
    required_scenarios: scenarios.map(([id, description]) => ({ id, description })),
    bindings: [
      {
        id: "rust",
        repository: "lazily-rs",
        package: { ecosystem: "cargo", coordinate: "lazily" },
        consumer: {
          target: "core-artifact-consumer-check",
          isolation: "clean-temporary-project",
          dependency_source: "built-artifact-only",
          toolchain_points: ["minimum", "current"],
          scenarios: scenarios.map(([id]) => id),
        },
      },
    ],
  };
  return { profile, contract };
}

test("validates a closed candidate binding and scenario set", () => {
  const { profile, contract } = fixture();
  const result = validateContract(profile, contract);
  assert.deepEqual([...result.contractById.keys()], ["rust"]);
});

test("rejects an omitted candidate without granting Preview Core credit", () => {
  const { profile, contract } = fixture();
  profile.bindings.push({
    ...profile.bindings[0],
    id: "python",
    language: "Python",
    imports: [{ id: "core", path: "lazily.core", kind: "module" }],
  });
  assert.throws(() => validateContract(profile, contract), /missing=\[python\]/);
});

test("rejects a vacuous consumer scenario list", () => {
  const { profile, contract } = fixture();
  contract.bindings[0].consumer.scenarios.pop();
  assert.throws(() => validateContract(profile, contract), /missing=\[typed-context\]/);
});

test("rejects a deprecation promise shorter than the policy floor", () => {
  const { profile, contract } = fixture();
  contract.policy.deprecation.minimum_days = 89;
  assert.throws(() => validateContract(profile, contract), /at least 90 days/);
});

test("renders toolchains, Core imports, package coordinates, and Preview disclaimer", () => {
  const { profile, contract } = fixture();
  const rendered = renderSupportPolicy(profile, contract);
  assert.match(rendered, /Rust 1\.88/);
  assert.match(rendered, /lazily::core/);
  assert.match(rendered, /cargo:`lazily`/);
  assert.match(rendered, /Non-Core exports remain Preview/);
  assert.match(rendered, /GDScript \(`gdscript`\) remains \*\*Preview\*\*/);
});

test("consumer runner is fail-closed in require-all mode", () => {
  const { profile, contract } = fixture();
  const bindingsRoot = mkdtempSync(join(tmpdir(), "lazily-core-consumers-"));
  assert.throws(
    () => runConsumers(profile, contract, { bindingsRoot, requireAll: true }),
    /sibling checkout .* is absent/,
  );
});

test("consumer runner invokes only an explicit artifact target", () => {
  const { profile, contract } = fixture();
  const bindingsRoot = mkdtempSync(join(tmpdir(), "lazily-core-consumers-"));
  const repository = join(bindingsRoot, "lazily-rs");
  mkdirSync(repository);
  writeFileSync(join(repository, "Makefile"), "core-artifact-consumer-check:\n\t@true\n");
  const calls = [];
  const results = runConsumers(profile, contract, {
    bindingsRoot,
    requireAll: true,
    execute(cwd, target) {
      calls.push({ cwd, target });
      return 0;
    },
  });
  assert.deepEqual(calls, [{ cwd: repository, target: "core-artifact-consumer-check" }]);
  assert.equal(results[0].status, "passed");
});
