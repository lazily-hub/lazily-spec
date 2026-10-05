#!/usr/bin/env python3
"""Shared wire model + per-binding codec generation (#lzwiremodel).

One language-neutral model of the lazily *data plane* (wire records, enums,
envelopes) is derived from the JSON Schemas named in ``codegen/surfaces.json``
and committed as the golden ``codegen/wire-model.json``. A schema change shows up
there as one readable diff before any binding is touched. Thin backends then
lower the model into each participating binding's wire types; the binding keeps
its semantics (constructors, terminality, projections) hand-written and calls
into the generated declarations.

The kernel (Source/Computed/Effect, scheduling, scopes) is deliberately NOT
modelled here: its hard problems are per-language lowering decisions.

The model accepts only the schema shapes it can lower faithfully and fails
closed on anything else, so a schema edit can never silently fall out of the
generated surface.

Usage:
  python3 scripts/wire_codegen.py --check          # golden model + present siblings
  python3 scripts/wire_codegen.py --check --require-all
  python3 scripts/wire_codegen.py --write          # regenerate model + present siblings
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

SPEC_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_SRC = SPEC_ROOT.parent
SURFACES = SPEC_ROOT / "codegen" / "surfaces.json"
GOLDEN_MODEL = SPEC_ROOT / "codegen" / "wire-model.json"
MODEL_VERSION = 1
GENERATOR = "scripts/wire_codegen.py"


class UnsupportedSchema(ValueError):
    """A schema construct the wire model cannot lower faithfully."""


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------


def _require_doc(node: dict, where: str) -> str:
    doc = node.get("description")
    if not isinstance(doc, str) or not doc.strip():
        raise UnsupportedSchema(f"{where}: a generated declaration needs a `description`")
    return doc.strip()


def _nullable_inner(node: dict) -> dict | None:
    """Return the non-null branch of a `oneOf: [null, T]` node, else None."""
    branches = node.get("oneOf")
    if not isinstance(branches, list) or len(branches) != 2:
        return None
    nulls = [b for b in branches if b == {"type": "null"}]
    others = [b for b in branches if b != {"type": "null"}]
    if len(nulls) != 1 or len(others) != 1:
        return None
    return others[0]


U64_MAX = 2**64 - 1
SHARED_DEFS = "schemas/defs.json"
SHARED_DEFS_PREFIX = "https://lazily.dev/schemas/defs.json#/$defs/"
LOCAL_PREFIX = "#/$defs/"


class _SurfaceBuilder:
    def __init__(self, name: str, schema_path: str, schema: dict, root: Path = SPEC_ROOT) -> None:
        self.name = name
        self.schema_path = schema_path
        self.schema = schema
        self.root = root
        self.defs: dict[str, dict] = schema.get("$defs", {})
        self._shared: dict[str, dict] | None = None
        # The document whose `#/$defs/` a local ref resolves against while a
        # declaration is being modelled: the surface schema, or defs.json.
        self.scope = (schema_path, self.defs)
        self.types: list[dict] = []
        self.emitted: set[str] = set()
        self.shared_queue: list[str] = []

    @property
    def shared(self) -> dict[str, dict]:
        if self._shared is None:
            self._shared = json.loads((self.root / SHARED_DEFS).read_text()).get("$defs", {})
        return self._shared

    def _resolve(self, ref: Any, where: str) -> tuple[str, dict, bool]:
        """(def name, node, is_shared) for a local or defs.json reference."""
        if not isinstance(ref, str):
            raise UnsupportedSchema(f"{where}: a $ref must be a string ({ref!r})")
        scope_path, scope_defs = self.scope
        if ref.startswith(LOCAL_PREFIX):
            name = ref[len(LOCAL_PREFIX) :]
            shared = scope_path == SHARED_DEFS
            defs = scope_defs
        elif ref.startswith(SHARED_DEFS_PREFIX):
            name = ref[len(SHARED_DEFS_PREFIX) :]
            shared = True
            defs = self.shared
        else:
            raise UnsupportedSchema(
                f"{where}: only local #/$defs/ and {SHARED_DEFS} references are modelled ({ref!r})"
            )
        node = defs.get(name)
        if node is None:
            raise UnsupportedSchema(f"{where}: unresolved $ref to {name!r}")
        if shared and name in self.defs and self.schema_path != SHARED_DEFS:
            raise UnsupportedSchema(f"{where}: {name!r} is declared both locally and in {SHARED_DEFS}")
        return name, node, shared

    def _def_kind(self, node: dict, where: str) -> str:
        if _nullable_inner(node) is not None:
            return "nullable_alias"
        if isinstance(node.get("oneOf"), list):
            return "union"
        if node.get("type") == "string" and "enum" in node:
            return "enum"
        if node.get("type") == "object":
            return "record"
        if node.get("type") in ("string", "integer", "boolean"):
            return "alias"
        raise UnsupportedSchema(f"{where}: unsupported definition shape")

    def type_expr(self, node: dict, where: str) -> dict:
        if "$ref" in node:
            name, target, shared = self._resolve(node["$ref"], where)
            if self._def_kind(target, f"{where} -> {name}") == "nullable_alias":
                return self.type_expr(target, f"{where} -> {name}")
            if shared and name not in self.shared_queue:
                self.shared_queue.append(name)
            return {"kind": "ref", "name": name}
        inner = _nullable_inner(node)
        if inner is not None:
            return {"kind": "nullable", "inner": self.type_expr(inner, where)}
        kind = node.get("type")
        if kind == "string" and "enum" in node:
            enum_name = node.get("x-lazily-name")
            if not isinstance(enum_name, str) or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", enum_name):
                raise UnsupportedSchema(f"{where}: an inline enum needs an `x-lazily-name` PascalCase type name")
            if enum_name not in self.emitted:
                self.emitted.add(enum_name)
                self.types.append(self.enum_type(enum_name, node, where))
            return {"kind": "ref", "name": enum_name}
        if kind == "string" and "const" not in node:
            expr: dict[str, Any] = {"kind": "string"}
            for key, model_key in (("minLength", "min_length"), ("maxLength", "max_length"), ("pattern", "pattern")):
                if key in node:
                    expr[model_key] = node[key]
            return expr
        if kind == "integer":
            if node.get("minimum") != 0:
                raise UnsupportedSchema(f"{where}: only non-negative integers (minimum: 0 -> u64) are modelled")
            maximum = node.get("maximum")
            if maximum is None or maximum == U64_MAX:
                return {"kind": "u64"}
            raise UnsupportedSchema(f"{where}: integer maximum {maximum!r} is not modelled (u64 or u8 bytes only)")
        if kind == "boolean":
            return {"kind": "bool"}
        if kind == "array" and isinstance(node.get("items"), dict):
            items = node["items"]
            if items == {"type": "integer", "minimum": 0, "maximum": 255}:
                return {"kind": "bytes"}
            return {"kind": "list", "items": self.type_expr(items, f"{where}[]")}
        raise UnsupportedSchema(f"{where}: unsupported type shape {json.dumps(node, sort_keys=True)}")

    def enum_type(self, name: str, node: dict, where: str) -> dict:
        values = node["enum"]
        if not values or not all(isinstance(v, str) for v in values):
            raise UnsupportedSchema(f"{where}: enum values must be non-empty strings")
        docs = node.get("x-lazily-enum-docs", {})
        unknown = sorted(set(docs) - set(values))
        if unknown:
            raise UnsupportedSchema(f"{where}: x-lazily-enum-docs names values not in the enum: {unknown}")
        out_values = []
        for value in values:
            doc = docs.get(value)
            if not isinstance(doc, str) or not doc.strip():
                raise UnsupportedSchema(f"{where}: enum value {value!r} needs an x-lazily-enum-docs entry")
            out_values.append({"wire": value, "doc": doc.strip()})
        return {
            "name": name,
            "kind": "enum",
            "open": False,
            "doc": _require_doc(node, where),
            "values": out_values,
        }

    def alias_type(self, name: str, node: dict, where: str) -> dict:
        """A named scalar (`NodeId` = u64, `NodeKey` = constrained string)."""
        return {"name": name, "kind": "alias", "doc": _require_doc(node, where), "target": self.type_expr(node, where)}

    def union_type(self, name: str, node: dict, where: str) -> dict:
        """A multi-variant externally-tagged union.

        Each `oneOf` branch is either a closed single-key object whose key is the
        PascalCase variant tag (`{"CellSet": {...}}`), or a bare string `const`
        unit variant (`"Opaque"`).
        """
        variants = []
        for i, branch in enumerate(node["oneOf"]):
            bwhere = f"{where}/oneOf/{i}"
            if not isinstance(branch, dict):
                raise UnsupportedSchema(f"{bwhere}: a union branch must be an object")
            if branch.get("type") == "string" and "const" in branch:
                tag = branch["const"]
                payload_node = None
            elif branch.get("type") == "object":
                if branch.get("additionalProperties") is not False:
                    raise UnsupportedSchema(f"{bwhere}: a tagged variant must be closed (additionalProperties: false)")
                props = branch.get("properties")
                if not isinstance(props, dict) or len(props) != 1:
                    raise UnsupportedSchema(f"{bwhere}: a tagged variant is a single-key object")
                (tag, payload_node), = props.items()
                if branch.get("required") != [tag]:
                    raise UnsupportedSchema(f"{bwhere}: a tagged variant must require its tag {tag!r}")
            else:
                raise UnsupportedSchema(f"{bwhere}: unsupported union branch shape")
            if not isinstance(tag, str) or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", tag):
                raise UnsupportedSchema(f"{bwhere}: variant tag {tag!r} must be PascalCase")
            if "title" in branch and branch["title"] != tag:
                raise UnsupportedSchema(f"{bwhere}: title {branch['title']!r} differs from tag {tag!r}")
            doc_source = branch if "description" in branch else (payload_node or {})
            variants.append(
                {
                    "tag": tag,
                    "doc": _require_doc(doc_source, f"{bwhere} ({tag})"),
                    "payload": None if payload_node is None else self.type_expr(payload_node, f"{bwhere}.{tag}"),
                }
            )
        tags = [v["tag"] for v in variants]
        if len(tags) != len(set(tags)) or len(tags) < 2:
            raise UnsupportedSchema(f"{where}: a union needs two or more distinct variant tags {tags}")
        return {"name": name, "kind": "union", "tagging": "external", "doc": _require_doc(node, where), "variants": variants}

    def record_type(self, name: str, node: dict, where: str) -> dict:
        if node.get("additionalProperties") is not False:
            raise UnsupportedSchema(f"{where}: generated records must be closed (additionalProperties: false)")
        properties = node.get("properties")
        if not isinstance(properties, dict) or not properties:
            raise UnsupportedSchema(f"{where}: a record needs properties")
        required = node.get("required", [])
        missing = sorted(set(required) - set(properties))
        if missing:
            raise UnsupportedSchema(f"{where}: required names unknown properties {missing}")
        fields = []
        for field_name, field_node in properties.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", field_name):
                raise UnsupportedSchema(f"{where}.{field_name}: wire field names must be snake_case")
            field_where = f"{where}.{field_name}"
            field = {
                "name": field_name,
                "doc": _require_doc(field_node, field_where),
                "presence": "required" if field_name in required else "optional",
                "type": self.type_expr(field_node, field_where),
            }
            if "default" in field_node:
                if field["presence"] == "required":
                    raise UnsupportedSchema(f"{field_where}: a required field cannot carry a `default`")
                field["default"] = field_node["default"]
            fields.append(field)
        return {
            "name": name,
            "kind": "record",
            "closed": True,
            "doc": _require_doc(node, where),
            "fields": fields,
        }

    def declaration(self, name: str, node: dict, where: str) -> dict | None:
        kind = self._def_kind(node, where)
        if kind == "nullable_alias":
            return None
        if kind == "enum":
            return self.enum_type(name, node, where)
        if kind == "record":
            return self.record_type(name, node, where)
        if kind == "union":
            return self.union_type(name, node, where)
        return self.alias_type(name, node, where)

    def _emit(self, name: str, node: dict, where: str) -> None:
        if name in self.emitted:
            return
        self.emitted.add(name)
        decl = self.declaration(name, node, where)
        if decl is not None:
            self.types.append(decl)

    def build(self) -> dict:
        for def_name, node in self.defs.items():
            self._emit(def_name, node, f"{self.schema_path}#/$defs/{def_name}")

        root = self.schema
        envelope = root.get("x-lazily-envelope")
        if envelope is not None:
            if root.get("type") != "object" or root.get("additionalProperties") is not False:
                raise UnsupportedSchema(f"{self.schema_path}: an envelope root must be a closed object")
            variants = []
            for tag, node in root.get("properties", {}).items():
                where = f"{self.schema_path}#/properties/{tag}"
                if "$ref" in node:
                    target = self.type_expr(node, where)
                    if target["kind"] != "ref":
                        raise UnsupportedSchema(f"{where}: an envelope variant must name a record")
                    type_name = target["name"]
                else:
                    self.emitted.add(tag)
                    self.types.append(self.record_type(tag, node, where))
                    type_name = tag
                variants.append({"tag": tag, "type": type_name})
            if root.get("required") != [v["tag"] for v in variants] or len(variants) != 1:
                raise UnsupportedSchema(
                    f"{self.schema_path}: only single-variant externally-tagged envelopes are modelled"
                )
            self.types.append(
                {
                    "name": envelope["name"],
                    "kind": "envelope",
                    "tagging": "external",
                    "doc": _require_doc(envelope, f"{self.schema_path}#/x-lazily-envelope"),
                    "variants": variants,
                }
            )

        elif any(key in root for key in ("properties", "oneOf", "anyOf", "allOf", "items")):
            # A root that is not an x-lazily-envelope would otherwise be skipped
            # silently, leaving a model that describes none of the wire.
            raise UnsupportedSchema(
                f"{self.schema_path}: the root declares a wire shape but is not an x-lazily-envelope"
            )

        # Shared declarations from defs.json, in first-reference order, closed
        # transitively: a shared record can itself reference shared types.
        self.scope = (SHARED_DEFS, self.shared)
        i = 0
        while i < len(self.shared_queue):
            name = self.shared_queue[i]
            self._emit(name, self.shared[name], f"{SHARED_DEFS}#/$defs/{name}")
            i += 1

        names = [t["name"] for t in self.types]
        if not names:
            raise UnsupportedSchema(f"{self.schema_path}: the schema declares nothing the model can generate")
        if len(names) != len(set(names)):
            raise UnsupportedSchema(f"{self.schema_path}: duplicate generated type names {names}")
        known = set(names)
        for t in self.types:
            for label, expr in _type_exprs(t):
                for ref in _refs(expr):
                    if ref not in known:
                        raise UnsupportedSchema(f"{self.schema_path}: {t['name']}.{label} names unknown {ref}")
        return {"name": self.name, "schema": self.schema_path, "types": self.types}


def _type_exprs(t: dict) -> list[tuple[str, dict]]:
    """Every (label, type expression) a declaration carries."""
    if t["kind"] == "record":
        return [(f["name"], f["type"]) for f in t["fields"]]
    if t["kind"] == "union":
        return [(v["tag"], v["payload"]) for v in t["variants"] if v["payload"] is not None]
    if t["kind"] == "alias":
        return [("target", t["target"])]
    return []


def _all_exprs(expr: dict) -> list[dict]:
    """``expr`` and every expression nested under it."""
    out = [expr]
    for key in ("inner", "items"):
        if key in expr:
            out += _all_exprs(expr[key])
    return out


def _refs(expr: dict) -> list[str]:
    if expr["kind"] == "ref":
        return [expr["name"]]
    if expr["kind"] == "nullable":
        return _refs(expr["inner"])
    if expr["kind"] == "list":
        return _refs(expr["items"])
    return []


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def surface_digest(surface: dict) -> str:
    return hashlib.sha256(canonical_json(surface).encode()).hexdigest()


def build_surface(name: str, schema_path: str, root: Path = SPEC_ROOT) -> dict:
    schema = json.loads((root / schema_path).read_text())
    return _SurfaceBuilder(name, schema_path, schema, root).build()


def load_manifest(root: Path = SPEC_ROOT) -> dict:
    return json.loads((root / "codegen" / "surfaces.json").read_text())


def build_model(root: Path = SPEC_ROOT) -> dict:
    surfaces = []
    for entry in load_manifest(root)["surfaces"]:
        surface = build_surface(entry["name"], entry["schema"], root)
        surface["model_sha256"] = surface_digest(surface)
        surfaces.append(surface)
    return {"model_version": MODEL_VERSION, "generator": GENERATOR, "surfaces": surfaces}


def render_model(model: dict) -> str:
    return json.dumps(model, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Shared backend helpers
# ---------------------------------------------------------------------------


def pascal(snake: str) -> str:
    name = "".join(part[:1].upper() + part[1:] for part in snake.split("_"))
    if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", name):
        raise UnsupportedSchema(f"wire name {snake!r} does not lower to an identifier ({name!r})")
    return name


def snake(pascal_name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", pascal_name).lower()


def _types_by_name(surface: dict) -> dict[str, dict]:
    return {t["name"]: t for t in surface["types"]}


def _comment(prefix: str, text: str, width: int) -> list[str]:
    return [prefix + line for line in textwrap.wrap(text, width=width - len(prefix), break_on_hyphens=False)]


_LOWERED_KINDS = frozenset({"enum", "record", "envelope"})
_LOWERED_EXPRS = frozenset({"string", "u64", "bool", "ref", "nullable", "list"})


def _require_lowerable(
    surface: dict,
    backend: str,
    *,
    types: list[dict] | None = None,
    kinds: frozenset[str] = _LOWERED_KINDS,
    exprs: frozenset[str] = _LOWERED_EXPRS,
    optional: bool = False,
) -> None:
    for t in surface["types"] if types is None else types:
        if t["kind"] not in kinds:
            raise UnsupportedSchema(f"{backend}: {t['kind']} declarations are modelled but not yet lowered ({t['name']})")
        for label, expr in _type_exprs(t):
            for node in _all_exprs(expr):
                kind = node["kind"]
                if kind not in exprs:
                    raise UnsupportedSchema(f"{backend}: {kind} is modelled but not yet lowered ({t['name']}.{label})")
                if {"max_length", "pattern"} & set(node):
                    raise UnsupportedSchema(
                        f"{backend}: string max_length/pattern are modelled but not yet lowered ({t['name']}.{label})"
                    )
        if t["kind"] == "enum" and t["open"]:
            raise UnsupportedSchema(f"{backend}: open enums are modelled but not yet lowered ({t['name']})")
        for field in t.get("fields", []):
            if "default" in field:
                raise UnsupportedSchema(
                    f"{backend}: field defaults are modelled but not yet lowered ({t['name']}.{field['name']})"
                )
            if field["presence"] != "required" and not optional:
                raise UnsupportedSchema(
                    f"{backend}: optional (may-be-absent) fields are modelled but not yet lowered "
                    f"({t['name']}.{field['name']})"
                )


# ---------------------------------------------------------------------------
# Rust backend
# ---------------------------------------------------------------------------

RUST_SERDE = '#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]'


def _rust_type(expr: dict) -> str:
    kind = expr["kind"]
    if kind == "string":
        return "String"
    if kind == "u64":
        return "u64"
    if kind == "bool":
        return "bool"
    if kind == "ref":
        return expr["name"]
    if kind == "nullable":
        return f"Option<{_rust_type(expr['inner'])}>"
    if kind == "list":
        return f"Vec<{_rust_type(expr['items'])}>"
    if kind == "bytes":
        return "Vec<u8>"
    raise UnsupportedSchema(f"rust: unsupported type kind {kind}")


def _required_nullable(field: dict) -> bool:
    return field["presence"] == "required" and field["type"]["kind"] == "nullable"


def _rust_header(surface: dict) -> list[str]:
    return [
        f"// @generated by lazily-spec {GENERATOR}. DO NOT EDIT.",
        f"// Surface `{surface['name']}` from {surface['schema']}, model sha256:{surface['model_sha256']}.",
        "// Regenerate from lazily-spec with `make wire-codegen`; semantics stay hand-written.",
    ]


def _rust_record(t: dict) -> list[str]:
    lines = ["#[derive(Debug, Clone, PartialEq, Eq)]", RUST_SERDE]
    lines.append('#[cfg_attr(feature = "serde", serde(deny_unknown_fields))]')
    lines.append(f"pub struct {t['name']} {{")
    for field in t["fields"]:
        lines.extend(_comment("    /// ", field["doc"], 100))
        if _required_nullable(field):
            lines.append('    #[cfg_attr(feature = "serde", serde(deserialize_with = "required_nullable"))]')
        lines.append(f"    pub {field['name']}: {_rust_type(field['type'])},")
    lines.append("}")
    return lines


def render_rust(surface: dict, target: dict) -> str:
    if any(t["kind"] == "union" for t in surface["types"]):
        return _render_rust_unions(surface, target)
    _require_lowerable(surface, "rust")
    lines = _rust_header(surface)
    if any(_required_nullable(f) for t in surface["types"] for f in t.get("fields", [])):
        lines.extend(
            [
                "",
                "/// Decodes a field that is always on the wire and is `null` when absent. A bare",
                "/// `Option` would let serde default a missing key to `None`.",
                '#[cfg(feature = "serde")]',
                "fn required_nullable<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>",
                "where",
                "    D: serde::Deserializer<'de>,",
                "    T: serde::Deserialize<'de>,",
                "{",
                "    <Option<T> as serde::Deserialize>::deserialize(deserializer)",
                "}",
            ]
        )
    for t in surface["types"]:
        lines.append("")
        lines.extend(_comment("/// ", t["doc"], 100))
        if t["kind"] == "enum":
            variants = [(pascal(v["wire"]), v) for v in t["values"]]
            uniform = all(snake(name) == v["wire"] for name, v in variants)
            lines.append("#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]")
            lines.append(RUST_SERDE)
            if uniform:
                lines.append('#[cfg_attr(feature = "serde", serde(rename_all = "snake_case"))]')
            lines.append(f"pub enum {t['name']} {{")
            for name, v in variants:
                lines.extend(_comment("    /// ", v["doc"], 100))
                if not uniform:
                    lines.append(f'    #[cfg_attr(feature = "serde", serde(rename = "{v["wire"]}"))]')
                lines.append(f"    {name},")
            lines.append("}")
        elif t["kind"] == "record":
            lines.extend(_rust_record(t))
        elif t["kind"] == "envelope":
            lines.append("#[derive(Debug, Clone, PartialEq, Eq)]")
            lines.append(RUST_SERDE)
            lines.append(f"pub enum {t['name']} {{")
            for variant in t["variants"]:
                lines.append(f"    /// `{variant['tag']}` envelope variant.")
                lines.append(f"    {variant['tag']}({variant['type']}),")
            lines.append("}")
    return "\n".join(lines) + "\n"


# Rust lowering for surfaces with unions (#lzwiremodel7). Receipts keep the
# path above byte for byte. The plan (flattened record payloads, `external`,
# reachability) is the Python backend's; a non-record payload lowers to a tuple
# variant, so it needs no `variant_fields` name.

_RUST_SERIALIZE_LOCALS = frozenset({"out", "serializer", "self_describing", "len"})


def _rust_optional_type(field: dict) -> str:
    # An optional field reads absence as None; a nullable one already is an Option.
    rust = _rust_type(field["type"])
    return rust if field["type"]["kind"] == "nullable" else f"Option<{rust}>"


def _rust_pattern(indent: str, head: str, names: list[str]) -> list[str]:
    """A struct pattern laid out the way rustfmt does (struct_lit_width = 18)."""
    inline = ", ".join(names)
    if len(inline) <= 18:
        return [f"{indent}{head} {{ {inline} }} => {{"]
    return [f"{indent}{head} {{"] + [f"{indent}    {n}," for n in names] + [f"{indent}}} => {{"]


def _render_rust_unions(surface: dict, target: dict) -> str:
    types = _types_by_name(surface)
    external: dict[str, str] = target.get("external", {})
    codec_aware = target.get("codec_aware_optional", False)
    if "variant_fields" in target:
        raise UnsupportedSchema("rust: a non-record union payload lowers to a tuple variant; `variant_fields` does not apply")
    # Tuple variants carry no field name; give the shared plan a placeholder for each.
    tuple_payloads = {
        f"{t['name']}.{v['tag']}": "0"
        for t in surface["types"]
        if t["kind"] == "union"
        for v in t["variants"]
        if v["payload"] is not None
        and not (
            v["payload"]["kind"] == "ref"
            and v["payload"]["name"] not in external
            and types[v["payload"]["name"]]["kind"] == "record"
        )
    }
    emitted, bodies = _py_plan(surface, {**target, "variant_fields": tuple_payloads}, "rust")
    for t in emitted:
        if t["kind"] == "alias":
            raise UnsupportedSchema(
                f"rust: alias {t['name']} must be `external` (a hand-written newtype or validated type)"
            )
        if t["kind"] == "envelope":
            raise UnsupportedSchema(f"rust: envelope {t['name']} is not lowered (set `envelope: false`)")
        if t["kind"] == "enum":
            raise UnsupportedSchema(f"rust: enum {t['name']} in a union surface is not lowered yet")
        for field in t.get("fields", []):
            if field["presence"] == "optional":
                raise UnsupportedSchema(
                    f"rust: optional field {t['name']}.{field['name']} outside a union variant is not lowered yet"
                )
            if _required_nullable(field):
                raise UnsupportedSchema(
                    f"rust: required-nullable field {t['name']}.{field['name']} in a union surface is not lowered yet"
                )
    for body in bodies.values():
        for field in body["fields"]:
            if field["presence"] == "optional" and not codec_aware:
                raise UnsupportedSchema(
                    f"rust: optional field {body['name']}.{field['name']} needs `codec_aware_optional`: "
                    "omitted when absent in self-describing codecs, always written in positional ones"
                )

    lines = _rust_header(surface)
    # rustfmt's import order: `self::`, `super::`, `crate::`, then other crates.
    rank = {"self": 0, "super": 1, "crate": 2}
    imports = sorted((p for p in external.values() if p), key=lambda p: (rank.get(p.split("::")[0], 3), p))
    if imports:
        lines.append("")
        lines.extend(f"use {path};" for path in imports)

    for t in emitted:
        lines.append("")
        lines.extend(_comment("/// ", t["doc"], 100))
        if t["kind"] == "record":
            lines.extend(_rust_record(t))
            continue
        # A union: record payloads flatten into struct variants, any other
        # payload is a tuple variant, and a unit variant stays a unit.
        name = t["name"]
        variants = []
        for index, v in enumerate(t["variants"]):
            payload = v["payload"]
            if payload is None:
                variants.append((index, v, "unit", None))
            elif f"{name}.{v['tag']}" in tuple_payloads:
                variants.append((index, v, "tuple", payload))
            else:
                variants.append((index, v, "struct", bodies[payload["name"]]["fields"]))
        aware = [
            (v, [f for f in fields if f["presence"] == "optional"])
            for _i, v, shape, fields in variants
            if shape == "struct" and any(f["presence"] == "optional" for f in fields)
        ]
        if aware:
            lines.extend(
                [
                    "///",
                    "/// Optional fields are codec-aware: a self-describing codec omits an absent one, and",
                    "/// positional Postcard always writes it so its schema stays stable.",
                ]
            )
        lines.append("#[derive(Debug, Clone, PartialEq, Eq)]")
        derives = "serde::Deserialize" if aware else "serde::Serialize, serde::Deserialize"
        lines.append(f'#[cfg_attr(feature = "serde", derive({derives}))]')
        if any(shape == "struct" for _i, _v, shape, _p in variants):
            lines.append('#[cfg_attr(feature = "serde", serde(deny_unknown_fields))]')
        lines.append(f"pub enum {name} {{")
        for _i, v, shape, payload in variants:
            lines.extend(_comment("    /// ", v["doc"], 100))
            if shape == "unit":
                lines.append(f"    {v['tag']},")
            elif shape == "tuple":
                lines.append(f"    {v['tag']}({_rust_type(payload)}),")
            else:
                lines.append(f"    {v['tag']} {{")
                for f in payload:
                    lines.extend(_comment("        /// ", f["doc"], 100))
                    if f["presence"] == "optional":
                        lines.append('        #[cfg_attr(feature = "serde", serde(default))]')
                        lines.append(f"        {f['name']}: {_rust_optional_type(f)},")
                    else:
                        lines.append(f"        {f['name']}: {_rust_type(f['type'])},")
                lines.append("    },")
        lines.append("}")
        if not aware:
            continue
        if any(shape != "struct" for _i, _v, shape, _p in variants):
            raise UnsupportedSchema(
                f"rust: codec-aware union {name} with tuple or unit variants is not lowered yet"
            )
        # serde's derive cannot make a field's presence depend on the codec, so
        # the codec-aware union writes its own Serialize. It is what the derive
        # emits for `skip_serializing_if`, with the skip taken only when the
        # serializer is self-describing (`is_human_readable`; lazily-rs's msgpack
        # encoder opts in).
        lines.extend(
            [
                "",
                '#[cfg(feature = "serde")]',
                f"impl serde::Serialize for {name} {{",
                "    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {",
                "        use serde::ser::SerializeStructVariant;",
                "        let self_describing = serializer.is_human_readable();",
                "        match self {",
            ]
        )
        for index, v, _shape, fields in variants:
            names = [f["name"] for f in fields]
            clash = sorted(_RUST_SERIALIZE_LOCALS & set(names) | {n for n in names if n.startswith("emit_")})
            if clash:
                raise UnsupportedSchema(f"rust: field {name}.{v['tag']}.{clash[0]} clashes with a Serialize local")
            lines.extend(_rust_pattern("            ", f"Self::{v['tag']}", names))
            required = sum(1 for f in fields if f["presence"] == "required")
            optional = [f["name"] for f in fields if f["presence"] == "optional"]
            for opt in optional:
                lines.append(f"                let emit_{opt} = {opt}.is_some() || !self_describing;")
            length = str(required)
            if optional:
                count = " + ".join([str(required)] + [f"usize::from(emit_{opt})" for opt in optional])
                lines.append(f"                let len = {count};")
                length = "len"
            call = f'serializer.serialize_struct_variant("{name}", {index}, "{v["tag"]}", {length})?;'
            if len(f"                let mut out = {call}") <= 100:
                lines.append(f"                let mut out = {call}")
            else:
                lines.extend(["                let mut out =", f"                    {call}"])
            for f in fields:
                if f["presence"] == "required":
                    lines.append(f'                out.serialize_field("{f["name"]}", {f["name"]})?;')
                else:
                    lines.extend(
                        [
                            f"                if emit_{f['name']} {{",
                            f'                    out.serialize_field("{f["name"]}", {f["name"]})?;',
                            "                } else {",
                            f'                    out.skip_field("{f["name"]}")?;',
                            "                }",
                        ]
                    )
            lines.append("                out.end()")
            lines.append("            }")
        lines.extend(["        }", "    }", "}"])
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Go backend
# ---------------------------------------------------------------------------


def _go_type(expr: dict, types: dict[str, dict]) -> str:
    kind = expr["kind"]
    if kind == "string":
        return "string"
    if kind == "u64":
        return "uint64"
    if kind == "bool":
        return "bool"
    if kind == "ref":
        return expr["name"]
    if kind == "nullable":
        return f"*{_go_type(expr['inner'], types)}"
    if kind == "list":
        return f"[]{_go_type(expr['items'], types)}"
    raise UnsupportedSchema(f"go: unsupported type kind {kind}")


def render_go(surface: dict, target: dict) -> str:
    if any(t["kind"] == "union" for t in surface["types"]):
        return _render_go_unions(surface, target)
    _require_lowerable(surface, "go")
    types = _types_by_name(surface)
    has_enum = any(t["kind"] == "enum" for t in surface["types"])
    lines = [
        f"// Code generated by lazily-spec {GENERATOR}. DO NOT EDIT.",
        f"// Surface `{surface['name']}` from {surface['schema']}, model sha256:{surface['model_sha256']}.",
        "// Regenerate from lazily-spec with `make wire-codegen`; semantics stay hand-written.",
        "// Externally-tagged envelopes are not lowered for Go; callers decode the tagged body.",
        "",
        f"package {target['package']}",
        "",
        "import (",
        '\t"encoding/json"',
    ]
    has_record = any(t["kind"] == "record" for t in surface["types"])
    if has_enum or has_record:
        lines.append('\t"fmt"')
    if has_record:
        lines.append('\t"sort"')
    lines.append(")")
    check_fields = f"{surface['name']}CheckWireFields"
    if has_record:
        lines.extend(
            [
                "",
                f"// {check_fields} rejects a record whose wire keys are not exactly its",
                "// declared fields: a closed record has no unknown keys, and a required field",
                "// is present even when its value is null.",
                f"func {check_fields}(name string, data []byte, fields []string) error {{",
                "\tvar keys map[string]json.RawMessage",
                "\tif err := json.Unmarshal(data, &keys); err != nil {",
                "\t\treturn err",
                "\t}",
                "\tif keys == nil {",
                '\t\treturn fmt.Errorf("%s: expected an object, got null", name)',
                "\t}",
                "\tfor _, field := range fields {",
                "\t\tif _, ok := keys[field]; !ok {",
                '\t\t\treturn fmt.Errorf("%s: missing field %q", name, field)',
                "\t\t}",
                "\t\tdelete(keys, field)",
                "\t}",
                "\tif len(keys) > 0 {",
                "\t\tunknown := make([]string, 0, len(keys))",
                "\t\tfor key := range keys {",
                "\t\t\tunknown = append(unknown, key)",
                "\t\t}",
                "\t\tsort.Strings(unknown)",
                '\t\treturn fmt.Errorf("%s: unknown field %q", name, unknown[0])',
                "\t}",
                "\treturn nil",
                "}",
            ]
        )
    for t in surface["types"]:
        name = t["name"]
        if t["kind"] == "enum":
            lines.append("")
            lines.extend(_comment("// ", f"{name}: {t['doc']}", 80))
            lines.append(f"type {name} string")
            lines.append("")
            lines.append("const (")
            consts = []
            for v in t["values"]:
                const = f"{name}{pascal(v['wire'])}"
                consts.append(const)
                lines.extend(_comment("\t// ", f"{const}: {v['doc']}", 80))
                lines.append(f'\t{const} {name} = "{v["wire"]}"')
            lines.append(")")
            lines.append("")
            lines.append(f"// Wire returns the bare wire string of this {name}.")
            lines.append(f"func (v {name}) Wire() string {{ return string(v) }}")
            lines.append("")
            lines.append(f"// {name}FromWire parses a wire string into a {name}, rejecting unknown")
            lines.append("// values.")
            lines.append(f"func {name}FromWire(v string) ({name}, error) {{")
            lines.append(f"\tswitch {name}(v) {{")
            lines.append(f"\tcase {', '.join(consts)}:")
            lines.append(f"\t\treturn {name}(v), nil")
            lines.append("\tdefault:")
            lines.append(f'\t\treturn "", fmt.Errorf("unknown {name}: %q", v)')
            lines.append("\t}")
            lines.append("}")
            lines.append("")
            lines.append(f"// UnmarshalJSON decodes a {name} wire string, rejecting unknown values.")
            lines.append(f"func (v *{name}) UnmarshalJSON(b []byte) error {{")
            lines.append("\tvar s string")
            lines.append("\tif err := json.Unmarshal(b, &s); err != nil {")
            lines.append("\t\treturn err")
            lines.append("\t}")
            lines.append(f"\tparsed, err := {name}FromWire(s)")
            lines.append("\tif err != nil {")
            lines.append("\t\treturn err")
            lines.append("\t}")
            lines.append("\t*v = parsed")
            lines.append("\treturn nil")
            lines.append("}")
        elif t["kind"] == "record":
            lines.append("")
            lines.extend(_comment("// ", f"{name}: {t['doc']}", 80))
            lines.append(f"type {name} struct {{")
            list_fields = []
            for field in t["fields"]:
                go_name = pascal(field["name"])
                go_type = _go_type(field["type"], types)
                if field["type"]["kind"] == "list":
                    list_fields.append((go_name, go_type))
                lines.extend(_comment("\t// ", f"{go_name}: {field['doc']}", 80))
                lines.append(f'\t{go_name} {go_type} `json:"{field["name"]}"`')
            lines.append("}")
            if list_fields:
                lines.append("")
                lines.append(f"// MarshalJSON emits {name}, writing absent lists as [] rather than null.")
                lines.append(f"func (r {name}) MarshalJSON() ([]byte, error) {{")
                lines.append(f"\ttype wire {name}")
                lines.append("\tw := wire(r)")
                for go_name, go_type in list_fields:
                    lines.append(f"\tif w.{go_name} == nil {{")
                    lines.append(f"\t\tw.{go_name} = {go_type}{{}}")
                    lines.append("\t}")
                lines.append("\treturn json.Marshal(w)")
                lines.append("}")
            wire_fields = ", ".join(f'"{f["name"]}"' for f in t["fields"])
            lines.append("")
            lines.append(f"// UnmarshalJSON decodes {name}, rejecting unknown and missing fields.")
            lines.append(f"func (r *{name}) UnmarshalJSON(data []byte) error {{")
            lines.append(f'\tif err := {check_fields}("{name}", data, []string{{{wire_fields}}}); err != nil {{')
            lines.append("\t\treturn err")
            lines.append("\t}")
            lines.append(f"\ttype wire {name}")
            lines.append("\tvar w wire")
            lines.append("\tif err := json.Unmarshal(data, &w); err != nil {")
            lines.append("\t\treturn err")
            lines.append("\t}")
            lines.append(f"\t*r = {name}(w)")
            lines.append("\treturn nil")
            lines.append("}")
            lines.append("")
            lines.append(f"// {name}FromWire decodes a {name} from its JSON wire form.")
            lines.append(f"func {name}FromWire(data []byte) ({name}, error) {{")
            lines.append(f"\tvar r {name}")
            lines.append("\tif err := json.Unmarshal(data, &r); err != nil {")
            lines.append(f"\t\treturn {name}{{}}, err")
            lines.append("\t}")
            lines.append("\treturn r, nil")
            lines.append("}")
    return "\n".join(lines) + "\n"


# Go lowering for surfaces with unions (#lzwiremodel6). Receipts keep the
# struct-tag path above; this path builds JSON by hand so it can carry
# interface-typed union fields, flattened variant bodies, optional fields, and
# u64 values held in a binding's signed 64-bit types.

_GO_UNION_HELPERS = {
    "core": [
        "// {p}Field is one key of a JSON object, written in declaration order.",
        "type {p}Field struct {",
        "\tname  string",
        "\tvalue any",
        "}",
        "",
        "// {p}Object writes a JSON object whose keys keep declaration order.",
        "func {p}Object(fields []{p}Field) ([]byte, error) {",
        "\tvar buf bytes.Buffer",
        "\tbuf.WriteByte('{')",
        "\tfor i, f := range fields {",
        "\t\tif i > 0 {",
        "\t\t\tbuf.WriteByte(',')",
        "\t\t}",
        "\t\tkey, err := json.Marshal(f.name)",
        "\t\tif err != nil {",
        "\t\t\treturn nil, err",
        "\t\t}",
        "\t\tvalue, err := json.Marshal(f.value)",
        "\t\tif err != nil {",
        "\t\t\treturn nil, err",
        "\t\t}",
        "\t\tbuf.Write(key)",
        "\t\tbuf.WriteByte(':')",
        "\t\tbuf.Write(value)",
        "\t}",
        "\tbuf.WriteByte('}')",
        "\treturn buf.Bytes(), nil",
        "}",
        "",
        "// {p}Tagged wraps an encoded body as the externally-tagged {tag: body}.",
        "func {p}Tagged(tag string, body any) ([]byte, error) {",
        "\treturn {p}Object([]{p}Field{{tag, body}})",
        "}",
        "",
        "// {p}Fields decodes a JSON object whose keys are every required field and",
        "// any optional ones, rejecting an unknown or missing key.",
        "func {p}Fields(name string, data []byte, required, optional []string) (map[string]json.RawMessage, error) {",
        "\ttrimmed := bytes.TrimSpace(data)",
        "\tif len(trimmed) == 0 || trimmed[0] != '{' {",
        "\t\treturn nil, fmt.Errorf(\"%s: expected an object, got %s\", name, trimmed)",
        "\t}",
        "\tvar fields map[string]json.RawMessage",
        "\tif err := json.Unmarshal(trimmed, &fields); err != nil {",
        "\t\treturn nil, fmt.Errorf(\"%s: %w\", name, err)",
        "\t}",
        "\tfor _, key := range required {",
        "\t\tif _, ok := fields[key]; !ok {",
        "\t\t\treturn nil, fmt.Errorf(\"%s: missing field %q\", name, key)",
        "\t\t}",
        "\t}",
        "\tunknown := make([]string, 0)",
        "\tfor key := range fields {",
        "\t\tif !{p}Contains(required, key) && !{p}Contains(optional, key) {",
        "\t\t\tunknown = append(unknown, key)",
        "\t\t}",
        "\t}",
        "\tif len(unknown) > 0 {",
        "\t\tsort.Strings(unknown)",
        "\t\treturn nil, fmt.Errorf(\"%s: unknown field %q\", name, unknown[0])",
        "\t}",
        "\treturn fields, nil",
        "}",
        "",
        "func {p}Contains(keys []string, key string) bool {",
        "\tfor _, k := range keys {",
        "\t\tif k == key {",
        "\t\t\treturn true",
        "\t\t}",
        "\t}",
        "\treturn false",
        "}",
        "",
        "// {p}IsNull reports whether raw is the JSON null literal.",
        "func {p}IsNull(raw json.RawMessage) bool {",
        "\treturn bytes.Equal(bytes.TrimSpace(raw), []byte(\"null\"))",
        "}",
        "",
        "// {p}Tag splits an externally-tagged single-key object.",
        "func {p}Tag(name string, raw json.RawMessage) (string, json.RawMessage, error) {",
        "\ttrimmed := bytes.TrimSpace(raw)",
        "\tif len(trimmed) == 0 || trimmed[0] != '{' {",
        "\t\treturn \"\", nil, fmt.Errorf(\"%s: expected a single-key object, got %s\", name, trimmed)",
        "\t}",
        "\tvar tagged map[string]json.RawMessage",
        "\tif err := json.Unmarshal(trimmed, &tagged); err != nil {",
        "\t\treturn \"\", nil, fmt.Errorf(\"%s: %w\", name, err)",
        "\t}",
        "\tif len(tagged) != 1 {",
        "\t\treturn \"\", nil, fmt.Errorf(\"%s: expected a single-key object, got %d keys\", name, len(tagged))",
        "\t}",
        "\tfor tag, body := range tagged {",
        "\t\treturn tag, body, nil",
        "\t}",
        "\treturn \"\", nil, fmt.Errorf(\"%s: expected a single-key object\", name)",
        "}",
    ],
    "string": [
        "func {p}String(name string, raw json.RawMessage) (string, error) {",
        "\ttrimmed := bytes.TrimSpace(raw)",
        "\tif len(trimmed) == 0 || trimmed[0] != '\"' {",
        "\t\treturn \"\", fmt.Errorf(\"%s: expected a string, got %s\", name, trimmed)",
        "\t}",
        "\tvar s string",
        "\tif err := json.Unmarshal(trimmed, &s); err != nil {",
        "\t\treturn \"\", fmt.Errorf(\"%s: %w\", name, err)",
        "\t}",
        "\treturn s, nil",
        "}",
    ],
    "u64": [
        "// {p}U64 decodes an unsigned integer literal: digits only, no sign, fraction,",
        "// exponent or leading zero, and at most 2^64-1.",
        "func {p}U64(name string, raw json.RawMessage) (uint64, error) {",
        "\ttrimmed := string(bytes.TrimSpace(raw))",
        "\tvalid := trimmed != \"\" && (trimmed == \"0\" || trimmed[0] != '0')",
        "\tfor _, c := range trimmed {",
        "\t\tif c < '0' || c > '9' {",
        "\t\t\tvalid = false",
        "\t\t}",
        "\t}",
        "\tif !valid {",
        "\t\treturn 0, fmt.Errorf(\"%s: expected an unsigned integer, got %s\", name, trimmed)",
        "\t}",
        "\tv, err := strconv.ParseUint(trimmed, 10, 64)",
        "\tif err != nil {",
        "\t\treturn 0, fmt.Errorf(\"%s: expected an unsigned integer in 0..=2^64-1, got %s\", name, trimmed)",
        "\t}",
        "\treturn v, nil",
        "}",
    ],
    "int64": [
        "// {p}Int64 decodes a u64 into a signed 64-bit field. A value past",
        "// 2^63-1 is refused rather than wrapped: a binding that cannot represent a",
        "// wire value exactly must reject the frame (protocol.md § NodeId / PeerId).",
        "func {p}Int64(name string, raw json.RawMessage) (int64, error) {",
        "\tv, err := {p}U64(name, raw)",
        "\tif err != nil {",
        "\t\treturn 0, err",
        "\t}",
        "\tif v > math.MaxInt64 {",
        "\t\treturn 0, fmt.Errorf(\"%s: %d exceeds this binding's int64 range\", name, v)",
        "\t}",
        "\treturn int64(v), nil",
        "}",
        "",
        "// {p}CheckInt64 refuses to encode a negative value as a u64.",
        "func {p}CheckInt64(name string, v int64) error {",
        "\tif v < 0 {",
        "\t\treturn fmt.Errorf(\"%s: %d is negative; the wire type is u64\", name, v)",
        "\t}",
        "\treturn nil",
        "}",
    ],
    "bytes": [
        "// {p}Bytes decodes serialized bytes from a JSON array of u8 (never base64).",
        "func {p}Bytes(name string, raw json.RawMessage) ([]byte, error) {",
        "\titems, err := {p}List(name, raw)",
        "\tif err != nil {",
        "\t\treturn nil, err",
        "\t}",
        "\tout := make([]byte, len(items))",
        "\tfor i, item := range items {",
        "\t\tv, err := {p}U64(name, item)",
        "\t\tif err != nil || v > 255 {",
        "\t\t\treturn nil, fmt.Errorf(\"%s: expected an array of bytes (0..=255), got %s\", name, bytes.TrimSpace(raw))",
        "\t\t}",
        "\t\tout[i] = byte(v)",
        "\t}",
        "\treturn out, nil",
        "}",
        "",
        "// {p}ByteArray encodes bytes as a JSON array of u8; empty is [].",
        "func {p}ByteArray(b []byte) []int {",
        "\tout := make([]int, len(b))",
        "\tfor i, x := range b {",
        "\t\tout[i] = int(x)",
        "\t}",
        "\treturn out",
        "}",
    ],
    "list": [
        "func {p}List(name string, raw json.RawMessage) ([]json.RawMessage, error) {",
        "\ttrimmed := bytes.TrimSpace(raw)",
        "\tif len(trimmed) == 0 || trimmed[0] != '[' {",
        "\t\treturn nil, fmt.Errorf(\"%s: expected an array, got %s\", name, trimmed)",
        "\t}",
        "\tvar items []json.RawMessage",
        "\tif err := json.Unmarshal(trimmed, &items); err != nil {",
        "\t\treturn nil, fmt.Errorf(\"%s: %w\", name, err)",
        "\t}",
        "\treturn items, nil",
        "}",
    ],
}


def _go_ident(snake_name: str) -> str:
    name = pascal(snake_name)
    return "f" + name


def _render_go_unions(surface: dict, target: dict) -> str:
    emitted, bodies = _py_plan(surface, target, "go")
    external: dict[str, str] = target.get("external", {})
    types = _types_by_name(surface)
    variant_fields: dict[str, str] = target.get("variant_fields", {})
    int64: dict[str, str] = target.get("int64", {})
    methods: dict[str, list[dict]] = target.get("interface_methods", {})
    p = target.get("helper_prefix", f"{surface['name']}Wire")
    for t in emitted:
        if t["kind"] == "alias" and t["name"] not in int64:
            raise UnsupportedSchema(f"go: alias {t['name']} needs an `int64` mapping to a hand-written type")
        if t["kind"] == "envelope":
            raise UnsupportedSchema(f"go: envelope {t['name']} is not lowered (set `envelope: false`)")
        if t["kind"] == "enum":
            raise UnsupportedSchema(f"go: enum {t['name']} in a union surface is not lowered yet")
    used: set[str] = {"core"}

    def go_type(expr: dict, slot: str) -> str:
        kind = expr["kind"]
        if kind == "u64":
            if slot in int64:
                used.add("int64")
                return int64[slot]
            return "uint64"
        if kind == "string":
            return "string"
        if kind == "bool":
            raise UnsupportedSchema("go: bool in a union surface is not lowered yet")
        if kind == "bytes":
            return "[]byte"
        if kind == "ref":
            if expr["name"] in int64:
                used.add("int64")
                return int64[expr["name"]]
            return expr["name"]
        if kind == "list":
            return "[]" + go_type(expr["items"], slot)
        if kind == "nullable":
            inner = go_type(expr["inner"], slot)
            return inner if _is_iface(expr["inner"]) else "*" + inner
        raise UnsupportedSchema(f"go: unsupported type kind {kind}")

    def _is_iface(expr: dict) -> bool:
        return expr["kind"] == "ref" and types[expr["name"]]["kind"] == "union"

    def i64_slot(expr: dict, slot: str) -> bool:
        return (expr["kind"] == "u64" and slot in int64) or (expr["kind"] == "ref" and expr["name"] in int64)

    def encode(expr: dict, src: str) -> str:
        kind = expr["kind"]
        if kind == "bytes":
            used.add("bytes")
            return f"{p}ByteArray({src})"
        if kind == "list" and expr["items"]["kind"] != "bytes":
            return f"{p}NonNil({src})"
        return src

    def decode(expr: dict, raw: str, label: str, slot: str, var: str) -> list[str]:
        """Statements assigning the decoded value of `raw` to `var` (declared)."""
        kind = expr["kind"]
        fail = "\t\treturn nil, err"
        if i64_slot(expr, slot):
            return [f'\t{var}, err := {p}Int64("{label}", {raw})', "\tif err != nil {", fail, "\t}"]
        if kind == "u64":
            used.add("u64")
            return [f'\t{var}, err := {p}U64("{label}", {raw})', "\tif err != nil {", fail, "\t}"]
        if kind == "string":
            used.add("string")
            return [f'\t{var}, err := {p}String("{label}", {raw})', "\tif err != nil {", fail, "\t}"]
        if kind == "bytes":
            used.add("bytes")
            used.add("list")
            return [f'\t{var}, err := {p}Bytes("{label}", {raw})', "\tif err != nil {", fail, "\t}"]
        if kind == "ref":
            name = expr["name"]
            if types[name]["kind"] == "union":
                return [f"\t{var}, err := unmarshal{name}({raw})", "\tif err != nil {", fail, "\t}"]
            return [
                f"\tvar {var} {name}",
                f"\tif err := json.Unmarshal({raw}, &{var}); err != nil {{",
                f'\t\treturn nil, fmt.Errorf("{label}: %w", err)',
                "\t}",
            ]
        if kind == "list":
            used.add("list")
            item_type = go_type(expr["items"], slot)
            lines = [
                f'\t{var}Items, err := {p}List("{label}", {raw})',
                "\tif err != nil {",
                fail,
                "\t}",
                f"\t{var} := make([]{item_type}, len({var}Items))",
                f"\tfor i, item := range {var}Items {{",
            ]
            inner = decode(expr["items"], "item", f"{label}[]", slot, "v")
            lines += ["\t" + line for line in inner]
            lines += [f"\t\t{var}[i] = v", "\t}"]
            return lines
        raise UnsupportedSchema(f"go: unsupported type kind {kind}")

    def field_block(owner: str, fields: list[dict]) -> list[str]:
        lines = []
        for f in fields:
            slot = f"{owner}.{f['name']}"
            go_name = pascal(f["name"])
            ftype = go_type(f["type"], slot)
            if f["presence"] == "optional" and not ftype.startswith("*") and not _is_iface(f["type"]):
                ftype = "*" + ftype
            lines += _comment("\t// ", f"{go_name}: {f['doc']}", 80)
            lines.append(f"\t{go_name} {ftype}")
        return lines

    def marshal_body(owner: str, fields: list[dict], recv: str) -> list[str]:
        lines = []
        for f in fields:
            slot = f"{owner}.{f['name']}"
            if i64_slot(f["type"], slot) and f["presence"] == "required":
                lines += [
                    f'\tif err := {p}CheckInt64("{owner}.{f["name"]}", {recv}.{pascal(f["name"])}); err != nil {{',
                    "\t\treturn nil, err",
                    "\t}",
                ]
        lines.append(f"\tfields := []{p}Field{{")
        for f in fields:
            if f["presence"] == "required":
                lines.append(f'\t\t{{"{f["name"]}", {encode(f["type"], recv + "." + pascal(f["name"]))}}},')
        lines.append("\t}")
        for f in fields:
            if f["presence"] == "optional":
                go_name = pascal(f["name"])
                lines += [
                    f"\tif {recv}.{go_name} != nil {{",
                    f'\t\tfields = append(fields, {p}Field{{"{f["name"]}", {recv}.{go_name}}})',
                    "\t}",
                ]
        return lines

    def unmarshal_body(owner: str, fields: list[dict], data: str) -> list[str]:
        req = ", ".join(f'"{f["name"]}"' for f in fields if f["presence"] == "required")
        opt = ", ".join(f'"{f["name"]}"' for f in fields if f["presence"] == "optional")
        lines = [
            f'\tf, err := {p}Fields("{owner}", {data}, []string{{{req}}}, {"[]string{" + opt + "}" if opt else "nil"})',
            "\tif err != nil {",
            "\t\treturn nil, err",
            "\t}",
        ]
        for f in fields:
            var = _go_ident(f["name"])
            slot = f"{owner}.{f['name']}"
            label = f"{owner}.{f['name']}"
            if f["presence"] == "optional":
                inner = f["type"]["inner"] if f["type"]["kind"] == "nullable" else f["type"]
                ftype = go_type(f["type"], slot)
                if not ftype.startswith("*") and not _is_iface(f["type"]):
                    ftype = "*" + ftype
                lines += [
                    f"\tvar {var} {ftype}",
                    f'\tif raw, ok := f["{f["name"]}"]; ok && !{p}IsNull(raw) {{',
                ]
                lines += ["\t" + line for line in decode(inner, "raw", label, slot, "v")]
                lines += [f"\t\t{var} = &v" if ftype.startswith("*") else f"\t\t{var} = v", "\t}"]
            else:
                lines += decode(f["type"], f'f["{f["name"]}"]', label, slot, var)
        return lines

    def construct(name: str, fields: list[dict]) -> str:
        args = ", ".join(f"{pascal(f['name'])}: {_go_ident(f['name'])}" for f in fields)
        return f"{name}{{{args}}}"

    body: list[str] = []
    for t in emitted:
        name = t["name"]
        if t["kind"] == "alias":
            continue
        body.append("")
        if t["kind"] == "union":
            units = [v for v in t["variants"] if v["payload"] is None]
            body += _comment("// ", f"{name}: {t['doc']}", 80)
            body += [f"type {name} interface {{", "\tjson.Marshaler"]
            for m in methods.get(name, []):
                body += _comment("\t// ", m["doc"], 80)
                body.append(f"\t{m['sig']}")
            body += [f"\tis{name}()", "}"]
            body += [
                "",
                f"// unmarshal{name} decodes a {name} strictly: exactly one known variant.",
                f"func unmarshal{name}(raw json.RawMessage) ({name}, error) {{",
            ]
            if units:
                body += [
                    "\ttrimmed := bytes.TrimSpace(raw)",
                    "\tif len(trimmed) > 0 && trimmed[0] == '\"' {",
                    "\t\tvar s string",
                    "\t\tif err := json.Unmarshal(trimmed, &s); err != nil {",
                    "\t\t\treturn nil, err",
                    "\t\t}",
                    "\t\tswitch s {",
                ]
                for v in units:
                    body += [f'\t\tcase "{v["tag"]}":', f"\t\t\treturn {name}{v['tag']}{{}}, nil"]
                body += ["\t\t}", f'\t\treturn nil, fmt.Errorf("unknown {name} unit variant: %s", s)', "\t}"]
            body += [
                f'\ttag, inner, err := {p}Tag("{name}", raw)',
                "\tif err != nil {",
                "\t\treturn nil, err",
                "\t}",
                "\tswitch tag {",
            ]
            for v in t["variants"]:
                if v["payload"] is not None:
                    body += [f'\tcase "{v["tag"]}":', f"\t\treturn unmarshal{name}{v['tag']}(inner)"]
            body += ["\t}", f'\treturn nil, fmt.Errorf("unknown {name} variant: %s", tag)', "}"]
            for v in t["variants"]:
                vname = f"{name}{v['tag']}"
                key = f"{name}.{v['tag']}"
                body.append("")
                body += _comment("// ", f"{vname}: {v['doc']}", 80)
                if v["payload"] is None:
                    body += [
                        f"type {vname} struct{{}}",
                        "",
                        f"func ({vname}) is{name}() {{}}",
                        "",
                        f"// MarshalJSON emits the bare unit tag \"{v['tag']}\".",
                        f'func ({vname}) MarshalJSON() ([]byte, error) {{ return json.Marshal("{v["tag"]}") }}',
                    ]
                    continue
                if key in variant_fields:
                    fname = variant_fields[key]
                    ftype = go_type(v["payload"], key)
                    body += [f"type {vname} struct {{", f"\t{fname} {ftype}", "}"]
                    body += ["", f"func ({vname}) is{name}() {{}}", ""]
                    body += [
                        f"// MarshalJSON emits {{\"{v['tag']}\": ...}}.",
                        f"func (v {vname}) MarshalJSON() ([]byte, error) {{",
                        f'\treturn {p}Tagged("{v["tag"]}", {encode(v["payload"], "v." + fname)})',
                        "}",
                        "",
                        f"func unmarshal{vname}(data json.RawMessage) ({name}, error) {{",
                    ]
                    body += decode(v["payload"], "data", key, key, "value")
                    body += [f"\treturn {vname}{{{fname}: value}}, nil", "}"]
                    continue
                record = types[v["payload"]["name"]]
                body += [f"type {vname} struct {{", *field_block(key, record["fields"]), "}"]
                body += ["", f"func ({vname}) is{name}() {{}}", ""]
                body += [
                    f"// MarshalJSON emits {{\"{v['tag']}\": {{...}}}}, omitting an absent optional field.",
                    f"func (o {vname}) MarshalJSON() ([]byte, error) {{",
                    *marshal_body(key, record["fields"], "o"),
                    f"\tinner, err := {p}Object(fields)",
                    "\tif err != nil {",
                    "\t\treturn nil, err",
                    "\t}",
                    f'\treturn {p}Tagged("{v["tag"]}", json.RawMessage(inner))',
                    "}",
                    "",
                    f"func unmarshal{vname}(data json.RawMessage) ({name}, error) {{",
                    *unmarshal_body(key, record["fields"], "data"),
                    f"\treturn {construct(vname, record['fields'])}, nil",
                    "}",
                ]
        elif t["kind"] == "record":
            fields = t["fields"]
            body += _comment("// ", f"{name}: {t['doc']}", 80)
            body += [f"type {name} struct {{", *field_block(name, fields), "}"]
            un = unmarshal_body(name, fields, "data")
            un = [line.replace("return nil, err", "return err").replace("return nil, fmt.Errorf", "return fmt.Errorf") for line in un]
            body += [
                "",
                f"// MarshalJSON emits {name}, writing absent lists as [] rather than null.",
                f"func (r {name}) MarshalJSON() ([]byte, error) {{",
                *marshal_body(name, fields, "r"),
                f"\treturn {p}Object(fields)",
                "}",
                "",
                f"// UnmarshalJSON decodes {name} strictly: the declared keys only, each well-typed.",
                f"func (r *{name}) UnmarshalJSON(data []byte) error {{",
                *un,
                f"\t*r = {construct(name, fields)}",
                "\treturn nil",
                "}",
            ]
    if any("NonNil" in line for line in body):
        body += [
            "",
            f"// {p}NonNil returns s, or an empty slice when s is nil, so it encodes as [].",
            f"func {p}NonNil[T any](s []T) []T {{",
            "\tif s == nil {",
            "\t\treturn []T{}",
            "\t}",
            "\treturn s",
            "}",
        ]
    if "bytes" in used:
        used.add("list")
    if "int64" in used:
        used.add("u64")
    helpers: list[str] = []
    for key in ("core", "string", "u64", "int64", "bytes", "list"):
        if key in used:
            helpers += [""] + [line.replace("{p}", p) for line in _GO_UNION_HELPERS[key]]
    imports = ["bytes", "encoding/json", "fmt"]
    if "int64" in used:
        imports.append("math")
    imports.append("sort")
    if "u64" in used:
        imports.append("strconv")
    lines = [
        f"// Code generated by lazily-spec {GENERATOR}. DO NOT EDIT.",
        f"// Surface `{surface['name']}` from {surface['schema']}, model sha256:{surface['model_sha256']}.",
        "// Regenerate from lazily-spec with `make wire-codegen`; semantics stay hand-written.",
        "",
        f"package {target['package']}",
        "",
        "import (",
        *[f'\t"{i}"' for i in imports],
        ")",
    ]
    return "\n".join(lines + helpers + body) + "\n"


# ---------------------------------------------------------------------------
# Python backend
# ---------------------------------------------------------------------------

_PY_HELPERS = {
    "object": [
        "def _wire_object(name: str, value: Any, fields: tuple[str, ...]) -> dict[str, Any]:",
        '    """Return ``value`` as a wire object whose keys are exactly ``fields``."""',
        "    if not isinstance(value, dict):",
        '        raise ValueError(f"{name}: expected an object, got {value!r}")',
        "    missing = [key for key in fields if key not in value]",
        "    if missing:",
        '        raise ValueError(f"{name}: missing field {missing[0]!r}")',
        "    unknown = sorted(key for key in value if key not in fields)",
        "    if unknown:",
        '        raise ValueError(f"{name}: unknown field {unknown[0]!r}")',
        "    return value",
    ],
    "string": [
        "def _wire_str(name: str, value: Any) -> str:",
        "    if not isinstance(value, str):",
        '        raise ValueError(f"{name}: expected a string, got {value!r}")',
        "    return value",
    ],
    "u64": [
        "def _wire_u64(name: str, value: Any) -> int:",
        "    if isinstance(value, bool) or not isinstance(value, int):",
        '        raise ValueError(f"{name}: expected an unsigned integer, got {value!r}")',
        "    return value",
    ],
    "bool": [
        "def _wire_bool(name: str, value: Any) -> bool:",
        "    if not isinstance(value, bool):",
        '        raise ValueError(f"{name}: expected a boolean, got {value!r}")',
        "    return value",
    ],
    "object_opt": [
        "def _wire_object_opt(",
        "    name: str, value: Any, required: tuple[str, ...], optional: tuple[str, ...]",
        ") -> dict[str, Any]:",
        '    """Return ``value`` as a wire object: every ``required`` key, any ``optional`` ones."""',
        "    if not isinstance(value, dict):",
        '        raise ValueError(f"{name}: expected an object, got {value!r}")',
        "    missing = [key for key in required if key not in value]",
        "    if missing:",
        '        raise ValueError(f"{name}: missing field {missing[0]!r}")',
        "    unknown = sorted(key for key in value if key not in required and key not in optional)",
        "    if unknown:",
        '        raise ValueError(f"{name}: unknown field {unknown[0]!r}")',
        "    return value",
    ],
    "bytes": [
        "def _wire_bytes(name: str, value: Any) -> bytes:",
        "    if not isinstance(value, list) or not all(",
        "        isinstance(b, int) and not isinstance(b, bool) and 0 <= b <= 255 for b in value",
        "    ):",
        '        raise ValueError(f"{name}: expected an array of bytes (0..=255), got {value!r}")',
        "    return bytes(value)",
    ],
    "list": [
        "def _wire_list(name: str, value: Any) -> list[Any]:",
        "    if not isinstance(value, list):",
        '        raise ValueError(f"{name}: expected an array, got {value!r}")',
        "    return value",
    ],
}


def _py_type(expr: dict) -> str:
    kind = expr["kind"]
    if kind == "string":
        return "str"
    if kind == "bytes":
        return "bytes"
    if kind == "u64":
        return "int"
    if kind == "bool":
        return "bool"
    if kind == "ref":
        return expr["name"]
    if kind == "nullable":
        return f"{_py_type(expr['inner'])} | None"
    if kind == "list":
        return f"list[{_py_type(expr['items'])}]"
    raise UnsupportedSchema(f"python: unsupported type kind {kind}")


def _py_kinds(expr: dict) -> set[str]:
    kinds = {expr["kind"]}
    for key in ("inner", "items"):
        if key in expr:
            kinds |= _py_kinds(expr[key])
    return kinds


def _py_alias_target(expr: dict, types: dict | None) -> dict | None:
    """The scalar an alias ref stands for (``NodeId`` -> u64), else None."""
    if expr["kind"] == "ref" and types and types.get(expr["name"], {}).get("kind") == "alias":
        return types[expr["name"]]["target"]
    return None


def _py_decode(expr: dict, src: str, label: str, depth: int = 0, types: dict | None = None) -> str:
    kind = expr["kind"]
    target = _py_alias_target(expr, types)
    if target is not None:
        return _py_decode(target, src, label, depth, types)
    if kind in ("string", "u64", "bool", "bytes"):
        helper = {"string": "_wire_str", "u64": "_wire_u64", "bool": "_wire_bool", "bytes": "_wire_bytes"}[kind]
        return f'{helper}("{label}", {src})'
    if kind == "ref":
        return f"{expr['name']}.from_wire({src})"
    if kind == "nullable":
        return f"None if {src} is None else {_py_decode(expr['inner'], src, label, depth, types)}"
    if kind == "list":
        item = f"item{depth}" if depth else "item"
        inner = _py_decode(expr["items"], item, f"{label}[]", depth + 1, types)
        return f'[{inner} for {item} in _wire_list("{label}", {src})]'
    raise UnsupportedSchema(f"python: unsupported type kind {kind}")


def _py_encode(expr: dict, src: str, depth: int = 0, types: dict | None = None) -> str:
    kind = expr["kind"]
    target = _py_alias_target(expr, types)
    if target is not None:
        return _py_encode(target, src, depth, types)
    if kind in ("string", "u64", "bool"):
        return src
    if kind == "bytes":
        return f"list({src})"
    if kind == "ref":
        return f"{src}.to_wire()"
    if kind == "nullable":
        inner = _py_encode(expr["inner"], src, depth, types)
        return src if inner == src else f"None if {src} is None else {inner}"
    if kind == "list":
        item = f"item{depth}" if depth else "item"
        inner = _py_encode(expr["items"], item, depth + 1, types)
        return f"list({src})" if inner == item else f"[{inner} for {item} in {src}]"
    raise UnsupportedSchema(f"python: unsupported type kind {kind}")


def _py_constraints(record: str, field: dict, types: dict | None = None) -> list[str]:
    """`__post_init__` checks for the schema constraints a field's type carries."""
    expr = field["type"]
    name = field["name"]
    guard = ""
    if expr["kind"] == "nullable" or field["presence"] == "optional":
        expr = expr["inner"] if expr["kind"] == "nullable" else expr
        guard = f"self.{name} is not None and "
    expr = _py_alias_target(expr, types) or expr
    if any(k in ("u64",) or "min_length" in e for k, e in _walk_nested(expr)):
        raise UnsupportedSchema(f"python: constraints inside lists are not lowered ({record}.{name})")
    if expr["kind"] == "u64":
        return [
            f"        if {guard}not 0 <= self.{name} <= _U64_MAX:",
            f'            raise ValueError(f"{name} must be in 0..=2^64-1, got {{self.{name}}}")',
        ]
    min_length = expr.get("min_length")
    if expr["kind"] == "string" and min_length:
        message = "a non-empty string" if min_length == 1 else f"at least {min_length} characters"
        return [
            f"        if {guard}len(self.{name}) < {min_length}:",
            f'            raise ValueError("{name} must be {message}")',
        ]
    return []


