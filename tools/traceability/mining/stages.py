"""Initial stage scaffolding for mining pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .anchor import run_anchor_stage
from .extract import run_extract_stage
from .ingest import run_ingest_stage
from .framework import RunPaths, utc_now, write_json
from .normalize import run_normalize_stage


@dataclass
class StageContext:
    run_id: str
    phase: int
    paths: RunPaths
    mode: str
    source_pdfset_path: Path
    relevant_policy_path: Path
    extraction_policy_path: Path
    lock_source_hashes: bool


@dataclass
class StageResult:
    outputs: list[Path]
    input_hashes: dict[str, str]


def _write_scaffold_marker(stage: str, ctx: StageContext) -> StageResult:
    marker = ctx.paths.control_run_root / "artifacts" / "scaffold" / f"{stage}.marker.json"
    write_json(
        marker,
        {
            "run_id": ctx.run_id,
            "stage": stage,
            "phase": ctx.phase,
            "mode": ctx.mode,
            "timestamp_utc": utc_now(),
            "status": "scaffold_only",
        },
    )
    return StageResult(outputs=[marker], input_hashes={})


def run_ingest(ctx: StageContext) -> StageResult:
    return run_ingest_stage(ctx)


def run_extract(ctx: StageContext) -> StageResult:
    return run_extract_stage(ctx)


def run_normalize(ctx: StageContext) -> StageResult:
    return run_normalize_stage(ctx)


def run_anchor(ctx: StageContext) -> StageResult:
    return run_anchor_stage(ctx)


def run_publish(ctx: StageContext) -> StageResult:
    return _write_scaffold_marker("publish", ctx)


def run_verify(ctx: StageContext) -> StageResult:
    return _write_scaffold_marker("verify", ctx)


def run_finalize(ctx: StageContext) -> StageResult:
    return _write_scaffold_marker("finalize", ctx)


HANDLERS: dict[str, Callable[[StageContext], StageResult]] = {
    "ingest": run_ingest,
    "extract": run_extract,
    "normalize": run_normalize,
    "anchor": run_anchor,
    "publish": run_publish,
    "verify": run_verify,
    "finalize": run_finalize,
}
