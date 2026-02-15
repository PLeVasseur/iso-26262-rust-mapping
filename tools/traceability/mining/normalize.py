"""Normalize stage and quality-aware unitization pipeline."""

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


LICENSE_PATTERNS = (
    re.compile(r"licensed to", re.IGNORECASE),
    re.compile(r"iso store order", re.IGNORECASE),
    re.compile(r"single user licence", re.IGNORECASE),
    re.compile(r"all rights reserved", re.IGNORECASE),
    re.compile(r"copyright protected document", re.IGNORECASE),
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


def _is_table_line(line: str) -> bool:
    return bool(TABLE_LINE_RE.search(line) or MULTI_COL_RE.search(line))


def _is_list_line(line: str) -> bool:
    return bool(BULLET_RE.match(line))


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
) -> list[str]:
    cleaned: list[str] = []
    for row in block_rows:
        line = _normalize_line(str(row.get("text", "")))
        if not line:
            continue
        lowered = _canonical_line(line)
        if f"{part}::{lowered}" in repeated_lines:
            continue
        if _looks_like_noise(line):
            continue
        cleaned.append(line)
    return cleaned


def _merge_wrapped_lines(lines: list[str]) -> tuple[list[str], dict[str, int]]:
    if not lines:
        return [], {
            "line_wrap_attempts": 0,
            "line_wrap_success": 0,
            "dehyphenation_attempts": 0,
            "dehyphenation_success": 0,
        }

    merged: list[str] = [lines[0]]
    stats = {
        "line_wrap_attempts": 0,
        "line_wrap_success": 0,
        "dehyphenation_attempts": 0,
        "dehyphenation_success": 0,
    }

    for current in lines[1:]:
        previous = merged[-1]
        prev_tail = previous[-1:] if previous else ""
        curr_head = current[:1] if current else ""

        if previous.endswith("-") and curr_head.islower():
            stats["dehyphenation_attempts"] += 1
            merged[-1] = previous[:-1] + current
            stats["dehyphenation_success"] += 1
            continue

        if (
            _is_heading_line(previous)
            or _is_heading_line(current)
            or _is_table_line(previous)
            or _is_table_line(current)
        ):
            merged.append(current)
            continue

        if _is_list_line(previous) and _is_list_line(current):
            merged.append(current)
            continue

        joinable = prev_tail not in {".", ":", ";", "!", "?"} and curr_head.islower()
        if joinable:
            stats["line_wrap_attempts"] += 1
            merged[-1] = f"{previous} {current}"
            stats["line_wrap_success"] += 1
            continue

        merged.append(current)

    return merged, stats


def _update_scope_context(
    lines: list[str], prior: dict[str, str], page: int
) -> tuple[dict[str, str], dict[str, int]]:
    context = dict(prior)
    boundaries = {"section": 0, "clause": 0, "table": 0}

    for line in lines:
        table_match = TABLE_CAPTION_RE.match(line)
        if table_match:
            context["table_id"] = f"Table-{table_match.group(1)}"
            boundaries["table"] += 1
            continue

        clause_match = CLAUSE_RE.match(line)
        if clause_match:
            clause_id = clause_match.group(1)
            context["clause"] = clause_id
            section_head = clause_id.split(".", 1)[0]
            context["section"] = f"{section_head}"
            boundaries["clause"] += 1
            boundaries["section"] += 1
            continue

        section_match = SECTION_RE.match(line)
        if section_match:
            section_id = section_match.group(1)
            context["section"] = section_id
            context["clause"] = f"{section_id}.0"
            boundaries["section"] += 1

    if not context.get("section"):
        context["section"] = str(max(page, 1))
    if not context.get("clause"):
        context["clause"] = f"{context['section']}.0"

    return context, boundaries


def _extract_paragraph_candidates(lines: list[str]) -> list[tuple[str, list[int]]]:
    candidates: list[tuple[str, list[int]]] = []
    acc: list[str] = []
    idxs: list[int] = []

    def flush() -> None:
        if not acc:
            return
        text = " ".join(acc).strip()
        if len(re.findall(r"[A-Za-z]{3,}", text)) >= 8:
            candidates.append((text, list(idxs)))
        acc.clear()
        idxs.clear()

    for idx, line in enumerate(lines):
        if _is_heading_line(line) or _is_list_line(line) or _is_table_line(line):
            flush()
            continue
        acc.append(line)
        idxs.append(idx)

    flush()
    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    return candidates


def _extract_list_candidates(lines: list[str]) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not _is_list_line(line):
            i += 1
            continue

        merged = [line]
        continuation = 0
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if _is_list_line(nxt) or _is_heading_line(nxt) or _is_table_line(nxt):
                break
            if nxt:
                merged.append(nxt)
                continuation += 1
            i += 1

        text = " ".join(merged).strip()
        if text:
            marker_ok = 1 if _is_list_line(merged[0]) else 0
            out.append((text, marker_ok, continuation))
    out.sort(key=lambda item: len(item[0]), reverse=True)
    return out


def _extract_table_cell_candidates(
    lines: list[str], current_table_id: str
) -> list[tuple[str, dict]]:
    candidates: list[tuple[str, dict]] = []
    row_index = 0

    for line in lines:
        if TABLE_CAPTION_RE.match(line):
            row_index = 0
            continue
        if not _is_table_line(line):
            continue

        row_index += 1
        if "|" in line:
            raw_cells = [cell.strip() for cell in line.split("|")]
        else:
            raw_cells = [cell.strip() for cell in re.split(r"\s{2,}", line)]
        cells = [cell for cell in raw_cells if cell]
        for col_index, cell in enumerate(cells, start=1):
            if len(re.findall(r"[A-Za-z]{2,}", cell)) < 1:
                continue
            candidates.append(
                (
                    cell,
                    {
                        "table_id": current_table_id or "Table-Unknown",
                        "row_index": row_index,
                        "col_index": col_index,
                        "row_span": 1,
                        "col_span": 1,
                    },
                )
            )

    candidates.sort(key=lambda item: len(item[0]), reverse=True)
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
        scope_context, boundary_delta = _update_scope_context(
            merged_lines, prior_scope, page
        )
        scope_context_by_part[part] = scope_context
        for scope_key in scope_boundaries:
            scope_boundaries[scope_key] += int(boundary_delta.get(scope_key, 0))

        paragraph_candidates = _extract_paragraph_candidates(merged_lines)
        list_candidates = _extract_list_candidates(merged_lines)
        table_candidates = _extract_table_cell_candidates(
            merged_lines, scope_context.get("table_id", "")
        )

        selections: list[tuple[str, str, dict]] = []
        if paragraph_candidates:
            text, _ = paragraph_candidates[0]
            selections.append(("paragraph", text, {"pattern_conformance": True}))
        elif merged_lines:
            selections.append(
                ("paragraph", merged_lines[0], {"pattern_conformance": False})
            )

        if list_candidates:
            list_text, marker_ok, continuation_count = list_candidates[0]
            selections.append(
                (
                    "list_bullet",
                    list_text,
                    {
                        "marker_valid": bool(marker_ok),
                        "continuation_line_count": int(continuation_count),
                    },
                )
            )

        if table_candidates:
            table_text, table_meta = table_candidates[0]
            selections.append(("table_cell", table_text, table_meta))

        if not selections:
            selections = [("paragraph", "", {"pattern_conformance": False})]

        unit_ordinal = 0
        for unit_type, unit_text, selection_meta in selections:
            if not unit_text.strip():
                continue
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
            source_block_refs = [
                str(row.get("block_id", ""))
                for row in block_rows
                if str(row.get("block_id", ""))
            ]
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