def _walk_nested(expr: dict) -> list[tuple[str, dict]]:
    """Constrained element types nested under a list (top-level constraints are checked)."""
    out = []
    if expr["kind"] == "list":
        stack = [expr["items"]]
        while stack:
            e = stack.pop()
            out.append((e["kind"], e))
            stack.extend(e[k] for k in ("inner", "items") if k in e)
    return out


def _py_docstring(indent: str, text: str) -> list[str]:
    one = f'{indent}"""{text}"""'
    if len(one) <= 88:
        return [one]
    body = textwrap.wrap(text, width=88 - len(indent), break_on_hyphens=False)
    return [f'{indent}"""{body[0]}', *[f"{indent}{line}" for line in body[1:]], f'{indent}"""']


def _py_tuple(const: str, names: list[str]) -> list[str]:
    quoted = [f'"{n}"' for n in names]
    one = f"{const} = ({', '.join(quoted)}{',' if len(quoted) == 1 else ''})"
    if len(one) <= 88:
        return [one]
    return [f"{const} = (", *[f"    {q}," for q in quoted], ")"]


def _py_enum_member(wire: str) -> str:
    return snake(pascal(wire)).upper()


_PY_KINDS = frozenset({"enum", "record", "envelope", "union", "alias"})
_PY_EXPRS = frozenset({"string", "u64", "bool", "ref", "nullable", "list", "bytes"})


