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

function signalingFramesWitness(document, witness) {
  if (!document || !Array.isArray(document.frames)) return false;

  if (witness === "signaling-frames-roster-exclusion") {
    return document.frames.some((frame) => {
      const assertions = frame?.assertions;
      const peer = assertions?.peer;
      const peers = assertions?.peers;
      return (
        assertions?.roster_excludes_self === true &&
        Number.isSafeInteger(peer) &&
        Array.isArray(peers) &&
        peers.length > 0 &&
        !peers.includes(peer) &&
        frame?.wire?.peer === peer &&
        JSON.stringify(frame?.wire?.peers) === JSON.stringify(peers)
      );
    });
  }

  if (witness === "signaling-frames-server-stamped-from") {
    const forwarded = document.frames.filter(
      (frame) => frame?.assertions?.server_stamped_from === true,
    );
    return (
      forwarded.length >= 4 &&
      forwarded.every((frame) => {
        const from = frame.assertions.from;
        return (
          Number.isSafeInteger(from) &&
          frame.direction === "server" &&
          frame.wire?.from === from &&
          !Object.hasOwn(frame.wire ?? {}, "to")
        );
      })
    );
  }

  return false;
}

function blobBackendWitness(document, witness) {
  if (!document || !Array.isArray(document.scenarios)) return false;
  const rejects = document.scenarios.filter((scenario) => scenario.outcome === "reject");
  const rejectForms = new Set(rejects.map((scenario) => scenario.backend_form));
  const rejectCodecs = new Set(rejects.map((scenario) => scenario.codec));
  const accepts = document.scenarios.filter((scenario) => scenario.outcome === "accept");
  const hasAttributionControls = [...rejectCodecs].every((codec) =>
    accepts.some(
      (scenario) =>
        scenario.codec === codec &&
        scenario.backend_form === "shm" &&
        scenario.expect?.decoded_backend === "shm",
    ),
  );

  if (witness === "blob-backend-rejection") {
    return (
      rejects.length === 4 &&
      rejectForms.has("rdma") &&
      rejectForms.has("non_string") &&
      rejectCodecs.has("json") &&
      rejectCodecs.has("msgpack") &&
      hasAttributionControls &&
      rejects.every(
        (scenario) =>
          scenario.expect?.rejected === true &&
          typeof scenario.expect?.wire_input_fnv1a64 === "string",
      )
    );
  }

  if (witness === "blob-backend-decode-error-family") {
    return (
      rejects.length === 4 &&
      hasAttributionControls &&
      rejects.every(
        (scenario) =>
          scenario.expect?.rejection_is_decode_error === true &&
          (scenario.expect?.rejection_kind === "unknown_token" ||
            scenario.expect?.rejection_kind === "non_string"),
      )
    );
  }

  return false;
}

function codecRoundTripWitness(document, witness) {
  if (!document || !Array.isArray(document.scenarios)) return false;
  const sync = document.scenarios.find(
    (scenario) => scenario.variant === "CrdtSync",
  );
  const ops = sync?.wire?.CrdtSync?.ops;

  if (witness === "codec-round-trip-keyless-op") {
    return (
      Array.isArray(ops) &&
      ops.length === 2 &&
      ops[0]?.key === null &&
      typeof ops[1]?.key === "string" &&
      sync.expect?.first_op_key_absent === true &&
      sync.expect?.first_op_node === ops[0]?.node &&
      sync.expect?.second_op_key === ops[1]?.key
    );
  }

  if (witness === "codec-round-trip-source-equality") {
    return (
      document.scenarios.length >= 3 &&
      document.scenarios.every(
        (scenario) =>
          scenario.expect?.round_trip_equals_source === true &&
          scenario.wire !== null &&
          typeof scenario.wire === "object",
      )
    );
  }

  return false;
}

