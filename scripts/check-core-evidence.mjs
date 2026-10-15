#!/usr/bin/env node
// Validate one or more binding-produced Core qualification reports against the
// canonical profile. Reports are run artifacts, not committed claims: the
// binding runner writes what it actually executed, while the small declaration
// under scripts/ names the skips it intentionally permits. Exact comparison in
// both directions makes an unreported skip and a stale declaration equally red.

import { spawnSync } from "node:child_process";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  statSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");

function fail(message) {
  throw new Error(message);
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    fail(`${path}: ${error.message}`);
  }
}

function isWithin(root, candidate) {
  const rel = relative(root, candidate);
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

function containedPath(root, path, label) {
  if (typeof path !== "string" || path.length === 0 || isAbsolute(path) || path.includes("\0")) {
    fail(`${label} must be a non-empty relative path`);
  }
  const rootReal = realpathSync(root);
  const candidate = resolve(rootReal, path);
  if (!isWithin(rootReal, candidate)) fail(`${label} escapes its evidence root`);

  let ancestor = existsSync(candidate) ? candidate : dirname(candidate);
  while (!existsSync(ancestor)) {
    const parent = dirname(ancestor);
    if (parent === ancestor) fail(`${label} has no existing ancestor`);
    ancestor = parent;
  }
  const ancestorReal = realpathSync(ancestor);
  if (!isWithin(rootReal, ancestorReal)) fail(`${label} traverses a symlink outside its evidence root`);
  return { candidate, rootReal };
}

function splitEvidenceReference(reference, label, requireFragment) {
  if (typeof reference !== "string" || reference.trim().length === 0) {
    fail(`${label} must be a non-empty evidence reference`);
  }
  const hash = reference.indexOf("#");
  const path = hash === -1 ? reference : reference.slice(0, hash);
  let fragment = hash === -1 ? null : reference.slice(hash + 1);
  if (requireFragment && (fragment === null || !fragment.startsWith("/"))) {
    fail(`${label} must identify a JSON value with a #/ JSON Pointer`);
  }
  if (fragment !== null) {
    try {
      fragment = decodeURIComponent(fragment);
    } catch {
      fail(`${label} contains an invalid URI fragment`);
    }
    if (fragment !== "" && !fragment.startsWith("/")) {
      fail(`${label} fragment must be empty or a JSON Pointer`);
    }
  }
  return { path, fragment };
}

function jsonPointer(document, pointer, label) {
  if (pointer === "") return document;
  let value = document;
  for (const encoded of pointer.slice(1).split("/")) {
    const token = encoded.replaceAll("~1", "/").replaceAll("~0", "~");
    if (
      value === null ||
      typeof value !== "object" ||
      !Object.prototype.hasOwnProperty.call(value, token)
    ) {
      fail(`${label} JSON Pointer does not resolve: #${pointer}`);
    }
    value = value[token];
  }
  return value;
}

function validateEvidenceReference(reference, root, label, requireFragment = false) {
  const parsed = splitEvidenceReference(reference, label, requireFragment);
  const { candidate, rootReal } = containedPath(root, parsed.path, label);
  if (!existsSync(candidate)) fail(`${label} does not exist: ${parsed.path}`);
  const metadata = lstatSync(candidate);
  if (metadata.isSymbolicLink() || !metadata.isFile()) {
    fail(`${label} must resolve to a regular file, not a symlink or directory`);
  }
  if (statSync(candidate).size === 0) fail(`${label} resolves to an empty file`);
  if (!isWithin(rootReal, realpathSync(candidate))) {
    fail(`${label} resolves outside its evidence root`);
  }
  if (parsed.fragment === null) return { path: candidate, value: null };

  let document;
  try {
    document = JSON.parse(readFileSync(candidate, "utf8"));
  } catch (error) {
    fail(`${label} fragment requires valid JSON: ${error.message}`);
  }
  const value = jsonPointer(document, parsed.fragment, label);
  if (value === null || value === undefined) fail(`${label} resolves to no evidence value`);
  if (typeof value === "object" && value.status === "untested") {
    fail(`${label} resolves to explicitly untested evidence`);
  }
  return { path: candidate, value };
}

function executeFixturelessProof({
  bindingId,
  claimId,
  command,
  cwd,
  evidenceReference,
  reportsRoot,
  reportPath,
  label,
  timeoutMs,
}) {
  const parsed = splitEvidenceReference(evidenceReference, `${label}.evidence`, false);
  if (parsed.fragment !== null) fail(`${label}.evidence must name the generated artifact itself`);
  if (!parsed.path.startsWith(`${bindingId}/`)) {
    fail(`${label}.evidence must live beneath the ${bindingId}/ report subdirectory`);
  }
  const { candidate } = containedPath(reportsRoot, parsed.path, `${label}.evidence`);
  mkdirSync(dirname(candidate), { recursive: true });
  if (existsSync(candidate)) {
    const metadata = lstatSync(candidate);
    if (metadata.isSymbolicLink() || !metadata.isFile()) {
      fail(`${label}.evidence target must be a regular file`);
    }
    rmSync(candidate);
  }

  const startedMarker = startGenerationMarker(dirname(candidate), `${claimId}.proof`);
  const result = spawnSync(command[0], command.slice(1), {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      LAZILY_CORE_CLAIM_ID: claimId,
      LAZILY_CORE_COMMAND_TIMEOUT_MS: String(timeoutMs),
      LAZILY_CORE_EVIDENCE_PATH: candidate,
      LAZILY_CORE_REPORT_PATH: reportPath,
    },
    maxBuffer: 10 * 1024 * 1024,
    shell: false,
    timeout: timeoutMs,
  });
  const startedMs = finishGenerationMarker(startedMarker);
  if (result.error) {
    if (result.error.code === "ETIMEDOUT") {
      fail(`${label}.command timed out after ${timeoutMs}ms`);
    }
    fail(`${label}.command could not run: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const detail = `${result.stderr ?? ""}${result.stdout ?? ""}`.trim().slice(0, 1000);
    fail(`${label}.command exited ${result.status}${detail ? `: ${detail}` : ""}`);
  }
  if (existsSync(candidate)) requireFresh([candidate], startedMs, `${label}.evidence`);
  validateEvidenceReference(evidenceReference, reportsRoot, `${label}.evidence`);
}

// Freshness is measured against a marker file the verifier writes immediately
// before spawning, on the same filesystem as the outputs, so the comparison
// uses one clock and one timestamp granularity. Deleting outputs before the
// spawn already proves existence-after-spawn means "written by this run";
// the mtime check additionally rejects a command that restores a preserved
// artifact (`cp -p`, `shutil.copy2`, a cache) instead of producing one.
function startGenerationMarker(directory, name) {
  mkdirSync(directory, { recursive: true });
  const marker = join(directory, `.${name}.generation-started`);
  rmSync(marker, { force: true });
  writeFileSync(marker, `${process.pid}\n`);
  return marker;
}

function finishGenerationMarker(marker) {
  const startedMs = statSync(marker).mtimeMs;
  rmSync(marker, { force: true });
  return startedMs;
}

function regularFilesBeneath(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...regularFilesBeneath(path));
    else if (entry.isFile()) files.push(path);
  }
  return files;
}

function requireFresh(paths, startedMs, label) {
  const stale = paths.filter((path) => lstatSync(path).mtimeMs < startedMs);
  if (stale.length > 0) {
    for (const path of stale) rmSync(path, { force: true });
    fail(
      `${label} is not freshly generated: ${stale.length} file(s) predate the command start ` +
        `(${new Date(startedMs).toISOString()}): ${stale.join(", ")}`,
    );
  }
}

function generateBindingReport({
  binding,
  bindingDir,
  command,
  options,
  reportPath,
}) {
  if (command.length === 0 || command.some((part) => part.length === 0)) {
    fail(`binding ${binding.id}: report_command must be a non-empty argv array`);
  }
  mkdirSync(options.reports, { recursive: true });
  const evidenceDir = containedPath(
    options.reports,
    binding.id,
    `binding ${binding.id}: generated evidence directory`,
  ).candidate;
  if (existsSync(evidenceDir)) {
    const metadata = lstatSync(evidenceDir);
    if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
      fail(`binding ${binding.id}: generated evidence target must be a directory`);
    }
    rmSync(evidenceDir, { force: true, recursive: true });
  }
  mkdirSync(evidenceDir, { recursive: true });
  if (existsSync(reportPath)) {
    const metadata = lstatSync(reportPath);
    if (metadata.isSymbolicLink() || !metadata.isFile()) {
      fail(`binding ${binding.id}: report target must be a regular file`);
    }
    rmSync(reportPath);
  }
  const startedMarker = startGenerationMarker(options.reports, binding.id);
  const result = spawnSync(command[0], command.slice(1), {
    cwd: bindingDir,
    encoding: "utf8",
    env: {
      ...process.env,
      LAZILY_CORE_BINDING_ID: binding.id,
      LAZILY_CORE_COMMAND_TIMEOUT_MS: String(options.commandTimeoutMs),
      LAZILY_CORE_PROFILE_PATH: options.profile,
      LAZILY_CORE_REPORT_PATH: reportPath,
      LAZILY_CORE_REPORTS_ROOT: options.reports,
      LAZILY_CORE_SPEC_ROOT: ROOT,
    },
    maxBuffer: 10 * 1024 * 1024,
    shell: false,
    timeout: options.commandTimeoutMs,
  });
  const startedMs = finishGenerationMarker(startedMarker);
  if (result.error) {
    if (result.error.code === "ETIMEDOUT") {
      fail(`binding ${binding.id}: report_command timed out after ${options.commandTimeoutMs}ms`);
    }
    fail(`binding ${binding.id}: report_command could not run: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const detail = `${result.stderr ?? ""}${result.stdout ?? ""}`.trim().slice(0, 1000);
    fail(`binding ${binding.id}: report_command exited ${result.status}${detail ? `: ${detail}` : ""}`);
  }
  if (!existsSync(reportPath)) fail(`binding ${binding.id}: report_command produced no report`);
  const metadata = lstatSync(reportPath);
  if (metadata.isSymbolicLink() || !metadata.isFile() || statSync(reportPath).size === 0) {
    fail(`binding ${binding.id}: report_command must produce a non-empty regular report file`);
  }
  requireFresh(
    [reportPath, ...regularFilesBeneath(evidenceDir)],
    startedMs,
    `binding ${binding.id}: report_command output`,
  );
  return startedMs;
}

function strings(value, label) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    fail(`${label} must be an array of strings`);
  }
  return value;
}