def _py_plan(surface: dict, target: dict, backend: str = "python") -> tuple[list[dict], dict[str, dict]]:
    """(declarations to emit in model order, flattened union-variant bodies).

    A union variant whose payload is a record is lowered with the record's fields
    inlined (``DeltaOp_CellSet(node, payload)``), so the body record itself is
    not emitted. Any other payload becomes one field the target names in
    ``variant_fields``. Declarations the target maps to hand-written ``external``
    types, and declarations reachable only through them, are not emitted.
    """
    types = _types_by_name(surface)
    external: dict[str, str] = target.get("external", {})
    variant_fields: dict[str, str] = target.get("variant_fields", {})
    unknown = sorted((set(external) - set(types)) | {k.split(".")[0] for k in variant_fields} - set(types))
    if unknown:
        raise UnsupportedSchema(f"{backend}: target names types the surface does not declare: {unknown}")
    bodies: dict[str, dict] = {}
    for t in surface["types"]:
        if t["kind"] != "union":
            continue
        for v in t["variants"]:
            payload = v["payload"]
            key = f"{t['name']}.{v['tag']}"
            if payload is None:
                if key in variant_fields:
                    raise UnsupportedSchema(f"{backend}: unit variant {key} carries no field to name")
                continue
            ref = payload["name"] if payload["kind"] == "ref" else None
            if key in variant_fields:
                continue
            if ref is None or ref in external or types[ref]["kind"] != "record":
                raise UnsupportedSchema(
                    f"{backend}: variant {key} carries a non-record payload; name its field in `variant_fields`"
                )
            bodies[ref] = types[ref]
    for t in surface["types"]:
        for _label, expr in ([] if t["kind"] == "union" else _type_exprs(t)):
            for ref in _refs(expr):
                if ref in bodies:
                    raise UnsupportedSchema(f"{backend}: {ref} is a flattened variant body and a field type ({t['name']})")

    envelope_on = target.get("envelope", True)
    referenced = {
        ref
        for t in surface["types"]
        for _label, expr in _type_exprs(t)
        for ref in _refs(expr)
    } | {v["type"] for t in surface["types"] if t["kind"] == "envelope" for v in t["variants"]}
    roots = [t["name"] for t in surface["types"] if t["name"] not in referenced]
    if not envelope_on:
        roots = [v["type"] if types[r]["kind"] == "envelope" else r for r in roots for v in (
            types[r]["variants"] if types[r]["kind"] == "envelope" else [{"type": r}]
        )]
    reachable: set[str] = set()
    stack = list(roots)
    while stack:
        name = stack.pop()
        if name in reachable or name in external:
            continue
        reachable.add(name)
        stack.extend(ref for _label, expr in _type_exprs(types[name]) for ref in _refs(expr))
        stack.extend(v["type"] for v in types[name].get("variants", []) if types[name]["kind"] == "envelope")
    emitted = [
        t
        for t in surface["types"]
        if t["name"] in reachable
        and t["name"] not in bodies
        and not (t["kind"] == "envelope" and not envelope_on)
    ]
    _require_lowerable(
        surface,
        backend,
        types=emitted + list(bodies.values()),
        kinds=_PY_KINDS,
        exprs=_PY_EXPRS,
        optional=True,
    )
    for t in emitted:
        if t["kind"] == "alias" and t["target"]["kind"] not in ("string", "u64", "bool"):
            raise UnsupportedSchema(f"{backend}: alias {t['name']} must name a scalar")
    return emitted, bodies


