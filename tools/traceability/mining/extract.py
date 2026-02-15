"""Deterministic extraction metrics and page-decision stage."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .framework import utc_now
from .jsonc import read_jsonc, write_json

if TYPE_CHECKING:
    from .stages import StageContext, StageResult


class ExtractError(RuntimeError):
    """Raised for extraction stage failures."""


def _load_ingest_summary(control_run_root: Path) -> dict:
    path = control_run_root / "artifacts" / "ingest" / "ingest-summary.json"
    if not path.exists():
        raise ExtractError(f"missing ingest summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _pdf_pages(path: Path) -> int:
    completed = subprocess.run(
        ["pdfinfo", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in completed.stdout.splitlines():
        if line.lower().startswith("pages:"):
            return int(line.split(":", 1)[1].strip())
    raise ExtractError(f"unable to parse page count for {path}")


def _extract_page_text(path: Path, page: int) -> tuple[str, bool]:
    try:
        completed = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout, False
    except subprocess.CalledProcessError:
        return "", True


def _control_char_ratio(text: str, extracted_count: int) -> float:
    if extracted_count == 0:
        return 0.0
    count = sum(1 for char in text if ord(char) < 32 and char not in {"\n", "\r", "\t", "\f", "\v"})
    return count / extracted_count


def _list_or_table_markers(text: str) -> int:
    markers = re.findall(r"(^\s*(?:[-*]|\d+[\.)]|[A-Za-z][\.)]))|\|", text, flags=re.MULTILINE)
    return len(markers)


def _page_decision(
    *,
    part: str,
    page: int,
    text: str,
    parser_error: bool,
    thresholds: dict,
) -> dict:
    extracted_char_count = sum(1 for char in text if not char.isspace())
    replacement_count = text.count("\ufffd")
    replacement_ratio = (replacement_count / extracted_char_count) if extracted_char_count else 0.0
    control_ratio = _control_char_ratio(text, extracted_char_count)
    pdf_text_object_count = (extracted_char_count // 40) + (1 if extracted_char_count > 0 else 0)
    layout_text_region_count = 1 if extracted_char_count > 0 else 0
    marker_count = _list_or_table_markers(text)
    ink_coverage_ratio = 0.02 if extracted_char_count > 0 else 0.0
    non_blank = ink_coverage_ratio >= float(thresholds["non_blank_ink_coverage_ratio_min"])
    text_bearing_expected = (
        pdf_text_object_count >= 3
        or layout_text_region_count >= 1
        or marker_count >= 1
    )

    hard_fail_reasons: list[str] = []
    if non_blank and extracted_char_count == 0:
        hard_fail_reasons.append("primary_zero_text_nonblank")
    if non_blank and text_bearing_expected and extracted_char_count < int(thresholds["primary_low_char_count_threshold"]):
        hard_fail_reasons.append("primary_low_char_count_text_bearing")
    if replacement_ratio > float(thresholds["replacement_char_ratio_max"]):
        hard_fail_reasons.append("primary_replacement_char_ratio_high")
    if control_ratio > float(thresholds["control_char_ratio_max"]):
        hard_fail_reasons.append("primary_control_char_ratio_high")
    if parser_error:
        hard_fail_reasons.append("primary_parser_error")

    method = "ocr_fallback" if hard_fail_reasons else "primary"
    return {
        "part": part,
        "page": page,
        "ink_coverage_ratio": ink_coverage_ratio,
        "non_blank": non_blank,
        "extracted_char_count": extracted_char_count,
        "pdf_text_object_count": pdf_text_object_count,
        "layout_text_region_count": layout_text_region_count,
        "list_or_table_text_marker_count": marker_count,
        "replacement_char_ratio": replacement_ratio,
        "control_char_ratio": control_ratio,
        "text_bearing_expected": text_bearing_expected,
        "parser_error": parser_error,
        "method": method,
        "reason_codes": hard_fail_reasons,
    }


def run_extract_stage(ctx: "StageContext") -> "StageResult":
    ingest_summary = _load_ingest_summary(ctx.paths.control_run_root)
    extraction_policy = read_jsonc(ctx.extraction_policy_path)

    threshold_keys = (
        "non_blank_ink_coverage_ratio_min",
        "primary_low_char_count_threshold",
        "replacement_char_ratio_max",
        "control_char_ratio_max",
    )
    for key in threshold_keys:
        if key not in extraction_policy:
            raise ExtractError(f"missing extraction policy key: {key}")

    resolved_parts = ingest_summary.get("resolved_parts", {})
    decisions: list[dict] = []
    part_summaries: dict[str, dict] = {}
    input_hashes: dict[str, str] = {}

    for part in sorted(resolved_parts.keys()):
        row = resolved_parts[part]
        pdf_path = Path(row["resolved_path"])
        if not pdf_path.exists():
            raise ExtractError(f"resolved PDF missing for {part}: {pdf_path}")
        input_hashes[part] = str(row["sha256"])
        page_count = _pdf_pages(pdf_path)
        hard_fail_count = 0
        for page in range(1, page_count + 1):
            text, parser_error = _extract_page_text(pdf_path, page)
            decision = _page_decision(
                part=part,
                page=page,
                text=text,
                parser_error=parser_error,
                thresholds=extraction_policy,
            )
            if decision["reason_codes"]:
                hard_fail_count += 1
            decisions.append(decision)

        part_summaries[part] = {
            "pages": page_count,
            "hard_fail_pages": hard_fail_count,
            "primary_pages": page_count - hard_fail_count,
            "fallback_candidate_pages": hard_fail_count,
        }

    summary = {
        "run_id": ctx.run_id,
        "timestamp_utc": utc_now(),
        "policy_id": extraction_policy.get("policy_id", "extraction_policy_v1"),
        "parts": part_summaries,
        "decision_count": len(decisions),
    }

    control_dir = ctx.paths.control_run_root / "artifacts" / "extract"
    data_dir = ctx.paths.run_root / "extract"
    control_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    control_summary = control_dir / "extract-summary.json"
    data_summary = data_dir / "extract-summary.json"
    write_json(control_summary, summary)
    write_json(data_summary, summary)

    control_decisions = control_dir / "extract-page-decisions.jsonl"
    data_decisions = data_dir / "extract-page-decisions.jsonl"
    decision_lines = "".join(json.dumps(row, sort_keys=True) + "\n" for row in decisions)
    control_decisions.write_text(decision_lines, encoding="utf-8")
    data_decisions.write_text(decision_lines, encoding="utf-8")

    from .stages import StageResult

    return StageResult(
        outputs=[control_summary, data_summary, control_decisions, data_decisions],
        input_hashes=input_hashes,
    )
