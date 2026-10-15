#!/usr/bin/env node
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PROFILE_PATH = join(ROOT, "profiles", "core-v1.json");
const COVERAGE_PATH = join(ROOT, "coverage.json");
const GENERATED_PATH = join(ROOT, "docs", "core-beta.md");
const CORE_COVERAGE_ROWS = new Set([
  "reactive-graph",
  "thread-safe-context",
  "async-reactive-context",
]);

const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const edgeKey = (from, to) => `${from}->${to}`;
const sorted = (values) => [...values].sort();

function duplicateValues(values) {
  const seen = new Set();
  const duplicates = new Set();
  for (const value of values) {
    if (seen.has(value)) duplicates.add(value);
    seen.add(value);
  }
  return sorted(duplicates);
}

function sameMembers(left, right) {
  return left.length === right.length && sorted(left).every((value, index) => value === sorted(right)[index]);
}

function validateProfile(profile, { readFixture = (path) => readFileSync(join(ROOT, "conformance", path)), coverage = readJson(COVERAGE_PATH) } = {}) {
  const problems = [];
  const fail = (message) => problems.push(message);

  const symbols = profile.abstract_symbols ?? [];
  const symbolIds = symbols.map((symbol) => symbol.id);
  for (const id of duplicateValues(symbolIds)) fail(`duplicate abstract symbol: ${id}`);
  for (const symbol of symbols) {
    const deprecated = symbol.deprecated_since !== null;
    if (deprecated !== (symbol.replacement !== null) || deprecated !== (symbol.earliest_removal !== null)) {
      fail(`symbol ${symbol.id} must set deprecated_since, replacement, and earliest_removal together`);
    }
    if (deprecated && symbol.earliest_removal <= symbol.deprecated_since) {
      fail(`symbol ${symbol.id} earliest_removal must be after deprecated_since`);
    }
  }

  const proofIds = new Set(Object.keys(profile.proof_classes ?? {}));
  const fixtures = profile.required_fixtures ?? [];
  const fixturePaths = fixtures.map((fixture) => fixture.path);
  for (const path of duplicateValues(fixturePaths)) fail(`duplicate required fixture: ${path}`);
  const digest = createHash("sha256");
  for (const fixture of [...fixtures].sort((a, b) => a.path.localeCompare(b.path))) {
    let bytes;
    try {
      bytes = readFixture(fixture.path);
    } catch {
      fail(`required fixture does not exist: ${fixture.path}`);
      continue;
    }
    digest.update(fixture.path);
    digest.update("\0");
    digest.update(bytes);
    let document;
    try {
      document = JSON.parse(bytes.toString("utf8"));
    } catch (error) {
      fail(`required fixture is not JSON: ${fixture.path}: ${error.message}`);
      continue;
    }
    const observedScenarios = Array.isArray(document.scenarios)
      ? document.scenarios.map((scenario) => scenario.id)
      : [];
    if (!sameMembers(fixture.scenario_ids, observedScenarios)) {
      fail(`${fixture.path} scenario_ids do not match the fixture (${observedScenarios.join(", ")})`);
    }
    for (const proof of fixture.proof_classes) {
      if (!proofIds.has(proof)) fail(`${fixture.path} references unknown proof class ${proof}`);
      else if (!profile.proof_classes[proof].fixture_required) {
        fail(`${fixture.path} uses non-fixture proof class ${proof}`);
      }
    }
  }
  if (fixtures.length > 0 && profile.fixture_corpus?.digest !== digest.digest("hex")) {
    fail("fixture_corpus.digest does not match the ordered required fixture closure");
  }

  const coverageById = new Map((coverage.rows ?? []).map((row) => [row.id, row]));
  const coreRows = profile.coverage?.core_row_ids ?? [];
  if (!sameMembers(coreRows, [...CORE_COVERAGE_ROWS])) {
    fail(`coverage.core_row_ids must be the closed Core allow-list: ${sorted(CORE_COVERAGE_ROWS).join(", ")}`);
  }
  for (const id of coreRows) {
    const row = coverageById.get(id);
    if (!row) fail(`unknown Core coverage row: ${id}`);
    else if (profile.capability_exclusions.coverage_families.includes(row.family)) {
      fail(`Core coverage row ${id} belongs to excluded capability family ${row.family}`);
    }
  }

  const excludedSymbols = new Set(profile.capability_exclusions?.public_symbols ?? []);
  const bindingIds = (profile.bindings ?? []).map((binding) => binding.id);
  for (const id of duplicateValues(bindingIds)) fail(`duplicate binding: ${id}`);
  for (const binding of profile.bindings ?? []) {
    const mappingIds = Object.keys(binding.symbol_mappings ?? {});
    const missing = symbolIds.filter((id) => !mappingIds.includes(id));
    const unknown = mappingIds.filter((id) => !symbolIds.includes(id));
    if (missing.length > 0) fail(`${binding.id} is missing symbol mappings: ${missing.join(", ")}`);
    if (unknown.length > 0) fail(`${binding.id} has unknown symbol mappings: ${unknown.join(", ")}`);

    const importIds = binding.imports.map((entry) => entry.id);
    for (const id of duplicateValues(importIds)) fail(`${binding.id} has duplicate import id ${id}`);
    for (const [symbol, mapping] of Object.entries(binding.symbol_mappings)) {
      if (!importIds.includes(mapping.import_id)) {
        fail(`${binding.id}.${symbol} references unknown import ${mapping.import_id}`);
      }
      for (const publicName of mapping.public_names) {
        const leaf = publicName.split(/::|\./).at(-1);
        if (excludedSymbols.has(publicName) || excludedSymbols.has(leaf)) {
          fail(`${binding.id}.${symbol} maps capability-only public symbol ${publicName} into Core`);
        }
      }
    }
    if (!sameMembers(binding.required_fixtures, fixturePaths)) {
      const missingFixtures = fixturePaths.filter((path) => !binding.required_fixtures.includes(path));
      const unknownFixtures = binding.required_fixtures.filter((path) => !fixturePaths.includes(path));
      if (missingFixtures.length > 0) fail(`${binding.id} is missing fixtures: ${missingFixtures.join(", ")}`);
      if (unknownFixtures.length > 0) fail(`${binding.id} has unknown fixtures: ${unknownFixtures.join(", ")}`);
    }
    const claimIds = binding.fixtureless_claims.map((claim) => claim.id);
    for (const id of duplicateValues(claimIds)) fail(`${binding.id} has duplicate fixtureless claim ${id}`);
    for (const claim of binding.fixtureless_claims) {
      for (const proof of claim.proof_classes) {
        if (!proofIds.has(proof)) fail(`${binding.id}.${claim.id} references unknown proof class ${proof}`);
        else if (profile.proof_classes[proof].fixture_required) {
          fail(`${binding.id}.${claim.id} uses fixture-required proof class ${proof}`);
        }
      }
    }
    const range = binding.support_range;
    if (range.minimum_core_api_generation > profile.core_api_generation ||
        (range.maximum_core_api_generation !== null && range.maximum_core_api_generation < profile.core_api_generation)) {
      fail(`${binding.id} support_range excludes core_api_generation ${profile.core_api_generation}`);
    }
  }

  const modules = profile.modules ?? [];
  const moduleById = new Map(modules.map((module) => [module.id, module]));
  if (moduleById.size !== modules.length) fail("module ids must be unique");
  const core = moduleById.get("core");
  if (!core || core.kind !== "core") fail("modules must declare core with kind core");
  else if (core.depends_on.length > 0) fail("Core must not depend on any module");

  const allowedEdges = new Set(
    (profile.dependency_policy?.allowed_module_edges ?? []).map(({ from, to }) => edgeKey(from, to)),
  );
  const declaredEdges = new Set();
  for (const module of modules) {
    for (const targetId of module.depends_on) {
      const key = edgeKey(module.id, targetId);
      declaredEdges.add(key);
      const target = moduleById.get(targetId);
      if (!target) fail(`${module.id} depends on unknown module ${targetId}`);
      if (!allowedEdges.has(key)) fail(`unregistered module dependency: ${key}`);
      if (module.kind !== "adapter" && target?.kind === "adapter") {
        fail(`adapter back-edge is forbidden: ${key}`);
      }
    }
  }
  for (const key of allowedEdges) {
    if (!declaredEdges.has(key)) fail(`stale allowed module dependency: ${key}`);
  }

  const visiting = new Set();
  const visited = new Set();
  function visit(id, trail) {
    if (visiting.has(id)) {
      fail(`module dependency cycle: ${[...trail, id].join(" -> ")}`);
      return;
    }
    if (visited.has(id)) return;
    visiting.add(id);
    for (const target of moduleById.get(id)?.depends_on ?? []) visit(target, [...trail, id]);
    visiting.delete(id);
    visited.add(id);
  }
  for (const id of moduleById.keys()) visit(id, []);
  if (profile.core_build?.module_id !== "core") fail("core_build.module_id must be core");
  if ((profile.core_build?.optional_modules_enabled ?? []).length > 0) {
    fail("Core-only build must disable every optional module");
  }

  return problems;
}