function unique(values, label) {
  const seen = new Set();
  for (const value of values) {
    if (seen.has(value)) fail(`${label} contains duplicate ${JSON.stringify(value)}`);
    seen.add(value);
  }
  return seen;
}

function exactSet(actual, expected, label) {
  const actualSet = unique(actual, label);
  const expectedSet = new Set(expected);
  const missing = [...expectedSet].filter((value) => !actualSet.has(value));
  const extra = [...actualSet].filter((value) => !expectedSet.has(value));
  if (missing.length || extra.length) {
    fail(
      `${label} is not the declared closure` +
        (missing.length ? `; missing: ${missing.join(", ")}` : "") +
        (extra.length ? `; extra: ${extra.join(", ")}` : ""),
    );
  }
}

function skipKey(skip, label) {
  if (skip === null || typeof skip !== "object" || Array.isArray(skip)) {
    fail(`${label} must be an object`);
  }
  if (typeof skip.fixture !== "string" || skip.fixture.length === 0) {
    fail(`${label}.fixture must be a non-empty string`);
  }
  if (typeof skip.scenario !== "string" || skip.scenario.length === 0) {
    fail(`${label}.scenario must be a non-empty string`);
  }
  if (
    skip.execution_flavor !== undefined &&
    (typeof skip.execution_flavor !== "string" || skip.execution_flavor.length === 0)
  ) {
    fail(`${label}.execution_flavor must be a non-empty string when present`);
  }
  if (typeof skip.reason !== "string" || skip.reason.trim().length === 0) {
    fail(`${label}.reason must be a non-empty string`);
  }
  return `${skip.fixture}\0${skip.scenario}\0${skip.execution_flavor ?? "*"}`;
}

