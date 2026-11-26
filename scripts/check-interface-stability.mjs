#!/usr/bin/env node
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const REGISTRY_PATH = join(ROOT, "profiles", "interface-stability.json");
const PROFILE_PATH = join(ROOT, "profiles", "core-v1.json");
const CONSUMERS_PATH = join(ROOT, "profiles", "core-artifact-consumers.json");
const GENERATED_PATH = join(ROOT, "docs", "interface-stability.md");
const RUST_FACADE = join(ROOT, "..", "lazily-rs", "src", "core.rs");
const REACTIVE_GRAPH_DIR = join(ROOT, "conformance", "reactive-graph");

const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const sorted = (values) => [...values].sort();
const sameMembers = (left, right) => {
  const a = sorted(left);
  const b = sorted(right);
  return a.length === b.length && a.every((value, index) => value === b[index]);
};

function rustTypeNames(binding) {
  return sorted(
    Object.values(binding.symbol_mappings).flatMap((mapping) =>
      mapping.public_names.filter((name) => /^[A-Z][A-Za-z0-9]*$/.test(name)),
    ),
  );
}

export function parseRustFacade(text) {
  const found = [];
  const pattern = /(?:#\[cfg\(feature = "([^"]+)"\)\]\s*)?pub use crate::\{([^}]+)\};/g;
  for (const match of text.matchAll(pattern)) {
    const cfg = match[1] ?? null;
    for (const raw of match[2].split(",")) {
      const name = raw.trim();
      if (name.length === 0) continue;
      found.push({ name, cfg });
    }
  }
  return found;
}

function outsideClosure() {
  return sorted(
    readdirSync(REACTIVE_GRAPH_DIR).filter((name) => name.endsWith(".json")),
  );
}

export function validateStability(registry, profile, consumers, { facade = null, reactiveGraphFiles = outsideClosure() } = {}) {
  const problems = [];
  const fail = (message) => problems.push(message);
  if (registry.profile_id !== profile.profile_id) fail("profile_id must equal the core profile");
  if (registry.profile_status !== profile.status) {
    fail(`profile_status must equal the core profile status (${profile.status})`);
  }

  const symbolIds = profile.abstract_symbols.map((symbol) => symbol.id);
  if (!sameMembers(registry.beta_contract.abstract_symbols, symbolIds)) {
    fail("beta-contract symbols must equal the core profile abstract symbols");
  }
  for (const binding of profile.bindings) {
    if (!sameMembers(binding.execution_flavors, registry.beta_contract.execution_flavors)) {
      fail(`${binding.id} execution flavors must equal the beta-contract flavor set`);
    }
  }
  const scenarios = consumers.required_scenarios.map((scenario) => scenario.id);
  if (!sameMembers(registry.beta_contract.consumer_scenarios, scenarios)) {
    fail("consumer scenarios must equal the artifact-consumer contract");
  }
  for (const fixture of profile.required_fixtures) {
    if (!fixture.path.startsWith("reactive-graph/")) {
      fail(`beta-contract fixture is outside reactive-graph: ${fixture.path}`);
    }
  }

  const moduleIds = profile.modules.filter((module) => module.kind !== "core").map((module) => module.id);
  const listed = registry.unstable_modules.map((module) => module.id);
  if (!sameMembers(listed, moduleIds)) fail("unstable modules must equal every non-core profile module");
  if (new Set(listed).size !== listed.length) fail("duplicate unstable module");

  const closure = new Set(profile.required_fixtures.map((fixture) => fixture.path.slice("reactive-graph/".length)));
  const outside = reactiveGraphFiles.filter((name) => !closure.has(name));
  if (!sameMembers(registry.reactive_graph_outside_core_closure, outside)) {
    fail("reactive-graph files outside the core closure must be listed as unstable");
  }

  const rust = profile.bindings.find((binding) => binding.id === "rust");
  const allowListed = rustTypeNames(rust);
  if (!sameMembers(registry.rust_core_facade.beta_contract_reexports, allowListed)) {
    fail("Rust beta-contract re-exports must equal the Rust binding's type names");
  }
  const unstableNames = registry.rust_core_facade.unstable_reexports.map((item) => item.name);
  if (new Set(unstableNames).size !== unstableNames.length) fail("duplicate unstable Rust re-export");
  for (const name of unstableNames) {
    if (allowListed.includes(name)) fail(`${name} is allow-listed and cannot be an unstable re-export`);
  }
  const excluded = new Set(profile.capability_exclusions.public_symbols);
  for (const name of registry.rust_core_facade.beta_contract_reexports) {
    if (excluded.has(name)) fail(`${name} is a capability exclusion and cannot be a beta-contract re-export`);
  }

  if (facade !== null) {
    const expected = [
      ...registry.rust_core_facade.beta_contract_reexports.map((name) => `${name}`),
      ...registry.rust_core_facade.unstable_reexports.map((item) => `${item.cfg ?? ""}:${item.name}`),
    ];
    const actual = facade.map((item) => (item.cfg === null && registry.rust_core_facade.beta_contract_reexports.includes(item.name))
      ? item.name
      : `${item.cfg ?? ""}:${item.name}`);
    if (!sameMembers(actual, expected)) {
      fail(`lazily::core re-exports must equal the registry facade, got ${sorted(actual).join(", ")}`);
    }
  }

  const bindingIds = new Set(profile.bindings.map((binding) => binding.id));
  for (const surface of registry.not_candidate_bindings) {
    if (bindingIds.has(surface.id)) fail(`${surface.id} is a candidate binding and cannot be listed as absent`);
  }
  return problems;
}

function render(registry, profile, consumers) {
  const policy = consumers.policy;
  const lines = [
    "<!-- GENERATED by scripts/check-interface-stability.mjs; edit profiles/interface-stability.json instead. -->",
    "# Interface stability",
    "",
    `Profile \`${profile.profile_id}\` is **${profile.status}** at Core API generation **${profile.core_api_generation}**.`,
    "This classification says which public interfaces are stable enough to treat as the beta contract, and which stay explicitly unstable.",
    "It does not promote the profile and it does not change runtime behavior.",
    "",
    "## What \"core\" means",
    "",
    "Three existing uses of the word are not the same contract:",
    "",
    "- **Beta contract.** The product allow-list in `profiles/core-v1.json`: the abstract symbols below, their per-binding names, the declared execution flavors, the reactive-graph fixture closure, and the installed-consumer scenarios.",
    "- **Collection method list.** [Cell model § Core surface vs. binding extensions](../cell-model.md#core-surface-vs-binding-extensions) names methods a collection implementation must expose. That is a module conformance list. It is not this beta contract.",
    "- **Rust facade.** `lazily::core` re-exports the allow-listed Rust names and also re-exports names that are not allow-listed. Always-compiled Rust modules are a build fact, not a promise.",
    "",
    "## Beta contract",
    "",
    "Only these abstract symbols are the beta contract.",
    "A public name is in the contract only when that binding's `symbol_mappings` lists it.",
    "A conformance fixture, a binding-matrix MUST, or a type that merely implements a flavor is not enough.",
    "",
    "| Symbol | Kind |",
    "| --- | --- |",
  ];
  for (const symbol of profile.abstract_symbols) {
    lines.push(`| \`${symbol.id}\` | ${symbol.kind} |`);
  }
  lines.push(
    "",
    `Execution flavors, for every candidate binding: ${registry.beta_contract.execution_flavors.map((flavor) => `\`${flavor}\``).join(", ")}.`,
    "Flavor behavior is in the contract because those bindings must keep passing the reactive-graph closure on each flavor they declare.",
    "The extra Rust type names that implement `thread_safe` and `async` are not in the Rust symbol mapping, so those names stay unstable.",
    "",
    `Fixture closure: **${profile.required_fixtures.length}** \`reactive-graph/\` files; digest \`${profile.fixture_corpus.algorithm}:${profile.fixture_corpus.digest}\`.`,
    `Installed-consumer scenarios: ${registry.beta_contract.consumer_scenarios.map((id) => `\`${id}\``).join(", ")}.`,
    "",
    policy.pre_1_0_compatibility,
    `A deprecated core symbol remains compatible for at least ${policy.deprecation.minimum_compatible_cohorts} compatible cohorts and ${policy.deprecation.minimum_days} days.`,
    policy.preview_disclaimer,
    "",
    "## Explicitly unstable modules",
    "",
    "Every profile module that is not `core` stays unstable.",
    "An umbrella export does not promote it.",
    "",
    "| Module | Reason |",
    "| --- | --- |",
  );
  for (const module of registry.unstable_modules) {
    lines.push(`| \`${module.id}\` | ${module.reason} |`);
  }
  lines.push(
    "",
    "Capability exclusions are unstable by reference to the profile, not by a second list:",
    `coverage families ${profile.capability_exclusions.coverage_families.map((id) => `\`${id}\``).join(", ")};`,
    `public symbols ${profile.capability_exclusions.public_symbols.map((id) => `\`${id}\``).join(", ")}.`,
    "",
    "## Reactive-graph fixtures outside the closure",
    "",
    "These files are normative for merge-cell behavior and are not in the core fixture digest.",
    "They stay unstable relative to the beta contract.",
    "",
  );
  for (const name of registry.reactive_graph_outside_core_closure) {
    lines.push(`- \`conformance/reactive-graph/${name}\``);
  }
  lines.push(
    "",
    "## Rust `lazily::core` facade",
    "",
    "Allow-listed re-exports, cfg-free:",
    registry.rust_core_facade.beta_contract_reexports.map((name) => `\`${name}\``).join(", ") + ".",
    "",
    "Unstable re-exports:",
    "",
    "| Name | cfg | Reason |",
    "| --- | --- | --- |",
  );
  for (const item of registry.rust_core_facade.unstable_reexports) {
    lines.push(`| \`${item.name}\` | ${item.cfg === null ? "—" : `\`${item.cfg}\``} | ${item.reason} |`);
  }
  lines.push(
    "",
    "## Not candidate bindings",
    "",
    "| Surface | Reason |",
    "| --- | --- |",
  );
  for (const surface of registry.not_candidate_bindings) {
    lines.push(`| \`${surface.id}\` | ${surface.reason} |`);
  }
  lines.push("", "## Keeping the beta contract stable", "");
  for (const item of registry.stability_work) lines.push(`- ${item}`);
  lines.push(
    "",
    "Per-binding names and imports stay in [Core Beta profile](core-beta.md).",
    "Support ranges and the deprecation window stay in [Core support](core-support.md).",
  );
  return `${lines.join("\n")}\n`;
}

