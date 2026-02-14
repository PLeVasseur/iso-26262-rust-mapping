#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


TRACE_STATUS_DEFAULT = "unmapped_with_rationale"


def _make_source_id(table_id: str, row_index: int, col_index: int) -> str:
    table_num = "".join(ch for ch in table_id if ch.isdigit()) or "00"
    return f"SRCN-T{int(table_num):02d}-R{row_index:04d}-C{col_index:02d}"


def instrument_table(path: Path) -> dict[str, int | str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    columns = [
        col.get("key")
        for col in payload.get("columns", [])
        if isinstance(col, dict) and col.get("key")
    ]
    rows = payload.get("rows") or []

    instrumented_cells = 0
    row_count = 0

    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue

        row_count += 1
        if not row.get("row_id"):
            row["row_id"] = f"r{row_index:04d}"

        cell_trace = row.get("cell_trace")
        if not isinstance(cell_trace, dict):
            cell_trace = {}
            row["cell_trace"] = cell_trace

        for col_index, key in enumerate(columns, start=1):
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue

            trace_entry = cell_trace.get(key)
            if not isinstance(trace_entry, dict):
                trace_entry = {}

            trace_entry.setdefault("source_id", _make_source_id(payload.get("id", path.stem), row_index, col_index))
            trace_entry.setdefault("trace_status", TRACE_STATUS_DEFAULT)
            trace_entry.setdefault("anchor_ids", [])
            trace_entry.setdefault("relation", "")
            cell_trace[key] = trace_entry
            instrumented_cells += 1

    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, width=1000, allow_unicode=False),
        encoding="utf-8",
    )

    return {
        "table_file": str(path),
        "rows": row_count,
        "instrumented_cells": instrumented_cells,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Add row_id/cell_trace instrumentation to table YAML files")
    parser.add_argument("--tables-dir", required=True)
    parser.add_argument("--report-json", default="")
    parser.add_argument("--report-md", default="")
    args = parser.parse_args(argv)

    tables_dir = Path(args.tables_dir)
    results = [instrument_table(path) for path in sorted(tables_dir.glob("table-*.yaml"))]
    total_rows = sum(int(item["rows"]) for item in results)
    total_cells = sum(int(item["instrumented_cells"]) for item in results)

    summary = {
        "table_count": len(results),
        "total_rows": total_rows,
        "total_instrumented_cells": total_cells,
        "tables": results,
    }

    if args.report_json:
        report_json_path = Path(args.report_json)
        report_json_path.parent.mkdir(parents=True, exist_ok=True)
        report_json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.report_md:
        report_md_path = Path(args.report_md)
        report_md_path.parent.mkdir(parents=True, exist_ok=True)
        report_md = "\n".join(
            [
                "# Table Schema Migration Report",
                "",
                f"- tables updated: {len(results)}",
                f"- total rows: {total_rows}",
                f"- total instrumented cells: {total_cells}",
            ]
        ) + "\n"
        report_md_path.write_text(report_md, encoding="utf-8")

    print(f"TABLE_COUNT={len(results)}")
    print(f"TOTAL_ROWS={total_rows}")
    print(f"TOTAL_INSTRUMENTED_CELLS={total_cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