function validateAssertionEvidence(reference, context, bindingId, label) {
  const { path } = splitEvidenceReference(reference, label, true);
  let evidence;
  if (path.startsWith(`${bindingId}/`)) {
    evidence = validateEvidenceReference(reference, context.reportsRoot, label, true);
  } else if (path.startsWith("audits/")) {
    evidence = validateEvidenceReference(reference, context.assertionEvidenceRoot, label, true);
  } else {
    fail(`${label} must be generated beneath ${bindingId}/ or reference a canonical audits/ artifact`);
  }
  if (
    evidence.value === null ||
    typeof evidence.value !== "object" ||
    Array.isArray(evidence.value)
  ) {
    fail(`${label} must resolve to a structured discriminability record`);
  }
  const acceptedStatuses = new Set([
    "mutation-killed",
    "consumed-with-family-negative-controls",
  ]);
  if (!acceptedStatuses.has(evidence.value.status)) {
    fail(
      `${label}.status must be mutation-killed or consumed-with-family-negative-controls, ` +
        `got ${JSON.stringify(evidence.value.status)}`,
    );
  }
  return evidence;
}

function validateProfile(profile) {
  if (typeof profile.profile_id !== "string" || profile.profile_id.length === 0) {
    fail("profile_id must be a non-empty string");
  }
  if (!Array.isArray(profile.required_fixtures)) fail("required_fixtures must be an array");
  if (!Array.isArray(profile.bindings)) fail("bindings must be an array");
  if (profile.proof_classes === null || typeof profile.proof_classes !== "object") {
    fail("proof_classes must be an object");
  }
  if (
    profile.fixture_corpus === null ||
    typeof profile.fixture_corpus !== "object" ||
    typeof profile.fixture_corpus.digest !== "string" ||
    !/^[0-9a-f]{64}$/.test(profile.fixture_corpus.digest)
  ) {
    fail("fixture_corpus.digest must be a lowercase SHA-256 hex digest");
  }
  const fixtures = new Map();
  for (const [index, fixture] of profile.required_fixtures.entries()) {
    const label = `required_fixtures[${index}]`;
    if (typeof fixture.path !== "string") fail(`${label}.path must be a string`);
    unique(strings(fixture.scenario_ids, `${label}.scenario_ids`), `${label}.scenario_ids`);
    for (const proof of strings(fixture.proof_classes, `${label}.proof_classes`)) {
      if (!(proof in profile.proof_classes)) fail(`${label} names unknown proof class ${proof}`);
    }
    if (fixtures.has(fixture.path)) fail(`duplicate required fixture ${fixture.path}`);
    fixtures.set(fixture.path, fixture);
  }
  const bindingIds = new Set();
  for (const [index, binding] of profile.bindings.entries()) {
    const label = `bindings[${index}]`;
    if (
      binding === null ||
      typeof binding !== "object" ||
      typeof binding.id !== "string" ||
      !/^[a-z0-9][a-z0-9_-]*$/.test(binding.id)
    ) {
      fail(`${label}.id must be a safe lowercase binding identifier`);
    }
    if (bindingIds.has(binding.id)) fail(`duplicate binding id ${binding.id}`);
    bindingIds.add(binding.id);
    unique(strings(binding.required_fixtures, `${label}.required_fixtures`), `${label}.required_fixtures`);
    if (!Array.isArray(binding.fixtureless_claims)) {
      fail(`${label}.fixtureless_claims must be an array`);
    }
    const claimIds = new Set();
    for (const [claimIndex, claim] of binding.fixtureless_claims.entries()) {
      const claimLabel = `${label}.fixtureless_claims[${claimIndex}]`;
      if (claim === null || typeof claim !== "object" || typeof claim.id !== "string" || claim.id.length === 0) {
        fail(`${claimLabel}.id must be a non-empty string`);
      }
      if (claimIds.has(claim.id)) fail(`${label} has duplicate fixtureless claim ${claim.id}`);
      claimIds.add(claim.id);
      for (const proof of strings(claim.proof_classes, `${claimLabel}.proof_classes`)) {
        if (!(proof in profile.proof_classes)) fail(`${claimLabel} names unknown proof class ${proof}`);
      }
    }
  }
  return fixtures;
}

