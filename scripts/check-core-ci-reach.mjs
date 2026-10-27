#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const configPath = new URL("./core-ci-reach.json", import.meta.url);
const config = JSON.parse(readFileSync(configPath, "utf8"));

function parseWorkflow(text) {
  const lines = text.split(/\r?\n/);
  const jobs = new Map();
  let inJobs = false;
  let job = null;
  let step = null;

  for (const line of lines) {
    if (line === "jobs:") {
      inJobs = true;
      continue;
    }
    if (!inJobs) continue;

    const jobMatch = line.match(/^  ([A-Za-z0-9_-]+):\s*$/);
    if (jobMatch) {
      job = { activation: {}, matrix: {}, steps: [] };
      jobs.set(jobMatch[1], job);
      step = null;
      continue;
    }
    if (!job) continue;

    const activation = line.match(/^    (continue-on-error|if|needs|strategy):\s*(.*)$/);
    if (activation) {
      job.activation[activation[1]] = activation[2].trim();
      continue;
    }
    const matrix = line.match(/^        ([A-Za-z0-9_-]+):\s*(.*)$/);
    if (matrix && job.activation.strategy !== undefined) {
      job.matrix[matrix[1]] = matrix[2].trim();
    }
    if (/^      - /.test(line)) {
      const name = line.match(/^      - name:\s*(.+)$/);
      step = { name: name ? name[1].trim() : "", run: "", activation: {}, text: "" };
      job.steps.push(step);
      step.text += `${line}\n`;
      const first = line.match(/^      - (if|continue-on-error):\s*(.*)$/);
      if (first) step.activation[first[1]] = first[2].trim();
      continue;
    }
    // Every raw line of a step, multi-line `run: |` bodies, `with:` and `env:`
    // included, so a pinned fragment can be required wherever it is spelled.
    if (step && /^(        |\s*$)/.test(line)) step.text += `${line}\n`;
    const stepName = line.match(/^        name:\s*(.+)$/);
    if (stepName && step) step.name = stepName[1].trim();
    // Step-level activation (#lzcoreciactivationfixes): a pinned step under
    // `if: false` or `continue-on-error: true` enforces nothing while every
    // job-level pin stays green, so the step's own keys are recorded.
    const stepActivation = line.match(/^        (if|continue-on-error):\s*(.*)$/);
    if (stepActivation && step) {
      const key = stepActivation[1];
      step.activation[key] = key in step.activation ? "!DUP" : stepActivation[2].trim();
    }
    const run = line.match(/^        run:\s*(.+)$/);
    if (run && step) step.run = run[1].trim();
  }
  return jobs;
}

function workflowDispatchInputs(text) {
  const permissions = text.indexOf("\npermissions:");
  assert.notEqual(permissions, -1, "workflow must declare explicit permissions");
  const trigger = text.slice(0, permissions);
  const events = [...trigger.matchAll(/^  ([A-Za-z0-9_-]+):\s*$/gm)].map((match) => match[1]);
  assert.deepEqual(events, ["workflow_dispatch"], "qualification must be dispatch-only");
  assert.match(trigger, /^    inputs:\s*$/m, "workflow_dispatch must declare explicit inputs");
  return [...trigger.matchAll(/^      ([A-Za-z0-9_-]+):\s*$/gm)].map((match) => match[1]);
}

// `make -n` (never `make -p`, which dumps the environment) with the Core
// variables and any parent make's flags removed, so the dry run shows each
// recipe exactly as an unconfigured CI step would expand it.
function dryRun(target, makefile = "Makefile") {
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      ([key]) => !key.startsWith("CORE_") && !["MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES"].includes(key),
    ),
  );
  const result = spawnSync("make", ["--no-print-directory", "-n", "-f", makefile, target], { encoding: "utf8", env });
  assert.equal(result.error, undefined, `make -n ${target} did not run: ${result.error}`);
  assert.equal(result.status, 0, `make -n ${target} failed:\n${result.stderr}`);
  return result.stdout.split("\n").filter((line) => line.trim() !== "");
}

function isSubsequence(needle, haystack) {
  let at = 0;
  for (const line of haystack) if (line === needle[at]) at += 1;
  return at === needle.length;
}