function queueStateWitness(document, witness) {
  if (!document || !Array.isArray(document.steps)) return false;

  if (witness === "queue-state-nonempty") {
    return document.steps.some(
      (step) =>
        step.expected?.is_empty === false &&
        Number.isSafeInteger(step.expected?.len) &&
        step.expected.len > 0 &&
        Array.isArray(step.expected?.elements) &&
        step.expected.elements.length === step.expected.len,
    );
  }

  if (witness === "queue-state-empty-after-drain") {
    return document.steps.some(
      (step) =>
        step.expected?.is_empty === true &&
        step.expected?.len === 0 &&
        step.expected?.closed === true &&
        Array.isArray(step.expected?.elements) &&
        step.expected.elements.length === 0,
    );
  }

  if (witness === "queue-state-unbounded-not-full") {
    return (
      document.initial?.capacity === null &&
      document.steps.some(
        (step) =>
          step.expected?.is_full === false &&
          Number.isSafeInteger(step.expected?.len),
      )
    );
  }

  if (witness === "queue-state-open") {
    return (
      document.initial?.closed === false &&
      document.steps.some(
        (step) =>
          step.expected?.closed === false &&
          Array.isArray(step.expected?.elements),
      )
    );
  }

  return false;
}

function scenarioNamed(document, name) {
  return document?.scenarios?.find(
    (scenario) => scenario.name === name || scenario.id === name,
  );
}

