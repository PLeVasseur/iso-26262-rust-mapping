"""Normalize stage and high-resolution locator model scaffold."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .framework import utc_now
from .jsonc import write_json

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


def _fingerprint(part: str, page: int, method: str) -> str:
    digest = hashlib.sha256(f"{part}:{page}:{method}".encode("utf-8")).hexdigest()
    return digest[:24]


def _unit_from_decision(decision: dict, pdf_sha: str) -> dict:
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
        "unit_type": "paragraph",
        "page_start": page,
        "page_end": page,
    }

    return {
        "unit_id": f"{part.lower()}-p{page:04d}",
        "unit_type": "paragraph",
        "source_locator": source_locator,
        "display_locator": f"{part} / Clause {page}.0 / Paragraph 1",
        "fingerprint": _fingerprint(part, page, method),
        "provenance": {
            "source_pdf_sha256": pdf_sha,
            "extract_method": method,
        },
        "review_state": review_state,
        "status": "mapped",
        "notes": "non-verbatim normalized unit",
    }


def run_normalize_stage(ctx: "StageContext") -> "StageResult":
    ingest_summary = _load_ingest_summary(ctx.paths.control_run_root)
    decisions = _load_extract_decisions(ctx.paths.control_run_root)
    if not decisions:
        raise NormalizeError("extract decisions are empty")

    resolved_parts = ingest_summary.get("resolved_parts", {})
    input_hashes = {part: info["sha256"] for part, info in resolved_parts.items()}

    seen_pages: set[tuple[str, int]] = set()
    units: list[dict] = []
    qa_items: list[dict] = []
    expected_counts: dict[str, int] = {}
    normalized_counts: dict[str, int] = {}

    for decision in decisions:
        part = decision["part"]
        page = int(decision["page"])
        key = (part, page)
        if key in seen_pages:
            raise NormalizeError(f"duplicate extract decision for {part} page {page}")
        seen_pages.add(key)

        expected_counts[part] = expected_counts.get(part, 0) + 1
        unit = _unit_from_decision(decision, input_hashes[part])
        units.append(unit)
        normalized_counts[part] = normalized_counts.get(part, 0) + 1

        if unit["review_state"] == "needs_review":
            qa_items.append(
                {
                    "qa_item_id": f"qa-{unit['unit_id']}",
                    "part": part,
                    "page": page,
                    "reason_codes": decision.get("reason_codes", []),
                    "confidence": 0.5,
                    "recommended_action": "manual_adjudication",
                }
            )

    coverage: dict[str, dict] = {}
    for part in sorted(expected_counts.keys()):
        expected = expected_counts[part]
        normalized = normalized_counts.get(part, 0)
        ratio = (normalized / expected) if expected else 0.0
        coverage[part] = {
            "expected": expected,
            "normalized": normalized,
            "coverage_ratio": ratio,
        }
        if ratio < 1.0:
            raise NormalizeError(f"required-part coverage below 100% for {part}: {normalized}/{expected}")

    now = utc_now()
    summary = {
        "run_id": ctx.run_id,
        "timestamp_utc": now,
        "unit_count": len(units),
        "qa_unresolved_count": len(qa_items),
        "coverage": coverage,
    }

    control_dir = ctx.paths.control_run_root / "artifacts" / "normalize"
    data_dir = ctx.paths.run_root / "normalize"
    qa_data_dir = ctx.paths.run_root / "qa"
    qa_control_dir = ctx.paths.control_run_root / "artifacts" / "qa"
    for directory in (control_dir, data_dir, qa_data_dir, qa_control_dir):
        directory.mkdir(parents=True, exist_ok=True)

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

    control_summary = control_dir / "normalize-summary.json"
    data_summary = data_dir / "normalize-summary.json"
    write_json(control_summary, summary)
    write_json(data_summary, summary)

    from .stages import StageResult

    return StageResult(
        outputs=[control_units, data_units, control_qa, data_qa, control_summary, data_summary],
        input_hashes=input_hashes,
    )
