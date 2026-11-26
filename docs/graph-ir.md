# Graph IR

The **graph IR** is the compute document for a lazily reactive graph. A host
turns that document into an inspectable expression tree, then lowers the tree
onto one concrete target: a reactive context of sources, computeds, and
effects. The same document can emit one textual form, `canonical-source`.
Application code holds the document, not a pile of host closures.

This is **compute, not protocol**. It is not a
[`Snapshot`](protocol.md) and not a [`Delta`](protocol.md). Those messages are
a value-and-edge image. They do not carry formulas, and a receiver MUST NOT
look for this document inside them. Only resolved cell values cross IPC/FFI,
as ordinary payloads. The behavior those values follow is the
[Reactive Graph](reactive-graph.md).

State-chart guards are a different form. `schemas/statechart.json` accepts a
host guard name and rejects a chart `{"expr": ...}` string. This document's
`expr` is an object tree, not that string, and it does not live in a chart.

The normative JSON shape is [`schemas/graph-ir.json`](../schemas/graph-ir.json)
(JSON Schema, Draft 2020-12). `ir` is `"1"`. Examples live in
[`examples/graph-ir/`](../examples/graph-ir/). The reference interpreter is
lazily-rs behind the `graph-ir` feature. Other bindings are not required to
lower the document until they take that work on; a schema test does not by
itself add a conformance-corpus obligation.

## Pipeline

1. **Parse** a `kind: "graph"` document into a tree of nodes, expressions, and
   statements. Unknown fields fail. A host closure (`{"fn": ...}` or a string
   formula) is not an expression.
2. **Check** static edges. Every `ref` names a source or a computed. Every
   `set` / `merge` target names a source. The read-edge graph is acyclic.
   `examples/graph-ir/cycle.json` is schema-valid and semantically rejected:
   the schema does not encode the cycle rule.
3. **Lower** onto a context. Sources first, then computeds, then eager
   materialization, then effects. Eager is the declarative flag from the
   reactive graph, not a separate node kind.
4. **Edit** with a `kind: "edit"` document while the runtime still holds the
   definition. Ops run in order. A failed op does not apply, and later ops in
   that document do not run. Earlier ops stay.
5. **Emit** `canonical-source` from the document the runtime holds. Emission
   does not read live cell values. Parsing that text back is not required.

`init` is the definition of a source. A later host write changes the live
value only. It does not change `init`, the static edges, or the emitted text.

## Document

```json
{
  "kind": "graph",
  "ir": "1",
  "id": "counter",
  "nodes": []
}
```

`id` is optional and names the graph in `canonical-source`. Node ids match
`^[A-Za-z_][A-Za-z0-9_]*$` and are at most 128 characters. Node order in
`nodes` is declaration order. Lowering still creates every source before any
computed, so a computed may read a source that appears later in the array.
An **edit** `add` is different: it may read only ids that already exist when
that op runs.

### Source

```json
{"id": "count", "kind": "source", "init": 1, "policy": "keep-latest"}
```

`init` is any JSON value. `policy` defaults to `keep-latest` when omitted.

| Policy | Init | `merge` |
|---|---|---|
| `keep-latest` | any JSON | replace with the op |
| `sum` | number | add the op |
| `max` | number | keep the greater operand; ties keep the current value |
| `min` | number | keep the lesser operand; ties keep the current value |
| `and` | boolean | boolean and |
| `or` | boolean | boolean or |

`set` always replaces, including on `sum`. `merge` folds under the policy.
Numbers are JSON numbers. Both integers use integer arithmetic; if either side
is not an integer, the op uses `f64`. Integer overflow and non-finite results
are faults. `div` always uses `f64`. A finite result that is an integer in
range is canonicalized back to an integer JSON number.

### Computed

```json
{"id": "doubled", "kind": "computed", "eager": true, "expr": {"op": "mul", "args": [{"ref": "count"}, {"lit": 2}]}}
```

`eager` defaults to false. Omitted on `replace`, the new computed is lazy; it
does not keep the previous flag. The equality guard of a computed is the
reactive-graph guard. There is no unguarded mode in this IR.

### Effect

```json
{"id": "log", "kind": "effect", "body": {"do": "eval", "expr": {"ref": "doubled"}}}
```

An effect is a sink. Nothing may `ref` it. Its body is a statement tree, not a
host function. The reference interpreter records each successful run as
`(id, result)` and does not erase that trace when the effect is removed.

| Statement | Result | Edges |
|---|---|---|
| `{"do":"eval","expr":Expr}` | the expression's value | reads in `expr` |
| `{"do":"set","target":Id,"expr":Expr}` | the source's value after replace | reads in `expr`; write to `target` |
| `{"do":"merge","target":Id,"expr":Expr}` | the source's value after the fold | reads in `expr`; write to `target` |
| `{"do":"seq","steps":[Stmt,...]}` | a JSON array of step results | union of the steps |
| `{"do":"when","cond":Expr,"then":Stmt,"else":Stmt?}` | the taken branch, or `null` when the condition is false and `else` is absent | see below |

