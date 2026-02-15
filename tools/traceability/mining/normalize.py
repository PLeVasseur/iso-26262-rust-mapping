"""Normalize stage and high-resolution locator model scaffold."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .framework import utc_now
from .jsonc import write_json
from .verbatim import normalize_for_query, text_sha256

if TYPE_CHECKING:
    from .stages import StageContext, StageResult


class NormalizeError(RuntimeError):
    """Raised for normalize-stage gate failures."""


def _load_ingest_summary(control_run_root: Path) -> dict:
    path = control_run_root / "artifacts" / "ingest" / "ingest-summary.json"
    if not path.exists():
        raise NormalizeError(f"missing ingest summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_extract_decisions(control_run_root: Path) -> list[dict]:
    path = control_run_root / "artifacts" / "extract" / "extract-page-decisions.jsonl"
    if not path.exists():
        raise NormalizeError(f"missing extract decisions: {path}")
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise NormalizeError(f"missing required input: {path}")
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _fingerprint(part: str, page: int, method: str, unit_type: str) -> str:
    digest = hashlib.sha256(f"{part}:{page}:{method}:{unit_type}".encode("utf-8")).hexdigest()
    return digest[:24]


def _pick_unit_text(unit_type: str, page_text: str, block_rows: list[dict]) -> tuple[str, list[dict]]:
    non_empty_blocks = [row for row in block_rows if str(row.get("text", "")).strip()]
    if unit_type == "paragraph":
        return page_text, non_empty_blocks or block_rows[:1]

    if unit_type == "list_bullet":
        for row in non_empty_blocks:
            if re.match(r"^\s*(?:[-*]|\d+[.)]|[A-Za-z][.)])\s+", str(row.get("text", ""))):
                return str(row.get("text", "")), [row]
        if non_empty_blocks:
            return str(non_empty_blocks[0].get("text", "")), [non_empty_blocks[0]]

    if unit_type == "table_cell":
        for row in non_empty_blocks:
            if "|" in str(row.get("text", "")):
                return str(row.get("text", "")), [row]
        if non_empty_blocks:
            return str(non_empty_blocks[0].get("text", "")), [non_empty_blocks[0]]

    fallback = non_empty_blocks[0] if non_empty_blocks else (block_rows[0] if block_rows else {"text": ""})
    return str(fallback.get("text", "")), [fallback]


def _unit_from_decision(decision: dict, pdf_sha: str, unit_type: str, unit_text: str) -> dict:
    part = decision["part"]
    page = int(decision["page"])
    method = decision["method"]
    review_state = "auto_confirmed"
    if method == "ocr_fallback":
        band = decision.get("ocr", {}).get("quality_band", "fail")
        review_state = "manual_confirmed" if band == "pass" else "needs_review"

    source_locator = {
        "edition": "2018-ed2",
        "part": part,
        "section": f"Sec-{page}",
        "clause": f"Clause-{page}",
        "subclause_path": [f"{page}.0"],
        "unit_type": unit_type,
        "page_start": page,
        "page_end": page,
    }

    suffix = {
        "paragraph": "par",
        "list_bullet": "lb",
        "table_cell": "tc",
    }.get(unit_type, unit_type)

    return {
        "unit_id": f"{part.lower()}-p{page:04d}-{suffix}",
        "unit_type": unit_type,
        "source_locator": source_locator,
        "display_locator": f"{part} / Clause {page}.0 / {unit_type}",
        "fingerprint": _fingerprint(part, page, method, unit_type),
        "provenance": {
            "source_pdf_sha256": pdf_sha,
            "extract_method": method,
            "unit_text_sha256": text_sha256(unit_text),
        },
        "review_state": review_state,
        "status": "mapped",
        "notes": "non-verbatim normalized unit",
    }


def run_normalize_stage(ctx: "StageContext") -> "StageResult":
    ingest_summary = _load_ingest_summary(ctx.paths.control_run_root)
    decisions = _load_extract_decisions(ctx.paths.control_run_root)
    page_text_rows = _load_jsonl(ctx.paths.run_root / "extract" / "verbatim" / "page-text.jsonl")
    page_block_rows = _load_jsonl(ctx.paths.run_root / "extract" / "verbatim" / "page-blocks.jsonl")
    if not decisions:
        raise NormalizeError("extract decisions are empty")

    page_text_by_key: dict[tuple[str, int], dict] = {}
    for row in page_text_rows:
        page_text_by_key[(str(row["part"]), int(row["page"]))] = row

    blocks_by_key: dict[tuple[str, int], list[dict]] = {}
    for row in page_block_rows:
        key = (str(row["part"]), int(row["page"]))
        blocks_by_key.setdefault(key, []).append(row)

    for key in blocks_by_key:
        blocks_by_key[key].sort(key=lambda row: (int(row.get("block_ordinal", 0)), str(row.get("block_id", ""))))

    resolved_parts = ingest_summary.get("resolved_parts", {})
    input_hashes = {part: info["sha256"] for part, info in resolved_parts.items()}

    seen_pages: set[tuple[str, int]] = set()
    units: list[dict] = []
    unit_slices: list[dict] = []
    unit_text_links: list[dict] = []
    query_source_rows: list[dict] = []
    qa_items: list[dict] = []
    expected_counts: dict[str, int] = {}
    normalized_counts: dict[str, dict[str, int]] = {}
    required_unit_types = ("paragraph", "list_bullet", "table_cell")

    for decision in decisions:
        part = decision["part"]
        page = int(decision["page"])
        key = (part, page)
        if key in seen_pages:
            raise NormalizeError(f"duplicate extract decision for {part} page {page}")
        seen_pages.add(key)

        if key not in page_text_by_key:
            raise NormalizeError(f"missing page-text record for {part} page {page}")

        page_record = page_text_by_key[key]
        page_text = str(page_record.get("text", ""))
        page_record_id = str(page_record.get("record_id", ""))
        block_rows = blocks_by_key.get(key, [])
        if not block_rows:
            raise NormalizeError(f"missing page-block rows for {part} page {page}")

        expected_counts[part] = expected_counts.get(part, 0) + 1
        normalized_counts.setdefault(part, {unit_type: 0 for unit_type in required_unit_types})

        for unit_type in required_unit_types:
            unit_text, source_blocks = _pick_unit_text(unit_type, page_text, block_rows)
            unit = _unit_from_decision(decision, input_hashes[part], unit_type, unit_text)
            units.append(unit)
            normalized_counts[part][unit_type] = normalized_counts[part].get(unit_type, 0) + 1

            unit_text_sha = text_sha256(unit_text)
            slice_id = hashlib.sha256(f"{unit['unit_id']}:{unit_text_sha}".encode("utf-8")).hexdigest()[:24]
            source_block_refs = [str(row.get("block_id", "")) for row in source_blocks if str(row.get("block_id", ""))]
            unit_slices.append(
                {
                    "unit_id": unit["unit_id"],
                    "unit_type": unit_type,
                    "part": part,
                    "page": page,
                    "slice_id": slice_id,
                    "text": unit_text,
                    "text_sha256": unit_text_sha,
                    "source_block_refs": source_block_refs,
                    "source_locator": unit["source_locator"],
                }
            )

            link_fingerprint = hashlib.sha256(
                f"{unit['unit_id']}:{slice_id}:{page_record_id}:{unit_text_sha}".encode("utf-8")
            ).hexdigest()[:24]
            unit_text_links.append(
                {
                    "unit_id": unit["unit_id"],
                    "part": part,
                    "unit_type": unit_type,
                    "slice_ids": [slice_id],
                    "page_record_ids": [page_record_id],
                    "coverage_status": "full",
                    "link_fingerprint": link_fingerprint,
                }
            )

            query_source_rows.append(
                {
                    "part": part,
                    "page": page,
                    "unit_type": unit_type,
                    "unit_id": unit["unit_id"],
                    "slice_id": slice_id,
                    "normalized_text": normalize_for_query(unit_text),
                    "tokens": sorted({token for token in re.findall(r"[a-z0-9_]+", normalize_for_query(unit_text)) if token}),
                    "source_locator": unit["source_locator"],
                }
            )

            if unit["review_state"] == "needs_review":
                qa_items.append(
                    {
                        "qa_item_id": f"qa-{unit['unit_id']}",
                        "part": part,
                        "page": page,
                        "unit_type": unit_type,
                        "reason_codes": decision.get("reason_codes", []),
                        "confidence": 0.5,
                        "recommended_action": "manual_adjudication",
                    }
                )

    coverage: dict[str, dict] = {}
    for part in sorted(expected_counts.keys()):
        expected = expected_counts[part]
        by_type = normalized_counts.get(part, {})
        type_rows: dict[str, dict] = {}
        for unit_type in required_unit_types:
            normalized = int(by_type.get(unit_type, 0))
            ratio = (normalized / expected) if expected else 0.0
            type_rows[unit_type] = {
                "expected": expected,
                "normalized": normalized,
                "coverage_ratio": ratio,
            }
            if ratio < 1.0:
                raise NormalizeError(
                    f"required-part {unit_type} coverage below 100% for {part}: {normalized}/{expected}"
                )

        normalized_total = sum(int(by_type.get(unit_type, 0)) for unit_type in required_unit_types)
        ratio = (normalized_total / (expected * len(required_unit_types))) if expected else 0.0
        coverage[part] = {
            "expected_pages": expected,
            "required_unit_types": list(required_unit_types),
            "unit_type_coverage": type_rows,
            "normalized_units": normalized_total,
            "coverage_ratio": ratio,
        }

    now = utc_now()
    summary = {
        "run_id": ctx.run_id,
        "timestamp_utc": now,
        "unit_count": len(units),
        "unit_slice_count": len(unit_slices),
        "unit_text_link_count": len(unit_text_links),
        "query_source_row_count": len(query_source_rows),
        "qa_unresolved_count": len(qa_items),
        "coverage": coverage,
    }

    control_dir = ctx.paths.control_run_root / "artifacts" / "normalize"
    data_dir = ctx.paths.run_root / "normalize"
    data_verbatim_dir = data_dir / "verbatim"
    query_dir = ctx.paths.run_root / "query"
    qa_data_dir = ctx.paths.run_root / "qa"
    qa_control_dir = ctx.paths.control_run_root / "artifacts" / "qa"
    for directory in (control_dir, data_dir, data_verbatim_dir, query_dir, qa_data_dir, qa_control_dir):
        directory.mkdir(parents=True, exist_ok=True)

    units.sort(key=lambda row: (row["source_locator"]["part"], int(row["source_locator"]["page_start"]), row["unit_type"], row["unit_id"]))
    unit_slices.sort(key=lambda row: (row["part"], int(row["page"]), row["unit_type"], row["unit_id"], row["slice_id"]))
    unit_text_links.sort(key=lambda row: (row["part"], row["unit_type"], row["unit_id"]))
    query_source_rows.sort(key=lambda row: (row["part"], int(row["page"]), row["unit_type"], row["unit_id"], row["slice_id"]))

    control_units = control_dir / "normalized-units.jsonl"
    data_units = data_dir / "normalized-units.jsonl"
    unit_lines = "".join(json.dumps(unit, sort_keys=True) + "\n" for unit in units)
    control_units.write_text(unit_lines, encoding="utf-8")
    data_units.write_text(unit_lines, encoding="utf-8")

    control_qa = qa_control_dir / "queue.jsonl"
    data_qa = qa_data_dir / "queue.jsonl"
    qa_lines = "".join(json.dumps(item, sort_keys=True) + "\n" for item in qa_items)
    control_qa.write_text(qa_lines, encoding="utf-8")
    data_qa.write_text(qa_lines, encoding="utf-8")

    unit_slices_path = data_verbatim_dir / "unit-slices.jsonl"
    unit_text_links_path = data_verbatim_dir / "unit-text-links.jsonl"
    query_source_rows_path = query_dir / "query-source-rows.jsonl"
    unit_slices_path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in unit_slices), encoding="utf-8")
    unit_text_links_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in unit_text_links),
        encoding="utf-8",
    )
    query_source_rows_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in query_source_rows),
        encoding="utf-8",
    )

    control_summary = control_dir / "normalize-summary.json"
    data_summary = data_dir / "normalize-summary.json"
    write_json(control_summary, summary)
    write_json(data_summary, summary)

    from .stages import StageResult

    return StageResult(
        outputs=[
            control_units,
            data_units,
            control_qa,
            data_qa,
            unit_slices_path,
            unit_text_links_path,
            query_source_rows_path,
            control_summary,
            data_summary,
        ],
        input_hashes=input_hashes,
    )
