#!/usr/bin/env node

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const DEFAULT_PROFILE = join(ROOT, "profiles", "core-v1.json");
const DEFAULT_CONTRACT = join(ROOT, "profiles", "core-artifact-consumers.json");
const DEFAULT_DOC = join(ROOT, "docs", "core-support.md");
const REQUIRED_SCENARIOS = new Set([
  "source-computed-effect",
  "batch-coalescing",
  "scoped-disposal",
  "typed-context",
]);
const QUALIFYING_MATURITY = new Set(["candidate", "beta"]);

function fail(message) {
  throw new Error(message);
}

function object(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(`${label} must be an object`);
  }
  return value;
}

function nonEmptyString(value, label) {
  if (typeof value !== "string" || value.trim() === "") {
    fail(`${label} must be a non-empty string`);
  }
  return value;
}

function uniqueBy(items, key, label) {
  const seen = new Set();
  for (const item of items) {
    const value = item[key];
    if (seen.has(value)) fail(`${label} repeats ${key}=${JSON.stringify(value)}`);
    seen.add(value);
  }
}

function sameSet(actual, expected, label) {
  const got = new Set(actual);
  const missing = [...expected].filter((value) => !got.has(value));
  const extra = [...got].filter((value) => !expected.has(value));
  if (got.size !== actual.length || missing.length || extra.length) {
    fail(
      `${label} must contain exactly ${[...expected].join(", ")}; ` +
        `missing=[${missing.join(", ")}], extra=[${extra.join(", ")}]`,
    );
  }
}

function profileImports(binding) {
  if (!Array.isArray(binding.imports) || binding.imports.length === 0) {
    fail(`profile binding ${binding.id} must declare at least one Core import`);
  }
  return binding.imports.map((entry, index) => {
    const item = object(entry, `profile binding ${binding.id} imports[${index}]`);
    return nonEmptyString(item.path, `profile binding ${binding.id} imports[${index}].path`);
  });
}

function toolchain(binding, side) {
  const tools = object(binding.toolchains, `profile binding ${binding.id}.toolchains`);
  const entry = object(tools[side], `profile binding ${binding.id}.toolchains.${side}`);
  return `${nonEmptyString(entry.name, `${binding.id} ${side} toolchain name`)} ${nonEmptyString(
    entry.version,
    `${binding.id} ${side} toolchain version`,
  )}`;
}