function reliableSyncWitness(document, witness) {
  if (!document || !Array.isArray(document.scenarios)) return false;

  if (witness === "reliable-idempotent-net-effect") {
    return document.scenarios.every((scenario) => {
      const unchanged =
        JSON.stringify(scenario.state_before) ===
        JSON.stringify(scenario.expect?.state_after);
      const stale = scenario.inbound?.every(
        (frame) => frame.frame?.Delta?.base_epoch < scenario.start_last_epoch,
      );
      return scenario.expect?.net_effect_unchanged === true && unchanged && stale;
    });
  }

  if (
    witness === "reliable-multi-epoch-shape" ||
    witness === "reliable-multi-epoch-atomic" ||
    witness === "reliable-multi-epoch-fold"
  ) {
    const span = scenarioNamed(document, "span_3_applies_equal_to_unit_fold");
    const delta = span?.delta;
    const units = span?.equivalent_unit_fold;
    const exactSpan =
      document.assertions?.is_multi_epoch === true &&
      document.assertions?.span === delta?.epoch - delta?.base_epoch &&
      document.assertions?.op_count === delta?.ops?.length &&
      span?.expect?.receiver_last_epoch_after === delta?.epoch;
    if (witness === "reliable-multi-epoch-shape") {
      return exactSpan;
    }
    if (witness === "reliable-multi-epoch-atomic") {
      return exactSpan && span.expect?.atomic_advance === true;
    }
    return (
      exactSpan &&
      span.expect?.fold_equivalent === true &&
      Array.isArray(units) &&
      units.length === delta.ops.length &&
      units[0]?.base_epoch === delta.base_epoch &&
      units.at(-1)?.epoch === delta.epoch
    );
  }

  if (witness === "reliable-resync-convergence") {
    const scenario = scenarioNamed(
      document,
      "drop_suffix_then_resync_converges",
    );
    const snapshot = scenario?.inbound?.find(
      (frame) => frame.frame?.Snapshot,
    )?.frame?.Snapshot;
    return (
      scenario?.inbound?.some((frame) => frame.dropped === true) &&
      snapshot?.epoch === scenario.expect?.final_last_epoch &&
      snapshot?.nodes?.length ===
        Object.keys(scenario.expect?.converged_nodes ?? {}).length &&
      scenario.expect?.equals_no_drop_receiver === true
    );
  }

  if (
    witness === "reliable-orset-present" ||
    witness === "reliable-orset-order"
  ) {
    const scenario = scenarioNamed(
      document,
      "open_set_add_wins_over_stale_remove",
    );
    const removed = new Set(
      scenario?.ops?.flatMap((op) => op.observed_tags ?? []) ?? [],
    );
    const survivingAdd = scenario?.ops?.some(
      (op) => op.op === "add" && !removed.has(op.tag),
    );
    return (
      survivingAdd &&
      (witness === "reliable-orset-present"
        ? scenario.expect?.present === true
        : scenario.expect?.order_independent === true)
    );
  }

  if (witness === "reliable-lww-value") {
    const scenario = scenarioNamed(
      document,
      "lww_alive_highest_stamp_wins",
    );
    const winner = scenario?.ops?.reduce((best, op) =>
      op.stamp.wall_time > best.stamp.wall_time ? op : best,
    );
    return (
      winner?.value === false &&
      scenario.ops.at(-1)?.value === true &&
      scenario.expect?.value === winner.value
    );
  }

  if (witness === "reliable-liveness-cascade") {
    const scenario = scenarioNamed(document, "whole_editor_death_cascades");
    return (
      scenario?.op?.value === false &&
      scenario.expect?.cascade === true &&
      scenario.expect?.live_docs_before?.length >
        scenario.expect?.live_docs_after?.length &&
      scenario.expect?.live_docs_after?.length > 0
    );
  }

  if (witness === "reliable-liveness-per-doc") {
    const scenario = scenarioNamed(
      document,
      "derived_live_doc_aggregate_converges_under_retry",
    );
    const opensByDocument = new Map();
    for (const op of scenario?.ops ?? []) {
      if (op.register_kind !== "orset" || op.op !== "add") continue;
      const [doc, process] = op.key.split("/");
      if (!opensByDocument.has(doc)) opensByDocument.set(doc, new Set());
      opensByDocument.get(doc).add(process);
    }
    const expected = scenario?.expect?.converged_live_docs;
    return (
      scenario?.expect?.per_doc_isolation === true &&
      Array.isArray(expected) &&
      new Set(expected).size === expected.length &&
      [...opensByDocument.values()].some((processes) => processes.size >= 2)
    );
  }

  if (
    witness === "reliable-outbox-exactly-once" ||
    witness === "reliable-outbox-retained" ||
    witness === "reliable-outbox-no-gap"
  ) {
    const crash = scenarioNamed(
      document,
      "crash_between_append_and_ack_replays_on_reconnect",
    );
    const failed = scenarioNamed(
      document,
      "send_failure_retains_frame_for_next_tick",
    );
    if (witness === "reliable-outbox-exactly-once") {
      return (
        crash?.expect?.ops_lost === 0 &&
        crash?.expect?.ops_doubled === 0 &&
        crash?.expect?.exactly_once_effect === true &&
        crash?.expect?.receiver_applies?.length > 1
      );
    }
    const appended = failed?.appended?.map((entry) => entry.epoch);
    const retained = failed?.expect?.retained;
    const resent = failed?.expect?.resent_on_next_tick;
    const exactControls =
      JSON.stringify(appended) === JSON.stringify(retained) &&
      JSON.stringify(appended) === JSON.stringify(resent);
    return (
      exactControls &&
      (witness === "reliable-outbox-retained"
        ? failed.expect?.frame_retained_after_failed_send === true
        : failed.expect?.permanent_gap === false)
    );
  }

  if (witness === "reliable-coalesce-fifo-front") {
    const scenario = scenarioNamed(
      document,
      "non_ack_fills_then_ack_drains_cursor_queue",
    );
    const retained = scenario?.expect?.retained_epochs_after;
    return (
      scenario?.expect?.dequeue_is_fifo_front === true &&
      Array.isArray(retained) &&
      retained.length >= 2 &&
      retained.every(
        (epoch, index) => index === 0 || retained[index - 1] < epoch,
      ) &&
      retained.length === scenario.expect?.retained_after_ack
    );
  }

  if (witness === "reliable-coalesce-state-equivalence") {
    const scenario = scenarioNamed(
      document,
      "state_suffix_collapses_to_snapshot",
    );
    const folded = new Map();
    for (const delta of scenario?.appended ?? []) {
      for (const op of delta.ops ?? []) {
        if (op.CellSet) {
          folded.set(op.CellSet.node, op.CellSet.payload.Inline);
        }
      }
    }
    const snapshot = scenario?.coalesce?.wire?.Snapshot;
    const materialized = new Map(
      snapshot?.nodes?.map((node) => [node.node, node.payload?.Inline]) ?? [],
    );
    return (
      scenario?.expect?.graph_equals_full_run === true &&
      scenario.expect?.effects_observed_identical === true &&
      snapshot?.epoch === scenario.expect?.receiver_last_epoch_after &&
      JSON.stringify([...folded]) === JSON.stringify([...materialized])
    );
  }

  if (
    witness === "reliable-coalesce-fusion-order" ||
    witness === "reliable-coalesce-fusion-multiset" ||
    witness === "reliable-coalesce-fusion-fold"
  ) {
    const scenario = scenarioNamed(
      document,
      "oplog_declines_snapshot_fuses_batch",
    );
    const appended = scenario?.appended?.flatMap((delta) => delta.ops ?? []) ?? [];
    const fused = scenario?.coalesce?.wire?.Delta;
    const fusedOps = fused?.ops ?? [];
    const exactOrder = JSON.stringify(appended) === JSON.stringify(fusedOps);
    const multiset = (ops) =>
      ops.map((op) => JSON.stringify(op)).sort().join("\n");
    if (witness === "reliable-coalesce-fusion-order") {
      return scenario?.expect?.order_preserved === true && exactOrder;
    }
    if (witness === "reliable-coalesce-fusion-multiset") {
      return (
        scenario?.expect?.element_multiset_preserved === true &&
        multiset(appended) === multiset(fusedOps)
      );
    }
    return (
      scenario?.expect?.fold_equivalent === true &&
      exactOrder &&
      fused?.base_epoch === scenario.appended?.[0]?.base_epoch &&
      fused?.epoch === scenario.appended?.at(-1)?.epoch
    );
  }

  if (witness === "reliable-lease-peer-isolation") {
    const scenario = scenarioNamed(
      document,
      "slow_peer_backpressured_not_evicted",
    );
    return (
      scenario?.expect?.A_stalled_by_B === false &&
      scenario.peers?.A?.lease_fresh === true &&
      scenario.peers.A.retained < scenario.peers.B.retained &&
      scenario.expect?.rung === "backpressure"
    );
  }
  if (witness === "reliable-lease-outbox-reclaimed") {
    const scenario = scenarioNamed(
      document,
      "lease_expiry_evicts_and_reclaims",
    );
    return (
      scenario?.expect?.outbox_reclaimed === true &&
      scenario.peers?.B?.lease_fresh === false &&
      scenario.peers.B.retained_before > 0 &&
      scenario.expect?.rung === "evict"
    );
  }
  if (witness === "reliable-lease-adopts-snapshot") {
    const scenario = scenarioNamed(
      document,
      "evicted_peer_rejoins_fresh_full_resync",
    );
    return (
      scenario?.expect?.adopts_snapshot === true &&
      scenario.returning_peer_last_epoch === 0 &&
      scenario.sender_final_epoch === scenario.expect?.receiver_last_epoch_after &&
      scenario.expect?.action === "Apply"
    );
  }
  if (witness === "reliable-lease-minority-write-block") {
    const scenario = scenarioNamed(
      document,
      "distributed_queue_minority_blocks_writes_cap",
    );
    return (
      scenario?.expect?.minority_writes_blocked === true &&
      scenario.queue?.majority_has_quorum === true &&
      scenario.queue?.minority_has_quorum === false &&
      scenario.expect?.queue_convergence_model === "CP"
    );
  }

  return false;
}

