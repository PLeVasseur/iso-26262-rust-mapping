from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment

from .record_store import _ensure_env, _record_error


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
    build_root = Path(app.outdir).parent
    paragraph_ids_path = build_root / "paragraph-ids.json"

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

    schema_path_raw = str(app.config.iso26262_trace_schema_path).strip()
    if schema_path_raw:
        schema_path = Path(schema_path_raw)
    else:
        schema_path = (
            Path(app.confdir).parent
            / "traceability"
            / "iso26262"
            / "schema"
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