`when` reads `cond` and only the taken branch at runtime. Static edges include
`cond`, `then`, and `else` when `else` is present. A write is not a read: an
effect that `set`s a source it also `ref`s reschedules when the value changes.
An equal write does not. A write that keeps changing a value the same effect
reads is a feedback loop; the context stops that drain at its existing budget
rather than treating it as a successful quiesce.

## Expressions

An expression is exactly one of `lit`, `ref`, `op` + `args`, or `object`.

| Form | Value |
|---|---|
| `{"lit": <json>}` | that JSON value |
| `{"ref": "<id>"}` | the current value of a source or computed; registers a read |
| `{"op":"array","args":[...]}` | JSON array, evaluated left to right, possibly empty |
| `{"object":[{"key":"<string>","value":Expr}, ...]}` | JSON object; duplicate keys are a fault; key order is not significant |
| `{"op":"get","args":[target, key]}` | object field or array element; a missing key or out-of-range index is a fault; no string/number coercion |
| `{"op":"len","args":[value]}` | length of a string (Unicode scalars), array, or object |
| `{"op":"concat","args":[a, b]}` | concatenation of two strings |
| `{"op":"if","args":[cond, then, else]}` | `cond` must be boolean; only the taken branch is evaluated |
| `{"op":"and","args":[a, b]}` / `or` | booleans; the second arg is not evaluated when the first decides the result |
| `{"op":"not","args":[a]}` | boolean negation |
| `{"op":"neg","args":[a]}` | numeric negation |
| `add` `sub` `mul` `mod` `min` `max` | two numbers; `mod` is integers only, truncated toward zero, and rejects a zero divisor |
| `div` | two numbers; real division; rejects a zero divisor |
| `eq` `ne` | any JSON values, structural equality |
| `lt` `le` `gt` `ge` | numbers only |

`and`, `or`, and `if` are why a runtime read-edge set can be smaller than the
static set. Static edges are every `ref` that appears, including untaken
branches. Observed edges are the refs actually evaluated on the latest run of
that node.

## Edges

Edges are not stored in the document. A lowering derives them so they cannot
drift from the tree.

- A **read** edge is `(from, read, to)` when `from`'s expression or statement
  contains `{"ref": to}`.
- A **write** edge is `(from, write, to)` when an effect `from` `set`s or
  `merge`s `to`.

The read graph MUST be acyclic. Write edges are not cycle edges. The derived
list is sorted by `(from, kind, to)` with `read` before `write`.

A runtime also records the refs read by the latest evaluation of each node.
That set is the observed edge set. It starts empty for a lazy computed that
has not been read.

## Edits

```json
{"kind": "edit", "ir": "1", "ops": [
  {"op": "add", "node": {"id": "label", "kind": "source", "init": "n"}},
  {"op": "replace", "node": {"id": "doubled", "kind": "computed", "expr": {"op": "add", "args": [{"ref": "count"}, {"lit": 10}]}}},
  {"op": "remove", "id": "log"}
]}
```

| Op | Rule |
|---|---|
| `add` | The id is new. The node is appended. Refs must already resolve, including ids added by earlier ops in this edit. |
| `replace` | The id already exists. The new node replaces that definition in place. Kind may change. A replaced source's live value becomes the new `init`. Optional fields that are omitted take defaults. |
| `remove` | The id exists, and no remaining node reads or writes it. Remove readers first. |

After each op the document is checked again. `remove` of a node that is still
read fails and leaves the runtime on the previous document. A fault while
installing an effect does not keep that effect. Source writes that the failing
statement already performed are not rolled back.

Lowering and edits own the context. Disposing a replaced or removed node
detaches its edges. Readers that survive a source replace read the new node
the next time they evaluate.

## `canonical-source`

The only textual target is `canonical-source`. It is a projection of the
document, one node per line, in declaration order:

```text
graph counter ir 1
source count = 1
source total = 0 policy sum
computed doubled eager = mul(ref(count), lit(2))
computed picked = if(ref(flag), ref(left), ref(right))
effect log = eval(ref(doubled))
effect bump = seq(eval(ref(tick)), merge(total, lit(1)))
```

A graph with no id emits `graph ir 1`. `keep-latest` and `eager: false` are
omitted. Literals use compact JSON. Object fields emit as
`object("key": expr, ...)`. This text is not an input language.

## Faults

A structural problem (unknown field, unknown id, bad arity, cycle, policy
init of the wrong JSON type) fails the parse or the edit before the runtime
changes. A value fault (`div` by zero, missing `get`, integer overflow) fails
the read or the write that evaluated it. A lazy computed is not evaluated at
lower time, so that fault surfaces on the first read. An eager computed is
evaluated at installation; if that fails, the node is not kept.

## What this IR does not do

- It does not extend `snapshot.json` or `delta.json`.
- It does not embed a host function, a chart action name, or a string formula.
- It does not sync the document over the wire. Two peers converge on derived
  cells only when each already holds the same document and the same inputs.
  The wire image remains values and edges.
- It does not require every binding to ship an interpreter yet. lazily-rs is
  the reference: `GraphIr::from_json_str`, `GraphRuntime::lower`,
  `GraphRuntime::apply`, `GraphIr::static_edges`, and `GraphIr::emit_source`.