function validateBinding(
  profile,
  fixtureDefinitions,
  assertionRoutes,
  binding,
  declaration,
  report,
  context,
) {
  const prefix = `binding ${binding.id}`;
  if (
    context === null ||
    typeof context !== "object" ||
    typeof context.bindingDir !== "string" ||
    typeof context.reportPath !== "string" ||
    typeof context.reportsRoot !== "string" ||
    typeof context.assertionEvidenceRoot !== "string"
  ) {
    fail(`${prefix}: verifier context is incomplete`);
  }
  if (declaration.schema_version !== 1) fail(`${prefix}: declaration schema_version must be 1`);
  if (report.schema_version !== 1) fail(`${prefix}: report schema_version must be 1`);
  if (declaration.binding_id !== binding.id || report.binding_id !== binding.id) {
    fail(`${prefix}: binding_id mismatch`);
  }
  if (declaration.profile_id !== profile.profile_id || report.profile_id !== profile.profile_id) {
    fail(`${prefix}: profile_id mismatch`);
  }
  const reportCommand = strings(declaration.report_command, `${prefix}.report_command`);
  if (reportCommand.length === 0 || reportCommand.some((part) => part.length === 0)) {
    fail(`${prefix}.report_command must be a non-empty argv array`);
  }
  if (report.fixture_corpus_digest !== profile.fixture_corpus.digest) {
    fail(`${prefix}: fixture corpus digest does not match the profile`);
  }

  const requiredPaths = strings(binding.required_fixtures, `${prefix}.required_fixtures`);
  exactSet(requiredPaths, fixtureDefinitions.keys(), `${prefix}.required_fixtures`);

  if (!Array.isArray(declaration.runtime_skips)) {
    fail(`${prefix}: declaration.runtime_skips must be an array`);
  }
  if (!Array.isArray(report.runtime_skips)) fail(`${prefix}: report.runtime_skips must be an array`);
  const declaredSkips = declaration.runtime_skips.map((skip, index) =>
    skipKey(skip, `${prefix}: declaration.runtime_skips[${index}]`),
  );
  const observedSkips = report.runtime_skips.map((skip, index) =>
    skipKey(skip, `${prefix}: report.runtime_skips[${index}]`),
  );
  exactSet(observedSkips, declaredSkips, `${prefix}: runtime skips`);
  const executionFlavors = strings(binding.execution_flavors, `${prefix}.execution_flavors`);
  unique(executionFlavors, `${prefix}.execution_flavors`);
  const skipsByFixture = new Map([...fixtureDefinitions.keys()].map((path) => [path, []]));
  for (const skip of declaration.runtime_skips) {
    if (!fixtureDefinitions.has(skip.fixture)) {
      fail(`${prefix}: declared skip names non-Core fixture ${skip.fixture}`);
    }
    const scenarios = fixtureDefinitions.get(skip.fixture).scenario_ids;
    if (skip.scenario !== "*" && !scenarios.includes(skip.scenario)) {
      fail(`${prefix}: declared skip names unknown scenario ${skip.fixture}#${skip.scenario}`);
    }
    if (skip.execution_flavor !== undefined && !executionFlavors.includes(skip.execution_flavor)) {
      fail(`${prefix}: declared skip names unknown execution flavor ${skip.execution_flavor}`);
    }
    skipsByFixture.get(skip.fixture).push(skip);
  }

  if (!Array.isArray(report.fixtures)) fail(`${prefix}: report.fixtures must be an array`);
  exactSet(
    report.fixtures.map((fixture) => fixture.path),
    requiredPaths,
    `${prefix}: observed fixtures`,
  );
  for (const observed of report.fixtures) {
    const required = fixtureDefinitions.get(observed.path);
    const fixtureSkips = skipsByFixture.get(observed.path);
    const scenarioCoveredInAllFlavors = (scenario) => {
      const relevant = fixtureSkips.filter(
        (skip) => skip.scenario === "*" || skip.scenario === scenario,
      );
      if (relevant.some((skip) => skip.execution_flavor === undefined)) return true;
      const skippedFlavors = new Set(relevant.map((skip) => skip.execution_flavor));
      return executionFlavors.length > 0 && executionFlavors.every((flavor) => skippedFlavors.has(flavor));
    };
    const expectedScenarios = required.scenario_ids.filter(
      (scenario) => !scenarioCoveredInAllFlavors(scenario),
    );
    exactSet(
      strings(observed.scenario_ids, `${prefix}: ${observed.path}.scenario_ids`),
      expectedScenarios,
      `${prefix}: ${observed.path} scenarios`,
    );
    exactSet(
      strings(observed.proof_classes, `${prefix}: ${observed.path}.proof_classes`),
      required.proof_classes,
      `${prefix}: ${observed.path} proof classes`,
    );
    const implicitScenarioSkipped =
      required.scenario_ids.length === 0 && scenarioCoveredInAllFlavors("*");
    const expectedStatus =
      implicitScenarioSkipped ||
      (required.scenario_ids.length > 0 && expectedScenarios.length === 0)
        ? "skipped"
        : fixtureSkips.length > 0
          ? "partial"
          : "passed";
    if (observed.status !== expectedStatus) {
      fail(`${prefix}: ${observed.path}.status must be ${expectedStatus}, got ${observed.status}`);
    }
    if (!Array.isArray(observed.assertion_blocks)) {
      fail(`${prefix}: ${observed.path}.assertion_blocks must be an array`);
    }
    const expectedBlocks = assertionRoutes.get(observed.path) ?? [];
    const observedBlockIds = observed.assertion_blocks.map((block) => block.id);
    unique(observedBlockIds, `${prefix}: ${observed.path} assertion blocks`);
    if (expectedStatus !== "skipped") {
      exactSet(observedBlockIds, expectedBlocks, `${prefix}: ${observed.path} assertion blocks`);
    } else {
      const unknown = observedBlockIds.filter((id) => !expectedBlocks.includes(id));
      if (unknown.length > 0) {
        fail(`${prefix}: ${observed.path} assertion blocks contain unknown routes: ${unknown.join(", ")}`);
      }
      if (expectedStatus === "skipped" && observedBlockIds.length > 0) {
        fail(`${prefix}: ${observed.path} skipped fixture cannot claim consumed assertion blocks`);
      }
    }
    for (const block of observed.assertion_blocks) {
      if (block.consumed !== true) {
        fail(`${prefix}: assertion block ${observed.path}#${block.id} was not consumed`);
      }
      if (
        typeof block.discriminability_evidence !== "string" ||
        block.discriminability_evidence.trim().length === 0
      ) {
        fail(`${prefix}: assertion block ${observed.path}#${block.id} lacks discriminability evidence`);
      }
      validateAssertionEvidence(
        block.discriminability_evidence,
        context,
        binding.id,
        `${prefix}: assertion block ${observed.path}#${block.id} discriminability_evidence`,
      );
    }
  }

  if (!Array.isArray(declaration.fixtureless_claims)) {
    fail(`${prefix}: declaration.fixtureless_claims must be an array`);
  }
  if (!Array.isArray(report.fixtureless_claims)) {
    fail(`${prefix}: report.fixtureless_claims must be an array`);
  }
  const expectedClaims = new Map(binding.fixtureless_claims.map((claim) => [claim.id, claim]));
  exactSet(
    declaration.fixtureless_claims.map((claim) => claim.id),
    expectedClaims.keys(),
    `${prefix}: declared fixtureless claims`,
  );
  exactSet(
    report.fixtureless_claims.map((claim) => claim.id),
    expectedClaims.keys(),
    `${prefix}: observed fixtureless claims`,
  );
  const declarations = new Map(declaration.fixtureless_claims.map((claim) => [claim.id, claim]));
  for (const observed of report.fixtureless_claims) {
    const expected = expectedClaims.get(observed.id);
    const declared = declarations.get(observed.id);
    exactSet(
      strings(declared.proof_classes, `${prefix}: ${observed.id} declared proof classes`),
      expected.proof_classes,
      `${prefix}: ${observed.id} declared proof classes`,
    );
    exactSet(
      strings(observed.proof_classes, `${prefix}: ${observed.id} observed proof classes`),
      expected.proof_classes,
      `${prefix}: ${observed.id} observed proof classes`,
    );
    const command = strings(declared.command, `${prefix}: ${observed.id}.command`);
    if (command.length === 0 || command.some((part) => part.length === 0)) {
      fail(`${prefix}: ${observed.id}.command must be a non-empty argv array`);
    }
    if (observed.passed !== true) fail(`${prefix}: fixtureless claim ${observed.id} did not pass`);
    if (typeof observed.evidence !== "string" || observed.evidence.trim().length === 0) {
      fail(`${prefix}: fixtureless claim ${observed.id} has no evidence reference`);
    }
    executeFixturelessProof({
      bindingId: binding.id,
      claimId: observed.id,
      command,
      cwd: context.bindingDir,
      evidenceReference: observed.evidence,
      reportsRoot: dirname(context.reportPath),
      reportPath: context.reportPath,
      label: `${prefix}: fixtureless claim ${observed.id}`,
      timeoutMs: context.commandTimeoutMs,
    });
  }
}

