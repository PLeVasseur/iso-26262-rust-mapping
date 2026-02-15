#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tools.traceability.irm_id_utils import is_valid_irm_id, mint_irm_id

SCRIPT_VERSION = "0.1"
DP_ROLE_RE = re.compile(r"\{dp\}`([^`]+)`")
P_ROLE_RE = re.compile(r"\{p\}`([^`]+)`")


@dataclass
class Inventory:
    metadata_ids: set[str]
    reference_ids: set[str]
    occurrence_counts: dict[str, int]
    file_occurrence_counts: dict[str, int]
    source_key_count: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, path)


def _read_mapping(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"mapping JSON must be an object: {path}")
    mapping: dict[str, str] = {}
    for key, value in payload.items():
        old_id = str(key).strip()
        new_id = str(value).strip()
        if not old_id:
            raise SystemExit("mapping JSON contains empty source key")
        if not is_valid_irm_id(new_id):
            raise SystemExit(f"mapping target is not a valid IRM ID: {new_id}")
        mapping[old_id] = new_id
    return mapping


def _collect_trace_entries(row: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    row_trace = row.get("_trace")
    if isinstance(row_trace, dict):
        entries.append(row_trace)

    cell_trace = row.get("cell_trace")
    if isinstance(cell_trace, dict):
        for value in cell_trace.values():
            if isinstance(value, dict):
                entries.append(value)
    return entries


def _build_inventory(markdown_path: Path, tables_dir: Path) -> Inventory:
    metadata_ids: set[str] = set()
    reference_ids: set[str] = set()
    occurrence_counts: dict[str, int] = {}
    file_occurrence_counts: dict[str, int] = {}
    source_key_count = 0

    markdown_text = markdown_path.read_text(encoding="utf-8")
    markdown_key = str(markdown_path)

    for match in DP_ROLE_RE.finditer(markdown_text):
        statement_id = match.group(1).strip()
        metadata_ids.add(statement_id)
        occurrence_counts[statement_id] = occurrence_counts.get(statement_id, 0) + 1
        file_occurrence_counts[markdown_key] = file_occurrence_counts.get(markdown_key, 0) + 1

    for match in P_ROLE_RE.finditer(markdown_text):
        reference_id = match.group(1).strip()
        reference_ids.add(reference_id)
        occurrence_counts[reference_id] = occurrence_counts.get(reference_id, 0) + 1
        file_occurrence_counts[markdown_key] = file_occurrence_counts.get(markdown_key, 0) + 1

    for table_path in sorted(tables_dir.glob("table-*.yaml")):
        payload = yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
        rows = payload.get("rows")
        if not isinstance(rows, list):
            continue

        file_key = str(table_path)
        for row in rows:
            if not isinstance(row, dict):
                continue
            for trace_entry in _collect_trace_entries(row):
                if "source_id" in trace_entry:
                    source_key_count += 1
                raw_id = ""
                if "irm_id" in trace_entry:
                    raw_id = str(trace_entry.get("irm_id", "")).strip()
                elif "source_id" in trace_entry:
                    raw_id = str(trace_entry.get("source_id", "")).strip()

                if not raw_id:
                    continue
                metadata_ids.add(raw_id)
                occurrence_counts[raw_id] = occurrence_counts.get(raw_id, 0) + 1
                file_occurrence_counts[file_key] = file_occurrence_counts.get(file_key, 0) + 1

    return Inventory(
        metadata_ids=metadata_ids,
        reference_ids=reference_ids,
        occurrence_counts=occurrence_counts,
        file_occurrence_counts=file_occurrence_counts,
        source_key_count=source_key_count,
    )


def _generate_mapping(inventory: Inventory) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used_ids = {item for item in inventory.metadata_ids if is_valid_irm_id(item)}
    legacy_ids = sorted(item for item in inventory.metadata_ids if not is_valid_irm_id(item))

    for legacy_id in legacy_ids:
        minted = mint_irm_id(used_ids)
        used_ids.add(minted)
        mapping[legacy_id] = minted
    return mapping


def _replace_markdown_ids(text: str, mapping: dict[str, str]) -> tuple[str, dict[str, int]]:
    replacement_counts = {"dp": 0, "p": 0}

    def replace_dp(match: re.Match[str]) -> str:
        current_id = match.group(1).strip()
        mapped_id = mapping.get(current_id, current_id)
        if mapped_id != current_id:
            replacement_counts["dp"] += 1
        return f"{{dp}}`{mapped_id}`"

    def replace_p(match: re.Match[str]) -> str:
        current_id = match.group(1).strip()
        mapped_id = mapping.get(current_id, current_id)
        if mapped_id != current_id:
            replacement_counts["p"] += 1
        return f"{{p}}`{mapped_id}`"

    updated = DP_ROLE_RE.sub(replace_dp, text)
    updated = P_ROLE_RE.sub(replace_p, updated)
    return updated, replacement_counts


def _atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def _rewrite_yaml_tables(
    tables_dir: Path,
    mapping: dict[str, str],
    apply: bool,
) -> dict[str, dict[str, int]]:
    file_counts: dict[str, dict[str, int]] = {}

    for table_path in sorted(tables_dir.glob("table-*.yaml")):
        payload = yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
        rows = payload.get("rows")
        if not isinstance(rows, list):
            continue

        source_key_updates = 0
        id_updates = 0

        for row in rows:
            if not isinstance(row, dict):
                continue

            for trace_entry in _collect_trace_entries(row):
                current_id = ""
                had_source_id_key = "source_id" in trace_entry
                if had_source_id_key:
                    source_key_updates += 1
                    current_id = str(trace_entry.pop("source_id", "")).strip()
                elif "irm_id" in trace_entry:
                    current_id = str(trace_entry.get("irm_id", "")).strip()

                if not current_id:
                    continue

                mapped_id = mapping.get(current_id, current_id)
                if mapped_id != current_id:
                    id_updates += 1
                trace_entry["irm_id"] = mapped_id

        if source_key_updates or id_updates:
            file_counts[str(table_path)] = {
                "source_key_updates": source_key_updates,
                "id_updates": id_updates,
            }

            if apply:
                rendered = yaml.safe_dump(
                    payload,
                    sort_keys=False,
                    width=1000,
                    allow_unicode=False,
                )
                _atomic_write_text(table_path, rendered)

    return file_counts


def _apply_mapping(
    markdown_path: Path,
    tables_dir: Path,
    mapping: dict[str, str],
    apply: bool,
) -> dict[str, Any]:
    markdown_before = markdown_path.read_text(encoding="utf-8")
    markdown_after, markdown_counts = _replace_markdown_ids(markdown_before, mapping)
    markdown_updated = markdown_after != markdown_before

    if apply and markdown_updated:
        _atomic_write_text(markdown_path, markdown_after)

    table_counts = _rewrite_yaml_tables(tables_dir, mapping, apply=apply)
    total_table_updates = sum(
        values["source_key_updates"] + values["id_updates"] for values in table_counts.values()
    )

    touched_files = []
    if markdown_updated:
        touched_files.append(str(markdown_path))
    touched_files.extend(sorted(table_counts.keys()))

    return {
        "markdown_replacements": markdown_counts,
        "table_replacements": table_counts,
        "total_table_updates": total_table_updates,
        "touched_files": touched_files,
    }


def _artifact_root_from_args(args: argparse.Namespace, repo_root: Path) -> Path:
    if args.artifact_root:
        return Path(args.artifact_root)
    run_root_raw = os.environ.get("SPHINX_MIGRATION_RUN_ROOT", "").strip()
    if run_root_raw:
        return Path(run_root_raw) / "artifacts" / "traceability" / "id-backfill"
    return repo_root / "build" / "id-backfill-artifacts"


def _validate_post_cutover(markdown_path: Path, tables_dir: Path) -> dict[str, Any]:
    inventory = _build_inventory(markdown_path=markdown_path, tables_dir=tables_dir)
    invalid_metadata_ids = sorted(
        statement_id
        for statement_id in inventory.metadata_ids
        if not is_valid_irm_id(statement_id)
    )
    invalid_reference_ids = sorted(
        reference_id
        for reference_id in inventory.reference_ids
        if not is_valid_irm_id(reference_id)
    )
    unresolved_reference_ids = sorted(
        reference_id
        for reference_id in inventory.reference_ids
        if reference_id not in inventory.metadata_ids
    )

    return {
        "valid": not (
            invalid_metadata_ids
            or invalid_reference_ids
            or unresolved_reference_ids
            or inventory.source_key_count
        ),
        "metadata_id_count": len(inventory.metadata_ids),
        "reference_id_count": len(inventory.reference_ids),
        "invalid_metadata_ids": invalid_metadata_ids,
        "invalid_reference_ids": invalid_reference_ids,
        "unresolved_reference_ids": unresolved_reference_ids,
        "remaining_source_id_keys": inventory.source_key_count,
    }


def _summarize_dry_run(
    inventory: Inventory,
    mapping: dict[str, str],
    preview: dict[str, Any],
) -> dict[str, Any]:
    unresolved_reference_ids = sorted(
        reference_id
        for reference_id in inventory.reference_ids
        if reference_id not in inventory.metadata_ids
    )
    return {
        "timestamp_utc": _utc_now(),
        "script_version": SCRIPT_VERSION,
        "mode": "dry-run",
        "statement_metadata_id_count": len(inventory.metadata_ids),
        "statement_reference_id_count": len(inventory.reference_ids),
        "legacy_id_count": len([item for item in inventory.metadata_ids if not is_valid_irm_id(item)]),
        "mapping_count": len(mapping),
        "unresolved_reference_ids": unresolved_reference_ids,
        "preview": preview,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill legacy statement IDs to ISO 26262 Rust Mapping IDs (IRM IDs) "
            "across markdown, table metadata, and statement references."
        )
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--markdown-path", default="src/iso26262_rust_mapping.md")
    parser.add_argument("--tables-dir", default="src/tables")
    parser.add_argument("--artifact-root", default="")
    parser.add_argument("--mapping-json", default="")
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--rewrite-summary-json", default="")
    parser.add_argument("--validation-summary-json", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check-idempotent", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    markdown_path = (repo_root / args.markdown_path).resolve()
    tables_dir = (repo_root / args.tables_dir).resolve()
    artifact_root = _artifact_root_from_args(args, repo_root)
    artifact_root.mkdir(parents=True, exist_ok=True)

    inventory = _build_inventory(markdown_path=markdown_path, tables_dir=tables_dir)

    if args.apply:
        if not args.mapping_json:
            raise SystemExit("--apply requires --mapping-json")

        mapping_path = Path(args.mapping_json).resolve()
        mapping = _read_mapping(mapping_path)
        discovered_legacy_ids = sorted(
            statement_id
            for statement_id in inventory.metadata_ids
            if not is_valid_irm_id(statement_id)
        )
        missing_mapping_ids = [
            statement_id for statement_id in discovered_legacy_ids if statement_id not in mapping
        ]
        if missing_mapping_ids:
            raise SystemExit(
                "mapping JSON is missing discovered IDs: "
                + ", ".join(missing_mapping_ids[:20])
            )

        rewrite_summary = _apply_mapping(
            markdown_path=markdown_path,
            tables_dir=tables_dir,
            mapping=mapping,
            apply=True,
        )

        validation_summary = _validate_post_cutover(markdown_path, tables_dir)
        if args.check_idempotent:
            idempotency_preview = _apply_mapping(
                markdown_path=markdown_path,
                tables_dir=tables_dir,
                mapping=mapping,
                apply=False,
            )
            idempotent = not idempotency_preview["touched_files"]
            validation_summary["idempotent_reapply"] = idempotent
            validation_summary["idempotent_preview"] = idempotency_preview
            if not idempotent:
                validation_summary["valid"] = False

        rewrite_payload = {
            "timestamp_utc": _utc_now(),
            "script_version": SCRIPT_VERSION,
            "mode": "apply",
            "mapping_json": str(mapping_path),
            **rewrite_summary,
        }

        rewrite_out = (
            Path(args.rewrite_summary_json).resolve()
            if args.rewrite_summary_json
            else artifact_root / "rewrite-summary.json"
        )
        validation_out = (
            Path(args.validation_summary_json).resolve()
            if args.validation_summary_json
            else artifact_root / "validation-summary.json"
        )
        _write_json(rewrite_out, rewrite_payload)
        _write_json(validation_out, validation_summary)

        if not validation_summary.get("valid", False):
            raise SystemExit("IRM ID validation failed after apply")

        print(f"REWRITE_SUMMARY={rewrite_out}")
        print(f"VALIDATION_SUMMARY={validation_out}")
        return 0

    mapping = _generate_mapping(inventory)
    preview = _apply_mapping(
        markdown_path=markdown_path,
        tables_dir=tables_dir,
        mapping=mapping,
        apply=False,
    )
    summary_payload = _summarize_dry_run(inventory=inventory, mapping=mapping, preview=preview)

    mapping_out = (
        Path(args.mapping_json).resolve() if args.mapping_json else artifact_root / "id-mapping.json"
    )
    summary_out = (
        Path(args.summary_json).resolve()
        if args.summary_json
        else artifact_root / "backfill-dry-run-summary.json"
    )
    _write_json(mapping_out, mapping)
    _write_json(summary_out, summary_payload)

    print(f"MAPPING_JSON={mapping_out}")
    print(f"DRY_RUN_SUMMARY={summary_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