function selfTest(registry, profile, consumers) {
  const facade = [
    ...registry.rust_core_facade.beta_contract_reexports.map((name) => ({ name, cfg: null })),
    ...registry.rust_core_facade.unstable_reexports.map((item) => ({ name: item.name, cfg: item.cfg })),
  ];
  const files = outsideClosure();
  const cases = [
    ["dropped symbol", (value) => value.beta_contract.abstract_symbols.pop(), "beta-contract symbols"],
    ["promoted status", (value) => { value.profile_status = "beta"; }, "profile_status"],
    ["dropped module", (value) => value.unstable_modules.pop(), "unstable modules"],
    ["allow-listed name marked unstable", (value) => {
      const name = value.rust_core_facade.beta_contract_reexports.pop();
      value.rust_core_facade.unstable_reexports.push({ name, cfg: null, reason: "no" });
    }, "allow-listed"],
    ["unlisted reactive-graph fixture", (value) => value.reactive_graph_outside_core_closure.pop(), "outside the core closure"],
    ["candidate listed as absent", (value) => value.not_candidate_bindings.push({ id: "rust", reason: "no" }), "candidate binding"],
  ];
  for (const [name, mutate, expected] of cases) {
    const value = structuredClone(registry);
    mutate(value);
    const problems = validateStability(value, profile, consumers, { facade, reactiveGraphFiles: files });
    if (!problems.some((problem) => problem.includes(expected))) {
      throw new Error(`self-test ${name} did not fail with ${expected}; got: ${problems.join("; ")}`);
    }
  }
  console.log(`interface stability self-test OK: ${cases.length} negative cases rejected`);
}