function parseArgs(argv) {
  const options = {
    profile: join(ROOT, "profiles", "core-v1.json"),
    bindingsRoot: join(ROOT, ".."),
    reports: null,
    binding: [],
    requireAll: false,
    selfTest: false,
    commandTimeoutMs: 600_000,
    generateReports: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--profile") options.profile = resolve(argv[++index]);
    else if (arg === "--bindings-root") options.bindingsRoot = resolve(argv[++index]);
    else if (arg === "--reports") options.reports = resolve(argv[++index]);
    else if (arg === "--binding") options.binding.push(argv[++index]);
    else if (arg === "--require-all") options.requireAll = true;
    else if (arg === "--self-test") options.selfTest = true;
    else if (arg === "--generate-reports") options.generateReports = true;
    else if (arg === "--command-timeout-ms") options.commandTimeoutMs = Number(argv[++index]);
    else fail(`unknown argument ${arg}`);
  }
  if (!Number.isSafeInteger(options.commandTimeoutMs) || options.commandTimeoutMs <= 0) {
    fail("--command-timeout-ms must be a positive integer");
  }
  return options;
}

function bindingDirectory(id) {
  return `lazily-${{
    rust: "rs",
    python: "py",
    kotlin: "kt",
    javascript: "js",
    csharp: "cs",
  }[id] ?? id}`;
}

function loadAssertionRoutes(path, fixtureDefinitions) {
  const schema = readJson(path);
  if (!Array.isArray(schema["x-fixture-routes"])) {
    fail(`${path}: x-fixture-routes must be an array`);
  }
  const routes = new Map([...fixtureDefinitions.keys()].map((fixture) => [fixture, []]));
  for (const route of schema["x-fixture-routes"]) {
    if (!routes.has(route.fixture)) continue;
    if (typeof route.pointer !== "string" || route.pointer.length === 0) {
      fail(`${path}: assertion route for ${route.fixture} has no pointer`);
    }
    routes.get(route.fixture).push(route.pointer);
  }
  for (const [fixture, pointers] of routes) unique(pointers, `${fixture} assertion routes`);
  return routes;
}

