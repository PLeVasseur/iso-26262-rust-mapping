"""Publish stage for tracked non-verbatim corpus and registry outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .framework import utc_now
from .jsonc import write_json

if TYPE_CHECKING:
    from .stages import StageContext, StageResult


class PublishError(RuntimeError):
    """Raised when publish-stage gates fail."""


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _validate_publish_gates(control_run_root: Path) -> None:
    normalize_summary_path = control_run_root / "artifacts" / "normalize" / "normalize-summary.json"
    if not normalize_summary_path.exists():
        raise PublishError(f"missing normalize summary: {normalize_summary_path}")
    normalize_summary = _read_json(normalize_summary_path)
    if int(normalize_summary.get("qa_unresolved_count", 0)) > 0:
        raise PublishError("required-part QA queue is not empty")

    coverage = normalize_summary.get("coverage", {})
    for part, row in coverage.items():
        if float(row.get("coverage_ratio", 0.0)) < 1.0:
            raise PublishError(f"required-part coverage below 100% for {part}")

    decisions_path = control_run_root / "artifacts" / "extract" / "extract-page-decisions.jsonl"
    for decision in _load_jsonl(decisions_path):
        if decision.get("method") == "ocr_fallback":
            quality = decision.get("ocr", {}).get("quality_band", "fail")
            if quality in {"needs_review", "fail"}:
                raise PublishError(
                    f"publish blocked by unresolved OCR quality for {decision.get('part')} page {decision.get('page')}"
                )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def run_publish_stage(ctx: "StageContext") -> "StageResult":
    control_root = ctx.paths.control_run_root
    _validate_publish_gates(control_root)

    anchored_path = control_root / "artifacts" / "anchor" / "anchored-units.jsonl"
    anchored_units = _load_jsonl(anchored_path)
    if not anchored_units:
        raise PublishError(f"missing anchored units: {anchored_path}")

    publish_control = control_root / "artifacts" / "publish"
    publish_control.mkdir(parents=True, exist_ok=True)
    begin_marker = publish_control / "publish.begin"
    begin_marker.write_text(f"run_id={ctx.run_id}\ntimestamp_utc={utc_now()}\n", encoding="utf-8")

    corpus_root = ctx.paths.repo_root / "traceability" / "iso26262" / "corpus" / "2018-ed2"
    index_root = ctx.paths.repo_root / "traceability" / "iso26262" / "index"
    corpus_root.mkdir(parents=True, exist_ok=True)
    index_root.mkdir(parents=True, exist_ok=True)

    by_part: dict[str, list[dict]] = {}
    for row in anchored_units:
        part = row["source_locator"]["part"]
        by_part.setdefault(part, []).append(row)

    outputs: list[Path] = [begin_marker]
    registry_anchors: list[dict] = []
    part_manifests: list[dict] = []

    for part, records in sorted(by_part.items()):
        records.sort(key=lambda row: (row["source_locator"]["page_start"], row["anchor_id"]))
        part_dir = corpus_root / part.lower()
        part_dir.mkdir(parents=True, exist_ok=True)

        shard_paths: list[str] = []
        shard_size = 250
        for offset in range(0, len(records), shard_size):
            shard_idx = offset // shard_size + 1
            shard_name = f"paragraph-{shard_idx:04d}.jsonl"
            shard_path = part_dir / shard_name
            _write_jsonl(shard_path, records[offset : offset + shard_size])
            shard_paths.append(shard_name)
            outputs.append(shard_path)

        clause_counts: dict[str, int] = {}
        for record in records:
            clause = str(record["source_locator"].get("clause", "unknown"))
            clause_counts[clause] = clause_counts.get(clause, 0) + 1

        clause_manifest = part_dir / "clause-manifest.jsonc"
        write_json(
            clause_manifest,
            {
                "part": part,
                "edition": "2018-ed2",
                "clauses": [{"clause": clause, "unit_count": count} for clause, count in sorted(clause_counts.items())],
            },
        )
        outputs.append(clause_manifest)

        part_manifest = part_dir / "part-manifest.jsonc"
        write_json(
            part_manifest,
            {
                "part": part,
                "edition": "2018-ed2",
                "unit_count": len(records),
                "shards": shard_paths,
                "clause_manifest": clause_manifest.name,
            },
        )
        outputs.append(part_manifest)
        part_manifests.append({"part": part, "manifest": f"corpus/2018-ed2/{part.lower()}/part-manifest.jsonc"})

        for record in records:
            registry_anchors.append(
                {
                    "anchor_id": record["anchor_id"],
                    "part": part,
                    "unit": record["unit_id"],
                    "status": "mapped",
                    "notes": "auto-published non-verbatim corpus entry",
                }
            )

    registry_anchors.sort(key=lambda row: row["anchor_id"])
    anchor_registry_path = index_root / "anchor-registry.jsonc"
    write_json(anchor_registry_path, {"schema_version": 1, "anchors": registry_anchors})
    outputs.append(anchor_registry_path)

    corpus_manifest_path = index_root / "corpus-manifest.jsonc"
    write_json(
        corpus_manifest_path,
        {
            "schema_version": 1,
            "edition": "2018-ed2",
            "parts": part_manifests,
            "record_count": len(anchored_units),
            "generated_at_utc": utc_now(),
        },
    )
    outputs.append(corpus_manifest_path)

    summary_path = publish_control / "publish-summary.json"
    write_json(
        summary_path,
        {
            "run_id": ctx.run_id,
            "timestamp_utc": utc_now(),
            "published_record_count": len(anchored_units),
            "published_parts": sorted(by_part.keys()),
            "anchor_registry": str(anchor_registry_path),
            "corpus_manifest": str(corpus_manifest_path),
        },
    )
    outputs.append(summary_path)

    commit_marker = publish_control / "publish.commit"
    commit_marker.write_text(f"run_id={ctx.run_id}\ntimestamp_utc={utc_now()}\n", encoding="utf-8")
    outputs.append(commit_marker)

    from .stages import StageResult

    return StageResult(outputs=outputs, input_hashes={})