export function validateContract(profileInput, contractInput) {
  const profile = object(profileInput, "Core profile");
  const contract = object(contractInput, "artifact-consumer contract");
  const profileId = nonEmptyString(profile.profile_id, "profile.profile_id");
  if (profileId !== contract.profile) {
    fail(`contract targets ${contract.profile}, but profile id is ${profileId}`);
  }
  if (!new Set(["candidate", "beta"]).has(profile.status)) {
    fail(`profile.status must be candidate or beta, got ${JSON.stringify(profile.status)}`);
  }
  if (!Number.isInteger(profile.core_api_generation) || profile.core_api_generation < 1) {
    fail("profile.core_api_generation must be a positive integer");
  }

  const policy = object(contract.policy, "contract.policy");
  nonEmptyString(policy.pre_1_0_compatibility, "contract.policy.pre_1_0_compatibility");
  nonEmptyString(policy.preview_disclaimer, "contract.policy.preview_disclaimer");
  const deprecation = object(policy.deprecation, "contract.policy.deprecation");
  if (!Number.isInteger(deprecation.minimum_compatible_cohorts) || deprecation.minimum_compatible_cohorts < 2) {
    fail("the deprecation window must cover at least two compatible cohorts");
  }
  if (!Number.isInteger(deprecation.minimum_days) || deprecation.minimum_days < 90) {
    fail("the deprecation window must cover at least 90 days");
  }

  if (!Array.isArray(contract.required_scenarios)) {
    fail("contract.required_scenarios must be an array");
  }
  sameSet(
    contract.required_scenarios.map((scenario) =>
      nonEmptyString(object(scenario, "required scenario").id, "required scenario id"),
    ),
    REQUIRED_SCENARIOS,
    "contract.required_scenarios",
  );

  if (!Array.isArray(profile.bindings) || profile.bindings.length === 0) {
    fail("profile.bindings must be a non-empty array");
  }
  if (!Array.isArray(contract.bindings) || contract.bindings.length === 0) {
    fail("contract.bindings must be a non-empty array");
  }
  uniqueBy(profile.bindings, "id", "profile.bindings");
  uniqueBy(contract.bindings, "id", "contract.bindings");
  uniqueBy(contract.bindings, "repository", "contract.bindings");

  const profileById = new Map(profile.bindings.map((binding) => [binding.id, binding]));
  const contractById = new Map(contract.bindings.map((binding) => [binding.id, binding]));
  const qualifyingIds = profile.bindings
    .filter((binding) => QUALIFYING_MATURITY.has(binding.maturity))
    .map((binding) => binding.id);
  sameSet(contract.bindings.map((binding) => binding.id), new Set(qualifyingIds), "contract binding ids");

  for (const contractBinding of contract.bindings) {
    const binding = profileById.get(contractBinding.id);
    if (!binding) fail(`contract binding ${contractBinding.id} is absent from the profile`);
    nonEmptyString(binding.language, `profile binding ${binding.id}.language`);
    if (!QUALIFYING_MATURITY.has(binding.maturity)) {
      fail(`contract binding ${binding.id} has non-qualifying maturity ${binding.maturity}`);
    }
    if (!Array.isArray(binding.execution_flavors) || binding.execution_flavors.length === 0) {
      fail(`profile binding ${binding.id} must declare execution_flavors`);
    }
    binding.execution_flavors.forEach((flavor, index) =>
      nonEmptyString(flavor, `profile binding ${binding.id}.execution_flavors[${index}]`),
    );
    profileImports(binding);
    toolchain(binding, "minimum");
    toolchain(binding, "current");

    nonEmptyString(contractBinding.repository, `contract binding ${binding.id}.repository`);
    const pkg = object(contractBinding.package, `contract binding ${binding.id}.package`);
    nonEmptyString(pkg.ecosystem, `contract binding ${binding.id}.package.ecosystem`);
    nonEmptyString(pkg.coordinate, `contract binding ${binding.id}.package.coordinate`);
    const consumer = object(contractBinding.consumer, `contract binding ${binding.id}.consumer`);
    if (consumer.target !== "core-artifact-consumer-check") {
      fail(`contract binding ${binding.id} must use target core-artifact-consumer-check`);
    }
    if (consumer.isolation !== "clean-temporary-project") {
      fail(`contract binding ${binding.id} must use clean-temporary-project isolation`);
    }
    if (consumer.dependency_source !== "built-artifact-only") {
      fail(`contract binding ${binding.id} must consume only a built artifact`);
    }
    if (!Array.isArray(consumer.toolchain_points)) {
      fail(`contract binding ${binding.id}.consumer.toolchain_points must be an array`);
    }
    sameSet(
      consumer.toolchain_points,
      new Set(["minimum", "current"]),
      `contract binding ${binding.id} toolchain points`,
    );
    if (!Array.isArray(consumer.scenarios)) {
      fail(`contract binding ${binding.id}.consumer.scenarios must be an array`);
    }
    sameSet(consumer.scenarios, REQUIRED_SCENARIOS, `contract binding ${binding.id} scenarios`);
  }

  return {
    profile,
    contract,
    profileById,
    contractById,
  };
}

function markdown(value) {
  return String(value).replaceAll("|", "\\|").replaceAll("\n", " ");
}