def _py_fields_block(
    owner: str, fields: list[dict], types: dict[str, dict]
) -> tuple[list[str], list[str], bool]:
    """Field declarations, `__post_init__` checks, and whether a list default was used."""
    defaultable = [False] * len(fields)
    for i in range(len(fields) - 1, -1, -1):
        if fields[i]["presence"] == "optional" or fields[i]["type"]["kind"] in ("nullable", "list"):
            defaultable[i] = True
        else:
            break
    decls: list[str] = []
    needs_factory = False
    for f, has_default in zip(fields, defaultable, strict=True):
        py_type = _py_type(f["type"])
        if f["presence"] == "optional" and f["type"]["kind"] != "nullable":
            py_type += " | None"
        decl = f"    {f['name']}: {py_type}"
        if has_default and (f["presence"] == "optional" or f["type"]["kind"] == "nullable"):
            decl += " = None"
        elif has_default:
            decl += " = field(default_factory=list)"
            needs_factory = True
        elif f["presence"] == "optional":
            raise UnsupportedSchema(f"python: optional field {owner}.{f['name']} must follow every required one")
        decls.append(decl)
        decls += _py_docstring("    ", f["doc"])
    checks = [line for f in fields for line in _py_constraints(owner, f, types)]
    return decls, checks, needs_factory


