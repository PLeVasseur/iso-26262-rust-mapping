from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from docutils import nodes
from docutils.parsers.rst import Directive, directives
from jsonschema import Draft202012Validator
from sphinx.application import Sphinx
from sphinx.domains import Domain
from sphinx.environment import BuildEnvironment
from sphinx.errors import ExtensionError
from sphinx.roles import SphinxRole
from sphinx.util import logging

LOGGER = logging.getLogger(__name__)

TRACE_STATUSES = {
    "mapped",
    "unmapped_with_rationale",
    "out_of_scope_with_rationale",
}


class dp_node(nodes.Inline, nodes.TextElement):
    pass


class ts_node(nodes.Inline, nodes.TextElement):
    pass


class a_node(nodes.Inline, nodes.TextElement):
    pass


class rel_node(nodes.Inline, nodes.TextElement):
    pass


class p_node(nodes.Inline, nodes.TextElement):
    pass


@dataclass
class PrefaceMetadata:
    source_id: str
    trace_status: str
    anchor_ids: list[str]
    relation: str
    inline_body: str


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def _statement_anchor_from_source_id(source_id: str) -> str:
    return _slug(source_id)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_jsonc(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8")
    stripped = re.sub(r"//.*$", "", raw, flags=re.MULTILINE)
    return json.loads(stripped)


def _ensure_env(env: BuildEnvironment) -> None:
    if not hasattr(env, "iso26262_trace_records"):
        env.iso26262_trace_records = {}
    if not hasattr(env, "iso26262_trace_order"):
        env.iso26262_trace_order = []
    if not hasattr(env, "iso26262_trace_errors"):
        env.iso26262_trace_errors = []
    if not hasattr(env, "iso26262_doc_statement_ids"):
        env.iso26262_doc_statement_ids = {}
    if not hasattr(env, "iso26262_doc_missing_units"):
        env.iso26262_doc_missing_units = {}
    if not hasattr(env, "iso26262_statement_locations"):
        env.iso26262_statement_locations = {}
    if not hasattr(env, "iso26262_anchor_registry_ids"):
        env.iso26262_anchor_registry_ids = set()


def _record_error(env: BuildEnvironment, message: str) -> None:
    _ensure_env(env)
    env.iso26262_trace_errors.append(message)


def _register_record(
    env: BuildEnvironment, record: dict[str, Any], source_context: str
) -> None:
    _ensure_env(env)
    source_id = record["id"]
    existing = env.iso26262_trace_records.get(source_id)
    if existing is not None:
        existing_doc = existing.get("doc", "<unknown>")
        _record_error(
            env,
            f"duplicate source_id '{source_id}' in {source_context}; "
            f"first seen in {existing_doc}",
        )
        return

    env.iso26262_trace_records[source_id] = record
    env.iso26262_trace_order.append(source_id)
    href = record.get("href", "")
    env.iso26262_statement_locations[source_id] = href


def _extract_preface(paragraph: nodes.paragraph) -> PrefaceMetadata | None:
    source_ids: list[str] = []
    statuses: list[str] = []
    anchor_ids: list[str] = []
    relations: list[str] = []
    has_non_metadata_content = False
    has_any_metadata = False

    for child in paragraph.children:
        if isinstance(child, dp_node):
            has_any_metadata = True
            source_ids.append(child.astext().strip())
            continue
        if isinstance(child, ts_node):
            has_any_metadata = True
            statuses.append(child.astext().strip())
            continue
        if isinstance(child, a_node):
            has_any_metadata = True
            value = child.astext().strip()
            if value:
                anchor_ids.append(value)
            continue
        if isinstance(child, rel_node):
            has_any_metadata = True
            value = child.astext().strip()
            if value:
                relations.append(value)
            continue
        if isinstance(child, p_node):
            has_any_metadata = True
            has_non_metadata_content = True
            continue
        if isinstance(child, nodes.Text):
            if child.astext().strip():
                has_non_metadata_content = True
            continue
        has_non_metadata_content = True

    if (
        has_any_metadata
        and (not has_non_metadata_content)
        and len(source_ids) == 1
        and len(statuses) == 1
    ):
        return PrefaceMetadata(
            source_id=source_ids[0],
            trace_status=statuses[0],
            anchor_ids=anchor_ids,
            relation=relations[0] if relations else "",
            inline_body="",
        )

    raw = (paragraph.rawsource or "").strip()
    role_preface_pattern = (
        r"^\{dp\}`(?P<sid>[^`]+)`\s+\{ts\}`(?P<status>[^`]+)`"
        r"(?:\s+\{rel\}`(?P<rel>[^`]+)`)?"
        r"(?:\s+\{a\}`(?P<aid>[^`]+)`)?"
        r"(?:\n(?P<body>[\s\S]+))?$"
    )
    role_preface = re.match(role_preface_pattern, raw)
    if role_preface:
        sid = role_preface.group("sid").strip()
        status = role_preface.group("status").strip()
        relation = (role_preface.group("rel") or "").strip()
        anchor = (role_preface.group("aid") or "").strip()
        body = (role_preface.group("body") or "").strip()
        return PrefaceMetadata(
            source_id=sid,
            trace_status=status,
            anchor_ids=[anchor] if anchor else [],
            relation=relation,
            inline_body=body,
        )

    text = paragraph.astext().strip()
    plain_preface_pattern = (
        r"^(?P<sid>SRCN-[A-Za-z0-9-]+)\s+"
        r"(?P<status>mapped|unmapped_with_rationale|out_of_scope_with_rationale)"
        r"(?:\n(?P<body>[\s\S]+)|\s+(?P<rest>.+))?$"
    )
    plain_preface = re.match(plain_preface_pattern, text)
    if plain_preface:
        sid = plain_preface.group("sid").strip()
        status = plain_preface.group("status").strip()
        rest = (plain_preface.group("rest") or "").strip()
        body = (plain_preface.group("body") or "").strip()
        return PrefaceMetadata(
            source_id=sid,
            trace_status=status,
            anchor_ids=[],
            relation=rest,
            inline_body=body,
        )

    return None


def _is_markdown_statement_node(node: nodes.Node) -> bool:
    if isinstance(node, nodes.paragraph):
        if isinstance(node.parent, nodes.entry):
            return False
        return bool(node.astext().strip())
    if isinstance(node, nodes.list_item):
        return bool(node.astext().strip())
    return False


def _set_paragraph_text(paragraph: nodes.paragraph, text: str) -> None:
    paragraph.children = []
    for index, line in enumerate(text.splitlines()):
        if index > 0:
            paragraph += nodes.Text("\n")
        paragraph += nodes.Text(line)


def _bind_prefaces(
    app: Sphinx, env: BuildEnvironment, docname: str, container: nodes.Element
) -> None:
    if not hasattr(container, "children"):
        return

    children = list(container.children)
    rebuilt: list[nodes.Node] = []
    idx = 0

    while idx < len(children):
        node = children[idx]
        if isinstance(node, nodes.paragraph):
            metadata = _extract_preface(node)
            if metadata is not None:
                inline_target = isinstance(node, nodes.paragraph) and bool(
                    metadata.inline_body
                )
                if inline_target:
                    _set_paragraph_text(node, metadata.inline_body)
                    target = node
                    source_id = metadata.source_id
                    trace_status = metadata.trace_status
                    if trace_status not in TRACE_STATUSES:
                        _record_error(
                            env,
                            f"invalid trace status '{trace_status}' "
                            f"for {source_id} in {docname}",
                        )

                    if trace_status == "mapped" and not metadata.anchor_ids:
                        _record_error(
                            env,
                            f"mapped statement '{source_id}' in {docname} "
                            "has no anchor_ids",
                        )
                    if trace_status == "mapped" and not metadata.relation:
                        _record_error(
                            env,
                            f"mapped statement '{source_id}' in {docname} "
                            "has no relation",
                        )

                    anchor_id = _statement_anchor_from_source_id(source_id)
                    target_ids = target.setdefault("ids", [])
                    if anchor_id not in target_ids:
                        target_ids.append(anchor_id)

                    target["trace_source_id"] = source_id
                    target["trace_status"] = trace_status
                    target["trace_anchor_ids"] = metadata.anchor_ids
                    target["trace_relation"] = metadata.relation

                    statement_text = target.astext().strip()
                    record = {
                        "id": source_id,
                        "unit_type": "paragraph",
                        "display_number": "",
                        "doc": docname,
                        "href": f"{docname}.html#{anchor_id}",
                        "checksum": _sha256_text(statement_text),
                        "trace_status": trace_status,
                        "anchor_ids": metadata.anchor_ids,
                        "relation": metadata.relation,
                        "source_locator": {
                            "kind": "markdown",
                            "path": f"src/{docname}.md",
                        },
                    }
                    _register_record(env, record, f"{docname} inline metadata preface")
                    env.iso26262_doc_statement_ids.setdefault(docname, []).append(
                        source_id
                    )

                    rebuilt.append(node)
                    idx += 1
                    continue

                if idx + 1 >= len(children):
                    _record_error(env, f"orphan metadata preface in {docname}")
                    idx += 1
                    continue

                target = children[idx + 1]
                if not _is_markdown_statement_node(target):
                    _record_error(
                        env,
                        f"metadata preface in {docname} is not directly above a "
                        "markdown statement unit",
                    )
                    idx += 1
                    continue

                source_id = metadata.source_id
                trace_status = metadata.trace_status
                if trace_status not in TRACE_STATUSES:
                    _record_error(
                        env,
                        f"invalid trace status '{trace_status}' "
                        f"for {source_id} in {docname}",
                    )

                if trace_status == "mapped" and not metadata.anchor_ids:
                    _record_error(
                        env,
                        f"mapped statement '{source_id}' in {docname} "
                        "has no anchor_ids",
                    )
                if trace_status == "mapped" and not metadata.relation:
                    _record_error(
                        env,
                        f"mapped statement '{source_id}' in {docname} "
                        "has no relation",
                    )

                anchor_id = _statement_anchor_from_source_id(source_id)
                target_ids = target.setdefault("ids", [])
                if anchor_id not in target_ids:
                    target_ids.append(anchor_id)

                target["trace_source_id"] = source_id
                target["trace_status"] = trace_status
                target["trace_anchor_ids"] = metadata.anchor_ids
                target["trace_relation"] = metadata.relation

                unit_type = (
                    "paragraph" if isinstance(target, nodes.paragraph) else "list_item"
                )
                statement_text = target.astext().strip()
                href = f"{docname}.html#{anchor_id}"

                record = {
                    "id": source_id,
                    "unit_type": unit_type,
                    "display_number": "",
                    "doc": docname,
                    "href": href,
                    "checksum": _sha256_text(statement_text),
                    "trace_status": trace_status,
                    "anchor_ids": metadata.anchor_ids,
                    "relation": metadata.relation,
                    "source_locator": {
                        "kind": "markdown",
                        "path": f"src/{docname}.md",
                    },
                }
                _register_record(env, record, f"{docname} markdown preface")
                env.iso26262_doc_statement_ids.setdefault(docname, []).append(source_id)

                idx += 1
                continue

        if isinstance(node, nodes.Element):
            _bind_prefaces(app, env, docname, node)
        rebuilt.append(node)
        idx += 1

    container.children = rebuilt


def _collect_missing_units(
    env: BuildEnvironment, docname: str, doctree: nodes.document
) -> None:
    missing: list[str] = []
    for paragraph in doctree.traverse(nodes.paragraph):
        if isinstance(paragraph.parent, nodes.entry):
            continue
        text = paragraph.astext().strip()
        if not text:
            continue
        if paragraph.get("trace_source_id"):
            continue
        missing.append(text)

    for list_item in doctree.traverse(nodes.list_item):
        text = list_item.astext().strip()
        if not text:
            continue
        if list_item.get("trace_source_id"):
            continue
        # If the list item contains a traced paragraph, treat it as covered.
        traced_child = any(
            isinstance(child, nodes.paragraph) and child.get("trace_source_id")
            for child in list_item.children
        )
        if not traced_child:
            missing.append(text)

    env.iso26262_doc_missing_units[docname] = missing


def _load_anchor_registry(app: Sphinx, env: BuildEnvironment) -> None:
    _ensure_env(env)
    registry_path = Path(app.config.iso26262_anchor_registry_path)
    if not registry_path.exists():
        _record_error(env, f"anchor registry missing: {registry_path}")
        return

    try:
        payload = _read_jsonc(registry_path)
    except Exception as exc:
        _record_error(env, f"failed to parse anchor registry {registry_path}: {exc}")
        return

    anchors: set[str] = set()
    for item in payload.get("anchors", []):
        if isinstance(item, dict):
            anchor_id = str(item.get("anchor_id", "")).strip()
            if anchor_id:
                anchors.add(anchor_id)

    env.iso26262_anchor_registry_ids = anchors


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _emit_trace_outputs(app: Sphinx, env: BuildEnvironment) -> None:
    _ensure_env(env)
    outdir = Path(app.outdir)
    paragraph_ids_path = outdir / "paragraph-ids.json"

    records: list[dict[str, Any]] = []
    for idx, source_id in enumerate(env.iso26262_trace_order, start=1):
        record = dict(env.iso26262_trace_records[source_id])
        record["display_number"] = str(idx)
        records.append(record)

    paragraph_payload = {
        "schema_version": 1,
        "records": records,
    }
    _write_json(paragraph_ids_path, paragraph_payload)

    schema_path = (
        Path(app.config.iso26262_opencode_config_dir)
        / "reports"
        / "schemas"
        / "paragraph-ids.schema.json"
    )
    schema_validation_result = {
        "schema_path": str(schema_path),
        "paragraph_ids_path": str(paragraph_ids_path),
        "valid": True,
        "errors": [],
    }

    if schema_path.exists():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
            errors = sorted(
                validator.iter_errors(paragraph_payload),
                key=lambda err: list(err.absolute_path),
            )
            if errors:
                schema_validation_result["valid"] = False
                schema_validation_result["errors"] = [err.message for err in errors]
                for err in errors:
                    _record_error(
                        env, f"paragraph-ids schema validation error: {err.message}"
                    )
        except Exception as exc:
            schema_validation_result["valid"] = False
            schema_validation_result["errors"] = [
                f"schema validation execution failed: {exc}"
            ]
            _record_error(
                env, f"paragraph-ids schema validation failed to execute: {exc}"
            )
    else:
        schema_validation_result["valid"] = False
        schema_validation_result["errors"] = ["schema file missing"]
        _record_error(env, f"paragraph-ids schema file missing: {schema_path}")

    status_counts = {
        "mapped": 0,
        "unmapped_with_rationale": 0,
        "out_of_scope_with_rationale": 0,
    }
    unit_counts = {
        "markdown_preface_units": 0,
        "table_cell_units": 0,
        "table_row_units": 0,
    }

    for record in records:
        status = record.get("trace_status", "")
        if status in status_counts:
            status_counts[status] += 1
        unit_type = record.get("unit_type")
        if unit_type in {"paragraph", "list_item"}:
            unit_counts["markdown_preface_units"] += 1
        elif unit_type == "table_cell":
            unit_counts["table_cell_units"] += 1
        elif unit_type == "table_row":
            unit_counts["table_row_units"] += 1

    total = len(records)
    coverage_json = {
        "schema_version": 1,
        "total": total,
        **status_counts,
        **unit_counts,
    }

    mapped_count = status_counts["mapped"]
    unmapped_with_rationale_count = status_counts["unmapped_with_rationale"]
    out_of_scope_with_rationale_count = status_counts["out_of_scope_with_rationale"]

    coverage_md = (
        "\n".join(
            [
                "# Traceability Statement Coverage",
                "",
                f"- total: {total}",
                f"- mapped: {mapped_count}",
                f"- unmapped_with_rationale: {unmapped_with_rationale_count}",
                f"- out_of_scope_with_rationale: {out_of_scope_with_rationale_count}",
                f"- markdown_preface_units: {unit_counts['markdown_preface_units']}",
                f"- table_cell_units: {unit_counts['table_cell_units']}",
                f"- table_row_units: {unit_counts['table_row_units']}",
                "",
                f"- paragraph_ids_json: `{paragraph_ids_path}`",
            ]
        )
        + "\n"
    )

    run_root_raw = app.config.iso26262_run_root
    opencode_config_dir_raw = app.config.iso26262_opencode_config_dir
    if run_root_raw:
        run_root = Path(run_root_raw)
        _write_json(run_root / "traceability-statement-coverage.json", coverage_json)
        _write_text(run_root / "traceability-statement-coverage.md", coverage_md)

        _write_json(
            run_root
            / "artifacts"
            / "traceability"
            / "paragraph-ids-schema-validation.json",
            schema_validation_result,
        )
        table_audit = {
            "table_cell_record_count": unit_counts["table_cell_units"],
            "table_row_record_count": unit_counts["table_row_units"],
            "canonical_anchor_pattern": "<table_label>--r-<row_id>--c-<col_key>",
        }
        _write_json(
            run_root
            / "artifacts"
            / "traceability"
            / "paragraph-ids-table-entry-audit.json",
            table_audit,
        )

        source_to_anchor_stats = {
            "record_count": total,
            "mapped_count": status_counts["mapped"],
            "unmapped_count": status_counts["unmapped_with_rationale"],
            "out_of_scope_count": status_counts["out_of_scope_with_rationale"],
        }
        _write_json(
            run_root / "artifacts" / "indexes" / "source_to_anchor.stats.json",
            source_to_anchor_stats,
        )
        anchor_to_source_stats = {
            "known_anchor_count": len(env.iso26262_anchor_registry_ids),
            "mapped_record_count": status_counts["mapped"],
        }
        _write_json(
            run_root / "artifacts" / "indexes" / "anchor_to_source.stats.json",
            anchor_to_source_stats,
        )

    if opencode_config_dir_raw:
        reports_root = Path(opencode_config_dir_raw) / "reports"
        _write_json(
            reports_root / "traceability-statement-coverage-latest.json", coverage_json
        )
        _write_text(
            reports_root / "traceability-statement-coverage-latest.md", coverage_md
        )


class _BaseTraceRole(SphinxRole):
    node_class: type[nodes.Node]

    def run(self) -> tuple[list[nodes.Node], list[nodes.system_message]]:
        text = self.text.strip()
        node = self.node_class(text, text)
        return [node], []


class DpRole(_BaseTraceRole):
    node_class = dp_node


class TsRole(_BaseTraceRole):
    node_class = ts_node


class ARole(_BaseTraceRole):
    node_class = a_node


class RelRole(_BaseTraceRole):
    node_class = rel_node


class PRole(_BaseTraceRole):
    node_class = p_node


class TraceMetaDirective(Directive):
    has_content = False
    required_arguments = 0
    option_spec = {
        "dp": directives.unchanged_required,
        "ts": directives.unchanged_required,
        "a": directives.unchanged,
        "rel": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        paragraph = nodes.paragraph()
        paragraph += dp_node(self.options["dp"], self.options["dp"])
        paragraph += nodes.Text(" ")
        paragraph += ts_node(self.options["ts"], self.options["ts"])
        anchors_raw = self.options.get("a", "")
        for anchor in [
            value.strip() for value in anchors_raw.split(",") if value.strip()
        ]:
            paragraph += nodes.Text(" ")
            paragraph += a_node(anchor, anchor)
        relation = self.options.get("rel", "").strip()
        if relation:
            paragraph += nodes.Text(" ")
            paragraph += rel_node(relation, relation)
        return [paragraph]


class IsoTableDirective(Directive):
    has_content = False
    required_arguments = 1
    option_spec = {
        "caption": directives.unchanged_required,
        "label": directives.unchanged_required,
        "class": directives.class_option,
        "name": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        env: BuildEnvironment = self.state.document.settings.env
        app = env.app
        _ensure_env(env)

        table_id = self.arguments[0].strip()
        caption = self.options.get("caption", "").strip()
        label = self.options.get("label", "").strip()
        if not caption:
            raise self.error("iso-table requires :caption: option")
        if not label:
            raise self.error("iso-table requires :label: option")

        table_root = Path(app.config.iso26262_table_root)
        table_path = table_root / f"{table_id}.yaml"
        if not table_path.exists():
            raise self.error(f"table file not found: {table_path}")

        payload = yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
        columns = payload.get("columns") or []
        rows = payload.get("rows") or []
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise self.error(f"invalid table structure in {table_path}")

        table_node = nodes.table()
        table_node["classes"].append("iso-table")
        if "class" in self.options:
            table_node["classes"].extend(self.options["class"])
        table_node["ids"].append(label)
        if "name" in self.options:
            table_node["names"].append(self.options["name"])

        title = nodes.title(text=caption)
        table_node += title

        tgroup = nodes.tgroup(cols=len(columns))
        table_node += tgroup
        for _ in columns:
            tgroup += nodes.colspec(colwidth=1)

        thead = nodes.thead()
        tgroup += thead
        head_row = nodes.row()
        thead += head_row

        col_keys: list[str] = []
        for column in columns:
            key = str(column.get("key", "")).strip()
            col_keys.append(key)
            title_text = str(column.get("title", key))
            entry = nodes.entry()
            entry += nodes.paragraph(text=title_text)
            head_row += entry

        tbody = nodes.tbody()
        tgroup += tbody

        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("row_id", "")).strip()
            if not row_id:
                _record_error(env, f"table '{table_id}' has row without row_id")
                row_id = "missing-row-id"
            row_slug = _slug(row_id)

            row_node = nodes.row()
            tbody += row_node
            row_trace = (
                row.get("_trace") if isinstance(row.get("_trace"), dict) else None
            )
            cell_trace = (
                row.get("cell_trace") if isinstance(row.get("cell_trace"), dict) else {}
            )

            row_anchor = f"{_slug(label)}--r-{row_slug}"
            if isinstance(row_trace, dict):
                row_source_id = str(row_trace.get("source_id", "")).strip()
                row_status = str(row_trace.get("trace_status", "")).strip()
                row_anchor_ids = [
                    str(item).strip()
                    for item in row_trace.get("anchor_ids", [])
                    if str(item).strip()
                ]
                row_relation = str(row_trace.get("relation", "")).strip()
                if row_source_id and row_status:
                    row_record = {
                        "id": row_source_id,
                        "unit_type": "table_row",
                        "display_number": "",
                        "doc": env.docname,
                        "href": f"{env.docname}.html#{row_anchor}",
                        "checksum": _sha256_text(
                            "|".join(str(row.get(key, "")) for key in col_keys)
                        ),
                        "trace_status": row_status,
                        "anchor_ids": row_anchor_ids,
                        "relation": row_relation,
                        "source_locator": {
                            "kind": "table_row",
                            "path": str(table_path),
                            "table_id": table_id,
                            "row_id": row_id,
                        },
                    }
                    _register_record(env, row_record, f"{table_id} row _trace")

            for index, key in enumerate(col_keys):
                value = row.get(key, "")
                text = str(value)
                entry = nodes.entry()
                if index == 0:
                    entry["ids"].append(row_anchor)

                paragraph = nodes.paragraph(text=text)
                entry += paragraph

                if text.strip():
                    meta = cell_trace.get(key)
                    if not isinstance(meta, dict):
                        _record_error(
                            env,
                            f"table '{table_id}' row '{row_id}' col '{key}' "
                            "missing cell_trace metadata",
                        )
                        meta = {}

                    source_id = str(meta.get("source_id", "")).strip()
                    trace_status = str(meta.get("trace_status", "")).strip()
                    anchor_ids = [
                        str(item).strip()
                        for item in meta.get("anchor_ids", [])
                        if str(item).strip()
                    ]
                    relation = str(meta.get("relation", "")).strip()

                    if not source_id:
                        _record_error(
                            env,
                            f"table '{table_id}' row '{row_id}' col '{key}' "
                            "missing source_id",
                        )
                    if not trace_status:
                        _record_error(
                            env,
                            f"table '{table_id}' row '{row_id}' col '{key}' "
                            "missing trace_status",
                        )
                    if trace_status == "mapped" and not anchor_ids:
                        _record_error(
                            env,
                            f"mapped table cell '{table_id}:{row_id}:{key}' "
                            "missing anchor_ids",
                        )
                    if trace_status == "mapped" and not relation:
                        _record_error(
                            env,
                            f"mapped table cell '{table_id}:{row_id}:{key}' "
                            "missing relation",
                        )

                    col_slug = _slug(key)
                    cell_anchor = f"{_slug(label)}--r-{row_slug}--c-{col_slug}"
                    entry["ids"].append(cell_anchor)

                    if source_id:
                        record = {
                            "id": source_id,
                            "unit_type": "table_cell",
                            "display_number": "",
                            "doc": env.docname,
                            "href": f"{env.docname}.html#{cell_anchor}",
                            "checksum": _sha256_text(text),
                            "trace_status": trace_status or "unmapped_with_rationale",
                            "anchor_ids": anchor_ids,
                            "relation": relation,
                            "source_locator": {
                                "kind": "table_cell",
                                "path": str(table_path),
                                "table_id": table_id,
                                "row_id": row_id,
                                "col_key": key,
                            },
                        }
                        _register_record(env, record, f"{table_id} cell_trace")

                row_node += entry

        return [table_node]


class TraceDomain(Domain):
    name = "trace"
    label = "Traceability"
    roles: dict[str, Any] = {}
    directives: dict[str, Any] = {}
    initial_data = {
        "objects": {},
    }

    def clear_doc(self, docname: str) -> None:
        stale = [
            key
            for key, value in self.data.get("objects", {}).items()
            if value[0] == docname
        ]
        for key in stale:
            del self.data["objects"][key]

    def merge_domaindata(self, docnames: list[str], otherdata: dict[str, Any]) -> None:
        self.data.setdefault("objects", {}).update(otherdata.get("objects", {}))

    def get_objects(self) -> list[tuple[str, str, str, str, str, int]]:
        objects = []
        for name, value in self.data.get("objects", {}).items():
            docname, anchor = value
            objects.append((name, name, "statement", docname, anchor, 1))
        return objects


def _on_builder_inited(app: Sphinx) -> None:
    _ensure_env(app.builder.env)
    _load_anchor_registry(app, app.builder.env)


def _on_env_purge_doc(app: Sphinx, env: BuildEnvironment, docname: str) -> None:
    _ensure_env(env)
    for source_id in list(env.iso26262_trace_records.keys()):
        record = env.iso26262_trace_records[source_id]
        if record.get("doc") == docname:
            env.iso26262_trace_records.pop(source_id, None)
            env.iso26262_statement_locations.pop(source_id, None)
            if source_id in env.iso26262_trace_order:
                env.iso26262_trace_order.remove(source_id)
    env.iso26262_doc_statement_ids.pop(docname, None)
    env.iso26262_doc_missing_units.pop(docname, None)


def _on_env_merge_info(
    app: Sphinx, env: BuildEnvironment, docnames: list[str], other: BuildEnvironment
) -> None:
    _ensure_env(env)
    _ensure_env(other)
    for source_id in other.iso26262_trace_order:
        record = other.iso26262_trace_records[source_id]
        _register_record(env, record, "parallel-merge")
    env.iso26262_trace_errors.extend(other.iso26262_trace_errors)
    env.iso26262_doc_statement_ids.update(other.iso26262_doc_statement_ids)
    env.iso26262_doc_missing_units.update(other.iso26262_doc_missing_units)
    env.iso26262_statement_locations.update(other.iso26262_statement_locations)
    env.iso26262_anchor_registry_ids.update(other.iso26262_anchor_registry_ids)


def _on_doctree_read(app: Sphinx, doctree: nodes.document) -> None:
    env = app.builder.env
    _ensure_env(env)
    _bind_prefaces(app, env, env.docname, doctree)
    _collect_missing_units(env, env.docname, doctree)


def _on_doctree_resolved(app: Sphinx, doctree: nodes.document, docname: str) -> None:
    env = app.builder.env
    _ensure_env(env)

    for ref in list(doctree.traverse(p_node)):
        target_id = ref.astext().strip()
        href = env.iso26262_statement_locations.get(target_id, "")
        if not href:
            _record_error(
                env, f"unresolved statement reference '{{p}}`{target_id}`' in {docname}"
            )
            ref.replace_self(nodes.literal(text=target_id))
            continue
        reference = nodes.reference(text=target_id, refuri=href)
        ref.replace_self(reference)

    for anchor_ref in list(doctree.traverse(a_node)):
        target_anchor = anchor_ref.astext().strip()
        if target_anchor and target_anchor not in env.iso26262_anchor_registry_ids:
            _record_error(
                env,
                f"unknown ISO anchor reference '{{a}}`{target_anchor}`' in {docname}",
            )
        anchor_ref.replace_self(nodes.literal(text=target_anchor))


def _on_build_finished(app: Sphinx, exception: Exception | None) -> None:
    env = app.builder.env
    _ensure_env(env)
    _emit_trace_outputs(app, env)

    if exception is None and env.iso26262_trace_errors:
        sample = "\n- " + "\n- ".join(env.iso26262_trace_errors[:10])
        raise ExtensionError(f"traceability errors detected:{sample}")


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_config_value("iso26262_trace_statuses", sorted(TRACE_STATUSES), "env")
    app.add_config_value("iso26262_trace_schema_path", "", "env")
    app.add_config_value("iso26262_anchor_registry_path", "", "env")
    app.add_config_value("iso26262_table_root", "", "env")
    app.add_config_value("iso26262_run_root", "", "env")
    app.add_config_value("iso26262_opencode_config_dir", "", "env")

    app.add_domain(TraceDomain)

    app.add_role("dp", DpRole())
    app.add_role("ts", TsRole())
    app.add_role("trace-status", TsRole())
    app.add_role("a", ARole())
    app.add_role("rel", RelRole())
    app.add_role("p", PRole())

    app.add_directive("trace-meta", TraceMetaDirective)
    app.add_directive("iso-table", IsoTableDirective)

    app.connect("builder-inited", _on_builder_inited)
    app.connect("env-purge-doc", _on_env_purge_doc)
    app.connect("env-merge-info", _on_env_merge_info)
    app.connect("doctree-read", _on_doctree_read)
    app.connect("doctree-resolved", _on_doctree_resolved)
    app.connect("build-finished", _on_build_finished)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
        "env_version": 1,
    }
