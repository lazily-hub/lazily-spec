#!/usr/bin/env node

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

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
      step = { name: name ? name[1].trim() : "", run: "", activation: {} };
      job.steps.push(step);
      const first = line.match(/^      - (if|continue-on-error):\s*(.*)$/);
      if (first) step.activation[first[1]] = first[2].trim();
      continue;
    }
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

export function check(text, pins) {
  if (pins.dispatch_inputs) {
    assert.deepEqual(
      workflowDispatchInputs(text).sort(),
      [...pins.dispatch_inputs].sort(),
      "workflow_dispatch inputs must exactly pin the manifest and nine bindings",
    );
  }
  const jobs = parseWorkflow(text);
  const job = jobs.get(pins.job);
  assert(job, `missing pinned job ${pins.job}`);

  for (const [key, expected] of Object.entries(pins.activation)) {
    const actual = job.activation[key] ?? "";
    assert.equal(actual, expected, `${pins.job}.${key} expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
  assert.deepEqual(job.matrix, {}, `${pins.job} must not acquire an unpinned matrix`);

  const counts = new Map();
  for (const item of job.steps) counts.set(item.name, (counts.get(item.name) ?? 0) + 1);
  for (const [name, run] of Object.entries(pins.steps)) {
    assert.equal(counts.get(name), 1, `step ${JSON.stringify(name)} must occur exactly once in ${pins.job}`);
    const found = job.steps.find((item) => item.name === name);
    assert.equal(found.run, run, `step ${JSON.stringify(name)} must run ${JSON.stringify(run)}`);
    assert.deepEqual(found.activation, {}, `step ${JSON.stringify(name)} must carry no step-level if/continue-on-error`);
  }

  const coreSteps = job.steps.filter((item) => item.run.startsWith("make core-"));
  assert.deepEqual(
    coreSteps.map((item) => item.name).sort(),
    Object.keys(pins.steps).sort(),
    "every Core make gate in the pinned job must have an exact mapping"
  );
}

function selfTest(text, pins) {
  check(text, pins);
  const first = Object.entries(pins.steps)[0];
  const mutations = [
    text.replace(`run: ${first[1]}`, "run: make coverage-check"),
    text.replace(`  ${pins.job}:\n`, `  ${pins.job}:\n    if: false\n`),
    text.replace(`  ${pins.job}:\n`, `  ${pins.job}:\n    strategy:\n      matrix:\n        node: [24]\n`),
    text.replace(`      - name: ${first[0]}\n`, ""),
    text.replace(`      - name: ${first[0]}\n`, `      - name: ${first[0]}\n        if: false\n`),
    text.replace(`      - name: ${first[0]}\n`, `      - name: ${first[0]}\n        continue-on-error: true\n`),
    text.replace(`      - name: ${first[0]}\n`, `      - if: false\n        name: ${first[0]}\n`)
  ];
  if (pins.dispatch_inputs) {
    mutations.push(
      text.replace("  workflow_dispatch:\n", "  workflow_call:\n"),
      text.replace(`      ${pins.dispatch_inputs[0]}:\n`, ""),
    );
  }
  for (const [index, mutation] of mutations.entries()) {
    assert.notEqual(mutation, text, `mutation ${index + 1} did not alter the workflow`);
    assert.throws(() => check(mutation, pins), `mutation ${index + 1} must fail closed`);
  }
  process.stdout.write(`core-ci-reach: self-test OK — ${mutations.length} mutations rejected\n`);
}

const checks = [
  config,
  { ...config.qualification, workflow: config.qualification.workflow }
];
if (process.argv.includes("--self-test")) {
  for (const pins of checks) selfTest(readFileSync(pins.workflow, "utf8"), pins);
} else {
  for (const pins of checks) check(readFileSync(pins.workflow, "utf8"), pins);
  const count = checks.reduce((sum, pins) => sum + Object.keys(pins.steps).length, 0);
  process.stdout.write(`core-ci-reach: OK — ${count} gates pinned across ${checks.length} workflows\n`);
}