def _py_body_codec(owner: str, fields: list[dict], types: dict[str, dict], src: str) -> tuple[list[str], list[str], str]:
    """(encode lines building ``body``, decode keyword lines, object-check expression)."""
    required = [f for f in fields if f["presence"] == "required"]
    optional = [f for f in fields if f["presence"] == "optional"]
    encode = ["        body: dict[str, Any] = {"]
    encode += [f'            "{f["name"]}": {_py_encode(f["type"], "self." + f["name"], types=types)},' for f in required]
    encode.append("        }")
    for f in optional:
        encode += [
            f"        if self.{f['name']} is not None:",
            f'            body["{f["name"]}"] = {_py_encode(f["type"], "self." + f["name"], types=types)}',
        ]
    decode = []
    for f in fields:
        label = f"{owner}.{f['name']}"
        if f["presence"] == "optional":
            inner = f["type"]["inner"] if f["type"]["kind"] == "nullable" else f["type"]
            got = f'd.get("{f["name"]}")'
            # An optional key may be omitted, and an explicit null reads as absent.
            decode.append(f"            {f['name']}=None if {got} is None else {_py_decode(inner, got, label, types=types)},")
        else:
            decode.append(f"            {f['name']}={_py_decode(f['type'], 'd[' + repr(f['name']).replace(chr(39), chr(34)) + ']', label, types=types)},")
    def tup(fs: list[dict]) -> str:
        names = [f'"{f["name"]}"' for f in fs]
        return f"({names[0]},)" if len(names) == 1 else f"({', '.join(names)})"

    req, opt = tup(required), tup(optional)
    check = f'_wire_object_opt("{owner}", {src}, {req}, {opt})'
    return encode, decode, check