export function run() {
  const registry = readJson(REGISTRY_PATH);
  const profile = readJson(PROFILE_PATH);
  const consumers = readJson(CONSUMERS_PATH);
  const facade = existsSync(RUST_FACADE) ? parseRustFacade(readFileSync(RUST_FACADE, "utf8")) : null;
  const problems = validateStability(registry, profile, consumers, { facade });
  if (problems.length > 0) {
    for (const problem of problems) console.error(`ERROR: ${problem}`);
    process.exit(1);
  }
  if (process.argv.includes("--self-test")) selfTest(registry, profile, consumers);
  const rendered = render(registry, profile, consumers);
  if (process.argv.includes("--write")) {
    writeFileSync(GENERATED_PATH, rendered);
    console.log(`wrote ${GENERATED_PATH.slice(ROOT.length + 1)}`);
  } else if (!existsSync(GENERATED_PATH) || readFileSync(GENERATED_PATH, "utf8") !== rendered) {
    console.error("ERROR: docs/interface-stability.md is stale; run node scripts/check-interface-stability.mjs --write");
    process.exit(1);
  } else {
    console.log(`interface stability OK: ${registry.beta_contract.abstract_symbols.length} beta-contract symbols, ${registry.unstable_modules.length} unstable modules`);
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) run();
