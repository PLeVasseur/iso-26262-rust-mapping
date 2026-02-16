"""Normalize stage and quality-aware unitization pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .framework import utc_now
from .jsonc import write_json
from .verbatim import normalize_for_query, text_sha256

if TYPE_CHECKING:
    from .stages import StageContext, StageResult


class NormalizeError(RuntimeError):
    """Raised for normalize-stage gate failures."""


LICENSE_PATTERNS = (
    re.compile(r"licensed to", re.IGNORECASE),
    re.compile(r"iso store order", re.IGNORECASE),
    re.compile(r"single user licence", re.IGNORECASE),
    re.compile(r"all rights reserved", re.IGNORECASE),
    re.compile(r"copyright protected document", re.IGNORECASE),
    re.compile(r"copyright office", re.IGNORECASE),
    re.compile(r"without prior written permission", re.IGNORECASE),
    re.compile(r"published in switzerland", re.IGNORECASE),
)

HEADER_PATTERNS = (
    re.compile(r"^iso\s*26262[-; ]\d+:2018\(e\)$", re.IGNORECASE),
    re.compile(r"^\u00a9\s*iso\s*2018", re.IGNORECASE),
    re.compile(r"^reference number$", re.IGNORECASE),
)

BULLET_RE = re.compile(
    r"^\s*(?:[-*]\s+|\d+[.)]\s+|[A-Za-z][.)]\s+|[ivxlcdm]+[.)]\s+|\u2014\s+)",
    re.IGNORECASE,
)
TABLE_CAPTION_RE = re.compile(
    r"^\s*table\s+(\d+|[a-z]\d*)\s*[\u2014\-:].*", re.IGNORECASE
)
CLAUSE_RE = re.compile(r"^\s*(\d+\.\d+(?:\.\d+)*)\s+(.+)$")
SECTION_RE = re.compile(r"^\s*(\d{1,2})\s+([A-Z].{2,})$")
TABLE_LINE_RE = re.compile(r"\|")
MULTI_COL_RE = re.compile(r"\S(?:.*\S)?\s{2,}\S")
TOC_DOT_LEADER_RE = re.compile(r"\.{3,}\s*\d*$")
NORMATIVE_MODAL_RE = re.compile(r"\b(shall|should|may|must)\b", re.IGNORECASE)


def _unique_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


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
    rows.sort(key=lambda row: (str(row.get("part", "")), int(row.get("page", 0))))
    return rows


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise NormalizeError(f"missing required input: {path}")
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _normalize_line(text: str) -> str:
    cleaned = text.replace("\ufeff", " ").replace("\f", " ").replace("\r", " ")
    return cleaned.strip()


def _canonical_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _looks_like_noise(line: str) -> bool:
    if not line:
        return True
    low = _canonical_line(line)
    if any(pattern.search(low) for pattern in LICENSE_PATTERNS):
        return True
    if any(pattern.match(low) for pattern in HEADER_PATTERNS):
        return True
    if re.fullmatch(r"[ivxlcdm]+", low):
        return True
    if re.fullmatch(r"\d+", low):
        return True
    return False


def _is_heading_line(line: str) -> bool:
    return bool(
        SECTION_RE.match(line) or CLAUSE_RE.match(line) or TABLE_CAPTION_RE.match(line)
    )


def _is_toc_line(line: str) -> bool:
    stripped = line.strip()
    low = _canonical_line(stripped)
    if not stripped:
        return False
    if low.startswith("contents"):
        return True
    if TOC_DOT_LEADER_RE.search(stripped):
        return True
    return bool(re.search(r"\.{3,}\s*\d+\s*$", stripped))


def _split_table_cells(line: str) -> list[str]:
    if "|" in line:
        raw_cells = [cell.strip() for cell in line.split("|")]
    else:
        raw_cells = [cell.strip() for cell in re.split(r"\s{2,}", line.strip())]
    return [cell for cell in raw_cells if cell]


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _is_list_line(stripped) or _is_heading_line(stripped) or _is_toc_line(stripped):
        return False

    has_pipe = bool(TABLE_LINE_RE.search(stripped))
    has_multicol = bool(MULTI_COL_RE.search(stripped))
    if not has_pipe and not has_multicol:
        return False

    cells = _split_table_cells(stripped)
    if len(cells) < 2:
        return False
    if not has_pipe and len(cells) < 3:
        return False

    token_count = len(re.findall(r"[A-Za-z0-9_]+", stripped))
    if not has_pipe and token_count > 22:
        return False

    informative_cells = sum(
        1
        for cell in cells
        if re.search(r"[A-Za-z]{2,}", cell) or re.search(r"\d", cell)
    )
    if informative_cells < 2:
        return False

    if any(len(cell) > 140 for cell in cells):
        return False
    return True


def _is_list_line(line: str) -> bool:
    return bool(BULLET_RE.match(line))


def _has_normative_modal(text: str) -> bool:
    return bool(NORMATIVE_MODAL_RE.search(text or ""))


def _line_is_contaminated(line: str) -> bool:
    canonical = _canonical_line(line)
    return any(pattern.search(canonical) for pattern in LICENSE_PATTERNS)


def _candidate_is_contaminated(text: str) -> bool:
    low = _canonical_line(text)
    hit_count = sum(1 for pattern in LICENSE_PATTERNS if pattern.search(low))
    if hit_count >= 2:
        return True
    if hit_count == 1 and len(re.findall(r"[A-Za-z]{2,}", text)) < 40:
        return True
    return False


def _build_repeated_line_filter(block_rows: list[dict]) -> set[str]:
    pages_by_part: dict[str, set[int]] = {}
    line_pages: dict[tuple[str, str], set[int]] = {}

    for row in block_rows:
        part = str(row.get("part", ""))
        page = int(row.get("page", 0))
        text = _canonical_line(_normalize_line(str(row.get("text", ""))))
        if not part or not text or len(text) < 8:
            continue
        pages_by_part.setdefault(part, set()).add(page)
        key = (part, text)
        line_pages.setdefault(key, set()).add(page)

    repeated: set[str] = set()
    for (part, line), seen_pages in line_pages.items():
        page_count = max(1, len(pages_by_part.get(part, set())))
        threshold = max(3, int(page_count * 0.30))
        if len(seen_pages) >= threshold:
            repeated.add(f"{part}::{line}")
    return repeated


def _clean_page_lines(
    part: str, block_rows: list[dict], repeated_lines: set[str]
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for line_index, row in enumerate(block_rows):
        line = _normalize_line(str(row.get("text", "")))
        if not line:
            continue
        lowered = _canonical_line(line)
        if f"{part}::{lowered}" in repeated_lines:
            continue
        if _looks_like_noise(line):
            continue

        block_id = str(row.get("block_id", ""))
        cleaned.append(
            {
                "text": line,
                "source_line_indices": [line_index],
                "source_block_refs": [block_id] if block_id else [],
            }
        )
    return cleaned


def _merge_wrapped_lines(
    lines: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not lines:
        return [], {
            "line_wrap_attempts": 0,
            "line_wrap_success": 0,
            "dehyphenation_attempts": 0,
            "dehyphenation_success": 0,
        }

    merged: list[dict[str, Any]] = [dict(lines[0])]
    stats = {
        "line_wrap_attempts": 0,
        "line_wrap_success": 0,
        "dehyphenation_attempts": 0,
        "dehyphenation_success": 0,
    }

    for current in lines[1:]:
        previous = merged[-1]
        previous_text = str(previous.get("text", ""))
        current_text = str(current.get("text", ""))
        prev_tail = previous_text[-1:] if previous_text else ""
        curr_head = current_text[:1] if current_text else ""

        if previous_text.endswith("-") and curr_head.islower():
            stats["dehyphenation_attempts"] += 1
            previous["text"] = previous_text[:-1] + current_text
            previous["source_line_indices"] = sorted(
                set(previous.get("source_line_indices", [])).union(
                    set(current.get("source_line_indices", []))
                )
            )
            previous["source_block_refs"] = _unique_preserve(
                [
                    *[str(value) for value in previous.get("source_block_refs", [])],
                    *[str(value) for value in current.get("source_block_refs", [])],
                ]
            )
            stats["dehyphenation_success"] += 1
            continue

        if (
            _is_heading_line(previous_text)
            or _is_heading_line(current_text)
            or _is_table_line(previous_text)
            or _is_table_line(current_text)
        ):
            merged.append(dict(current))
            continue

        if _is_list_line(previous_text) and _is_list_line(current_text):
            merged.append(dict(current))
            continue

        joinable = prev_tail not in {".", ":", ";", "!", "?"} and curr_head.islower()
        if joinable:
            stats["line_wrap_attempts"] += 1
            previous["text"] = f"{previous_text} {current_text}"
            previous["source_line_indices"] = sorted(
                set(previous.get("source_line_indices", [])).union(
                    set(current.get("source_line_indices", []))
                )
            )
            previous["source_block_refs"] = _unique_preserve(
                [
                    *[str(value) for value in previous.get("source_block_refs", [])],
                    *[str(value) for value in current.get("source_block_refs", [])],
                ]
            )
            stats["line_wrap_success"] += 1
            continue

        merged.append(dict(current))

    return merged, stats


def _update_scope_context(
    lines: list[dict[str, Any]], prior: dict[str, str], page: int
) -> tuple[dict[str, str], dict[str, int], dict[str, int]]:
    context = dict(prior)
    boundaries = {"section": 0, "clause": 0, "table": 0}
    opportunities = {"section": 0, "clause": 0, "table": 0}

    table_line_hits = 0

    for line in lines:
        text = str(line.get("text", ""))
        table_match = TABLE_CAPTION_RE.match(text)
        if table_match:
            context["table_id"] = f"Table-{table_match.group(1)}"
            boundaries["table"] += 1
            opportunities["table"] += 1
            continue

        clause_match = CLAUSE_RE.match(text)
        if clause_match:
            clause_id = clause_match.group(1)
            context["clause"] = clause_id
            section_head = clause_id.split(".", 1)[0]
            context["section"] = f"{section_head}"
            boundaries["clause"] += 1
            boundaries["section"] += 1
            opportunities["clause"] += 1
            opportunities["section"] += 1
            continue

        section_match = SECTION_RE.match(text)
        if section_match:
            section_id = section_match.group(1)
            context["section"] = section_id
            context["clause"] = f"{section_id}.0"
            boundaries["section"] += 1
            opportunities["section"] += 1
            continue

        if _is_table_line(text):
            table_line_hits += 1

    if table_line_hits > 0 and opportunities["table"] == 0:
        opportunities["table"] = 1

    opportunities["section"] = max(opportunities["section"], boundaries["section"])
    opportunities["clause"] = max(opportunities["clause"], boundaries["clause"])
    opportunities["table"] = max(opportunities["table"], boundaries["table"])

    if not context.get("section"):
        context["section"] = str(max(page, 1))
    if not context.get("clause"):
        context["clause"] = f"{context['section']}.0"

    return context, boundaries, opportunities


def _collect_source_meta(lines: list[dict[str, Any]]) -> tuple[list[int], list[str]]:
    line_indices = sorted(
        {
            int(value)
            for line in lines
            for value in line.get("source_line_indices", [])
            if isinstance(value, int) or str(value).isdigit()
        }
    )
    block_refs = _unique_preserve(
        [
            str(value)
            for line in lines
            for value in line.get("source_block_refs", [])
            if str(value)
        ]
    )
    return line_indices, block_refs


def _build_paragraph_candidate(lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not lines:
        return None
    text = " ".join(
        str(line.get("text", "")).strip()
        for line in lines
        if str(line.get("text", "")).strip()
    ).strip()
    if not text or _is_toc_line(text):
        return None

    alpha_tokens = re.findall(r"[A-Za-z]{2,}", text)
    if len(alpha_tokens) < 6 and not _has_normative_modal(text):
        return None
    if _candidate_is_contaminated(text) and not _has_normative_modal(text):
        return None

    source_line_indices, source_block_refs = _collect_source_meta(lines)
    return {
        "text": text,
        "source_line_indices": source_line_indices,
        "source_block_refs": source_block_refs,
        "selection_meta": {
            "pattern_conformance": True,
            "segment_line_count": len(lines),
        },
    }


def _extract_paragraph_candidates(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    acc: list[dict[str, Any]] = []

    def flush() -> None:
        if not acc:
            return
        candidate = _build_paragraph_candidate(list(acc))
        if candidate is not None:
            candidates.append(candidate)
        acc.clear()

    for line in lines:
        text = str(line.get("text", ""))
        if _is_heading_line(text) or _is_list_line(text) or _is_table_line(text):
            flush()
            continue

        if acc:
            previous_text = str(acc[-1].get("text", "")).strip()
            current_text = text.strip()
            split_after_sentence = bool(
                re.search(r"[.!?;:]$", previous_text)
                and re.match(r"^[A-Z][A-Za-z]", current_text)
                and len(re.findall(r"[A-Za-z]{2,}", previous_text)) >= 6
            )
            if split_after_sentence:
                flush()

        acc.append(line)

    flush()
    return candidates


def _extract_list_candidates(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        line_text = str(line.get("text", ""))
        if not _is_list_line(line_text):
            i += 1
            continue

        merged = [line]
        continuation = 0
        i += 1
        while i < len(lines):
            nxt = lines[i]
            nxt_text = str(nxt.get("text", ""))
            if (
                _is_list_line(nxt_text)
                or _is_heading_line(nxt_text)
                or _is_table_line(nxt_text)
            ):
                break
            if nxt_text:
                merged.append(nxt)
                continuation += 1
            i += 1

        text = " ".join(
            str(item.get("text", "")).strip()
            for item in merged
            if str(item.get("text", "")).strip()
        ).strip()
        if not text:
            continue
        if _candidate_is_contaminated(text) and not _has_normative_modal(text):
            continue

        source_line_indices, source_block_refs = _collect_source_meta(merged)
        out.append(
            {
                "text": text,
                "source_line_indices": source_line_indices,
                "source_block_refs": source_block_refs,
                "selection_meta": {
                    "marker_valid": True,
                    "continuation_line_count": int(continuation),
                },
            }
        )
    return out


def _extract_table_cell_candidates(
    lines: list[dict[str, Any]], current_table_id: str
) -> list[dict[str, Any]]:
    regions: list[tuple[list[dict[str, Any]], bool, str]] = []
    current_region: list[dict[str, Any]] = []
    region_has_caption = False
    region_table_id = current_table_id

    for line in lines:
        text = str(line.get("text", ""))
        caption_match = TABLE_CAPTION_RE.match(text)
        if caption_match:
            if current_region:
                regions.append(
                    (list(current_region), region_has_caption, region_table_id)
                )
                current_region.clear()
            region_has_caption = True
            region_table_id = f"Table-{caption_match.group(1)}"
            continue

        if _is_table_line(text):
            cells = _split_table_cells(text)
            if len(cells) >= 2:
                current_region.append({"line": line, "cells": cells})
            continue

        if current_region:
            regions.append((list(current_region), region_has_caption, region_table_id))
            current_region.clear()
            region_has_caption = False
            region_table_id = current_table_id

    if current_region:
        regions.append((list(current_region), region_has_caption, region_table_id))

    candidates: list[dict[str, Any]] = []
    for region_rows, has_caption, table_id in regions:
        if len(region_rows) < 2:
            continue

        col_counts = [len(row.get("cells", [])) for row in region_rows]
        max_cols = max(col_counts) if col_counts else 0
        stable_rows = sum(
            1 for count in col_counts if count >= 2 and abs(count - max_cols) <= 1
        )
        if stable_rows < 2:
            continue

        table_name = table_id
        if not table_name:
            if has_caption or stable_rows >= 3:
                table_name = "Table-Unknown"
            else:
                continue

        for row_index, region_row in enumerate(region_rows, start=1):
            row_line = region_row.get("line", {})
            row_cells = [
                str(cell).strip()
                for cell in region_row.get("cells", [])
                if str(cell).strip()
            ]
            for col_index, cell in enumerate(row_cells, start=1):
                if len(re.findall(r"[A-Za-z0-9]", cell)) < 2:
                    continue
                if _candidate_is_contaminated(cell) and not _has_normative_modal(cell):
                    continue

                source_line_indices = sorted(
                    {
                        int(value)
                        for value in row_line.get("source_line_indices", [])
                        if isinstance(value, int) or str(value).isdigit()
                    }
                )
                source_block_refs = _unique_preserve(
                    [
                        str(value)
                        for value in row_line.get("source_block_refs", [])
                        if str(value)
                    ]
                )
                candidates.append(
                    {
                        "text": cell,
                        "source_line_indices": source_line_indices,
                        "source_block_refs": source_block_refs,
                        "selection_meta": {
                            "table_id": table_name,
                            "row_index": row_index,
                            "col_index": col_index,
                            "row_span": 1,
                            "col_span": 1,
                            "table_context_rows": len(region_rows),
                        },
                    }
                )

    return candidates


def _unit_id(part: str, page: int, unit_type: str, ordinal: int) -> str:
    suffix = {
        "paragraph": "par",
        "list_bullet": "lb",
        "table_cell": "tc",
    }.get(unit_type, unit_type)
    return f"{part.lower()}-p{page:04d}-{suffix}-{ordinal:03d}"


def _fingerprint(unit_id: str, method: str) -> str:
    return hashlib.sha256(f"{unit_id}:{method}".encode("utf-8")).hexdigest()[:24]


def _unit_from_selection(
    *,
    decision: dict,
    pdf_sha: str,
    unit_id: str,
    unit_type: str,
    unit_text: str,
    scope_context: dict[str, str],
    selection_meta: dict,
) -> dict:
    part = str(decision["part"])
    page = int(decision["page"])
    method = str(decision["method"])
    review_state = "auto_confirmed"
    if method == "ocr_fallback":
        band = decision.get("ocr", {}).get("quality_band", "fail")
        review_state = "manual_confirmed" if band == "pass" else "needs_review"

    section = scope_context.get("section", str(page))
    clause = scope_context.get("clause", f"{section}.0")
    table_id = scope_context.get("table_id", "") if unit_type == "table_cell" else ""

    source_locator = {
        "edition": "2018-ed2",
        "part": part,
        "section": section,
        "clause": clause,
        "table": table_id,
        "subclause_path": clause.split("."),
        "unit_type": unit_type,
        "page_start": page,
        "page_end": page,
    }

    return {
        "unit_id": unit_id,
        "unit_type": unit_type,
        "source_locator": source_locator,
        "display_locator": f"{part} / Clause {clause} / {unit_type}",
        "fingerprint": _fingerprint(unit_id, method),
        "provenance": {
            "source_pdf_sha256": pdf_sha,
            "extract_method": method,
            "unit_text_sha256": text_sha256(unit_text),
        },
        "review_state": review_state,
        "status": "mapped",
        "notes": "non-verbatim normalized unit",
        "selection_meta": selection_meta,
        "parent_scope": {
            "part": part,
            "section_id": f"{part}:{section}",
            "clause_id": f"{part}:{clause}",
            "table_id": f"{part}:{table_id}" if table_id else "",
        },
    }


def run_normalize_stage(ctx: "StageContext") -> "StageResult":
    ingest_summary = _load_ingest_summary(ctx.paths.control_run_root)
    decisions = _load_extract_decisions(ctx.paths.control_run_root)
    page_text_rows = _load_jsonl(
        ctx.paths.run_root / "extract" / "verbatim" / "page-text.jsonl"
    )
    page_block_rows = _load_jsonl(
        ctx.paths.run_root / "extract" / "verbatim" / "page-blocks.jsonl"
    )
    if not decisions:
        raise NormalizeError("extract decisions are empty")

    page_text_by_key: dict[tuple[str, int], dict] = {}
    for row in page_text_rows:
        page_text_by_key[(str(row["part"]), int(row["page"]))] = row

    blocks_by_key: dict[tuple[str, int], list[dict]] = {}
    for row in page_block_rows:
        key = (str(row["part"]), int(row["page"]))
        blocks_by_key.setdefault(key, []).append(row)
    for rows in blocks_by_key.values():
        rows.sort(
            key=lambda row: (
                int(row.get("block_ordinal", 0)),
                str(row.get("block_id", "")),
            )
        )

    repeated_line_filter = _build_repeated_line_filter(page_block_rows)

    resolved_parts = ingest_summary.get("resolved_parts", {})
    input_hashes = {part: info["sha256"] for part, info in resolved_parts.items()}

    units: list[dict] = []
    unit_slices: list[dict] = []
    unit_text_links: list[dict] = []
    query_source_rows: list[dict] = []
    qa_items: list[dict] = []

    required_unit_types = ("paragraph", "list_bullet", "table_cell")
    part_page_counts: dict[str, int] = {}
    part_unit_counts: dict[str, dict[str, int]] = {}
    wrap_stats = {
        "line_wrap_attempts": 0,
        "line_wrap_success": 0,
        "dehyphenation_attempts": 0,
        "dehyphenation_success": 0,
    }
    scope_boundaries = {"section": 0, "clause": 0, "table": 0}
    scope_opportunities = {"section": 0, "clause": 0, "table": 0}
    scope_boundaries_by_part: dict[str, dict[str, int]] = {}
    scope_opportunities_by_part: dict[str, dict[str, int]] = {}
    scope_context_by_part: dict[str, dict[str, str]] = {}

    for decision in decisions:
        part = str(decision["part"])
        page = int(decision["page"])
        key = (part, page)

        page_record = page_text_by_key.get(key)
        if page_record is None:
            raise NormalizeError(f"missing page-text record for {part} page {page}")
        page_record_id = str(page_record.get("record_id", ""))

        block_rows = blocks_by_key.get(key, [])
        if not block_rows:
            raise NormalizeError(f"missing page-block rows for {part} page {page}")

        part_page_counts[part] = part_page_counts.get(part, 0) + 1
        part_unit_counts.setdefault(
            part, {unit_type: 0 for unit_type in required_unit_types}
        )

        cleaned_lines = _clean_page_lines(part, block_rows, repeated_line_filter)
        merged_lines, line_stats = _merge_wrapped_lines(cleaned_lines)
        for stat_key in wrap_stats:
            wrap_stats[stat_key] += int(line_stats.get(stat_key, 0))

        prior_scope = scope_context_by_part.get(
            part, {"section": "1", "clause": "1.0", "table_id": ""}
        )
        scope_context, boundary_delta, opportunity_delta = _update_scope_context(
            merged_lines, prior_scope, page
        )
        scope_context_by_part[part] = scope_context

        scope_boundaries_by_part.setdefault(
            part, {"section": 0, "clause": 0, "table": 0}
        )
        scope_opportunities_by_part.setdefault(
            part, {"section": 0, "clause": 0, "table": 0}
        )
        for scope_key in scope_boundaries:
            boundary_value = int(boundary_delta.get(scope_key, 0))
            opportunity_value = int(opportunity_delta.get(scope_key, 0))
            scope_boundaries[scope_key] += boundary_value
            scope_opportunities[scope_key] += opportunity_value
            scope_boundaries_by_part[part][scope_key] += boundary_value
            scope_opportunities_by_part[part][scope_key] += opportunity_value

        paragraph_candidates = _extract_paragraph_candidates(merged_lines)
        list_candidates = _extract_list_candidates(merged_lines)
        table_candidates = _extract_table_cell_candidates(
            merged_lines, scope_context.get("table_id", "")
        )

        if table_candidates:
            scope_opportunities["table"] += 1
            scope_opportunities_by_part[part]["table"] += 1
            if int(boundary_delta.get("table", 0)) == 0:
                scope_boundaries["table"] += 1
                scope_boundaries_by_part[part]["table"] += 1

        selections: list[dict[str, Any]] = []
        if paragraph_candidates:
            for candidate in paragraph_candidates:
                selections.append(
                    {
                        "unit_type": "paragraph",
                        "text": str(candidate.get("text", "")),
                        "selection_meta": dict(candidate.get("selection_meta", {})),
                        "source_line_indices": list(
                            candidate.get("source_line_indices", [])
                        ),
                        "source_block_refs": list(
                            candidate.get("source_block_refs", [])
                        ),
                    }
                )
        elif merged_lines:
            first_line = str(merged_lines[0].get("text", ""))
            first_source_lines = [
                int(value)
                for value in merged_lines[0].get("source_line_indices", [])
                if isinstance(value, int) or str(value).isdigit()
            ]
            first_source_refs = _unique_preserve(
                [
                    str(value)
                    for value in merged_lines[0].get("source_block_refs", [])
                    if str(value)
                ]
            )
            selections.append(
                {
                    "unit_type": "paragraph",
                    "text": first_line,
                    "selection_meta": {"pattern_conformance": False},
                    "source_line_indices": first_source_lines,
                    "source_block_refs": first_source_refs,
                }
            )

        if list_candidates:
            for candidate in list_candidates:
                selections.append(
                    {
                        "unit_type": "list_bullet",
                        "text": str(candidate.get("text", "")),
                        "selection_meta": dict(candidate.get("selection_meta", {})),
                        "source_line_indices": list(
                            candidate.get("source_line_indices", [])
                        ),
                        "source_block_refs": list(
                            candidate.get("source_block_refs", [])
                        ),
                    }
                )

        if table_candidates:
            for candidate in table_candidates:
                selections.append(
                    {
                        "unit_type": "table_cell",
                        "text": str(candidate.get("text", "")),
                        "selection_meta": dict(candidate.get("selection_meta", {})),
                        "source_line_indices": list(
                            candidate.get("source_line_indices", [])
                        ),
                        "source_block_refs": list(
                            candidate.get("source_block_refs", [])
                        ),
                    }
                )

        if not selections:
            selections = [
                {
                    "unit_type": "paragraph",
                    "text": "",
                    "selection_meta": {"pattern_conformance": False},
                    "source_line_indices": [],
                    "source_block_refs": [],
                }
            ]

        unit_ordinal = 0
        for selection in selections:
            unit_type = str(selection.get("unit_type", ""))
            unit_text = str(selection.get("text", ""))
            selection_meta = dict(selection.get("selection_meta", {}))
            source_line_indices = sorted(
                {
                    int(value)
                    for value in selection.get("source_line_indices", [])
                    if isinstance(value, int) or str(value).isdigit()
                }
            )
            source_block_refs = _unique_preserve(
                [
                    str(value)
                    for value in selection.get("source_block_refs", [])
                    if str(value)
                ]
            )

            if not unit_type:
                continue
            if not unit_text.strip():
                continue

            if _candidate_is_contaminated(unit_text) and not _has_normative_modal(
                unit_text
            ):
                continue

            selection_meta["source_line_indices"] = source_line_indices
            selection_meta["source_block_ref_count"] = len(source_block_refs)

            unit_ordinal += 1
            unit_id = _unit_id(part, page, unit_type, unit_ordinal)
            unit = _unit_from_selection(
                decision=decision,
                pdf_sha=input_hashes.get(part, ""),
                unit_id=unit_id,
                unit_type=unit_type,
                unit_text=unit_text,
                scope_context=scope_context,
                selection_meta=selection_meta,
            )
            units.append(unit)
            if unit_type in part_unit_counts[part]:
                part_unit_counts[part][unit_type] += 1

            unit_text_sha = text_sha256(unit_text)
            slice_id = hashlib.sha256(
                f"{unit_id}:{unit_text_sha}".encode("utf-8")
            ).hexdigest()[:24]
            unit_slices.append(
                {
                    "unit_id": unit_id,
                    "unit_type": unit_type,
                    "part": part,
                    "page": page,
                    "slice_id": slice_id,
                    "text": unit_text,
                    "text_sha256": unit_text_sha,
                    "source_block_refs": source_block_refs,
                    "source_line_indices": source_line_indices,
                    "source_locator": unit["source_locator"],
                    "selection_meta": selection_meta,
                }
            )

            link_fingerprint = hashlib.sha256(
                f"{unit_id}:{slice_id}:{page_record_id}:{unit_text_sha}".encode("utf-8")
            ).hexdigest()[:24]
            unit_text_links.append(
                {
                    "unit_id": unit_id,
                    "part": part,
                    "unit_type": unit_type,
                    "slice_ids": [slice_id],
                    "page_record_ids": [page_record_id],
                    "coverage_status": "full",
                    "link_fingerprint": link_fingerprint,
                }
            )

            normalized = normalize_for_query(unit_text)
            query_source_rows.append(
                {
                    "part": part,
                    "page": page,
                    "unit_type": unit_type,
                    "unit_id": unit_id,
                    "slice_id": slice_id,
                    "normalized_text": normalized,
                    "tokens": sorted(
                        {
                            token
                            for token in re.findall(r"[a-z0-9_]+", normalized)
                            if token
                        }
                    ),
                    "source_locator": unit["source_locator"],
                }
            )

            if unit["review_state"] == "needs_review":
                qa_items.append(
                    {
                        "qa_item_id": f"qa-{unit_id}",
                        "part": part,
                        "page": page,
                        "unit_type": unit_type,
                        "reason_codes": decision.get("reason_codes", []),
                        "confidence": 0.5,
                        "recommended_action": "manual_adjudication",
                    }
                )

    coverage: dict[str, dict] = {}
    for part in sorted(part_page_counts.keys()):
        pages_seen = int(part_page_counts.get(part, 0))
        by_type = part_unit_counts.get(part, {})
        presence = {
            unit_type: int(by_type.get(unit_type, 0)) > 0
            for unit_type in required_unit_types
        }
        coverage[part] = {
            "pages_seen": pages_seen,
            "unit_counts": {
                unit_type: int(by_type.get(unit_type, 0))
                for unit_type in required_unit_types
            },
            "unit_type_presence": presence,
            "coverage_ratio": (
                1.0 if pages_seen > 0 and presence.get("paragraph") else 0.0
            ),
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
        "line_reconstruction": wrap_stats,
        "scope_boundaries": scope_boundaries,
        "scope_boundaries_by_part": scope_boundaries_by_part,
        "scope_opportunities": {
            key: max(
                int(scope_boundaries.get(key, 0)), int(scope_opportunities.get(key, 0))
            )
            for key in scope_boundaries
        },
        "scope_opportunities_by_part": {
            part: {
                key: max(
                    int(scope_boundaries_by_part.get(part, {}).get(key, 0)),
                    int(scope_opportunities_by_part.get(part, {}).get(key, 0)),
                )
                for key in scope_boundaries
            }
            for part in sorted(scope_boundaries_by_part.keys())
        },
    }

    control_dir = ctx.paths.control_run_root / "artifacts" / "normalize"
    data_dir = ctx.paths.run_root / "normalize"
    data_verbatim_dir = data_dir / "verbatim"
    query_dir = ctx.paths.run_root / "query"
    qa_data_dir = ctx.paths.run_root / "qa"
    qa_control_dir = ctx.paths.control_run_root / "artifacts" / "qa"
    for directory in (
        control_dir,
        data_dir,
        data_verbatim_dir,
        query_dir,
        qa_data_dir,
        qa_control_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    units.sort(
        key=lambda row: (
            row["source_locator"]["part"],
            int(row["source_locator"]["page_start"]),
            row["unit_type"],
            row["unit_id"],
        )
    )
    unit_slices.sort(
        key=lambda row: (
            row["part"],
            int(row["page"]),
            row["unit_type"],
            row["unit_id"],
            row["slice_id"],
        )
    )
    unit_text_links.sort(
        key=lambda row: (row["part"], row["unit_type"], row["unit_id"])
    )
    query_source_rows.sort(
        key=lambda row: (
            row["part"],
            int(row["page"]),
            row["unit_type"],
            row["unit_id"],
            row["slice_id"],
        )
    )

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
    unit_slices_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in unit_slices),
        encoding="utf-8",
    )
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
