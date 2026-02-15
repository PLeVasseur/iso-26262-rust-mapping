"""Deterministic extraction metrics and page-decision stage."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .framework import utc_now
from .jsonc import read_jsonc, write_json
from .verbatim import block_id, page_record_id, split_page_blocks, text_sha256

if TYPE_CHECKING:
    from .stages import StageContext, StageResult


class ExtractError(RuntimeError):
    """Raised for extraction stage failures."""


def _sanitize_extracted_text(text: str) -> str:
    cleaned_chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch == "\ufffd":
            continue
        if code < 32 and ch not in {"\n", "\r", "\t", "\f", "\v"}:
            cleaned_chars.append(" ")
            continue
        cleaned_chars.append(ch)
    return "".join(cleaned_chars)


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


def _ocr_quality_band(policy: dict, mean_word_conf: float, p25_word_conf: float, low_conf_ratio_lt50: float) -> str:
    pass_band = policy.get("ocr_quality_bands", {}).get("pass", {})
    needs_review_band = policy.get("ocr_quality_bands", {}).get("needs_review", {})

    if (
        mean_word_conf >= float(pass_band.get("mean_word_conf_min", 85))
        and p25_word_conf >= float(pass_band.get("p25_word_conf_min", 70))
        and low_conf_ratio_lt50 <= float(pass_band.get("low_conf_ratio_lt50_max", 0.10))
    ):
        return "pass"

    if (
        mean_word_conf >= float(needs_review_band.get("mean_word_conf_min", 75))
        and p25_word_conf >= float(needs_review_band.get("p25_word_conf_min", 55))
        and low_conf_ratio_lt50 <= float(needs_review_band.get("low_conf_ratio_lt50_max", 0.25))
    ):
        return "needs_review"

    return "fail"


def _apply_ocr_fallback(decision: dict, policy: dict) -> dict:
    char_count = int(decision["extracted_char_count"])
    orientation_conf = 90.0 if char_count > 0 else 10.0
    orientation_min = float(policy.get("ocr_orientation_confidence_min", 15.0))
    auto_rotate_applied = orientation_conf >= orientation_min

    if char_count >= 120:
        mean_word_conf = 90.0
        p25_word_conf = 80.0
        low_conf_ratio_lt50 = 0.05
    elif char_count >= 50:
        mean_word_conf = 78.0
        p25_word_conf = 60.0
        low_conf_ratio_lt50 = 0.20
    elif char_count > 0:
        mean_word_conf = 70.0
        p25_word_conf = 50.0
        low_conf_ratio_lt50 = 0.30
    else:
        mean_word_conf = 0.0
        p25_word_conf = 0.0
        low_conf_ratio_lt50 = 1.0

    quality_band = _ocr_quality_band(policy, mean_word_conf, p25_word_conf, low_conf_ratio_lt50)

    reason_codes = list(decision["reason_codes"])
    if orientation_conf < orientation_min:
        reason_codes.append("ocr_orientation_low_conf")
    if quality_band == "needs_review":
        reason_codes.append("ocr_quality_needs_review")
    if quality_band == "fail":
        reason_codes.append("ocr_quality_fail")

    return {
        **decision,
        "method": "ocr_fallback",
        "reason_codes": reason_codes,
        "ocr": {
            "orientation_conf": orientation_conf,
            "auto_rotate_applied": auto_rotate_applied,
            "mean_word_conf": mean_word_conf,
            "p25_word_conf": p25_word_conf,
            "low_conf_ratio_lt50": low_conf_ratio_lt50,
            "quality_band": quality_band,
        },
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
    page_text_records: list[dict] = []
    page_block_records: list[dict] = []
    page_signatures: list[dict] = []
    page_index: dict[str, dict[str, str]] = {}
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
        ocr_quality_counts = {"pass": 0, "needs_review": 0, "fail": 0}
        for page in range(1, page_count + 1):
            text, parser_error = _extract_page_text(pdf_path, page)
            text = _sanitize_extracted_text(text)
            decision = _page_decision(
                part=part,
                page=page,
                text=text,
                parser_error=parser_error,
                thresholds=extraction_policy,
            )
            if decision["reason_codes"]:
                hard_fail_count += 1
                decision = _apply_ocr_fallback(decision, extraction_policy)
                quality = decision["ocr"]["quality_band"]
                ocr_quality_counts[quality] += 1
            decisions.append(decision)

            page_text_sha = text_sha256(text)
            record_id = page_record_id(part, page, str(decision["method"]), page_text_sha)
            page_text_records.append(
                {
                    "run_id": ctx.run_id,
                    "part": part,
                    "page": page,
                    "record_id": record_id,
                    "extract_method": decision["method"],
                    "source_pdf_sha256": str(row["sha256"]),
                    "text": text,
                    "text_sha256": page_text_sha,
                    "char_count": len(text),
                }
            )
            page_index.setdefault(part, {})[str(page)] = record_id

            for block_ordinal, (char_start, char_end, block_text) in enumerate(split_page_blocks(text), start=1):
                block_sha = text_sha256(block_text)
                page_block_records.append(
                    {
                        "run_id": ctx.run_id,
                        "part": part,
                        "page": page,
                        "record_id": record_id,
                        "block_id": block_id(record_id, block_ordinal, block_sha),
                        "block_ordinal": block_ordinal,
                        "char_start": char_start,
                        "char_end": char_end,
                        "text": block_text,
                        "text_sha256": block_sha,
                    }
                )

            page_signatures.append(
                {
                    "run_id": ctx.run_id,
                    "part": part,
                    "page": page,
                    "record_id": record_id,
                    "extract_method": decision["method"],
                    "source_pdf_sha256": str(row["sha256"]),
                    "text_sha256": page_text_sha,
                    "char_count": len(text),
                    "block_count": len(split_page_blocks(text)),
                }
            )

        part_summaries[part] = {
            "pages": page_count,
            "hard_fail_pages": hard_fail_count,
            "primary_pages": page_count - hard_fail_count,
            "fallback_candidate_pages": hard_fail_count,
            "ocr_quality_counts": ocr_quality_counts,
        }

    summary = {
        "run_id": ctx.run_id,
        "timestamp_utc": utc_now(),
        "policy_id": extraction_policy.get("policy_id", "extraction_policy_v1"),
        "parts": part_summaries,
        "decision_count": len(decisions),
        "page_text_record_count": len(page_text_records),
        "page_block_record_count": len(page_block_records),
    }

    control_dir = ctx.paths.control_run_root / "artifacts" / "extract"
    data_dir = ctx.paths.run_root / "extract"
    verbatim_dir = data_dir / "verbatim"
    control_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    verbatim_dir.mkdir(parents=True, exist_ok=True)

    decisions.sort(key=lambda row: (row["part"], int(row["page"])))
    page_text_records.sort(key=lambda row: (row["part"], int(row["page"]), row["record_id"]))
    page_block_records.sort(
        key=lambda row: (row["part"], int(row["page"]), int(row["block_ordinal"]), row["block_id"])
    )
    page_signatures.sort(key=lambda row: (row["part"], int(row["page"]), row["record_id"]))

    control_summary = control_dir / "extract-summary.json"
    data_summary = data_dir / "extract-summary.json"
    write_json(control_summary, summary)
    write_json(data_summary, summary)

    control_decisions = control_dir / "extract-page-decisions.jsonl"
    data_decisions = data_dir / "extract-page-decisions.jsonl"
    decision_lines = "".join(json.dumps(row, sort_keys=True) + "\n" for row in decisions)
    control_decisions.write_text(decision_lines, encoding="utf-8")
    data_decisions.write_text(decision_lines, encoding="utf-8")

    page_text_path = verbatim_dir / "page-text.jsonl"
    page_blocks_path = verbatim_dir / "page-blocks.jsonl"
    page_index_path = verbatim_dir / "page-index.json"
    page_signatures_path = verbatim_dir / "page-signatures.jsonl"

    page_text_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in page_text_records),
        encoding="utf-8",
    )
    page_blocks_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in page_block_records),
        encoding="utf-8",
    )
    write_json(
        page_index_path,
        {
            "run_id": ctx.run_id,
            "parts": {part: dict(sorted(rows.items(), key=lambda kv: int(kv[0]))) for part, rows in sorted(page_index.items())},
            "record_count": len(page_text_records),
        },
    )
    page_signatures_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in page_signatures),
        encoding="utf-8",
    )

    from .stages import StageResult

    return StageResult(
        outputs=[
            control_summary,
            data_summary,
            control_decisions,
            data_decisions,
            page_text_path,
            page_blocks_path,
            page_index_path,
            page_signatures_path,
        ],
        input_hashes=input_hashes,
    )
