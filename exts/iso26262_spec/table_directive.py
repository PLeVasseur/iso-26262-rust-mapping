from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from docutils import nodes
from docutils.parsers.rst import Directive, directives
from sphinx.environment import BuildEnvironment

from .record_store import _ensure_env, _record_error, _register_record
from .utils import _sha256_text, _slug

IRM_ID_RE = re.compile(r"^irm_[A-Za-z0-9]{12}$")


def _read_trace_id(
    env: BuildEnvironment,
    meta: dict[str, Any],
    *,
    strict_mode: bool,
    context: str,
) -> str:
    has_irm_id = "irm_id" in meta
    has_legacy_key = "source_id" in meta

    if strict_mode and has_legacy_key:
        _record_error(
            env,
            f"{context} uses legacy key 'source_id'; use 'irm_id' in strict mode",
        )

    trace_id = ""
    if has_irm_id:
        trace_id = str(meta.get("irm_id", "")).strip()
    elif has_legacy_key:
        trace_id = str(meta.get("source_id", "")).strip()

    if strict_mode and trace_id and not IRM_ID_RE.match(trace_id):
        _record_error(
            env,
            f"{context} has invalid IRM ID '{trace_id}' "
            "(expected pattern irm_[A-Za-z0-9]{12})",
        )

    return trace_id


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
        strict_mode = bool(getattr(app.config, "iso26262_irm_id_strict_mode", False))

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
            raw_cell_trace = row.get("cell_trace")
            if isinstance(raw_cell_trace, dict):
                cell_trace_map: dict[str, Any] = raw_cell_trace
            else:
                cell_trace_map = {}

            row_anchor = f"{_slug(label)}--r-{row_slug}"
            if isinstance(row_trace, dict):
                row_trace_meta = row_trace
                row_trace_id = _read_trace_id(
                    env,
                    row_trace_meta,
                    strict_mode=strict_mode,
                    context=f"table '{table_id}' row '{row_id}' _trace",
                )
                row_status = str(row_trace_meta.get("trace_status", "")).strip()
                row_anchor_ids = [
                    str(item).strip()
                    for item in row_trace_meta.get("anchor_ids", [])
                    if str(item).strip()
                ]
                row_relation = str(row_trace_meta.get("relation", "")).strip()

                if strict_mode and not row_trace_id:
                    _record_error(
                        env,
                        f"table '{table_id}' row '{row_id}' missing irm_id in _trace",
                    )

                if row_trace_id and row_status:
                    row_record: dict[str, Any] = {
                        "id": row_trace_id,
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
                    meta = cell_trace_map.get(key)
                    if not isinstance(meta, dict):
                        _record_error(
                            env,
                            f"table '{table_id}' row '{row_id}' col '{key}' "
                            "missing cell_trace metadata",
                        )
                        meta = {}

                    trace_id = _read_trace_id(
                        env,
                        meta,
                        strict_mode=strict_mode,
                        context=f"table '{table_id}' row '{row_id}' col '{key}'",
                    )
                    trace_status = str(meta.get("trace_status", "")).strip()
                    anchor_ids = [
                        str(item).strip()
                        for item in meta.get("anchor_ids", [])
                        if str(item).strip()
                    ]
                    relation = str(meta.get("relation", "")).strip()

                    if strict_mode and not trace_id:
                        _record_error(
                            env,
                            f"table '{table_id}' row '{row_id}' col '{key}' "
                            "missing irm_id",
                        )
                    elif not strict_mode and not trace_id:
                        _record_error(
                            env,
                            f"table '{table_id}' row '{row_id}' col '{key}' "
                            "missing IRM ID",
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

                    if trace_id:
                        record = {
                            "id": trace_id,
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