def render_python(surface: dict, target: dict) -> str:
    emitted, bodies = _py_plan(surface, target)
    external: dict[str, str] = target.get("external", {})
    # An external type keeps its own hand-written codec: never resolve it as an alias.
    types = {n: t for n, t in _types_by_name(surface).items() if n not in external}
    variant_fields: dict[str, str] = target.get("variant_fields", {})
    mixins: dict[str, str] = target.get("mixins", {})
    emitted_names = {t["name"] for t in emitted}
    unknown_mixins = sorted(set(mixins) - emitted_names)
    if unknown_mixins:
        raise UnsupportedSchema(f"python: mixins name types the surface does not generate: {unknown_mixins}")
    if mixins and "semantics_module" not in target:
        raise UnsupportedSchema("python: mixins need a `semantics_module`")

    # A single-variant external envelope lowers onto its variant record: the record's
    # codec carries the tag, exactly as the hand-written frame types always have.
    tagged: dict[str, str] = {}
    for t in emitted:
        if t["kind"] != "envelope":
            continue
        (variant,) = t["variants"]
        if types[variant["type"]]["kind"] != "record":
            raise UnsupportedSchema(f"python: envelope {t['name']} must wrap a record")
        for other in surface["types"]:
            for f in other.get("fields", []):
                if variant["type"] in _refs(f["type"]):
                    raise UnsupportedSchema(
                        f"python: {variant['type']} is an envelope variant and a field type ({other['name']}.{f['name']})"
                    )
        tagged[variant["type"]] = variant["tag"]

    records = [t for t in emitted if t["kind"] == "record"]
    enums = [t for t in emitted if t["kind"] == "enum"]
    unions = [t for t in emitted if t["kind"] == "union"]
    kinds: set[str] = set()
    for t in [*records, *bodies.values()]:
        for f in t["fields"]:
            kinds |= _py_kinds(f["type"])
            target_expr = _py_alias_target(f["type"], types)
            if target_expr is not None:
                kinds |= _py_kinds(target_expr)
    for t in unions:
        for v in t["variants"]:
            if v["payload"] is not None and f"{t['name']}.{v['tag']}" in variant_fields:
                kinds |= _py_kinds(v["payload"])
    has_u64 = "u64" in kinds
    needs_factory = False
    needs_object = any(all(f["presence"] == "required" for f in t["fields"]) for t in records)
    needs_object_opt = bool(bodies) or any(f["presence"] == "optional" for t in records for f in t["fields"])

    body: list[str] = []
    for t in emitted:
        name = t["name"]
        bases = ", ".join([*([mixins[name]] if name in mixins else []), *(["Enum"] if t["kind"] == "enum" else [])])
        if t["kind"] == "alias":
            body += ["", ""]
            body += _comment("#: ", t["doc"], 88)
            body.append(f"{name} = {_py_type(t['target'])}")
        elif t["kind"] == "enum":
            body += ["", "", f"class {name}({bases}):"]
            body += _py_docstring("    ", t["doc"])
            body.append("")
            for v in t["values"]:
                body.append(f'    {_py_enum_member(v["wire"])} = "{v["wire"]}"')
                body += _py_docstring("    ", v["doc"])
            expected = "/".join(v["wire"] for v in t["values"])
            body += [
                "",
                "    @classmethod",
                f"    def from_wire(cls, value: Any) -> {name}:",
                '        """Parse a wire string, rejecting unknown values."""',
                "        for member in cls:",
                "            if member.value == value:",
                "                return member",
                "        raise ValueError(",
                f'            f"unknown {name}: {{value!r}} (expected one of {expected})"',
                "        )",
                "",
                "    def to_wire(self) -> str:",
                "        return self.value",
            ]
        elif t["kind"] == "union":
            units = [v for v in t["variants"] if v["payload"] is None]
            body += ["", "", f"class {name}({bases}):" if bases else f"class {name}:"]
            body += _py_docstring("    ", t["doc"])
            body += [
                "",
                "    __slots__ = ()",
                "",
                "    def to_wire(self) -> Any:  # pragma: no cover - every variant overrides it",
                "        raise NotImplementedError",
                "",
                "    @staticmethod",
                f"    def from_wire(value: Any) -> {name}:",
                '        """Decode strictly: exactly one known, externally-tagged variant."""',
            ]
            if units:
                body.append("        if isinstance(value, str):")
                for v in units:
                    body += [f'            if value == "{v["tag"]}":', f"                return {name}_{v['tag']}()"]
                body.append(f'            raise ValueError(f"unknown {name} unit variant: {{value!r}}")')
            body += [
                "        if not isinstance(value, dict) or len(value) != 1:",
                f'            raise ValueError(f"{name}: expected a single-key object, got {{value!r}}")',
                "        ((tag, body),) = value.items()",
            ]
            for v in t["variants"]:
                if v["payload"] is not None:
                    body += [f'        if tag == "{v["tag"]}":', f"            return {name}_{v['tag']}._from_body(body)"]
            body.append(f'        raise ValueError(f"unknown {name} variant: {{tag!r}}")')
            for v in t["variants"]:
                vname = f"{name}_{v['tag']}"
                key = f"{name}.{v['tag']}"
                body += ["", "", "@dataclass(frozen=True, slots=True)", f"class {vname}({name}):"]
                body += _py_docstring("    ", v["doc"])
                if v["payload"] is None:
                    body += ["", "    def to_wire(self) -> str:", f'        return "{v["tag"]}"']
                    continue
                if key in variant_fields:
                    fname = variant_fields[key]
                    pseudo = {"name": fname, "doc": v["doc"], "presence": "required", "type": v["payload"]}
                    decls, checks, used_factory = _py_fields_block(key, [pseudo], types)
                    needs_factory |= used_factory
                    body += ["", decls[0]]
                    if checks:
                        body += ["", "    def __post_init__(self) -> None:", *checks]
                    body += [
                        "",
                        "    def to_wire(self) -> dict[str, Any]:",
                        f'        return {{"{v["tag"]}": {_py_encode(v["payload"], "self." + fname, types=types)}}}',
                        "",
                        "    @classmethod",
                        f"    def _from_body(cls, value: Any) -> {vname}:",
                        f"        return cls({fname}={_py_decode(v['payload'], 'value', key, types=types)})",
                    ]
                    continue
                record = types[v["payload"]["name"]]
                decls, checks, used_factory = _py_fields_block(key, record["fields"], types)
                needs_factory |= used_factory
                body += ["", *decls]
                if checks:
                    body += ["", "    def __post_init__(self) -> None:", *checks]
                encode, decode, check = _py_body_codec(key, record["fields"], types, "value")
                body += [
                    "",
                    "    def to_wire(self) -> dict[str, Any]:",
                    *encode,
                    f'        return {{"{v["tag"]}": body}}',
                    "",
                    "    @classmethod",
                    f"    def _from_body(cls, value: Any) -> {vname}:",
                    f"        d = {check}",
                    "        return cls(",
                    *decode,
                    "        )",
                ]
        elif t["kind"] == "record" and any(f["presence"] == "optional" for f in t["fields"]):
            if name in tagged:
                raise UnsupportedSchema(f"python: tagged record {name} with optional fields is not lowered")
            decls, checks, used_factory = _py_fields_block(name, t["fields"], types)
            needs_factory |= used_factory
            body += ["", "", "@dataclass(frozen=True, slots=True)", f"class {name}({bases}):" if bases else f"class {name}:"]
            body += _py_docstring("    ", t["doc"])
            body += ["", *decls]
            if checks:
                body += ["", "    def __post_init__(self) -> None:", *checks]
            encode, decode, check = _py_body_codec(name, t["fields"], types, "value")
            body += [
                "",
                "    def to_wire(self) -> dict[str, Any]:",
                *encode,
                "        return body",
                "",
                "    @classmethod",
                f"    def from_wire(cls, value: Any) -> {name}:",
                '        """Decode strictly: the declared keys only, each well-typed."""',
                f"        d = {check}",
                "        return cls(",
                *decode,
                "        )",
            ]
        elif t["kind"] == "record":
            fields = t["fields"]
            const = f"_{snake(name).upper()}_FIELDS"
            body += ["", "", *_py_tuple(const, [f["name"] for f in fields])]
            body += ["", "", "@dataclass(frozen=True, slots=True)", f"class {name}({bases}):" if bases else f"class {name}:"]
            body += _py_docstring("    ", t["doc"])
            body.append("")
            decls, checks, used_factory = _py_fields_block(name, fields, types)
            needs_factory |= used_factory
            body += decls
            if checks:
                body += ["", "    def __post_init__(self) -> None:", *checks]
            encoded = [f'            "{f["name"]}": {_py_encode(f["type"], "self." + f["name"], types=types)},' for f in fields]
            if name in tagged:
                tag = tagged[name]
                body += [
                    "",
                    "    def to_wire(self) -> dict[str, Any]:",
                    f'        """Encode the externally-tagged ``{tag}`` frame."""',
                    "        body = {",
                    *encoded,
                    "        }",
                    f'        return {{"{tag}": body}}',
                ]
                envelope = next(e["name"] for e in emitted if e["kind"] == "envelope")
                prelude = [
                    f'        tagged = _wire_object("{envelope}", value, ("{tag}",))',
                    f'        d = _wire_object("{name}", tagged["{tag}"], {const})',
                ]
                doc = f'        """Decode the externally-tagged ``{tag}`` frame strictly."""'
            else:
                body += [
                    "",
                    "    def to_wire(self) -> dict[str, Any]:",
                    "        return {",
                    *encoded,
                    "        }",
                ]
                prelude = [f'        d = _wire_object("{name}", value, {const})']
                doc = '        """Decode strictly: exactly the declared keys, each well-typed."""'
            decoded = []
            for f in fields:
                src = 'd["' + f["name"] + '"]'
                decoded.append(f"            {f['name']}={_py_decode(f['type'], src, name + '.' + f['name'], types=types)},")
            body += [
                "",
                "    @classmethod",
                f"    def from_wire(cls, value: Any) -> {name}:",
                doc,
                *prelude,
                "        return cls(",
                *decoded,
                "        )",
            ]

    helpers: list[str] = []
    if needs_object or tagged:
        helpers += ["", "", *_PY_HELPERS["object"]]
    if needs_object_opt:
        helpers += ["", "", *_PY_HELPERS["object_opt"]]
    for kind in ("string", "u64", "bool", "bytes", "list"):
        if kind in kinds:
            helpers += ["", "", *_PY_HELPERS[kind]]

    header = [
        f"# @generated by lazily-spec {GENERATOR}. DO NOT EDIT.",
        f"# Surface `{surface['name']}` from {surface['schema']},",
        f"# model sha256:{surface['model_sha256']}.",
        "# Regenerate from lazily-spec with `make wire-codegen`; semantics stay hand-written.",
        "# fmt: off",
        f'"""Generated wire types for the `{surface["name"]}` surface."""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass, field" if needs_factory else "from dataclasses import dataclass",
    ]
    if enums:
        header.append("from enum import Enum")
    header.append("from typing import Any")
    imports: dict[str, list[str]] = {}
    for type_name, module in external.items():
        if any(type_name in _refs(expr) for t in [*emitted, *bodies.values()] for _l, expr in _type_exprs(t)):
            imports.setdefault(module, []).append(type_name)
    if mixins:
        imports.setdefault(target["semantics_module"], []).extend(mixins.values())
    if imports:
        header.append("")
        header += [f"from {module} import {', '.join(sorted(set(names)))}" for module, names in sorted(imports.items())]
    if has_u64:
        header += ["", "", "_U64_MAX = 0xFFFF_FFFF_FFFF_FFFF"]
    return "\n".join(header + helpers + body) + "\n"


