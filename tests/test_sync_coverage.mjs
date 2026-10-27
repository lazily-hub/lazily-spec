// Regression suite for scripts/sync-coverage.mjs --require-all (#lzspecreadmeci).
//
// Every sibling binding README carries a roll-up rendered from coverage.json.
// Spec CI used to run `--check` with no sibling checked out, so every README
// target was skipped and the run passed having compared two files; all eleven
// READMEs drifted a row behind with CI green (#lzcoverageresync). These tests
// drive the real script against an isolated sibling layout and prove the three
// outcomes CI depends on: green when every README matches, red when one is
// stale, red when one is missing. A last test pins that ci.yml actually fetches
// every sibling the script names and runs the --require-all gate after it.

import assert from "node:assert/strict";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, test } from "node:test";
import { spawnSync } from "node:child_process";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, "..");
const SCRIPT_SOURCE = readFileSync(join(REPO, "scripts", "sync-coverage.mjs"), "utf8");
// Derived from the script, not restated, so a new sibling target is covered here
// (and by the workflow pin below) the moment it is added there.
const SIBLINGS = [...SCRIPT_SOURCE.matchAll(/join\(ROOT, "\.\.", "(lazily-[a-z]+)", "README\.md"\)/g)].map(
  (m) => m[1],
);
const MARKERS = "<!-- coverage-table:start -->\n<!-- coverage-table:end -->\n";
const scratch = [];

afterEach(() => {
  while (scratch.length > 0) rmSync(scratch.pop(), { recursive: true, force: true });
});

function setup() {
  const suite = mkdtempSync(join(tmpdir(), "lazily-sync-coverage-"));
  scratch.push(suite);
  const spec = join(suite, "lazily-spec");
  mkdirSync(join(spec, "scripts"), { recursive: true });
  mkdirSync(join(spec, "docs"), { recursive: true });
  copyFileSync(join(REPO, "scripts", "sync-coverage.mjs"), join(spec, "scripts", "sync-coverage.mjs"));
  copyFileSync(join(REPO, "coverage.json"), join(spec, "coverage.json"));
  copyFileSync(join(REPO, "README.md"), join(spec, "README.md"));
  copyFileSync(join(REPO, "docs", "coverage.md"), join(spec, "docs", "coverage.md"));
  for (const sibling of SIBLINGS) {
    mkdirSync(join(suite, sibling), { recursive: true });
    writeFileSync(join(suite, sibling, "README.md"), `# ${sibling}\n\n${MARKERS}`);
  }
  // Render every table with the script's own write mode, so the in-sync
  // baseline is whatever the script produces rather than a copy of it here.
  const write = run(spec);
  assert.equal(write.status, 0, write.stderr);
  return { suite, spec };
}

function run(spec, ...args) {
  return spawnSync(process.execPath, [join(spec, "scripts", "sync-coverage.mjs"), ...args], {
    encoding: "utf8",
  });
}

test("the script names all eleven sibling README targets", () => {
  assert.deepEqual(SIBLINGS, [
    "lazily-rs",
    "lazily-py",
    "lazily-kt",
    "lazily-js",
    "lazily-dart",
    "lazily-zig",
    "lazily-go",
    "lazily-cpp",
    "lazily-cs",
    "lazily-gd",
    "lazily-formal",
  ]);
});

test("--require-all passes only after comparing every target", () => {
  const { spec } = setup();
  const result = run(spec, "--check", "--require-all");
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, new RegExp(`✓ ${SIBLINGS.length + 2} of ${SIBLINGS.length + 2} coverage table target`));
});

test("a stale sibling README fails --check", () => {
  const { suite, spec } = setup();
  const readme = join(suite, "lazily-gd", "README.md");
  const current = readFileSync(readme, "utf8");
  const stale = current.replace(/A family cell summarises \d+ feature rows/, "A family cell summarises 1 feature rows");
  assert.notEqual(stale, current, "perturbation must change the README");
  writeFileSync(readme, stale);
  for (const args of [["--check"], ["--check", "--require-all"]]) {
    const result = run(spec, ...args);
    assert.equal(result.status, 1, `${args.join(" ")} must fail on a stale README`);
    assert.match(result.stderr, /lazily-gd\/README\.md: coverage table is out of sync/);
  }
});

test("a sibling README without markers fails --check", () => {
  const { suite, spec } = setup();
  writeFileSync(join(suite, "lazily-formal", "README.md"), "# lazily-formal\n");
  const result = run(spec, "--check", "--require-all");
  assert.equal(result.status, 1);
  assert.match(result.stderr, /lazily-formal\/README\.md: missing coverage-table markers/);
});

test("a missing sibling is skipped by default and fails under --require-all", () => {
  const { suite, spec } = setup();
  rmSync(join(suite, "lazily-formal"), { recursive: true, force: true });

  const lenient = run(spec, "--check");
  assert.equal(lenient.status, 0, lenient.stderr);
  assert.match(lenient.stdout, /1 absent target\(s\) skipped/, "a skip must be visible, never silent");

  const strict = run(spec, "--check", "--require-all");
  assert.equal(strict.status, 1, "--require-all must not pass vacuously over a missing sibling");
  assert.match(strict.stderr, /lazily-formal\/README\.md: missing/);
  assert.match(strict.stderr, /1 of 13 target\(s\) missing/);
});

test("spec CI fetches every sibling README and runs the --require-all gate after it", () => {
  const makefile = readFileSync(join(REPO, "Makefile"), "utf8");
  const recipe = makefile.match(/^coverage-check-all:\n((?:>.*\n)+)/m);
  assert.ok(recipe, "Makefile must define coverage-check-all");
  assert.match(recipe[1], /^>node scripts\/sync-coverage\.mjs --check --require-all$/m);

  const workflow = readFileSync(join(REPO, ".github", "workflows", "ci.yml"), "utf8");
  const job = workflow.match(/^  coverage:\n((?:(?: {4}.*)?\n)+)/m);
  assert.ok(job, "ci.yml must define the coverage job");
  const body = job[1];
  const loop = body.match(/for repo in ([a-z ]+); do/);
  assert.ok(loop, "coverage job must clone the sibling ledgers in a loop");
  const looped = new Set(loop[1].trim().split(/\s+/).map((r) => `lazily-${r}`));
  for (const sibling of SIBLINGS) {
    assert.ok(
      looped.has(sibling) || body.includes(`https://github.com/lazily-hub/${sibling}.git`),
      `coverage job never clones ${sibling}, so --require-all would fail on it`,
    );
  }
  const gate = body.indexOf("make coverage-check-all");
  assert.notEqual(gate, -1, "coverage job must run make coverage-check-all");
  assert.ok(gate > body.indexOf("for repo in"), "the gate must run after the siblings are cloned");
  const step = body.slice(body.lastIndexOf("      - ", gate), gate);
  assert.doesNotMatch(step, /^        (if|continue-on-error):/m, "the gate step must be unconditional");
});
