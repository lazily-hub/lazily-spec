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


class _SurfaceBuilder:
    def __init__(self, name: str, schema_path: str, schema: dict) -> None:
        self.name = name
        self.schema_path = schema_path
        self.schema = schema
        self.defs: dict[str, dict] = schema.get("$defs", {})
        self.types: list[dict] = []

    def _def_kind(self, def_name: str) -> str:
        node = self.defs.get(def_name)
        if node is None:
            raise UnsupportedSchema(f"{self.schema_path}: unresolved $ref to {def_name!r}")
        if _nullable_inner(node) is not None:
            return "alias"
        if node.get("type") == "string" and "enum" in node:
            return "enum"
        if node.get("type") == "object":
            return "record"
        raise UnsupportedSchema(f"{self.schema_path}#/$defs/{def_name}: unsupported definition shape")

    def type_expr(self, node: dict, where: str) -> dict:
        if "$ref" in node:
            ref = node["$ref"]
            prefix = "#/$defs/"
            if not isinstance(ref, str) or not ref.startswith(prefix):
                raise UnsupportedSchema(f"{where}: only local #/$defs/ references are modelled ({ref!r})")
            def_name = ref[len(prefix) :]
            if self._def_kind(def_name) == "alias":
                return self.type_expr(self.defs[def_name], f"{where} -> {def_name}")
            return {"kind": "ref", "name": def_name}
        inner = _nullable_inner(node)
        if inner is not None:
            return {"kind": "nullable", "inner": self.type_expr(inner, where)}
        kind = node.get("type")
        if kind == "string" and "enum" not in node and "const" not in node:
            expr: dict[str, Any] = {"kind": "string"}
            if "minLength" in node:
                expr["min_length"] = node["minLength"]
            return expr
        if kind == "integer":
            if node.get("minimum") != 0:
                raise UnsupportedSchema(f"{where}: only non-negative integers (minimum: 0 -> u64) are modelled")
            return {"kind": "u64"}
        if kind == "boolean":
            return {"kind": "bool"}
        if kind == "array" and isinstance(node.get("items"), dict):
            return {"kind": "list", "items": self.type_expr(node["items"], f"{where}[]")}
        raise UnsupportedSchema(f"{where}: unsupported type shape {json.dumps(node, sort_keys=True)}")

    def enum_type(self, name: str, node: dict) -> dict:
        where = f"{self.schema_path}#/$defs/{name}"
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
            fields.append(
                {
                    "name": field_name,
                    "doc": _require_doc(field_node, field_where),
                    "presence": "required" if field_name in required else "optional",
                    "type": self.type_expr(field_node, field_where),
                }
            )
        return {
            "name": name,
            "kind": "record",
            "closed": True,
            "doc": _require_doc(node, where),
            "fields": fields,
        }

    def build(self) -> dict:
        for def_name, node in self.defs.items():
            kind = self._def_kind(def_name)
            if kind == "enum":
                self.types.append(self.enum_type(def_name, node))
            elif kind == "record":
                self.types.append(self.record_type(def_name, node, f"{self.schema_path}#/$defs/{def_name}"))

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

        names = [t["name"] for t in self.types]
        if len(names) != len(set(names)):
            raise UnsupportedSchema(f"{self.schema_path}: duplicate generated type names {names}")
        known = set(names)
        for t in self.types:
            for field in t.get("fields", []):
                for ref in _refs(field["type"]):
                    if ref not in known:
                        raise UnsupportedSchema(f"{self.schema_path}: {t['name']}.{field['name']} names unknown {ref}")
        return {"name": self.name, "schema": self.schema_path, "types": self.types}


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
    return _SurfaceBuilder(name, schema_path, schema).build()


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


def _require_lowerable(surface: dict, backend: str) -> None:
    for t in surface["types"]:
        if t["kind"] == "enum" and t["open"]:
            raise UnsupportedSchema(f"{backend}: open enums are modelled but not yet lowered ({t['name']})")
        for field in t.get("fields", []):
            if field["presence"] != "required":
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
    raise UnsupportedSchema(f"rust: unsupported type kind {kind}")


def _required_nullable(field: dict) -> bool:
    return field["presence"] == "required" and field["type"]["kind"] == "nullable"


def render_rust(surface: dict, target: dict) -> str:
    _require_lowerable(surface, "rust")
    lines = [
        f"// @generated by lazily-spec {GENERATOR}. DO NOT EDIT.",
        f"// Surface `{surface['name']}` from {surface['schema']}, model sha256:{surface['model_sha256']}.",
        "// Regenerate from lazily-spec with `make wire-codegen`; semantics stay hand-written.",
    ]
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
            lines.append("#[derive(Debug, Clone, PartialEq, Eq)]")
            lines.append(RUST_SERDE)
            lines.append('#[cfg_attr(feature = "serde", serde(deny_unknown_fields))]')
            lines.append(f"pub struct {t['name']} {{")
            for field in t["fields"]:
                lines.extend(_comment("    /// ", field["doc"], 100))
                if _required_nullable(field):
                    lines.append('    #[cfg_attr(feature = "serde", serde(deserialize_with = "required_nullable"))]')
                lines.append(f"    pub {field['name']}: {_rust_type(field['type'])},")
            lines.append("}")
        elif t["kind"] == "envelope":
            lines.append("#[derive(Debug, Clone, PartialEq, Eq)]")
            lines.append(RUST_SERDE)
            lines.append(f"pub enum {t['name']} {{")
            for variant in t["variants"]:
                lines.append(f"    /// `{variant['tag']}` envelope variant.")
                lines.append(f"    {variant['tag']}({variant['type']}),")
            lines.append("}")
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