function renderProfile(profile) {
  const lines = [
    "<!-- GENERATED by scripts/check-core-profile.mjs; edit profiles/core-v1.json instead. -->",
    "# Lazily Core Beta profile",
    "",
    `Profile \`${profile.profile_id}\` is **${profile.status}** at Core API generation **${profile.core_api_generation}**.`,
    "Only the allow-listed symbols and imports below are in the Core compatibility promise; other umbrella exports remain Preview or independently maturing modules.",
    "",
    "## Abstract Core surface",
    "",
    "| Symbol | Kind | Introduced | Deprecation |",
    "| --- | --- | ---: | --- |",
  ];
  for (const symbol of profile.abstract_symbols) {
    const deprecation = symbol.deprecated_since === null
      ? "—"
      : `since ${symbol.deprecated_since}; use ${symbol.replacement}; earliest removal ${symbol.earliest_removal}`;
    lines.push(`| \`${symbol.id}\` | ${symbol.kind} | ${symbol.introduced} | ${deprecation} |`);
  }
  lines.push("", "## Candidate bindings", "", "| Binding | Flavors | Imports | Toolchains | Core range | Fixtureless module claims |", "| --- | --- | --- | --- | --- | --- |");
  for (const binding of profile.bindings) {
    const imports = binding.imports.map((entry) => `\`${entry.path}\``).join("<br>");
    const tools = `${binding.toolchains.minimum.name} ${binding.toolchains.minimum.version} → ${binding.toolchains.current.version}`;
    const maximum = binding.support_range.maximum_core_api_generation ?? "∞";
    const fixturelessClaims = binding.fixtureless_claims.length === 0
      ? "—"
      : binding.fixtureless_claims.map((claim) => `\`${claim.id}\` (${claim.proof_classes.map((proof) => `\`${proof}\``).join(", ")})`).join("<br>");
    lines.push(`| ${binding.language} (${binding.maturity}) | ${binding.execution_flavors.join(", ")} | ${imports} | ${tools} | ${binding.support_range.minimum_core_api_generation}–${maximum} | ${fixturelessClaims} |`);
  }
  lines.push("", "## Per-binding public symbols", "");
  for (const binding of profile.bindings) {
    lines.push(`### ${binding.language}`, "", "| Abstract symbol | Public names | Import |", "| --- | --- | --- |");
    const imports = new Map(binding.imports.map((entry) => [entry.id, entry.path]));
    for (const symbol of profile.abstract_symbols) {
      const mapping = binding.symbol_mappings[symbol.id];
      lines.push(`| \`${symbol.id}\` | ${mapping.public_names.map((name) => `\`${name}\``).join(", ")} | \`${imports.get(mapping.import_id)}\` |`);
    }
    lines.push("");
  }
  lines.push(
    "## Required evidence",
    "",
    `Fixture closure: **${profile.required_fixtures.length}** files; digest \`${profile.fixture_corpus.algorithm}:${profile.fixture_corpus.digest}\`.`,
    "",
    "Every candidate binding must replay the complete closure. Fixtureless claims name their proof class explicitly; C-ABI is a module claim and does not enter Core by being shipped in an umbrella package.",
    "",
    "## Dependency boundary",
    "",
    "Core has no module dependencies. Modules may depend on Core; every module-to-module edge is registered, no non-adapter may depend on an adapter, and the graph must remain acyclic. The Core-only build enables no optional modules.",
    "",
    "| Module | Kind | Depends on | Core generations |",
    "| --- | --- | --- | --- |",
  );
  for (const module of profile.modules) {
    const maximum = module.core_api_range.maximum_core_api_generation ?? "∞";
    lines.push(`| \`${module.id}\` | ${module.kind} | ${module.depends_on.map((id) => `\`${id}\``).join(", ") || "—"} | ${module.core_api_range.minimum_core_api_generation}–${maximum} |`);
  }
  return `${lines.join("\n")}\n`;
}

function selfTest(profile, coverage) {
  const cases = [
    ["missing mapping", (value) => delete value.bindings[0].symbol_mappings.context, "missing symbol mappings"],
    ["unknown mapping", (value) => { value.bindings[0].symbol_mappings.queue_cell = value.bindings[0].symbol_mappings.source; }, "unknown symbol mappings"],
    ["missing fixture", (value) => value.bindings[0].required_fixtures.pop(), "missing fixtures"],
    ["unknown fixture", (value) => value.bindings[0].required_fixtures.push("reactive-graph/not-real.json"), "unknown fixtures"],
    ["Core-to-module edge", (value) => value.modules.find((module) => module.id === "core").depends_on.push("collections"), "Core must not depend"],
    ["unregistered module edge", (value) => value.modules.find((module) => module.id === "collections").depends_on.push("codecs"), "unregistered module dependency"],
    ["adapter back-edge", (value) => { value.modules.find((module) => module.id === "collections").depends_on.push("react"); value.dependency_policy.allowed_module_edges.push({ from: "collections", to: "react" }); }, "adapter back-edge"],
    ["dependency cycle", (value) => { value.modules.find((module) => module.id === "core").depends_on.push("collections"); value.dependency_policy.allowed_module_edges.push({ from: "core", to: "collections" }); }, "dependency cycle"],
    ["capability symbol", (value) => value.bindings[0].symbol_mappings.source.public_names.push("QueueCell"), "capability-only public symbol"],
    ["capability coverage row", (value) => value.coverage.core_row_ids.push("keyed-reactive-maps"), "closed Core allow-list"],
    ["optional module in Core build", (value) => value.core_build.optional_modules_enabled.push("collections"), "Core-only build"],
  ];
  for (const [name, mutate, expected] of cases) {
    const value = structuredClone(profile);
    mutate(value);
    const problems = validateProfile(value, { coverage });
    if (!problems.some((problem) => problem.includes(expected))) {
      throw new Error(`self-test ${name} did not fail with ${expected}; got: ${problems.join("; ")}`);
    }
  }
  console.log(`core profile self-test OK: ${cases.length} negative cases rejected`);
}

const profile = readJson(PROFILE_PATH);
const coverage = readJson(COVERAGE_PATH);
const problems = validateProfile(profile, { coverage });
if (problems.length > 0) {
  for (const problem of problems) console.error(`ERROR: ${problem}`);
  process.exit(1);
}

if (process.argv.includes("--self-test")) selfTest(profile, coverage);
const rendered = renderProfile(profile);
if (process.argv.includes("--write")) {
  writeFileSync(GENERATED_PATH, rendered);
  console.log(`wrote ${GENERATED_PATH.slice(ROOT.length + 1)}`);
} else {
  if (!existsSync(GENERATED_PATH) || readFileSync(GENERATED_PATH, "utf8") !== rendered) {
    console.error("ERROR: docs/core-beta.md is stale; run node scripts/check-core-profile.mjs --write");
    process.exit(1);
  }
  console.log(`core profile OK: ${profile.bindings.length} candidate bindings, ${profile.abstract_symbols.length} symbols, ${profile.required_fixtures.length} fixtures`);
}

export { renderProfile, validateProfile };