export function renderSupportPolicy(profileInput, contractInput) {
  const { profile, contract, profileById } = validateContract(profileInput, contractInput);
  const lines = [
    "# Lazily Core support and artifact consumers",
    "",
    "> Generated by `scripts/core-support.mjs` from `profiles/core-v1.json` and",
    "> `profiles/core-artifact-consumers.json`. Do not edit this file directly.",
    "",
    `Profile: \`${profile.profile_id}\` (${profile.status}), Core API generation ${profile.core_api_generation}.`,
    "",
    "## Compatibility policy",
    "",
    contract.policy.pre_1_0_compatibility,
    "",
    `A deprecated Core API remains compatible for at least ${contract.policy.deprecation.minimum_compatible_cohorts} compatible cohorts and ${contract.policy.deprecation.minimum_days} days. Its profile entry names the replacement and earliest removal generation.`,
    "",
    contract.policy.preview_disclaimer,
    "",
    "## Supported bindings",
    "",
    "| Binding | Maturity | Execution flavors | Minimum toolchain | Current toolchain | Core entry point(s) | Package | Installed consumer |",
    "| --- | --- | --- | --- | --- | --- | --- | --- |",
  ];

  for (const contractBinding of contract.bindings) {
    const binding = profileById.get(contractBinding.id);
    const imports = profileImports(binding).map((entry) => `\`${entry}\``).join("<br>");
    const pkg = `${contractBinding.package.ecosystem}:\`${contractBinding.package.coordinate}\``;
    lines.push(
      `| ${markdown(binding.language)} | ${binding.maturity} | ${markdown(binding.execution_flavors.join(", "))} | ${markdown(toolchain(binding, "minimum"))} | ${markdown(toolchain(binding, "current"))} | ${imports} | ${pkg} | \`make ${contractBinding.consumer.target}\` |`,
    );
  }

  const previewBindings = profile.bindings.filter((binding) => binding.maturity === "preview");
  if (previewBindings.length > 0) {
    lines.push(
      "",
      "## Preview bindings",
      "",
      ...previewBindings.map(
        (binding) =>
          `- ${binding.language} (\`${binding.id}\`) remains **Preview**; it has no qualifying Core artifact consumer and receives no Core Beta credit.`,
      ),
    );
  }

  lines.push(
    "",
    "Each installed consumer runs at the binding's declared minimum and current toolchains, builds the distributable artifact, copies it outside the checkout, creates a clean temporary project, installs only that copied artifact, and exercises all four required scenarios through a declared Core entry point:",
    "",
    ...contract.required_scenarios.map((scenario) => `- \`${scenario.id}\`: ${scenario.description}`),
    "",
    "A source-tree path dependency, an undeclared development dependency, a skipped scenario, or an example that only runs inside the package checkout is not qualifying evidence.",
    "",
  );
  return lines.join("\n");
}

export function runConsumers(profileInput, contractInput, options = {}) {
  const { profileById, contract } = validateContract(profileInput, contractInput);
  const bindingsRoot = resolve(options.bindingsRoot ?? join(ROOT, ".."));
  const requireAll = Boolean(options.requireAll);
  const execute = options.execute ?? ((cwd, target) => {
    const result = spawnSync("make", [target], { cwd, encoding: "utf8", stdio: "inherit" });
    return result.status ?? 1;
  });
  const results = [];

  for (const binding of contract.bindings) {
    const repository = join(bindingsRoot, binding.repository);
    if (!existsSync(repository)) {
      const message = `${binding.id}: sibling checkout ${repository} is absent`;
      if (requireAll) fail(message);
      results.push({ id: binding.id, status: "missing", message });
      continue;
    }
    const makefile = join(repository, "Makefile");
    if (!existsSync(makefile)) {
      const message = `${binding.id}: ${makefile} is absent`;
      if (requireAll) fail(message);
      results.push({ id: binding.id, status: "staged", message });
      continue;
    }
    const target = binding.consumer.target;
    const makefileText = readFileSync(makefile, "utf8");
    const targetPattern = new RegExp(`^${target.replaceAll("-", "\\-")}:`, "m");
    if (!targetPattern.test(makefileText)) {
      const message = `${binding.id}: ${binding.repository}/Makefile has no ${target} target`;
      if (requireAll) fail(message);
      results.push({ id: binding.id, status: "staged", message });
      continue;
    }
    const status = execute(repository, target, profileById.get(binding.id));
    if (status !== 0) fail(`${binding.id}: ${target} exited ${status}`);
    results.push({ id: binding.id, status: "passed", message: `${binding.id}: installed consumer passed` });
  }
  return results;
}

function argumentValue(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) return undefined;
  if (!process.argv[index + 1]) fail(`${name} requires a value`);
  return process.argv[index + 1];
}

function load(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function main() {
  const profilePath = resolve(argumentValue("--profile") ?? DEFAULT_PROFILE);
  const contractPath = resolve(argumentValue("--contract") ?? DEFAULT_CONTRACT);
  const outputPath = resolve(argumentValue("--output") ?? DEFAULT_DOC);
  const profile = load(profilePath);
  const contract = load(contractPath);
  const rendered = renderSupportPolicy(profile, contract);

  if (process.argv.includes("--write")) {
    writeFileSync(outputPath, rendered, "utf8");
  } else {
    if (!existsSync(outputPath)) fail(`${outputPath} is missing; run with --write`);
    const actual = readFileSync(outputPath, "utf8");
    if (actual !== rendered) fail(`${outputPath} is stale; run with --write`);
  }

  if (process.argv.includes("--run-consumers")) {
    const results = runConsumers(profile, contract, {
      bindingsRoot: argumentValue("--bindings-root"),
      requireAll: process.argv.includes("--require-all"),
    });
    for (const result of results) process.stdout.write(`${result.message}\n`);
  }
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`core-support: ${error.message}\n`);
    process.exitCode = 1;
  }
}