# ---------------------------------------------------------------------------
# Kotlin backend
# ---------------------------------------------------------------------------

_KT_KEYWORDS = frozenset(
    "as break class continue do else false for fun if in interface is null object package return "
    "super this throw true try typealias typeof val var when while".split()
)


def _kt_name(wire: str) -> str:
    name = pascal(wire)
    name = name[:1].lower() + name[1:]
    if name in _KT_KEYWORDS:
        raise UnsupportedSchema(f"kotlin: wire name {wire!r} lowers to the keyword {name!r}")
    return name


def _kt_type(expr: dict) -> str:
    kind = expr["kind"]
    if kind == "string":
        return "String"
    if kind == "u64":
        return "ULong"
    if kind == "bool":
        return "Boolean"
    if kind == "ref":
        return expr["name"]
    if kind == "nullable":
        return f"{_kt_type(expr['inner'])}?"
    if kind == "list":
        return f"List<{_kt_type(expr['items'])}>"
    raise UnsupportedSchema(f"kotlin: unsupported type kind {kind}")


def _kt_kinds(expr: dict) -> set[str]:
    kinds = {expr["kind"]}
    for key in ("inner", "items"):
        if key in expr:
            kinds |= _kt_kinds(expr[key])
    return kinds


def _kt_encode(expr: dict, src: str, types: dict[str, dict], depth: int = 0) -> str:
    kind = expr["kind"]
    if kind in ("string", "u64", "bool"):
        return f"JsonPrimitive({src})"
    if kind == "ref":
        if types[expr["name"]]["kind"] == "enum":
            return f"JsonPrimitive({src}.wireName)"
        return f"{src}.toJson()"
    if kind == "nullable":
        inner = _kt_encode(expr["inner"], "it", types, depth)
        return f"{src}?.let {{ {inner} }} ?: JsonNull"
    if kind == "list":
        item = f"item{depth}" if depth else "item"
        inner = _kt_encode(expr["items"], item, types, depth + 1)
        return f"JsonArray({src}.map {{ {item} -> {inner} }})"
    raise UnsupportedSchema(f"kotlin: unsupported type kind {kind}")


def _kt_decode(expr: dict, src: str, label: str, types: dict[str, dict], helper: str, depth: int = 0) -> str:
    kind = expr["kind"]
    if kind in ("string", "u64", "bool"):
        fn = {"string": "String", "u64": "U64", "bool": "Boolean"}[kind]
        return f'{helper}{fn}("{label}", {src})'
    if kind == "ref":
        if types[expr["name"]]["kind"] == "enum":
            return f'{expr["name"]}.fromWire({helper}String("{label}", {src}))'
        return f"{expr['name']}.fromJson({src})"
    if kind == "nullable":
        value = f"value{depth}" if depth else "value"
        inner = _kt_decode(expr["inner"], value, label, types, helper, depth + 1)
        return f"{src}.let {{ {value} -> if ({value} is JsonNull) null else {inner} }}"
    if kind == "list":
        item = f"item{depth}" if depth else "item"
        inner = _kt_decode(expr["items"], item, f"{label}[]", types, helper, depth + 1)
        return f'{helper}List("{label}", {src}).map {{ {item} -> {inner} }}'
    raise UnsupportedSchema(f"kotlin: unsupported type kind {kind}")


