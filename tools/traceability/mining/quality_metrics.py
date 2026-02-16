"""Quality scoring helpers for extraction remediation runs."""

from __future__ import annotations

import itertools
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

LICENSE_TOKENS = (
    "licensed to",
    "iso store order",
    "single user licence",
    "copyright office",
)

BOILERPLATE_TOKENS = (
    "all rights reserved",
    "copyright protected document",
    "reference number",
    "published in switzerland",
)

FRAGMENT_CONNECTORS = {
    "and",
    "or",
    "but",
    "for",
    "to",
    "of",
    "in",
    "on",
    "with",
    "by",
    "from",
    "including",
    "without",
}

REQUIRED_PARTS = ("P06", "P08", "P09")
BOUNDARY_UNIT_TYPES = ("paragraph", "list_bullet", "table_cell")

BULLET_RE = re.compile(
    r"^\s*(?:[-*]\s+|\d+[.)]\s+|[A-Za-z][.)]\s+|[ivxlcdm]+[.)]\s+|\u2014\s+)",
    re.IGNORECASE,
)
SENTENCE_END_RE = re.compile(r"[.!?;:)](?:['\"])?$")

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


def _clamp_pct(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 100.0:
        return 100.0
    return value


def _pct(
    numerator: int | float,
    denominator: int | float,
    *,
    zero_denominator: float = 100.0,
) -> float:
    if denominator <= 0:
        return _clamp_pct(float(zero_denominator))
    return _clamp_pct((float(numerator) / float(denominator)) * 100.0)


def _f1(hit: int | float, expected: int | float) -> float:
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


def _row_part(row: dict[str, Any]) -> str:
    part = str(row.get("part", "")).upper()
    if part:
        return part
    locator = row.get("source_locator", {}) if isinstance(row, dict) else {}
    return str(locator.get("part", "")).upper()


def _source_signature(row: dict[str, Any]) -> tuple[str, ...]:
    refs = row.get("source_block_refs", [])
    if not isinstance(refs, list):
        return tuple()
    return tuple(sorted(str(item) for item in refs if str(item)))


def _row_page(row: dict[str, Any]) -> int:
    try:
        return int(row.get("page", 0) or 0)
    except Exception:
        return 0


def _empty_boundary_scores(mode: str) -> dict[str, Any]:
    return {
        "scorer_mode": mode,
        "goldset_row_count": 0,
        "matched_segments": {
            "paragraph": 0,
            "list_bullet": 0,
            "table_cell": 0,
        },
        "expected_segments": {
            "paragraph": 0,
            "list_bullet": 0,
            "table_cell": 0,
        },
        "predicted_segments": {
            "paragraph": 0,
            "list_bullet": 0,
            "table_cell": 0,
        },
        "paragraph_boundary_precision": 1.0,
        "paragraph_boundary_recall": 1.0,
        "paragraph_boundary_f1": 1.0,
        "list_boundary_precision": 1.0,
        "list_boundary_recall": 1.0,
        "list_boundary_f1": 1.0,
        "table_cell_boundary_precision": 1.0,
        "table_cell_boundary_recall": 1.0,
        "table_cell_boundary_f1": 1.0,
    }


def _parse_expected_counts(row: dict[str, Any], unit_type: str) -> int:
    expected_counts = row.get("expected_counts", {})
    if isinstance(expected_counts, dict) and unit_type in expected_counts:
        try:
            return max(0, int(expected_counts.get(unit_type, 0) or 0))
        except Exception:
            return 0

    expected_boundaries = row.get("expected_boundaries", {})
    if isinstance(expected_boundaries, dict):
        if unit_type in expected_boundaries and isinstance(
            expected_boundaries.get(unit_type), list
        ):
            return len(expected_boundaries.get(unit_type, []))

    row_type = str(row.get("unit_type", ""))
    if row_type == unit_type:
        return 1
    return 0


def _compute_boundary_goldset_scores(
    *,
    unit_slices: list[dict[str, Any]],
    goldset_rows: list[dict[str, Any]],
    part: str | None,
) -> dict[str, Any]:
    if not goldset_rows:
        return _empty_boundary_scores("fixture")

    fixture_rows = []
    for row in goldset_rows:
        row_part = str(row.get("part", "")).upper()
        if part and row_part != part:
            continue
        row_page = _row_page(row)
        if not row_part or row_page <= 0:
            continue
        fixture_rows.append((row_part, row_page, row))

    if not fixture_rows:
        return _empty_boundary_scores("fixture")

    predicted_by_key: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    for row in unit_slices:
        row_part = _row_part(row)
        if part and row_part != part:
            continue
        row_page = _row_page(row)
        unit_type = str(row.get("unit_type", ""))
        if row_page <= 0 or unit_type not in BOUNDARY_UNIT_TYPES:
            continue
        predicted_by_key[(row_part, row_page)][unit_type] += 1

    expected_totals = {unit_type: 0 for unit_type in BOUNDARY_UNIT_TYPES}
    predicted_totals = {unit_type: 0 for unit_type in BOUNDARY_UNIT_TYPES}
    matched_totals = {unit_type: 0 for unit_type in BOUNDARY_UNIT_TYPES}

    for row_part, row_page, row in fixture_rows:
        pred_counter = predicted_by_key.get((row_part, row_page), Counter())
        for unit_type in BOUNDARY_UNIT_TYPES:
            expected_count = _parse_expected_counts(row, unit_type)
            predicted_count = int(pred_counter.get(unit_type, 0))
            expected_totals[unit_type] += expected_count
            predicted_totals[unit_type] += predicted_count
            matched_totals[unit_type] += min(expected_count, predicted_count)

    def score(unit_type: str) -> tuple[float, float, float]:
        expected_total = expected_totals[unit_type]
        predicted_total = predicted_totals[unit_type]
        matched_total = matched_totals[unit_type]

        if predicted_total <= 0:
            precision = 1.0 if expected_total <= 0 else 0.0
        else:
            precision = float(matched_total) / float(predicted_total)

        if expected_total <= 0:
            recall = 1.0
        else:
            recall = float(matched_total) / float(expected_total)

        if precision + recall <= 0.0:
            f1 = 0.0
        else:
            f1 = (2.0 * precision * recall) / (precision + recall)
        return precision, recall, f1

    paragraph_precision, paragraph_recall, paragraph_f1 = score("paragraph")
    list_precision, list_recall, list_f1 = score("list_bullet")
    table_precision, table_recall, table_f1 = score("table_cell")

    return {
        "scorer_mode": "fixture",
        "goldset_row_count": len(fixture_rows),
        "matched_segments": matched_totals,
        "expected_segments": expected_totals,
        "predicted_segments": predicted_totals,
        "paragraph_boundary_precision": paragraph_precision,
        "paragraph_boundary_recall": paragraph_recall,
        "paragraph_boundary_f1": paragraph_f1,
        "list_boundary_precision": list_precision,
        "list_boundary_recall": list_recall,
        "list_boundary_f1": list_f1,
        "table_cell_boundary_precision": table_precision,
        "table_cell_boundary_recall": table_recall,
        "table_cell_boundary_f1": table_f1,
    }


def _starts_like_fragment(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    first = stripped[0]
    if first.islower() or first in {",", ";", ")", "-"}:
        return True
    match = re.match(r"[A-Za-z]+", stripped)
    if not match:
        return False
    return match.group(0).lower() in FRAGMENT_CONNECTORS


def _ends_like_fragment(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return False
    if SENTENCE_END_RE.search(stripped):
        return False
    if stripped.endswith(("-", ",", "...")):
        return True
    return stripped[-1].isalnum()


def _compute_pathology_metrics(
    *,
    unit_slices: list[dict[str, Any]],
    paragraph_rows: list[dict[str, Any]],
    list_rows: list[dict[str, Any]],
    table_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    residual_legal_hits = 0
    fragment_start_hits = 0
    fragment_end_hits = 0
    oversized_hits = 0

    paragraph_page_counts: Counter[tuple[str, int]] = Counter()
    page_rows: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    page_type_refsets: defaultdict[tuple[str, int], dict[str, set[str]]] = defaultdict(
        lambda: {"paragraph": set(), "list_bullet": set(), "table_cell": set()}
    )
    page_type_signatures: defaultdict[
        tuple[str, int], dict[str, Counter[tuple[str, ...]]]
    ] = defaultdict(
        lambda: {
            "paragraph": Counter(),
            "list_bullet": Counter(),
            "table_cell": Counter(),
        }
    )

    for row in unit_slices:
        part = _row_part(row)
        page = int(row.get("page", 0) or 0)
        if not part or page <= 0:
            continue
        key = (part, page)
        unit_type = str(row.get("unit_type", ""))
        text = str(row.get("text", ""))

        page_rows[key].append(row)
        if unit_type in {"paragraph", "list_bullet", "table_cell"}:
            refs = page_type_refsets[key][unit_type]
            refs.update(
                str(item) for item in row.get("source_block_refs", []) if str(item)
            )
            page_type_signatures[key][unit_type][_source_signature(row)] += 1

        if _has_license_noise(text) or _has_boilerplate_noise(text):
            residual_legal_hits += 1

    for row in paragraph_rows:
        part = _row_part(row)
        page = int(row.get("page", 0) or 0)
        if part and page > 0:
            paragraph_page_counts[(part, page)] += 1

        text = str(row.get("text", ""))
        if _starts_like_fragment(text):
            fragment_start_hits += 1
        if _ends_like_fragment(text):
            fragment_end_hits += 1
        if len(_tokenize(text)) > 220:
            oversized_hits += 1

    singleton_pages = sum(1 for count in paragraph_page_counts.values() if count == 1)
    paragraph_page_total = len(paragraph_page_counts)

    triad_identity_pages = 0
    triad_identity_hits = 0
    overlap_values: list[float] = []

    for key, rows in page_rows.items():
        _ = key
        present_types = {str(row.get("unit_type", "")) for row in rows}
        active_types = [
            unit_type
            for unit_type in ("paragraph", "list_bullet", "table_cell")
            if unit_type in present_types
        ]
        if len(active_types) < 2:
            continue

        triad_identity_pages += 1
        dominant_signatures: list[tuple[str, ...]] = []
        for unit_type in active_types:
            counter = page_type_signatures[key][unit_type]
            if not counter:
                continue
            dominant_signatures.append(counter.most_common(1)[0][0])
        if dominant_signatures and len(set(dominant_signatures)) == 1:
            triad_identity_hits += 1

        type_pairs = list(itertools.combinations(active_types, 2))
        for left, right in type_pairs:
            left_refs = page_type_refsets[key][left]
            right_refs = page_type_refsets[key][right]
            union = left_refs.union(right_refs)
            if not union:
                continue
            overlap_values.append(
                float(len(left_refs.intersection(right_refs))) / float(len(union))
            )

    pathology = {
        "residual_legal_boilerplate_hit_count": residual_legal_hits,
        "triad_source_set_identity_rate_pct": _pct(
            triad_identity_hits,
            triad_identity_pages,
            zero_denominator=100.0,
        ),
        "paragraph_fragment_start_rate_pct": _pct(
            fragment_start_hits,
            len(paragraph_rows),
            zero_denominator=100.0,
        ),
        "paragraph_fragment_end_rate_pct": _pct(
            fragment_end_hits,
            len(paragraph_rows),
            zero_denominator=100.0,
        ),
        "paragraph_singleton_page_rate_pct": _pct(
            singleton_pages,
            paragraph_page_total,
            zero_denominator=100.0,
        ),
        "oversized_paragraph_rate_pct": _pct(
            oversized_hits,
            len(paragraph_rows),
            zero_denominator=100.0,
        ),
        "unit_type_provenance_overlap_rate_pct": (
            _clamp_pct(float(sum(overlap_values)) / float(len(overlap_values)) * 100.0)
            if overlap_values
            else 0.0
        ),
    }
    _ = list_rows
    _ = table_rows
    return pathology


def _compute_metrics_core(
    *,
    unit_slices: list[dict[str, Any]],
    anchor_links: list[dict[str, Any]],
    anchored_rows: list[dict[str, Any]],
    normalize_summary: dict[str, Any],
    replay_summary: dict[str, Any],
    goldset_rows: list[dict[str, Any]],
    part: str | None,
    boundary_goldset_required: bool,
) -> dict[str, Any]:
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
    if part:
        part_coverage = coverage.get(part, {}) if isinstance(coverage, dict) else {}
        pages_total = int((part_coverage or {}).get("pages_seen", 0))
    else:
        pages_total = sum(
            int((row or {}).get("pages_seen", 0))
            for row in coverage.values()
            if isinstance(row, dict)
        )
    if pages_total <= 0:
        pages_total = len(
            {
                (_row_part(row), int(row.get("page", 0) or 0))
                for row in unit_slices
                if _row_part(row) and int(row.get("page", 0) or 0) > 0
            }
        )
    paragraph_pages = len(
        {
            (_row_part(row), int(row.get("page", 0) or 0))
            for row in paragraph_rows
            if _row_part(row) and int(row.get("page", 0) or 0) > 0
        }
    )
    paragraph_boundary_proxy_f1 = _f1(paragraph_pages, pages_total)

    if part:
        scope_boundaries = (
            normalize_summary.get("scope_boundaries_by_part", {}).get(part, {})
            if isinstance(normalize_summary, dict)
            else {}
        )
        scope_opportunities = (
            normalize_summary.get("scope_opportunities_by_part", {}).get(part, {})
            if isinstance(normalize_summary, dict)
            else {}
        )
    else:
        scope_boundaries = normalize_summary.get("scope_boundaries", {})
        scope_opportunities = normalize_summary.get("scope_opportunities", {})

    section_boundary_count = int((scope_boundaries or {}).get("section", 0))
    clause_boundary_count = int((scope_boundaries or {}).get("clause", 0))
    table_boundary_count = int((scope_boundaries or {}).get("table", 0))

    section_opportunity_count = int(
        max(
            section_boundary_count,
            int((scope_opportunities or {}).get("section", 0)),
            1 if pages_total > 0 else 0,
        )
    )
    clause_opportunity_count = int(
        max(
            clause_boundary_count,
            int((scope_opportunities or {}).get("clause", 0)),
            1 if pages_total > 0 else 0,
        )
    )
    table_opportunity_count = int(
        max(
            table_boundary_count,
            int((scope_opportunities or {}).get("table", 0)),
        )
    )

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

    pathology = _compute_pathology_metrics(
        unit_slices=unit_slices,
        paragraph_rows=paragraph_rows,
        list_rows=list_rows,
        table_rows=table_rows,
    )

    if boundary_goldset_required and not goldset_rows:
        raise RuntimeError("Boundary goldset fixture missing or empty")

    if goldset_rows:
        boundary_goldset = _compute_boundary_goldset_scores(
            unit_slices=unit_slices,
            goldset_rows=goldset_rows,
            part=part,
        )
    else:
        boundary_goldset = _empty_boundary_scores("proxy")
        boundary_goldset.update(
            {
                "paragraph_boundary_precision": paragraph_boundary_proxy_f1,
                "paragraph_boundary_recall": paragraph_boundary_proxy_f1,
                "paragraph_boundary_f1": paragraph_boundary_proxy_f1,
                "list_boundary_precision": _f1(list_marker, len(list_rows)),
                "list_boundary_recall": _f1(list_marker, len(list_rows)),
                "list_boundary_f1": _f1(list_marker, len(list_rows)),
                "table_cell_boundary_precision": _f1(table_structural, len(table_rows)),
                "table_cell_boundary_recall": _f1(table_structural, len(table_rows)),
                "table_cell_boundary_f1": _f1(table_structural, len(table_rows)),
            }
        )

    return {
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
            "paragraph_boundary_f1": paragraph_boundary_proxy_f1,
        },
        "scope_extraction": {
            "section_boundary_f1": _f1(
                section_boundary_count,
                section_opportunity_count,
            ),
            "clause_boundary_f1": _f1(
                clause_boundary_count,
                clause_opportunity_count,
            ),
            "table_scope_detection_recall_pct": _pct(
                table_boundary_count,
                table_opportunity_count,
                zero_denominator=100.0,
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
                    if _row_part(row) and int(row.get("page", 0) or 0) > 0
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
        "pathology": pathology,
        "boundary_goldset": boundary_goldset,
    }


def compute_quality_metrics(
    *,
    run_root: Path,
    control_root: Path,
    boundary_goldset_path: Path | None = None,
    boundary_goldset_required: bool = False,
) -> dict[str, Any]:
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

    if boundary_goldset_path is None:
        boundary_goldset_path = (
            control_root / "artifacts" / "fixtures" / "boundary-goldset.jsonl"
        )
    goldset_rows = _read_jsonl(boundary_goldset_path)

    overall = _compute_metrics_core(
        unit_slices=unit_slices,
        anchor_links=anchor_links,
        anchored_rows=anchored_rows,
        normalize_summary=normalize_summary,
        replay_summary=replay_summary,
        goldset_rows=goldset_rows,
        part=None,
        boundary_goldset_required=boundary_goldset_required,
    )

    parts_in_rows = {_row_part(row) for row in unit_slices if _row_part(row)}
    parts = sorted(set(REQUIRED_PARTS).union(parts_in_rows))

    by_part: dict[str, dict[str, Any]] = {}
    for part in parts:
        unit_rows = [row for row in unit_slices if _row_part(row) == part]
        part_anchor_links = [row for row in anchor_links if _row_part(row) == part]
        part_anchored = [row for row in anchored_rows if _row_part(row) == part]
        if not unit_rows and part in parts_in_rows:
            continue
        by_part[part] = _compute_metrics_core(
            unit_slices=unit_rows,
            anchor_links=part_anchor_links,
            anchored_rows=part_anchored,
            normalize_summary=normalize_summary,
            replay_summary=replay_summary,
            goldset_rows=goldset_rows,
            part=part,
            boundary_goldset_required=boundary_goldset_required,
        )

    overall["by_part"] = by_part
    overall["required_parts"] = list(REQUIRED_PARTS)
    return overall
