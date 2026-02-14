#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def update_common_schema(common_schema_path: Path) -> None:
    schema = json.loads(common_schema_path.read_text(encoding="utf-8"))
    schema.setdefault("properties", {}).setdefault("rows", {}).setdefault("items", {})["additionalProperties"] = True
    defs = schema.setdefault("$defs", {})
    defs["traceStatus"] = {
        "type": "string",
        "enum": [
            "mapped",
            "unmapped_with_rationale",
            "out_of_scope_with_rationale",
        ],
    }
    defs["traceMetadata"] = {
        "type": "object",
        "required": [
            "source_id",
            "trace_status",
        ],
        "properties": {
            "source_id": {
                "type": "string",
                "minLength": 1,
            },
            "trace_status": {
                "$ref": "#/$defs/traceStatus",
            },
            "anchor_ids": {
                "type": "array",
                "items": {
                    "type": "string",
                    "minLength": 1,
                },
                "uniqueItems": True,
            },
            "relation": {
                "type": "string",
            },
        },
        "allOf": [
            {
                "if": {
                    "properties": {
                        "trace_status": {
                            "const": "mapped",
                        }
                    },
                    "required": [
                        "trace_status",
                    ],
                },
                "then": {
                    "required": [
                        "anchor_ids",
                        "relation",
                    ],
                    "properties": {
                        "anchor_ids": {
                            "minItems": 1,
                        },
                        "relation": {
                            "minLength": 1,
                        },
                    },
                },
            }
        ],
        "additionalProperties": False,
    }

    common_schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_table_schema(table_schema_path: Path) -> dict[str, int | str]:
    schema = json.loads(table_schema_path.read_text(encoding="utf-8"))
    row_items = schema["properties"]["rows"]["items"]
    properties = row_items.setdefault("properties", {})
    required = row_items.setdefault("required", [])

    properties["row_id"] = {
        "type": "string",
        "pattern": "^[a-z0-9][a-z0-9-]*$",
    }
    if "row_id" not in required:
        required.append("row_id")

    col_keys = [key for key in properties.keys() if key not in {"row_id", "_trace", "cell_trace"}]

    properties["_trace"] = {
        "$ref": "table_common.schema.json#/$defs/traceMetadata",
    }

    properties["cell_trace"] = {
        "type": "object",
        "properties": {
            col_key: {
                "$ref": "table_common.schema.json#/$defs/traceMetadata",
            }
            for col_key in col_keys
        },
        "required": col_keys,
        "additionalProperties": False,
    }
    if "cell_trace" not in required:
        required.append("cell_trace")

    row_items["required"] = required
    row_items["additionalProperties"] = False

    table_schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema": str(table_schema_path),
        "column_count": len(col_keys),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Update table schemas with trace-aware metadata contracts")
    parser.add_argument("--schemas-dir", required=True)
    parser.add_argument("--report-json", default="")
    args = parser.parse_args(argv)

    schemas_dir = Path(args.schemas_dir)
    update_common_schema(schemas_dir / "table_common.schema.json")
    per_table = [
        update_table_schema(path)
        for path in sorted(schemas_dir.glob("table-*.schema.json"))
    ]

    summary = {
        "updated_common_schema": str(schemas_dir / "table_common.schema.json"),
        "table_schema_count": len(per_table),
        "tables": per_table,
    }

    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"TABLE_SCHEMA_COUNT={len(per_table)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
