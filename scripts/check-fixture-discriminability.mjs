#!/usr/bin/env node

/**
 * Audit the fourth conformance rung: fixture data must discriminate the claim.
 *
 * Exact-value routes are falsifiable by construction: a changed observed value
 * differs from the canonical value. Boolean predicates need more care. A route
 * containing both true and false has a corpus control that kills either
 * constant mutant. Every remaining single-valued boolean route must have an
 * explicit ledger entry: either a recorded library-source mutant killed by a
 * canonical fixture, or an honest `untested` reason.
 *
 * The ledger is fail-closed. New single-valued boolean routes fail this check
 * until they are classified; stale entries fail too.
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURE_ROOT = path.join(ROOT, "conformance");
const LEDGER_PATH = path.join(ROOT, "audits", "fixture-discriminability.json");
const BLOCK_NAMES = new Set(["assertions", "expect", "expected"]);
const INIT = process.argv.includes("--write-initial-ledger");

function jsonFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...jsonFiles(full));
    else if (entry.isFile() && entry.name.endsWith(".json")) out.push(full);
  }
  return out.sort();
}

function pointer(parts) {
  return `/${parts
    .map((part) =>
      typeof part === "number"
        ? "*"
        : String(part).replaceAll("~", "~0").replaceAll("/", "~1"),
    )
    .join("/")}`;
}

function keyPointer(blockPointer, key) {
  const encoded = key.replaceAll("~", "~0").replaceAll("/", "~1");
  return `${blockPointer}/${encoded}`;
}

function* assertionBlocks(value, parts = []) {
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      yield* assertionBlocks(value[index], [...parts, index]);
    }
    return;
  }
  if (value === null || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    const childParts = [...parts, key];
    if (
      BLOCK_NAMES.has(key) &&
      child !== null &&
      typeof child === "object" &&
      !Array.isArray(child)
    ) {
      yield [pointer(childParts), child];
    }
    yield* assertionBlocks(child, childParts);
  }
}

function corpusClaims() {
  const routes = new Map();
  const documents = new Map();
  for (const file of jsonFiles(FIXTURE_ROOT)) {
    const fixture = path.relative(FIXTURE_ROOT, file).split(path.sep).join("/");
    const document = JSON.parse(fs.readFileSync(file, "utf8"));
    documents.set(fixture, document);
    for (const [blockPointer, block] of assertionBlocks(document)) {
      const prose = new Set(Array.isArray(block.prose) ? block.prose : []);
      for (const [key, value] of Object.entries(block)) {
        if (key === "prose" || prose.has(key)) continue;
        const id = `${fixture}#${keyPointer(blockPointer, key)}`;
        const record = routes.get(id) ?? { fixture, pointer: blockPointer, key, values: [] };
        record.values.push(value);
        routes.set(id, record);
      }
    }
  }
  return { routes, documents };
}

function stableValue(value) {
  return JSON.stringify(value, Object.keys(value ?? {}).sort());
}

function initialProof(id, value) {
  const common = {
    status: "mutation-killed",
    binding: "lazily-js",
    command: "node --test test/signaling.test.js",
  };
  if (
    id ===
    "signaling/anti_spoof_session.json#/assertions/roster_sorted_ascending"
  ) {
    return {
      ...common,
      mutation:
        "SignalingRoom.roster comparator `(a, b) => a - b` changed to `(a, b) => b - a`",
      expected_failure:
        "canonical replay fails at conn=c: actual peers [2,1], expected [1,2]",
      witness: "signaling-roster-order",
    };
  }
  if (
    id ===
    "signaling/anti_spoof_session.json#/assertions/roster_excludes_self"
  ) {
    return {
      ...common,
      mutation:
        "SignalingRoom join path stopped filtering the joining peer from `roster()`",
      expected_failure:
        "canonical replay fails because ServerWelcome rejects a roster containing its own peer",
      witness: "signaling-roster-excludes-self",
    };
  }
  if (
    id ===
    "signaling/anti_spoof_session.json#/assertions/forwarded_from_is_server_registered"
  ) {
    return {
      ...common,
      mutation:
        "SignalingRoom forward path stamped `from` with the target peer instead of the registered sender",
      expected_failure:
        "canonical replay fails at conn=a: actual from 2, expected registered sender 1",
      witness: "signaling-forwarded-from-registration",
    };
  }
  return {
    status: "untested",
    reason:
      `No library-source mutant is registered for this single-valued boolean claim ` +
      `(canonical value ${String(value)}); it remains explicitly unproven.`,
  };
}

function writeInitialLedger(singleValueBooleans) {
  const existing = fs.existsSync(LEDGER_PATH)
    ? JSON.parse(fs.readFileSync(LEDGER_PATH, "utf8"))
    : { version: 1, claims: {} };
  const claims = {};
  for (const [id, record] of [...singleValueBooleans].sort(([a], [b]) =>
    a.localeCompare(b),
  )) {
    claims[id] = existing.claims?.[id] ?? initialProof(id, record.values[0]);
  }
  const ledger = {
    version: 1,
    scope:
      "Single-valued boolean routes in assertions/expect/expected blocks. Exact values and boolean routes with both outcomes are audited automatically.",
    claims,
  };
  fs.mkdirSync(path.dirname(LEDGER_PATH), { recursive: true });
  fs.writeFileSync(LEDGER_PATH, `${JSON.stringify(ledger, null, 2)}\n`);
}

function signalingWitness(document, witness) {
  if (!document || !Array.isArray(document.steps)) return false;
  const registry = new Map();
  let rosterOrder = false;
  let rosterExcludesSelf = false;
  let forwardedFromRegistration = false;

  for (const step of document.steps) {
    const input = step?.input;
    const recv = input?.recv;
    if (recv?.type === "join") {
      registry.set(input.conn, recv.peer);
    }
    for (const emit of step?.expect ?? []) {
      const frame = emit?.frame;
      if (frame?.type === "welcome" && Array.isArray(frame.peers)) {
        const ascending = frame.peers.every(
          (peer, index) => index === 0 || frame.peers[index - 1] < peer,
        );
        const differsWhenReversed =
          JSON.stringify([...frame.peers].reverse()) !== JSON.stringify(frame.peers);
        rosterOrder ||= Boolean(
          frame.peers.length >= 2 && ascending && differsWhenReversed,
        );
        rosterExcludesSelf ||= Boolean(
          frame.peers.length > 0 && !frame.peers.includes(frame.peer),
        );
      }
      if (frame && Object.hasOwn(frame, "from")) {
        const registered = registry.get(input?.conn);
        forwardedFromRegistration ||= Boolean(
          registered === frame.from && frame.from !== recv?.to,
        );
      }
    }
  }

  return {
    "signaling-roster-order": rosterOrder,
    "signaling-roster-excludes-self": rosterExcludesSelf,
    "signaling-forwarded-from-registration": forwardedFromRegistration,
  }[witness];
}

function validateLedger(singleValueBooleans, documents) {
  if (!fs.existsSync(LEDGER_PATH)) {
    throw new Error(
      "missing audits/fixture-discriminability.json; run " +
        "node scripts/check-fixture-discriminability.mjs --write-initial-ledger",
    );
  }
  const ledger = JSON.parse(fs.readFileSync(LEDGER_PATH, "utf8"));
  if (ledger.version !== 1 || ledger.claims === null || typeof ledger.claims !== "object") {
    throw new Error("fixture discriminability ledger must have version 1 and a claims object");
  }

  const required = new Set(singleValueBooleans.keys());
  const recorded = new Set(Object.keys(ledger.claims));
  const missing = [...required].filter((id) => !recorded.has(id));
  const stale = [...recorded].filter((id) => !required.has(id));
  const errors = [];
  if (missing.length) errors.push(`missing claim(s):\n  ${missing.join("\n  ")}`);
  if (stale.length) errors.push(`stale claim(s):\n  ${stale.join("\n  ")}`);

  let killed = 0;
  let untested = 0;
  for (const id of [...required].sort()) {
    const proof = ledger.claims[id];
    if (!proof) continue;
    if (proof.status === "untested") {
      untested += 1;
      if (typeof proof.reason !== "string" || proof.reason.trim().length < 24) {
        errors.push(`${id}: untested claim requires a specific reason`);
      }
      continue;
    }
    if (proof.status !== "mutation-killed") {
      errors.push(`${id}: status must be mutation-killed or untested`);
      continue;
    }
    killed += 1;
    for (const field of ["binding", "command", "mutation", "expected_failure", "witness"]) {
      if (typeof proof[field] !== "string" || proof[field].trim() === "") {
        errors.push(`${id}: mutation-killed claim requires ${field}`);
      }
    }
    const fixture = id.slice(0, id.indexOf("#"));
    if (!signalingWitness(documents.get(fixture), proof.witness)) {
      errors.push(
        `${id}: canonical fixture does not satisfy the registered executable witness ` +
          `${proof.witness}; add a checker before recording new mutation evidence`,
      );
    }
  }
  if (errors.length) throw new Error(errors.join("\n\n"));
  return { killed, untested };
}

try {
  const { routes, documents } = corpusClaims();
  const singleValueBooleans = new Map();
  let exactRoutes = 0;
  let controlledBooleans = 0;
  for (const [id, record] of routes) {
    if (record.values.every((value) => typeof value === "boolean")) {
      const values = new Set(record.values.map(stableValue));
      if (values.size === 1) singleValueBooleans.set(id, record);
      else controlledBooleans += 1;
    } else {
      exactRoutes += 1;
    }
  }
  if (INIT) writeInitialLedger(singleValueBooleans);
  const { killed, untested } = validateLedger(singleValueBooleans, documents);
  console.log(
    `fixture discriminability: ${exactRoutes} exact-value route(s), ` +
      `${controlledBooleans} boolean route(s) with both outcomes, ` +
      `${killed} library mutant(s) killed, ${untested} explicitly untested; OK`,
  );
} catch (error) {
  console.error(`fixture discriminability check failed:\n${error.message}`);
  process.exitCode = 1;
}