function selfTest() {
  const sandbox = mkdtempSync(join(tmpdir(), "lazily-core-evidence-"));
  const assertionEvidenceRoot = join(sandbox, "spec");
  const bindingDir = join(sandbox, "lazily-rust");
  const reportsRoot = join(sandbox, "reports");
  const reportPath = join(reportsRoot, "rust.json");
  mkdirSync(join(assertionEvidenceRoot, "audits"), { recursive: true });
  mkdirSync(bindingDir, { recursive: true });
  mkdirSync(reportsRoot, { recursive: true });
  writeFileSync(
    join(assertionEvidenceRoot, "audits", "discriminability.json"),
    `${JSON.stringify({
      claims: {
        a: { status: "mutation-killed", witness: "fixture-a" },
        family: {
          status: "consumed-with-family-negative-controls",
          witness: "expectation-key-family",
        },
        consumedOnly: { status: "consumed", witness: "successful replay only" },
        unproven: { status: "untested", reason: "no negative control" },
      },
    })}\n`,
  );
  const profile = {
    profile_id: "core-v1",
    fixture_corpus: { digest: "a".repeat(64) },
    proof_classes: {
      fixture_replay: { fixture_required: true },
      native_artifact_consumer: { fixture_required: false },
    },
    required_fixtures: [
      { path: "reactive-graph/a.json", scenario_ids: ["a"], proof_classes: ["fixture_replay"] },
    ],
    bindings: [
      {
        id: "rust",
        execution_flavors: ["single_threaded", "async"],
        required_fixtures: ["reactive-graph/a.json"],
        fixtureless_claims: [
          { id: "c_abi_ffi_boundary", scope: "module", proof_classes: ["native_artifact_consumer"] },
        ],
      },
    ],
  };
  const declaration = {
    schema_version: 1,
    profile_id: "core-v1",
    binding_id: "rust",
    report_command: [process.execPath, "-e", "process.exit(0)"],
    runtime_skips: [],
    fixtureless_claims: [
      {
        id: "c_abi_ffi_boundary",
        proof_classes: ["native_artifact_consumer"],
        command: [
          process.execPath,
          "-e",
          'require("node:fs").writeFileSync(process.env.LAZILY_CORE_EVIDENCE_PATH, JSON.stringify({ passed: true }))',
        ],
      },
    ],
  };
  const report = {
    schema_version: 1,
    profile_id: "core-v1",
    binding_id: "rust",
    fixture_corpus_digest: "a".repeat(64),
    fixtures: [
      { path: "reactive-graph/a.json", scenario_ids: ["a"], proof_classes: ["fixture_replay"], status: "passed" },
    ],
    runtime_skips: [],
    fixtureless_claims: [
      {
        id: "c_abi_ffi_boundary",
        proof_classes: ["native_artifact_consumer"],
        passed: true,
        evidence: "rust/native-consumer.json",
      },
    ],
  };
  const fixtureDefinitions = validateProfile(profile);
  const assertionRoutes = new Map([["reactive-graph/a.json", ["/steps/*/expect"]]]);
  report.fixtures[0].assertion_blocks = [
    {
      id: "/steps/*/expect",
      consumed: true,
      discriminability_evidence: "rust/assertion-evidence.json#/claims/a",
    },
  ];
  const context = {
    assertionEvidenceRoot,
    bindingDir,
    commandTimeoutMs: 10_000,
    reportPath,
    reportsRoot,
  };
  try {
    const generatedReportPath = join(reportsRoot, "generated.json");
    const generationOptions = {
      commandTimeoutMs: 10_000,
      profile: join(sandbox, "profile.json"),
      reports: reportsRoot,
    };
    generateBindingReport({
      binding: profile.bindings[0],
      bindingDir,
      command: [
        process.execPath,
        "-e",
        'require("node:fs").writeFileSync(process.env.LAZILY_CORE_REPORT_PATH, "{}")',
      ],
      options: generationOptions,
      reportPath: generatedReportPath,
    });
    let missingGeneratedReportRejected = false;
    try {
      generateBindingReport({
        binding: profile.bindings[0],
        bindingDir,
        command: [process.execPath, "-e", "process.exit(0)"],
        options: generationOptions,
        reportPath: generatedReportPath,
      });
    } catch {
      missingGeneratedReportRejected = true;
    }
    if (!missingGeneratedReportRejected) fail("self-test did not reject missing generated report");
    if (existsSync(generatedReportPath)) {
      fail("self-test accepted a stale report after report_command produced no report");
    }

    const staleEvidencePath = join(reportsRoot, "rust", "stale-before-timeout.json");
    mkdirSync(dirname(staleEvidencePath), { recursive: true });
    writeFileSync(staleEvidencePath, "stale evidence\n");
    writeFileSync(generatedReportPath, "stale report\n");
    let timeoutRejected = false;
    try {
      generateBindingReport({
        binding: profile.bindings[0],
        bindingDir,
        command: [process.execPath, "-e", "setTimeout(() => {}, 10_000)"],
        options: { ...generationOptions, commandTimeoutMs: 25 },
        reportPath: generatedReportPath,
      });
    } catch (error) {
      timeoutRejected = error.message.includes("report_command timed out after 25ms");
    }
    if (!timeoutRejected) fail("self-test did not reject a timed-out report_command deterministically");
    if (existsSync(generatedReportPath) || existsSync(staleEvidencePath)) {
      fail("self-test retained stale report/evidence after report_command timeout");
    }

    // The per-command budget reaches the generator so it can bound its own
    // children below the verifier's blind timeout (#lzcoreevidencedarttimeout).
    generateBindingReport({
      binding: profile.bindings[0],
      bindingDir,
      command: [
        process.execPath,
        "-e",
        'if (process.env.LAZILY_CORE_COMMAND_TIMEOUT_MS !== "10000") process.exit(3); require("node:fs").writeFileSync(process.env.LAZILY_CORE_REPORT_PATH, "{}")',
      ],
      options: generationOptions,
      reportPath: generatedReportPath,
    });

    // Freshness: a command that restores a preserved artifact instead of
    // producing one is rejected, and the stale artifact does not survive to be
    // validated by a later non-generating run. Timestamps are pinned far in the
    // past, so the outcome does not depend on scheduling or clock resolution.
    const ancient = new Date("2000-01-01T00:00:00Z");
    const backdate = (target) =>
      `const fs = require("node:fs"); fs.writeFileSync(${target}, "{}"); ` +
      `fs.utimesSync(${target}, new Date(${ancient.getTime()}), new Date(${ancient.getTime()}));`;
    const freshReport = 'require("node:fs").writeFileSync(process.env.LAZILY_CORE_REPORT_PATH, "{}");';
    const staleCases = [
      {
        name: "backdated report",
        script: backdate("process.env.LAZILY_CORE_REPORT_PATH"),
        stale: generatedReportPath,
      },
      {
        name: "backdated evidence",
        script: `${freshReport} ${backdate(
          'require("node:path").join(process.env.LAZILY_CORE_REPORTS_ROOT, "rust", "copied.json")',
        )}`,
        stale: join(reportsRoot, "rust", "copied.json"),
      },
    ];
    for (const staleCase of staleCases) {
      let staleRejected = false;
      try {
        generateBindingReport({
          binding: profile.bindings[0],
          bindingDir,
          command: [process.execPath, "-e", staleCase.script],
          options: generationOptions,
          reportPath: generatedReportPath,
        });
      } catch (error) {
        staleRejected = error.message.includes("is not freshly generated");
      }
      if (!staleRejected) fail(`self-test accepted a ${staleCase.name}`);
      if (existsSync(staleCase.stale)) fail(`self-test retained a rejected ${staleCase.name}`);
    }
    if (existsSync(join(reportsRoot, ".rust.generation-started"))) {
      fail("self-test left a generation marker behind");
    }

    const proofEvidence = join(reportsRoot, "rust", "fresh-proof.json");
    let staleProofRejected = false;
    try {
      executeFixturelessProof({
        bindingId: "rust",
        claimId: "c_abi_ffi_boundary",
        command: [process.execPath, "-e", backdate("process.env.LAZILY_CORE_EVIDENCE_PATH")],
        cwd: bindingDir,
        evidenceReference: "rust/fresh-proof.json",
        reportsRoot,
        reportPath,
        label: "self-test proof",
        timeoutMs: 10_000,
      });
    } catch (error) {
      staleProofRejected = error.message.includes("is not freshly generated");
    }
    if (!staleProofRejected) fail("self-test accepted backdated fixtureless proof evidence");
    if (existsSync(proofEvidence)) fail("self-test retained backdated fixtureless proof evidence");
    writeFileSync(
      join(reportsRoot, "rust", "assertion-evidence.json"),
      `${JSON.stringify({ claims: { a: { status: "mutation-killed", witness: "fixture-a" } } })}\n`,
    );

    validateBinding(
      profile,
      fixtureDefinitions,
      assertionRoutes,
      profile.bindings[0],
      declaration,
      report,
      context,
    );
    const familyControl = structuredClone(report);
    familyControl.fixtures[0].assertion_blocks[0].discriminability_evidence =
      "audits/discriminability.json#/claims/family";
    validateBinding(
      profile,
      fixtureDefinitions,
      assertionRoutes,
      profile.bindings[0],
      declaration,
      familyControl,
      context,
    );
    const partial = structuredClone({ declaration, report });
    partial.declaration.runtime_skips = [
      {
        fixture: "reactive-graph/a.json",
        scenario: "*",
        execution_flavor: "async",
        reason: "not supported by the async runner",
      },
    ];
    partial.report.runtime_skips = structuredClone(partial.declaration.runtime_skips);
    partial.report.fixtures[0].status = "partial";
    validateBinding(
      profile,
      fixtureDefinitions,
      assertionRoutes,
      profile.bindings[0],
      partial.declaration,
      partial.report,
      context,
    );
    const skippedFixture = structuredClone({ declaration, report });
    skippedFixture.declaration.runtime_skips = [
      {
        fixture: "reactive-graph/a.json",
        scenario: "*",
        reason: "runner has no implementation",
      },
    ];
    skippedFixture.report.runtime_skips = structuredClone(skippedFixture.declaration.runtime_skips);
    skippedFixture.report.fixtures[0].scenario_ids = [];
    skippedFixture.report.fixtures[0].assertion_blocks = [];
    skippedFixture.report.fixtures[0].status = "skipped";
    validateBinding(
      profile,
      fixtureDefinitions,
      assertionRoutes,
      profile.bindings[0],
      skippedFixture.declaration,
      skippedFixture.report,
      context,
    );
    const probes = [
      ["unreported runtime skip", (copy) => copy.report.runtime_skips.push({ fixture: "reactive-graph/a.json", scenario: "a", reason: "hidden" })],
      ["stale declared skip", (copy) => copy.declaration.runtime_skips.push({ fixture: "reactive-graph/a.json", scenario: "a", reason: "stale" })],
      ["uncovered fixture", (copy) => { copy.report.fixtures = []; }],
      ["unbound assertion block", (copy) => { copy.report.fixtures[0].assertion_blocks = []; }],
      ["unbound assertion block in partial fixture", (copy) => {
        const skip = {
          fixture: "reactive-graph/a.json",
          scenario: "*",
          execution_flavor: "async",
          reason: "not supported by the async runner",
        };
        copy.declaration.runtime_skips = [skip];
        copy.report.runtime_skips = [structuredClone(skip)];
        copy.report.fixtures[0].status = "partial";
        copy.report.fixtures[0].assertion_blocks = [];
      }],
      ["missing fixtureless proof", (copy) => { copy.report.fixtureless_claims = []; }],
      ["missing assertion evidence", (copy) => { copy.report.fixtures[0].assertion_blocks[0].discriminability_evidence = "audits/missing.json#/claim"; }],
      ["explicitly untested assertion evidence", (copy) => { copy.report.fixtures[0].assertion_blocks[0].discriminability_evidence = "audits/discriminability.json#/claims/unproven"; }],
      ["consumption-only assertion evidence", (copy) => { copy.report.fixtures[0].assertion_blocks[0].discriminability_evidence = "audits/discriminability.json#/claims/consumedOnly"; }],
      ["non-evidence repository file", (copy) => { copy.report.fixtures[0].assertion_blocks[0].discriminability_evidence = "conformance/reactive-graph/a.json#/steps/0/expect"; }],
      ["escaping fixtureless evidence", (copy) => { copy.report.fixtureless_claims[0].evidence = "../escaped.json"; }],
      ["cross-binding fixtureless evidence", (copy) => { copy.report.fixtureless_claims[0].evidence = "other/escaped.json"; }],
      ["fixtureless command failure", (copy) => { copy.declaration.fixtureless_claims[0].command = [process.execPath, "-e", "process.exit(7)"]; }],
      ["fixtureless command produced no evidence", (copy) => { copy.declaration.fixtureless_claims[0].command = [process.execPath, "-e", ""]; }],
    ];
    for (const [name, mutate] of probes) {
      const copy = structuredClone({ declaration, report });
      mutate(copy);
      let rejected = false;
      try {
        validateBinding(
          profile,
          fixtureDefinitions,
          assertionRoutes,
          profile.bindings[0],
          copy.declaration,
          copy.report,
          context,
        );
      } catch {
        rejected = true;
      }
      if (!rejected) fail(`self-test did not reject ${name}`);
    }
    console.log(`core evidence self-test OK (${probes.length + 2} negative probes)`);
  } finally {
    rmSync(sandbox, { force: true, recursive: true });
  }
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.selfTest) return selfTest();
  if (options.reports === null) fail("--reports <directory> is required");
  const profile = readJson(options.profile);
  const fixtureDefinitions = validateProfile(profile);
  const assertionRoutes = loadAssertionRoutes(
    join(ROOT, "schemas", "assertion-blocks.json"),
    fixtureDefinitions,
  );
  const requested = new Set(options.binding);
  const selected = profile.bindings.filter((binding) => requested.size === 0 || requested.has(binding.id));
  if (requested.size > 0 && selected.length !== requested.size) {
    fail(`unknown binding id(s): ${[...requested].filter((id) => !selected.some((b) => b.id === id)).join(", ")}`);
  }
  const skipped = [];
  for (const binding of selected) {
    const declarationPath = join(
      options.bindingsRoot,
      bindingDirectory(binding.id),
      "scripts",
      "core-conformance.json",
    );
    const reportPath = join(options.reports, `${binding.id}.json`);
    if (!existsSync(declarationPath)) {
      skipped.push(binding.id);
      continue;
    }
    const declaration = readJson(declarationPath);
    if (declaration.binding_id !== binding.id || declaration.profile_id !== profile.profile_id) {
      fail(`binding ${binding.id}: declaration identity does not match the selected profile binding`);
    }
    const reportCommand = strings(declaration.report_command, `binding ${binding.id}.report_command`);
    let generatedAtMs = null;
    if (options.generateReports) {
      generatedAtMs = generateBindingReport({
        binding,
        bindingDir: dirname(dirname(declarationPath)),
        command: reportCommand,
        options,
        reportPath,
      });
    }
    if (!existsSync(reportPath)) {
      skipped.push(binding.id);
      continue;
    }
    validateBinding(
      profile,
      fixtureDefinitions,
      assertionRoutes,
      binding,
      declaration,
      readJson(reportPath),
      {
        assertionEvidenceRoot: ROOT,
        bindingDir: dirname(dirname(declarationPath)),
        commandTimeoutMs: options.commandTimeoutMs,
        reportPath,
        reportsRoot: options.reports,
      },
    );
    const reportDate = new Date(statSync(reportPath).mtimeMs).toISOString();
    console.log(
      generatedAtMs === null
        ? `core evidence: ${binding.id} OK (report dated ${reportDate}; not regenerated)`
        : `core evidence: ${binding.id} OK (report dated ${reportDate}; generated by a command started ${new Date(generatedAtMs).toISOString()})`,
    );
  }
  if (skipped.length > 0) {
    const message = `missing declaration/report for: ${skipped.join(", ")}`;
    if (options.requireAll) fail(message);
    console.log(`core evidence: SKIP ${message}`);
  }
}

try {
  main();
} catch (error) {
  console.error(`core evidence FAILED: ${error.message}`);
  process.exit(1);
}
