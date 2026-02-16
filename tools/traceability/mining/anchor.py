"""Anchor stage: deterministic anchor IDs and shard planning."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .framework import utc_now
from .jsonc import write_json

if TYPE_CHECKING:
    from .stages import StageContext, StageResult


class AnchorError(RuntimeError):
    """Raised for anchor-stage failures."""


def _load_normalized_units(control_run_root: Path) -> list[dict]:
    path = control_run_root / "artifacts" / "normalize" / "normalized-units.jsonl"
    if not path.exists():
        raise AnchorError(f"missing normalized units: {path}")
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise AnchorError(f"missing required file: {path}")
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _anchor_id(unit: dict) -> str:
    locator = unit["source_locator"]
    unit_type = str(unit.get("unit_type", "paragraph"))
    raw = (
        f"{locator['part']}|{locator['clause']}|{locator['page_start']}|"
        f"{unit_type}|{unit['unit_id']}"
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    edition = str(locator.get("edition", "2018-ed2"))
    page = int(locator.get("page_start", 0))
    unit_code = {
        "paragraph": "PAR",
        "list_bullet": "LST",
        "table_cell": "TBL",
    }.get(unit_type, "UNK")
    return f"ISO26262:{edition}:{locator['part']}:PG{page:04d}:{unit_code}:{digest}"


def _scope_anchor_id(scope_type: str, part: str, scope_value: str) -> str:
    token = scope_value.strip() or "unknown"
    digest = hashlib.sha256(f"{scope_type}:{part}:{token}".encode("utf-8")).hexdigest()[
        :16
    ]
    return f"ISO26262:2018-ed2:{part}:{scope_type.upper()}:{digest}"


def _shard_name(unit_type: str, index: int) -> str:
    return f"{unit_type}-{index:04d}.jsonl"


def run_anchor_stage(ctx: "StageContext") -> "StageResult":
    units = _load_normalized_units(ctx.paths.control_run_root)
    unit_slices = _load_jsonl(
        ctx.paths.run_root / "normalize" / "verbatim" / "unit-slices.jsonl"
    )
    unit_text_links = _load_jsonl(
        ctx.paths.run_root / "normalize" / "verbatim" / "unit-text-links.jsonl"
    )
    if not units:
        raise AnchorError("normalized unit set is empty")

    slices_by_unit: dict[str, list[dict]] = {}
    for row in unit_slices:
        slices_by_unit.setdefault(str(row["unit_id"]), []).append(row)

    links_by_unit: dict[str, dict] = {}
    for row in unit_text_links:
        unit_id = str(row["unit_id"])
        if unit_id in links_by_unit:
            raise AnchorError(f"duplicate unit-text-link row for unit_id={unit_id}")
        links_by_unit[unit_id] = row

    anchored: list[dict] = []
    anchor_text_links: list[dict] = []
    scope_anchor_rows: list[dict] = []
    seen_ids: set[str] = set()
    seen_scope_ids: set[str] = set()
    for unit in units:
        unit_id = str(unit["unit_id"])
        if unit_id not in links_by_unit:
            raise AnchorError(f"missing unit-text-link record for {unit_id}")
        if unit_id not in slices_by_unit:
            raise AnchorError(f"missing unit-slice records for {unit_id}")

        aid = _anchor_id(unit)
        if aid in seen_ids:
            raise AnchorError(f"duplicate anchor_id generated: {aid}")
        seen_ids.add(aid)

        locator = unit.get("source_locator", {})
        part = str(locator.get("part", ""))
        section = str(locator.get("section", ""))
        clause = str(locator.get("clause", ""))
        table = str(locator.get("table", ""))

        section_anchor_id = _scope_anchor_id("section", part, section)
        clause_anchor_id = _scope_anchor_id("clause", part, clause)
        table_anchor_id = _scope_anchor_id("table", part, table) if table else ""

        for scope_type, scope_value, scope_anchor_id in (
            ("section", section, section_anchor_id),
            ("clause", clause, clause_anchor_id),
            ("table", table, table_anchor_id),
        ):
            if not scope_anchor_id or not scope_value:
                continue
            if scope_anchor_id in seen_scope_ids:
                continue
            seen_scope_ids.add(scope_anchor_id)
            scope_anchor_rows.append(
                {
                    "scope_anchor_id": scope_anchor_id,
                    "scope_type": scope_type,
                    "part": part,
                    "scope_value": scope_value,
                }
            )

        parent_scope_anchor_id = (
            table_anchor_id or clause_anchor_id or section_anchor_id
        )

        anchored.append(
            {
                **unit,
                "anchor_id": aid,
                "scope_anchors": {
                    "section": section_anchor_id,
                    "clause": clause_anchor_id,
                    "table": table_anchor_id,
                },
                "parent_scope_anchor_id": parent_scope_anchor_id,
            }
        )

        slice_rows = sorted(
            slices_by_unit[unit_id],
            key=lambda row: (
                str(row.get("slice_id", "")),
                str(row.get("text_sha256", "")),
            ),
        )
        text_sha256_set = sorted(
            {
                str(row.get("text_sha256", ""))
                for row in slice_rows
                if str(row.get("text_sha256", ""))
            }
        )
        link_fingerprint = hashlib.sha256(
            f"{aid}:{unit_id}:{'|'.join(text_sha256_set)}".encode("utf-8")
        ).hexdigest()[:24]
        link_row = links_by_unit[unit_id]
        anchor_text_links.append(
            {
                "anchor_id": aid,
                "unit_id": unit_id,
                "part": unit["source_locator"]["part"],
                "unit_type": unit["unit_type"],
                "slice_ids": list(link_row.get("slice_ids", [])),
                "text_sha256_set": text_sha256_set,
                "link_fingerprint": link_fingerprint,
                "parent_scope_anchor_id": parent_scope_anchor_id,
            }
        )

    anchored.sort(
        key=lambda item: (
            item["source_locator"]["part"],
            int(item["source_locator"]["page_start"]),
            item["unit_type"],
            item["unit_id"],
        )
    )
    anchor_text_links.sort(
        key=lambda row: (
            row["part"],
            row["unit_type"],
            row["unit_id"],
            row["anchor_id"],
        )
    )
    scope_anchor_rows.sort(
        key=lambda row: (
            row["scope_type"],
            row["part"],
            row["scope_value"],
            row["scope_anchor_id"],
        )
    )

    by_part: dict[str, list[dict]] = {}
    for record in anchored:
        by_part.setdefault(record["source_locator"]["part"], []).append(record)

    control_dir = ctx.paths.control_run_root / "artifacts" / "anchor"
    data_dir = ctx.paths.run_root / "normalize"
    verbatim_dir = ctx.paths.run_root / "anchor" / "verbatim"
    query_dir = ctx.paths.run_root / "query"
    preview_root = ctx.paths.run_root / "publish-preview" / "2018-ed2"
    for directory in (control_dir, data_dir, verbatim_dir, query_dir, preview_root):
        directory.mkdir(parents=True, exist_ok=True)

    anchored_control = control_dir / "anchored-units.jsonl"
    anchored_data = data_dir / "anchored-units.jsonl"
    lines = "".join(json.dumps(row, sort_keys=True) + "\n" for row in anchored)
    anchored_control.write_text(lines, encoding="utf-8")
    anchored_data.write_text(lines, encoding="utf-8")

    anchor_text_links_path = verbatim_dir / "anchor-text-links.jsonl"
    anchor_text_links_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in anchor_text_links),
        encoding="utf-8",
    )

    anchor_link_index_path = verbatim_dir / "anchor-link-index.json"
    by_anchor: dict[str, dict] = {}
    for row in anchor_text_links:
        by_anchor[row["anchor_id"]] = {
            "unit_id": row["unit_id"],
            "part": row["part"],
            "unit_type": row["unit_type"],
            "slice_ids": row["slice_ids"],
            "link_fingerprint": row["link_fingerprint"],
        }
    write_json(
        anchor_link_index_path,
        {
            "run_id": ctx.run_id,
            "record_count": len(anchor_text_links),
            "anchors": dict(sorted(by_anchor.items())),
        },
    )

    scope_anchor_index_path = verbatim_dir / "scope-anchor-index.json"
    write_json(
        scope_anchor_index_path,
        {
            "run_id": ctx.run_id,
            "record_count": len(scope_anchor_rows),
            "scope_anchors": scope_anchor_rows,
        },
    )

    manifests: list[str] = []
    shard_outputs: list[str] = []
    for part, records in sorted(by_part.items()):
        part_root = preview_root / part.lower()
        part_root.mkdir(parents=True, exist_ok=True)
        shard_names: list[str] = []
        for unit_type in ("paragraph", "list_bullet", "table_cell"):
            typed_records = [
                row for row in records if str(row.get("unit_type")) == unit_type
            ]
            shard_size = 250
            shard_count = 0
            for offset in range(0, len(typed_records), shard_size):
                shard_count += 1
                shard_path = part_root / _shard_name(unit_type, shard_count)
                chunk = typed_records[offset : offset + shard_size]
                shard_path.write_text(
                    "".join(json.dumps(row, sort_keys=True) + "\n" for row in chunk),
                    encoding="utf-8",
                )
                shard_outputs.append(str(shard_path))
                shard_names.append(shard_path.name)

        manifest_path = part_root / "part-manifest.preview.json"
        write_json(
            manifest_path,
            {
                "part": part,
                "edition": "2018-ed2",
                "unit_count": len(records),
                "shards": sorted(shard_names),
            },
        )
        manifests.append(str(manifest_path))

    query_binding_path = query_dir / "index-bindings.json"
    write_json(
        query_binding_path,
        {
            "run_id": ctx.run_id,
            "anchor_text_links_path": str(anchor_text_links_path),
            "anchor_link_index_path": str(anchor_link_index_path),
            "unit_slice_input_path": str(
                ctx.paths.run_root / "normalize" / "verbatim" / "unit-slices.jsonl"
            ),
        },
    )

    summary_path = control_dir / "anchor-summary.json"
    required_unit_link_count = len(anchored)
    bijection_pass = required_unit_link_count == len(anchor_text_links) == len(seen_ids)
    if not bijection_pass:
        raise AnchorError(
            "anchor-text-link bijection failed: "
            f"units={required_unit_link_count} "
            f"anchors={len(seen_ids)} "
            f"links={len(anchor_text_links)}"
        )

    summary = {
        "run_id": ctx.run_id,
        "timestamp_utc": utc_now(),
        "anchored_unit_count": len(anchored),
        "unique_anchor_count": len(seen_ids),
        "anchor_text_link_count": len(anchor_text_links),
        "scope_anchor_count": len(scope_anchor_rows),
        "duplicate_anchor_count": 0,
        "link_bijection_pass": bijection_pass,
        "parts": {part: len(records) for part, records in sorted(by_part.items())},
    }
    write_json(summary_path, summary)

    from .stages import StageResult

    return StageResult(
        outputs=[
            anchored_control,
            anchored_data,
            anchor_text_links_path,
            anchor_link_index_path,
            scope_anchor_index_path,
            query_binding_path,
            summary_path,
            *[Path(path) for path in manifests],
            *[Path(path) for path in shard_outputs],
        ],
        input_hashes={},
    )