export function check(text, pins, makefile = "Makefile") {
  if (pins.dispatch_inputs) {
    assert.deepEqual(
      workflowDispatchInputs(text).sort(),
      [...pins.dispatch_inputs].sort(),
      "workflow_dispatch inputs must exactly pin the manifest and nine bindings",
    );
  }
  if (pins.permissions !== undefined) {
    const block = text.match(/^permissions:\n((?:  .*\n)*)/m);
    assert(block, "workflow must declare top-level permissions");
    assert.equal(block[1], pins.permissions, "workflow permissions must equal the pinned read-only block");
    assert(!/\$\{\{\s*secrets\./.test(text), "qualification must not reference repository secrets");
  }
  const jobs = parseWorkflow(text);
  const job = jobs.get(pins.job);
  assert(job, `missing pinned job ${pins.job}`);

  for (const [key, expected] of Object.entries(pins.activation)) {
    const actual = job.activation[key] ?? "";
    assert.equal(actual, expected, `${pins.job}.${key} expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
  assert.deepEqual(job.matrix, {}, `${pins.job} must not acquire an unpinned matrix`);

  // Named steps in a pinned order (#lzcorecireachaudit). The `make core-*`
  // pins below say nothing about the job's other steps, and in the Phase 6
  // caller those are what reject a floating pin, check out the exact
  // revisions, and verify the manifest: deleting any of them, or making it
  // conditional, left this guard green at exit 0.
  for (const item of job.steps) assert.notEqual(item.name, "", `${pins.job} must not contain an unnamed step`);
  assert.deepEqual(
    job.steps.map((item) => item.name),
    pins.step_order,
    `${pins.job} steps must be exactly, and in order: ${JSON.stringify(pins.step_order)}`,
  );
  for (const item of job.steps) {
    assert.deepEqual(item.activation, {}, `step ${JSON.stringify(item.name)} must carry no step-level if/continue-on-error`);
  }
  for (const [name, fragments] of Object.entries(pins.step_fragments ?? {})) {
    const found = job.steps.find((item) => item.name === name);
    assert(found, `fragment pin names missing step ${JSON.stringify(name)}`);
    for (const fragment of fragments) {
      assert(found.text.includes(fragment), `step ${JSON.stringify(name)} must contain ${JSON.stringify(fragment)}`);
    }
  }

  const counts = new Map();
  for (const item of job.steps) counts.set(item.name, (counts.get(item.name) ?? 0) + 1);
  for (const [name, run] of Object.entries(pins.steps)) {
    assert.equal(counts.get(name), 1, `step ${JSON.stringify(name)} must occur exactly once in ${pins.job}`);
    const found = job.steps.find((item) => item.name === name);
    assert.equal(found.run, run, `step ${JSON.stringify(name)} must run ${JSON.stringify(run)}`);
  }

  const coreSteps = job.steps.filter((item) => item.run.startsWith("make core-"));
  assert.deepEqual(
    coreSteps.map((item) => item.name).sort(),
    Object.keys(pins.steps).sort(),
    "every Core make gate in the pinned job must have an exact mapping"
  );

  // Make-derived oracle (#lzcorecireachaudit): a step that runs `make <gate>`
  // enforces whatever that recipe does, so each pinned target's dry run must
  // equal its pinned command lines. Hollowing a recipe to `true`, or dropping
  // `--require-all`, left every pin above green.
  for (const run of Object.values(pins.steps)) {
    const target = run.replace(/^make /, "");
    const expected = pins.recipes?.[target];
    assert(expected, `no pinned recipe for ${target}`);
    assert.deepEqual(dryRun(target, makefile), expected, `make -n ${target} must run exactly its pinned commands`);
  }
  if (pins.check_root) {
    const closure = dryRun(pins.check_root, makefile);
    for (const run of Object.values(pins.steps)) {
      const target = run.replace(/^make /, "");
      assert(
        isSubsequence(pins.recipes[target], closure),
        `make -n ${pins.check_root} must run ${target}'s pinned commands`,
      );
    }
  }
}

// Replace inside the pinned job only: step names such as `Checkout` repeat
// across jobs, and a mutation landing in a neighbouring job proves nothing.
function inJob(text, job, before, after) {
  const start = text.indexOf(`\n  ${job}:\n`);
  assert.notEqual(start, -1, `job ${job} not found`);
  const rest = text.slice(start + 1);
  const next = rest.slice(1).search(/^  \S/m);
  const end = next === -1 ? text.length : start + 2 + next;
  const section = text.slice(start, end);
  assert.equal(section.split(before).length - 1, 1, `mutation anchor must occur once in ${job}: ${JSON.stringify(before)}`);
  return text.slice(0, start) + section.replace(before, after) + text.slice(end);
}

function selfTest(text, pins) {
  check(text, pins);
  const first = Object.entries(pins.steps)[0];
  const plain = pins.step_order.find((name) => !(name in pins.steps));
  const mutations = [
    text.replace(`run: ${first[1]}`, "run: make coverage-check"),
    text.replace(`  ${pins.job}:\n`, `  ${pins.job}:\n    if: false\n`),
    text.replace(`  ${pins.job}:\n`, `  ${pins.job}:\n    strategy:\n      matrix:\n        node: [24]\n`),
    text.replace(`      - name: ${first[0]}\n`, ""),
    text.replace(`      - name: ${first[0]}\n`, `      - name: ${first[0]}\n        if: false\n`),
    text.replace(`      - name: ${first[0]}\n`, `      - name: ${first[0]}\n        continue-on-error: true\n`),
    text.replace(`      - name: ${first[0]}\n`, `      - if: false\n        name: ${first[0]}\n`),
    inJob(text, pins.job, `      - name: ${plain}\n`, `      - name: ${plain}\n        if: false\n`),
    inJob(text, pins.job, `      - name: ${plain}\n`, `      - name: ${plain} renamed\n`),
    inJob(text, pins.job, `      - name: ${plain}\n`, `      - name: Unpinned extra step\n        run: "true"\n      - name: ${plain}\n`),
  ];
  for (const [name, fragments] of Object.entries(pins.step_fragments ?? {})) {
    const fragment = fragments[fragments.length - 1];
    const at = text.indexOf(fragment, text.indexOf(`      - name: ${name}\n`));
    mutations.push(text.slice(0, at) + fragment.replace(/\S+$/, "") + text.slice(at + fragment.length));
    mutations.push(text.replace(`      - name: ${name}\n`, `      - name: ${name}\n        continue-on-error: \${{ true }}\n`));
  }
  if (pins.dispatch_inputs) {
    mutations.push(
      text.replace("  workflow_dispatch:\n", "  workflow_call:\n"),
      text.replace(`      ${pins.dispatch_inputs[0]}:\n`, ""),
    );
  }
  if (pins.permissions !== undefined) {
    mutations.push(
      text.replace(`permissions:\n${pins.permissions}`, "permissions:\n  contents: write\n"),
      text.replace("    steps:\n", "    env:\n      TOKEN: ${{ secrets.NPM_TOKEN }}\n    steps:\n"),
    );
  }
  for (const [index, mutation] of mutations.entries()) {
    assert.notEqual(mutation, text, `mutation ${index + 1} did not alter the workflow`);
    assert.throws(() => check(mutation, pins), `mutation ${index + 1} must fail closed`);
  }

  // Recipe mutations run against a scratch copy of the Makefile so the oracle
  // reads exactly the mutated text and the real file is never touched.
  const makefile = readFileSync("Makefile", "utf8");
  const scratch = mkdtempSync(join(tmpdir(), "core-ci-reach-"));
  const recipeMutations = [];
  try {
    for (const run of Object.values(pins.steps)) {
      const target = run.replace(/^make /, "");
      // The target's LAST source recipe line, read from Makefile text so
      // variable-bearing recipes (core-evidence-check) are attacked too.
      const rule = makefile.match(new RegExp(`^${target}:[^\\n]*\\n((?:>[^\\n]*\\n)+)`, "m"));
      if (rule === null) {
        recipeMutations.push([`${target} has a recipe`, makefile.replace(new RegExp(`^${target}:`, "m"), `${target}-moved:`)]);
        continue;
      }
      const lines = rule[1].split("\n").filter((line) => line !== "");
      const last = lines[lines.length - 1];
      const at = rule.index + rule[0].length - rule[1].length + rule[1].lastIndexOf(last);
      const swap = (replacement) => makefile.slice(0, at) + replacement + makefile.slice(at + last.length);
      recipeMutations.push([`${target} hollowed`, swap(">true")]);
      const flag = last.match(/ (--[a-z-]+)$/);
      if (flag) recipeMutations.push([`${target} drops ${flag[1]}`, swap(last.slice(0, -flag[0].length))]);
    }
    if (pins.check_root) {
      const target = Object.values(pins.steps)[0].replace(/^make /, "");
      const root = makefile.match(new RegExp(`^${pins.check_root}:.*$`, "m"))[0];
      recipeMutations.push([`${target} dropped from ${pins.check_root}`, makefile.replace(root, root.replace(` ${target}`, ""))]);
    }
    assert(recipeMutations.length > 0, "self-test generated no recipe mutations");
    for (const [label, mutated] of recipeMutations) {
      assert.notEqual(mutated, makefile, `recipe mutation ${label} did not alter the Makefile`);
      const path = join(scratch, "Makefile");
      writeFileSync(path, mutated);
      assert.throws(() => check(text, pins, path), `recipe mutation ${label} must fail closed`);
    }
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
  process.stdout.write(
    `core-ci-reach: self-test OK — ${mutations.length} workflow and ${recipeMutations.length} recipe mutations rejected\n`,
  );
}

const checks = [
  { ...config, recipes: config.recipes },
  { ...config.qualification, recipes: config.recipes }
];
if (process.argv.includes("--self-test")) {
  for (const pins of checks) selfTest(readFileSync(pins.workflow, "utf8"), pins);
} else {
  for (const pins of checks) check(readFileSync(pins.workflow, "utf8"), pins);
  const count = checks.reduce((sum, pins) => sum + Object.keys(pins.steps).length, 0);
  const steps = checks.reduce((sum, pins) => sum + pins.step_order.length, 0);
  process.stdout.write(
    `core-ci-reach: OK — ${count} gates pinned with make-derived recipes, ${steps} named steps in pinned order across ${checks.length} workflows\n`,
  );
}