function crdtTreeAlgebraWitness(document, witness) {
  if (!document || !Array.isArray(document.scenarios)) return false;
  const merge = document.scenarios.find(
    (scenario) => scenario.id === "merge_is_order_and_duplication_independent",
  );
  const snapshot = document.scenarios.find(
    (scenario) => scenario.id === "empty_frontier_snapshot_preserves_lineage",
  );
  const steady = document.scenarios.find(
    (scenario) => scenario.id === "own_frontier_emits_empty_delta",
  );

  if (witness === "crdt-tree-merge-text") {
    return (
      merge?.expect?.texts_equal === true &&
      merge.merge_orders?.length >= 3 &&
      new Set(merge.merge_orders.map((order) => order.join(","))).size >= 3 &&
      merge.replicas?.length >= 3
    );
  }
  if (witness === "crdt-tree-merge-version-vector") {
    return (
      merge?.expect?.version_vectors_equal === true &&
      merge.merge_orders?.some(
        (order) => new Set(order).size !== order.length,
      ) &&
      merge.replicas?.every((replica) => Number.isSafeInteger(replica.peer))
    );
  }
  if (witness === "crdt-tree-snapshot-text") {
    return (
      snapshot?.snapshot === "delta_since({})" &&
      snapshot?.expect?.restored_text_equal === true &&
      typeof snapshot.seed?.text === "string" &&
      snapshot.seed.text.length > 1
    );
  }
  if (witness === "crdt-tree-snapshot-op-identity") {
    return (
      snapshot?.expect?.op_ids_equal === true &&
      snapshot?.expect?.later_merge_duplicates === 0 &&
      snapshot?.then_concurrent_edit === true &&
      snapshot.restore_peer !== snapshot.seed?.peer
    );
  }
  if (witness === "crdt-tree-empty-delta-no-change") {
    return (
      steady?.frontier === "version_vector()" &&
      Array.isArray(steady?.expect?.delta) &&
      steady.expect.delta.length === 0 &&
      steady.expect?.apply_changed === false
    );
  }

  return false;
}

