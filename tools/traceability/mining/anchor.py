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


def _anchor_id(unit: dict) -> str:
    locator = unit["source_locator"]
    raw = f"{locator['part']}|{locator['clause']}|{locator['page_start']}|{unit['unit_type']}|{unit['unit_id']}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"iso26262:{locator['part'].lower()}:{digest}"


def _shard_name(unit_type: str, index: int) -> str:
    return f"{unit_type}-{index:04d}.jsonl"


def run_anchor_stage(ctx: "StageContext") -> "StageResult":
    units = _load_normalized_units(ctx.paths.control_run_root)
    if not units:
        raise AnchorError("normalized unit set is empty")

    anchored: list[dict] = []
    seen_ids: set[str] = set()
    for unit in units:
        aid = _anchor_id(unit)
        if aid in seen_ids:
            raise AnchorError(f"duplicate anchor_id generated: {aid}")
        seen_ids.add(aid)
        anchored.append({**unit, "anchor_id": aid})

    anchored.sort(key=lambda item: (item["source_locator"]["part"], item["source_locator"]["page_start"], item["unit_id"]))

    by_part: dict[str, list[dict]] = {}
    for record in anchored:
        by_part.setdefault(record["source_locator"]["part"], []).append(record)

    control_dir = ctx.paths.control_run_root / "artifacts" / "anchor"
    data_dir = ctx.paths.run_root / "normalize"
    preview_root = ctx.paths.run_root / "publish-preview" / "2018-ed2"
    for directory in (control_dir, data_dir, preview_root):
        directory.mkdir(parents=True, exist_ok=True)

    anchored_control = control_dir / "anchored-units.jsonl"
    anchored_data = data_dir / "anchored-units.jsonl"
    lines = "".join(json.dumps(row, sort_keys=True) + "\n" for row in anchored)
    anchored_control.write_text(lines, encoding="utf-8")
    anchored_data.write_text(lines, encoding="utf-8")

    manifests: list[str] = []
    shard_outputs: list[str] = []
    for part, records in sorted(by_part.items()):
        part_root = preview_root / part.lower()
        part_root.mkdir(parents=True, exist_ok=True)
        shard_size = 250
        shard_count = 0
        for offset in range(0, len(records), shard_size):
            shard_count += 1
            shard_path = part_root / _shard_name("paragraph", shard_count)
            chunk = records[offset : offset + shard_size]
            shard_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in chunk), encoding="utf-8")
            shard_outputs.append(str(shard_path))

        manifest_path = part_root / "part-manifest.preview.json"
        write_json(
            manifest_path,
            {
                "part": part,
                "edition": "2018-ed2",
                "unit_count": len(records),
                "shards": sorted(Path(path).name for path in shard_outputs if f"/{part.lower()}/" in path),
            },
        )
        manifests.append(str(manifest_path))

    summary_path = control_dir / "anchor-summary.json"
    summary = {
        "run_id": ctx.run_id,
        "timestamp_utc": utc_now(),
        "anchored_unit_count": len(anchored),
        "unique_anchor_count": len(seen_ids),
        "duplicate_anchor_count": 0,
        "parts": {part: len(records) for part, records in sorted(by_part.items())},
    }
    write_json(summary_path, summary)

    from .stages import StageResult

    return StageResult(
        outputs=[anchored_control, anchored_data, summary_path, *[Path(path) for path in manifests], *[Path(path) for path in shard_outputs]],
        input_hashes={},
    )