def _py_decode(expr: dict, src: str, label: str, depth: int = 0) -> str:
    kind = expr["kind"]
    if kind in ("string", "u64", "bool"):
        helper = {"string": "_wire_str", "u64": "_wire_u64", "bool": "_wire_bool"}[kind]
        return f'{helper}("{label}", {src})'
    if kind == "ref":
        return f"{expr['name']}.from_wire({src})"
    if kind == "nullable":
        return f"None if {src} is None else {_py_decode(expr['inner'], src, label, depth)}"
    if kind == "list":
        item = f"item{depth}" if depth else "item"
        inner = _py_decode(expr["items"], item, f"{label}[]", depth + 1)
        return f'[{inner} for {item} in _wire_list("{label}", {src})]'
    raise UnsupportedSchema(f"python: unsupported type kind {kind}")


def _py_encode(expr: dict, src: str, depth: int = 0) -> str:
    kind = expr["kind"]
    if kind in ("string", "u64", "bool"):
        return src
    if kind == "ref":
        return f"{src}.to_wire()"
    if kind == "nullable":
        inner = _py_encode(expr["inner"], src, depth)
        return src if inner == src else f"None if {src} is None else {inner}"
    if kind == "list":
        item = f"item{depth}" if depth else "item"
        inner = _py_encode(expr["items"], item, depth + 1)
        return f"list({src})" if inner == item else f"[{inner} for {item} in {src}]"
    raise UnsupportedSchema(f"python: unsupported type kind {kind}")


def _py_constraints(record: str, field: dict) -> list[str]:
    """`__post_init__` checks for the schema constraints a field's type carries."""
    expr = field["type"]
    name = field["name"]
    guard = ""
    if expr["kind"] == "nullable":
        expr = expr["inner"]
        guard = f"self.{name} is not None and "
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


def render_python(surface: dict, target: dict) -> str:
    _require_lowerable(surface, "python")
    types = _types_by_name(surface)
    mixins: dict[str, str] = target.get("mixins", {})
    unknown_mixins = sorted(set(mixins) - set(types))
    if unknown_mixins:
        raise UnsupportedSchema(f"python: mixins name types the surface does not generate: {unknown_mixins}")
    if mixins and "semantics_module" not in target:
        raise UnsupportedSchema("python: mixins need a `semantics_module`")

    # A single-variant external envelope lowers onto its variant record: the record's
    # codec carries the tag, exactly as the hand-written frame types always have.
    tagged: dict[str, str] = {}
    for t in surface["types"]:
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

    records = [t for t in surface["types"] if t["kind"] == "record"]
    enums = [t for t in surface["types"] if t["kind"] == "enum"]
    kinds: set[str] = set()
    for t in records:
        for f in t["fields"]:
            kinds |= _py_kinds(f["type"])
    has_u64 = "u64" in kinds
    needs_factory = False

    body: list[str] = []
    for t in surface["types"]:
        name = t["name"]
        bases = ", ".join([*([mixins[name]] if name in mixins else []), *(["Enum"] if t["kind"] == "enum" else [])])
        if t["kind"] == "enum":
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
        elif t["kind"] == "record":
            fields = t["fields"]
            defaultable = [False] * len(fields)
            for i in range(len(fields) - 1, -1, -1):
                if fields[i]["type"]["kind"] in ("nullable", "list"):
                    defaultable[i] = True
                else:
                    break
            const = f"_{snake(name).upper()}_FIELDS"
            body += ["", "", *_py_tuple(const, [f["name"] for f in fields])]
            body += ["", "", "@dataclass(frozen=True, slots=True)", f"class {name}({bases}):" if bases else f"class {name}:"]
            body += _py_docstring("    ", t["doc"])
            body.append("")
            for f, has_default in zip(fields, defaultable, strict=True):
                decl = f"    {f['name']}: {_py_type(f['type'])}"
                if has_default and f["type"]["kind"] == "nullable":
                    decl += " = None"
                elif has_default:
                    decl += " = field(default_factory=list)"
                    needs_factory = True
                body.append(decl)
                body += _py_docstring("    ", f["doc"])
            checks = [line for f in fields for line in _py_constraints(name, f)]
            if checks:
                body += ["", "    def __post_init__(self) -> None:", *checks]
            encoded = [f'            "{f["name"]}": {_py_encode(f["type"], "self." + f["name"])},' for f in fields]
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
                envelope = next(e["name"] for e in surface["types"] if e["kind"] == "envelope")
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
                decoded.append(f"            {f['name']}={_py_decode(f['type'], src, name + '.' + f['name'])},")
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
    if records:
        helpers += ["", "", *_PY_HELPERS["object"]]
    for kind in ("string", "u64", "bool", "list"):
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
    if mixins:
        header += ["", f"from {target['semantics_module']} import {', '.join(sorted(mixins.values()))}"]
    if has_u64:
        header += ["", "", "_U64_MAX = 0xFFFF_FFFF_FFFF_FFFF"]
    return "\n".join(header + helpers + body) + "\n"


BACKENDS = {"rust": render_rust, "go": render_go, "python": render_python}


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