function distributedWitness(document, witness) {
  if (!document) return false;

  if (witness === "distributed-anti-entropy-order") {
    const scenario = scenarioNamed(document, "out_of_order_converges");
    const stamps = scenario?.ops?.map((op) => op.stamp?.wall_time);
    return (
      scenario?.expect?.order_independent === true &&
      stamps?.length >= 3 &&
      stamps[1] === Math.max(...stamps) &&
      stamps.at(-1) !== Math.max(...stamps) &&
      scenario.expect?.converged?.length > 0
    );
  }

  if (!Array.isArray(document.frames)) return false;
  const mixed = document.frames.find(
    (frame) => frame.label === "crdt_sync_keyed_and_keyless",
  );
  const suppressed = document.frames.find(
    (frame) => frame.label === "crdt_sync_frontier_suppressed",
  );
  const ops = mixed?.wire?.CrdtSync?.ops;

  if (witness === "distributed-frontier-omission") {
    return (
      suppressed?.assertions?.frontier_omitted === true &&
      !Object.hasOwn(suppressed?.wire?.CrdtSync ?? {}, "frontier") &&
      suppressed?.assertions?.op_count ===
        suppressed?.wire?.CrdtSync?.ops?.length
    );
  }
  if (witness === "distributed-keyed-op") {
    return (
      mixed?.assertions?.has_keyed_op === true &&
      mixed?.assertions?.op_count === ops?.length &&
      ops?.some((op) => typeof op.key === "string")
    );
  }
  if (witness === "distributed-keyless-op") {
    return (
      mixed?.assertions?.has_keyless_op === true &&
      mixed?.assertions?.op_count === ops?.length &&
      ops?.some((op) => op.key === null)
    );
  }

  return false;
}

function materializationAndConflictWitness(document, witness) {
  if (!document) return false;

  if (witness === "family-materialization-epoch") {
    return (
      Array.isArray(document.scenarios) &&
      document.scenarios.length >= 3 &&
      document.scenarios.every((scenario) => {
        const keys = scenario.expect?.target_keys;
        return (
          scenario.expect?.target_epoch_bumped === true &&
          Array.isArray(keys) &&
          keys.length === scenario.expect?.target_present_count &&
          Object.keys(scenario.expect?.target_values ?? {}).length ===
            keys.length
        );
      })
    );
  }

  if (witness === "terminal-conflict-sequence") {
    const conflictAt = document.expect?.conflict_after_frame_index;
    const receipts = document.frames
      ?.flatMap((frame) => frame.wire?.CausalReceipts?.receipts ?? []);
    return (
      document.expect?.conflict === true &&
      Number.isSafeInteger(conflictAt) &&
      conflictAt === document.frames?.length - 1 &&
      receipts?.length === 2 &&
      receipts[0]?.causation_id === document.expect?.conflict_command_id &&
      receipts[1]?.causation_id === document.expect?.conflict_command_id &&
      receipts[0]?.outcome !== receipts[1]?.outcome &&
      document.expect?.projection_before_conflict?.commands?.[0]?.terminal ===
        true
    );
  }

  return false;
}