def _kt_constraints(record: str, field: dict) -> list[str]:
    """`init` checks for the schema constraints a field's type carries (u64 is the type itself)."""
    expr = field["type"]
    name = _kt_name(field["name"])
    guard = ""
    if expr["kind"] == "nullable":
        expr = expr["inner"]
        guard = f"{name} == null || "
    if any("min_length" in e for _, e in _walk_nested(expr)):
        raise UnsupportedSchema(f"kotlin: constraints inside lists are not lowered ({record}.{field['name']})")
    min_length = expr.get("min_length")
    if expr["kind"] == "string" and min_length:
        message = "a non-empty string" if min_length == 1 else f"at least {min_length} characters"
        return [f'        require({guard}{name}.length >= {min_length}) {{ "{field["name"]} must be {message}" }}']
    return []


def _kt_kdoc(indent: str, text: str) -> list[str]:
    one = f"{indent}/** {text} */"
    if len(one) <= 120:
        return [one]
    body = textwrap.wrap(text, width=120 - len(indent) - 3, break_on_hyphens=False)
    return [f"{indent}/**", *[f"{indent} * {line}" for line in body], f"{indent} */"]


_KT_HELPERS = {
    "object": [
        "private fun {h}Object(",
        "    name: String,",
        "    value: JsonElement,",
        "    fields: List<String>,",
        "): JsonObject {",
        '    val obj = value as? JsonObject ?: throw IllegalArgumentException("$name: expected an object, got $value")',
        '    fields.firstOrNull { it !in obj }?.let { throw IllegalArgumentException("$name: missing field \\"$it\\"") }',
        '    obj.keys.filter { it !in fields }.minOrNull()?.let { throw IllegalArgumentException("$name: unknown field \\"$it\\"") }',
        "    return obj",
        "}",
    ],
    "string": [
        "private fun {h}String(",
        "    name: String,",
        "    value: JsonElement,",
        "): String {",
        "    val primitive = value as? JsonPrimitive",
        "    if (primitive == null || !primitive.isString) {",
        '        throw IllegalArgumentException("$name: expected a string, got $value")',
        "    }",
        "    return primitive.content",
        "}",
    ],
    "u64": [
        "private val {h}U64Literal = Regex(\"0|[1-9][0-9]*\")",
        "",
        "private fun {h}U64(",
        "    name: String,",
        "    value: JsonElement,",
        "): ULong {",
        "    val primitive = value as? JsonPrimitive",
        "    val literal = primitive?.takeUnless { it.isString }?.content",
        "    return literal?.takeIf { {h}U64Literal.matches(it) }?.toULongOrNull()",
        '        ?: throw IllegalArgumentException("$name: expected an unsigned integer, got $value")',
        "}",
    ],
    "bool": [
        "private fun {h}Boolean(",
        "    name: String,",
        "    value: JsonElement,",
        "): Boolean {",
        "    val primitive = value as? JsonPrimitive",
        "    return when (primitive?.takeUnless { it.isString }?.content) {",
        '        "true" -> true',
        '        "false" -> false',
        '        else -> throw IllegalArgumentException("$name: expected a boolean, got $value")',
        "    }",
        "}",
    ],
    "list": [
        "private fun {h}List(",
        "    name: String,",
        "    value: JsonElement,",
        "): JsonArray = value as? JsonArray ?: throw IllegalArgumentException(\"$name: expected an array, got $value\")",
    ],
}


def render_kotlin(surface: dict, target: dict) -> str:
    _require_lowerable(surface, "kotlin")
    types = _types_by_name(surface)
    helper = _kt_name(surface["name"]) + "Wire"
    variant_fields: dict[str, str] = target.get("variant_fields", {})

    kinds: set[str] = set()
    for t in surface["types"]:
        for f in t.get("fields", []):
            kinds |= _kt_kinds(f["type"])
            # An enum decodes through the string helper.
            if any(types[ref]["kind"] == "enum" for ref in _refs(f["type"])):
                kinds.add("string")
    records = [t for t in surface["types"] if t["kind"] == "record"]
    envelopes = [t for t in surface["types"] if t["kind"] == "envelope"]

    body: list[str] = []
    for t in surface["types"]:
        name = t["name"]
        body.append("")
        body += _kt_kdoc("", t["doc"])
        if t["kind"] == "enum":
            body += [f"enum class {name}(", "    val wireName: String,", ") {"]
            for i, v in enumerate(t["values"]):
                # ktlint separates documented enum entries with a blank line.
                body += ([""] if i else []) + _kt_kdoc("    ", v["doc"])
                body.append(f'    {pascal(v["wire"])}("{v["wire"]}"),')
            body += [
                "    ;",
                "",
                "    companion object {",
                "        /** Parse a wire string, rejecting unknown values. */",
                f"        fun fromWire(value: String): {name} =",
                "            entries.firstOrNull { it.wireName == value }",
                f'                ?: throw IllegalArgumentException("unknown {name}: \\"$value\\"")',
                "    }",
                "}",
            ]
        elif t["kind"] == "record":
            fields = t["fields"]
            defaultable = [False] * len(fields)
            for i in range(len(fields) - 1, -1, -1):
                if fields[i]["type"]["kind"] in ("nullable", "list"):
                    defaultable[i] = True
                else:
                    break
            body.append(f"data class {name}(")
            for f, has_default in zip(fields, defaultable, strict=True):
                body += _kt_kdoc("    ", f["doc"])
                decl = f"    val {_kt_name(f['name'])}: {_kt_type(f['type'])}"
                if has_default:
                    decl += " = null" if f["type"]["kind"] == "nullable" else " = emptyList()"
                body.append(decl + ",")
            body.append(") {")
            checks = [line for f in fields for line in _kt_constraints(name, f)]
            if checks:
                body += ["    init {", *checks, "    }", ""]
            body += [
                "    /** Encode the wire object; every declared key is emitted, `null` when absent. */",
                "    fun toJson(): JsonObject =",
                "        buildJsonObject {",
            ]
            for f in fields:
                body.append(f'            put("{f["name"]}", {_kt_encode(f["type"], _kt_name(f["name"]), types)})')
            body += [
                "        }",
                "",
                "    companion object {",
                f"        private val FIELDS = listOf({', '.join(chr(34) + f['name'] + chr(34) for f in fields)})",
                "",
                "        /** Decode strictly: exactly the declared keys, each well-typed. */",
                f"        fun fromJson(element: JsonElement): {name} {{",
                f'            val obj = {helper}Object("{name}", element, FIELDS)',
                f"            return {name}(",
            ]
            for f in fields:
                src = f'obj.getValue("{f["name"]}")'
                label = f"{name}.{f['name']}"
                body.append(f"                {_kt_name(f['name'])} = {_kt_decode(f['type'], src, label, types, helper)},")
            body += ["            )", "        }", "    }", "}"]
        elif t["kind"] == "envelope":
            body += [
                f"sealed interface {name} {{",
                "    /** Encode the externally-tagged wire object. */",
                "    fun toJson(): JsonObject",
                "",
                "    /** Encode this message as compact JSON bytes. */",
                "    fun encodeJson(): ByteArray = toJson().toString().encodeToByteArray()",
            ]
            for variant in t["variants"]:
                tag, vtype = variant["tag"], variant["type"]
                if types[vtype]["kind"] != "record":
                    raise UnsupportedSchema(f"kotlin: envelope {name} must wrap records ({tag})")
                field = variant_fields.get(tag, "value")
                body += [
                    "",
                    f"    /** `{tag}` envelope variant. */",
                    f"    data class {tag}Message(",
                    f"        val {field}: {vtype},",
                    f"    ) : {name} {{",
                    f'        override fun toJson(): JsonObject = buildJsonObject {{ put("{tag}", {field}.toJson()) }}',
                    "    }",
                ]
            body += [
                "",
                "    companion object {",
                "        /** Decode JSON bytes strictly. */",
                f"        fun decodeJson(data: ByteArray): {name} = decodeJson(data.decodeToString())",
                "",
                "        /** Decode a JSON string strictly. */",
                f"        fun decodeJson(data: String): {name} = fromJson(Json.parseToJsonElement(data))",
                "",
                "        /** Decode strictly: exactly one known variant tag. */",
                f"        fun fromJson(element: JsonElement): {name} {{",
                f'            val obj = element as? JsonObject ?: throw IllegalArgumentException("{name}: expected an object, got $element")',
                f'            require(obj.size == 1) {{ "{name}: expected exactly one variant tag, got ${{obj.keys.sorted()}}" }}',
                "            val (tag, body) = obj.entries.single()",
                "            return when (tag) {",
                *[
                    f'                "{v["tag"]}" -> {v["tag"]}Message({v["type"]}.fromJson(body))'
                    for v in t["variants"]
                ],
                f'                else -> throw IllegalArgumentException("{name}: unknown variant \\"$tag\\"")',
                "            }",
                "        }",
                "    }",
                "}",
            ]

    helpers: list[str] = []
    if records:
        helpers += ["", *(line.replace("{h}", helper) for line in _KT_HELPERS["object"])]
    for kind in ("string", "u64", "bool", "list"):
        if kind in kinds:
            helpers += ["", *(line.replace("{h}", helper) for line in _KT_HELPERS[kind])]

    imports = {"kotlinx.serialization.json.JsonElement", "kotlinx.serialization.json.JsonObject"}
    if records or envelopes:
        imports.add("kotlinx.serialization.json.buildJsonObject")
    if envelopes:
        imports.add("kotlinx.serialization.json.Json")
    if kinds & {"string", "u64", "bool", "ref"}:
        imports.add("kotlinx.serialization.json.JsonPrimitive")
    if "nullable" in kinds:
        imports.add("kotlinx.serialization.json.JsonNull")
    if "list" in kinds:
        imports.add("kotlinx.serialization.json.JsonArray")
    header = [
        f"// @generated by lazily-spec {GENERATOR}. DO NOT EDIT.",
        f"// Surface `{surface['name']}` from {surface['schema']}, model sha256:{surface['model_sha256']}.",
        "// Regenerate from lazily-spec with `make wire-codegen`; semantics stay hand-written.",
    ]
    if "u64" in kinds:
        # JsonPrimitive(ULong) is experimental in kotlinx.serialization.
        header += ["@file:OptIn(ExperimentalSerializationApi::class)"]
        imports.add("kotlinx.serialization.ExperimentalSerializationApi")
    header += ["", f"package {target['package']}", ""]
    header += [f"import {i}" for i in sorted(imports)]
    return "\n".join(header + helpers + body) + "\n"


BACKENDS = {"rust": render_rust, "go": render_go, "python": render_python, "kotlin": render_kotlin}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def generated_targets(
    model: dict, manifest: dict, workspace: Path = WORKSPACE_SRC
) -> list[tuple[str, Path, Path, str]]:
    """(label, repo root, destination, content) for every binding target in the manifest."""
    surfaces = {s["name"]: s for s in model["surfaces"]}
    out = []
    for entry in manifest["surfaces"]:
        surface = surfaces[entry["name"]]
        for backend, target in entry["targets"].items():
            content = BACKENDS[backend](surface, target)
            repo_root = workspace / target["repo"]
            label = f"{entry['name']}:{backend} -> {target['repo']}/{target['path']}"
            out.append((label, repo_root, repo_root / target["path"], content))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail on any drift")
    mode.add_argument("--write", action="store_true", help="regenerate the golden model and present siblings")
    parser.add_argument("--require-all", action="store_true", help="fail when a sibling checkout is absent")
    args = parser.parse_args(argv)

    try:
        model = build_model()
        targets = generated_targets(model, load_manifest(), WORKSPACE_SRC)
    except UnsupportedSchema as exc:
        print(f"wire-codegen: {exc}", file=sys.stderr)
        return 1

    rendered = render_model(model)
    failures = []
    if args.write:
        GOLDEN_MODEL.write_text(rendered)
        print(f"wrote {GOLDEN_MODEL.relative_to(SPEC_ROOT)}")
    elif not GOLDEN_MODEL.exists() or GOLDEN_MODEL.read_text() != rendered:
        failures.append("codegen/wire-model.json is stale; run `make wire-codegen`")

    for label, repo_root, dest, content in targets:
        if not repo_root.is_dir():
            message = f"staged: {label} (sibling checkout absent)"
            if args.require_all:
                failures.append(message)
            else:
                print(message)
            continue
        if args.write:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
            print(f"wrote {label}")
        elif not dest.exists() or dest.read_text() != content:
            failures.append(f"drift: {label} differs from the generated output; run `make wire-codegen`")
        else:
            print(f"ok: {label}")

    for failure in failures:
        print(f"wire-codegen: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
