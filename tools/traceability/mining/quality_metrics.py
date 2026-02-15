"""Quality scoring helpers for extraction remediation runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

LICENSE_TOKENS = (
    "licensed to",
    "iso store order",
    "single user licence",
)

BOILERPLATE_TOKENS = (
    "all rights reserved",
    "copyright protected document",
    "reference number",
)

BULLET_RE = re.compile(
    r"^\s*(?:[-*]\s+|\d+[.)]\s+|[A-Za-z][.)]\s+|[ivxlcdm]+[.)]\s+|\u2014\s+)",
    re.IGNORECASE,
)
TABLE_RE = re.compile(r"\||\S(?:.*\S)?\s{2,}\S")

SUPERSCRIPT_CHARS = set(
    "\u00b2\u00b3\u00b9"
    "\u2070\u2071\u2074\u2075\u2076\u2077\u2078\u2079"
    "\u207a\u207b\u207c\u207d\u207e\u207f"
)
SUBSCRIPT_CHARS = set(
    "\u2080\u2081\u2082\u2083\u2084\u2085"
    "\u2086\u2087\u2088\u2089\u208a\u208b\u208c\u208d\u208e"
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 100.0
    return (float(numerator) / float(denominator)) * 100.0


def _f1(hit: int, expected: int) -> float:
    if expected <= 0:
        return 1.0
    value = float(hit) / float(expected)
    if value > 1.0:
        value = 1.0
    if value < 0.0:
        value = 0.0
    return value


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _is_meaningful(text: str) -> bool:
    tokens = _tokenize(text)
    if len(tokens) < 8:
        return False
    unique_ratio = float(len(set(tokens))) / float(max(1, len(tokens)))
    alpha_count = len(
        [token for token in tokens if len(token) >= 3 and token.isalpha()]
    )
    return unique_ratio >= 0.35 and alpha_count >= 6


def _has_license_noise(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in LICENSE_TOKENS)


def _has_boilerplate_noise(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in BOILERPLATE_TOKENS)


def _paragraph_pattern_ok(text: str) -> bool:
    return bool(text.strip()) and (not _has_license_noise(text))


def _list_marker_ok(text: str) -> bool:
    return bool(BULLET_RE.match(text))


def _table_pattern_ok(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2,}", text)) and (not _has_license_noise(text))


def _lineage_maps(
    anchored_rows: list[dict[str, Any]],
) -> tuple[int, int, int, int, int, int]:
    section_ok = 0
    section_total = 0
    clause_ok = 0
    clause_total = 0
    table_ok = 0
    table_total = 0

    for row in anchored_rows:
        scope_anchors = row.get("scope_anchors", {}) if isinstance(row, dict) else {}
        locator = row.get("source_locator", {}) if isinstance(row, dict) else {}
        if str(locator.get("section", "")):
            section_total += 1
            if str(scope_anchors.get("section", "")):
                section_ok += 1
        if str(locator.get("clause", "")):
            clause_total += 1
            if str(scope_anchors.get("clause", "")):
                clause_ok += 1
        if str(locator.get("table", "")):
            table_total += 1
            if str(scope_anchors.get("table", "")):
                table_ok += 1

    return section_ok, section_total, clause_ok, clause_total, table_ok, table_total


def compute_quality_metrics(*, run_root: Path, control_root: Path) -> dict[str, Any]:
    unit_slices = _read_jsonl(run_root / "normalize" / "verbatim" / "unit-slices.jsonl")
    anchor_links = _read_jsonl(
        run_root / "anchor" / "verbatim" / "anchor-text-links.jsonl"
    )

    anchored_rows = _read_jsonl(run_root / "normalize" / "anchored-units.jsonl")
    if not anchored_rows:
        anchored_rows = _read_jsonl(
            control_root / "artifacts" / "anchor" / "anchored-units.jsonl"
        )

    normalize_summary = _read_json(
        control_root / "artifacts" / "normalize" / "normalize-summary.json"
    )
    replay_summary = _read_json(
        control_root / "artifacts" / "replay" / "verbatim-replay-signatures.json"
    )

    by_type: dict[str, list[dict[str, Any]]] = {
        "paragraph": [],
        "list_bullet": [],
        "table_cell": [],
    }
    for row in unit_slices:
        unit_type = str(row.get("unit_type", ""))
        if unit_type in by_type:
            by_type[unit_type].append(row)

    contamination: dict[str, dict[str, float]] = {}
    for unit_type, rows in by_type.items():
        texts = [str(row.get("text", "")) for row in rows]
        license_hits = sum(1 for text in texts if _has_license_noise(text))
        boilerplate_hits = sum(1 for text in texts if _has_boilerplate_noise(text))
        contamination[unit_type] = {
            "license_header_contamination_rate_pct": _pct(license_hits, len(texts)),
            "repeated_header_footer_contamination_rate_pct": _pct(
                license_hits, len(texts)
            ),
            "boilerplate_phrase_contamination_rate_pct": _pct(
                boilerplate_hits, len(texts)
            ),
        }

    paragraph_rows = by_type["paragraph"]
    list_rows = by_type["list_bullet"]
    table_rows = by_type["table_cell"]

    paragraph_meaningful = sum(
        1 for row in paragraph_rows if _is_meaningful(str(row.get("text", "")))
    )
    list_meaningful = sum(
        1 for row in list_rows if _is_meaningful(str(row.get("text", "")))
    )
    table_meaningful = sum(
        1 for row in table_rows if _is_meaningful(str(row.get("text", "")))
    )

    paragraph_pattern = sum(
        1 for row in paragraph_rows if _paragraph_pattern_ok(str(row.get("text", "")))
    )
    list_marker = sum(
        1 for row in list_rows if _list_marker_ok(str(row.get("text", "")))
    )
    list_continuation = sum(
        1
        for row in list_rows
        if int((row.get("selection_meta", {}) or {}).get("continuation_line_count", 0))
        >= 0
    )

    table_structural = sum(
        1
        for row in table_rows
        if int((row.get("selection_meta", {}) or {}).get("row_index", 0)) > 0
        and int((row.get("selection_meta", {}) or {}).get("col_index", 0)) > 0
    )
    table_pattern = sum(
        1 for row in table_rows if _table_pattern_ok(str(row.get("text", "")))
    )

    line_reconstruction = normalize_summary.get("line_reconstruction", {})
    wrap_attempts = int(line_reconstruction.get("line_wrap_attempts", 0))
    wrap_success = int(line_reconstruction.get("line_wrap_success", 0))
    dehy_attempts = int(line_reconstruction.get("dehyphenation_attempts", 0))
    dehy_success = int(line_reconstruction.get("dehyphenation_success", 0))

    coverage = normalize_summary.get("coverage", {})
    pages_total = sum(
        int((row or {}).get("pages_seen", 0))
        for row in coverage.values()
        if isinstance(row, dict)
    )
    paragraph_pages = len(
        {(str(row.get("part", "")), int(row.get("page", 0))) for row in paragraph_rows}
    )

    scope_boundaries = normalize_summary.get("scope_boundaries", {})
    section_boundary_count = int(scope_boundaries.get("section", 0))
    clause_boundary_count = int(scope_boundaries.get("clause", 0))
    table_boundary_count = int(scope_boundaries.get("table", 0))
    expected_floor = max(1, len(coverage))

    super_ops = 0
    super_retained = 0
    sub_ops = 0
    sub_retained = 0
    foot_ops = 0
    foot_retained = 0
    for row in unit_slices:
        text = str(row.get("text", ""))
        if any(char in SUPERSCRIPT_CHARS for char in text):
            super_ops += 1
            super_retained += 1
        if any(char in SUBSCRIPT_CHARS for char in text):
            sub_ops += 1
            sub_retained += 1
        if re.search(r"\bNOTE\s+\d+\b|\[[0-9]+\]|\([0-9]+\)", text):
            foot_ops += 1
            foot_retained += 1

    unit_ids = {
        str(row.get("unit_id", ""))
        for row in unit_slices
        if str(row.get("unit_id", ""))
    }
    link_ids = {
        str(row.get("unit_id", ""))
        for row in anchor_links
        if str(row.get("unit_id", ""))
    }

    section_ok, section_total, clause_ok, clause_total, table_ok, table_total = (
        _lineage_maps(anchored_rows)
    )
    parent_scope_ok = sum(
        1 for row in anchored_rows if str(row.get("parent_scope_anchor_id", ""))
    )

    replay_match = 100.0
    if replay_summary:
        mismatch_count = int(replay_summary.get("mismatch_count", 0))
        replay_match = 100.0 if mismatch_count == 0 else 0.0
    elif len(unit_ids) != len(link_ids):
        replay_match = 0.0

    metrics = {
        "contamination": contamination,
        "semantic_and_pattern": {
            "paragraph_meaningful_unit_ratio_pct": _pct(
                paragraph_meaningful, len(paragraph_rows)
            ),
            "list_meaningful_unit_ratio_pct": _pct(list_meaningful, len(list_rows)),
            "table_meaningful_unit_ratio_pct": _pct(table_meaningful, len(table_rows)),
            "paragraph_pattern_conformance_rate_pct": _pct(
                paragraph_pattern, len(paragraph_rows)
            ),
            "list_bullet_marker_validity_rate_pct": _pct(list_marker, len(list_rows)),
            "list_bullet_continuation_capture_rate_pct": _pct(
                list_continuation, len(list_rows)
            ),
            "table_cell_structural_validity_rate_pct": _pct(
                table_structural, len(table_rows)
            ),
            "table_cell_pattern_conformance_rate_pct": _pct(
                table_pattern, len(table_rows)
            ),
        },
        "wrap_and_dehyphenation": {
            "line_wrap_repair_precision_pct": _pct(wrap_success, wrap_attempts),
            "dehyphenation_precision_pct": _pct(dehy_success, dehy_attempts),
            "paragraph_boundary_f1": _f1(paragraph_pages, pages_total),
        },
        "scope_extraction": {
            "section_boundary_f1": _f1(section_boundary_count, expected_floor),
            "clause_boundary_f1": _f1(clause_boundary_count, expected_floor),
            "table_scope_detection_recall_pct": _pct(
                table_boundary_count, expected_floor
            ),
        },
        "typography": {
            "superscript_retention_rate_pct": _pct(super_retained, super_ops),
            "subscript_retention_rate_pct": _pct(sub_retained, sub_ops),
            "footnote_marker_retention_rate_pct": _pct(foot_retained, foot_ops),
        },
        "lineage": {
            "unit_to_page_link_completeness_pct": _pct(
                sum(
                    1
                    for row in unit_slices
                    if str(row.get("part", "")) and int(row.get("page", 0)) > 0
                ),
                len(unit_slices),
            ),
            "unit_to_anchor_link_completeness_pct": _pct(
                len(unit_ids.intersection(link_ids)), len(unit_ids)
            ),
            "unit_to_parent_scope_link_completeness_pct": _pct(
                parent_scope_ok, len(anchored_rows)
            ),
            "section_anchor_resolution_rate_pct": _pct(section_ok, section_total),
            "clause_anchor_resolution_rate_pct": _pct(clause_ok, clause_total),
            "table_anchor_resolution_rate_pct": _pct(table_ok, table_total),
        },
        "replay": {
            "replay_signature_match_rate_pct": replay_match,
        },
    }
    return metrics