function ipcConformanceWitness(document, witness) {
  if (!document) return false;
  const snapshot = document.wire?.Snapshot;
  const delta = document.wire?.Delta;

  if (witness === "ipc-snapshot-opaque-node") {
    const opaque = snapshot?.nodes?.find((node) => node.state === "Opaque");
    return (
      document.assertions?.has_opaque_node === true &&
      opaque?.node === document.assertions?.opaque_node_id
    );
  }
  if (witness === "ipc-delta-sequential") {
    return (
      document.assertions?.is_sequential === true &&
      Number.isSafeInteger(delta?.base_epoch) &&
      delta.epoch === delta.base_epoch + 1
    );
  }
  if (witness === "ipc-delta-all-op-variants") {
    const expectedKinds = new Set([
      "CellSet",
      "SlotValue",
      "Invalidate",
      "NodeAdd",
      "NodeRemove",
      "EdgeAdd",
      "EdgeRemove",
    ]);
    const actualKinds = new Set(
      delta?.ops?.map((op) => Object.keys(op)[0]) ?? [],
    );
    return (
      document.assertions?.has_all_op_variants === true &&
      actualKinds.size === expectedKinds.size &&
      [...expectedKinds].every((kind) => actualKinds.has(kind))
    );
  }
  if (witness === "ipc-delta-resync-after-10") {
    return (
      document.assertions?.resync_after_epoch_10 === true &&
      delta?.base_epoch > 10 &&
      delta.epoch === delta.base_epoch + 1
    );
  }

  const agentDocTags = new Set([
    "agent_doc.document.baseline",
    "agent_doc.closeout.cycle",
    "agent_doc.queue.head",
    "agent_doc.transport.patch",
  ]);
  if (witness === "ipc-agent-doc-snapshot-vocabulary") {
    const wireTags = snapshot?.nodes?.map((node) => node.type_tag) ?? [];
    return (
      document.assertions?.all_type_tags_in_vocabulary === true &&
      JSON.stringify(wireTags) ===
        JSON.stringify(document.assertions?.type_tags) &&
      wireTags.every((tag) => agentDocTags.has(tag))
    );
  }
  if (witness === "ipc-agent-doc-delta-vocabulary") {
    const wireTags =
      delta?.ops
        ?.map((op) => op.NodeAdd?.type_tag)
        .filter((tag) => tag !== undefined) ?? [];
    return (
      document.assertions?.all_type_tags_in_vocabulary === true &&
      JSON.stringify(wireTags) ===
        JSON.stringify(document.assertions?.added_type_tags) &&
      wireTags.every((tag) => agentDocTags.has(tag))
    );
  }

  return false;
}

function executableWitness(document, witness) {
  return (
    signalingWitness(document, witness) ||
    signalingFramesWitness(document, witness) ||
    blobBackendWitness(document, witness) ||
    codecRoundTripWitness(document, witness) ||
    queueStateWitness(document, witness) ||
    reliableSyncWitness(document, witness) ||
    crdtTreeAlgebraWitness(document, witness) ||
    distributedWitness(document, witness) ||
    materializationAndConflictWitness(document, witness) ||
    ipcConformanceWitness(document, witness)
  );
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
      if (
        /No library-source mutant is registered|remains explicitly unproven/.test(
          proof.reason,
        )
      ) {
        errors.push(`${id}: replace the generic untested boilerplate with a claim-specific limitation`);
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
    if (!executableWitness(documents.get(fixture), proof.witness)) {
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
