"""Stage framework primitives for mining runs."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json_checksum(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class RunPaths:
    repo_root: Path
    control_run_root: Path
    run_root: Path
    pdf_root: Path

    @property
    def checkpoint_dir(self) -> Path:
        return self.control_run_root / "artifacts" / "checkpoints"


def write_stage_checkpoint(
    *,
    paths: RunPaths,
    run_id: str,
    stage: str,
    phase: int,
    input_hashes: dict[str, str],
    outputs: list[str],
) -> Path:
    payload = {
        "run_id": run_id,
        "stage": stage,
        "phase": phase,
        "input_hashes": dict(sorted(input_hashes.items())),
        "outputs": sorted(outputs),
    }
    checkpoint = {
        **payload,
        "timestamp_utc": utc_now(),
        "canonical_checksum": canonical_json_checksum(payload),
    }
    out_path = paths.checkpoint_dir / f"{stage}.done.json"
    write_json(out_path, checkpoint)
    return out_path


def write_phase_checkpoint(
    *,
    paths: RunPaths,
    run_id: str,
    phase: int,
    stage: str,
    input_hashes: dict[str, str],
    outputs: list[str],
) -> Path:
    payload = {
        "run_id": run_id,
        "phase": phase,
        "stage": stage,
        "input_hashes": dict(sorted(input_hashes.items())),
        "outputs": sorted(outputs),
    }
    checkpoint = {
        **payload,
        "checkpoint": f"phase-{phase}.done",
        "timestamp_utc": utc_now(),
        "canonical_checksum": canonical_json_checksum(payload),
    }
    out_path = paths.checkpoint_dir / f"phase-{phase}.done.json"
    write_json(out_path, checkpoint)
    return out_path
