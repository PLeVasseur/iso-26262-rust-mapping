"""Ingest stage implementation for required-part PDF discovery."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .constants import FALLBACK_PATTERNS, PREFERRED_FILENAMES
from .framework import utc_now, write_json
from .jsonc import read_jsonc

if TYPE_CHECKING:
    from .stages import StageContext, StageResult


class IngestError(RuntimeError):
    """Raised when ingest validation or discovery fails."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pdf_inventory(pdf_root: Path) -> list[Path]:
    return sorted([path for path in pdf_root.rglob("*.pdf") if path.is_file()])


def _resolve_part_file(part: str, pdf_root: Path, inventory: list[Path]) -> tuple[Path, str]:
    preferred = pdf_root / PREFERRED_FILENAMES[part]
    if preferred.exists():
        return preferred, "preferred_exact"

    pattern = re.compile(FALLBACK_PATTERNS[part])
    candidates = [path for path in inventory if pattern.match(path.name)]
    if len(candidates) == 1:
        return candidates[0], "fallback_regex"
    if not candidates:
        raise IngestError(
            f"missing required part {part} under {pdf_root}; expected {PREFERRED_FILENAMES[part]} or {FALLBACK_PATTERNS[part]}"
        )
    raise IngestError(
        f"ambiguous required part {part} under {pdf_root}; candidates={','.join(str(path) for path in candidates)}"
    )


def _load_required_parts(relevant_policy_path: Path) -> list[str]:
    policy = read_jsonc(relevant_policy_path)
    in_scope = policy.get("in_scope_parts", [])
    if not isinstance(in_scope, list) or not all(isinstance(item, str) for item in in_scope):
        raise IngestError(f"invalid in_scope_parts in {relevant_policy_path}")
    return [item.strip() for item in in_scope if item.strip()]


def _load_source_pdfset(source_pdfset_path: Path) -> dict:
    source = read_jsonc(source_pdfset_path)
    parts = source.get("parts")
    if not isinstance(parts, list):
        raise IngestError(f"invalid parts array in {source_pdfset_path}")
    return source


def _parts_map(source_pdfset: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in source_pdfset.get("parts", []):
        if not isinstance(row, dict):
            continue
        part = row.get("part")
        if isinstance(part, str) and part:
            out[part] = row
    return out


def _write_source_pdfset(source_pdfset_path: Path, source_pdfset: dict) -> None:
    write_json(source_pdfset_path, source_pdfset)


def run_ingest_stage(ctx: "StageContext") -> "StageResult":
    required_parts = _load_required_parts(ctx.relevant_policy_path)
    source_pdfset = _load_source_pdfset(ctx.source_pdfset_path)
    parts_map = _parts_map(source_pdfset)
    pdf_root = ctx.paths.pdf_root
    inventory = _pdf_inventory(pdf_root)

    resolved: dict[str, dict[str, str]] = {}
    input_hashes: dict[str, str] = {}
    source_changed = False

    for part in required_parts:
        if part not in parts_map:
            raise IngestError(f"missing {part} in {ctx.source_pdfset_path}")
        path, match_mode = _resolve_part_file(part, pdf_root, inventory)
        observed_sha = _sha256(path)
        declared_sha = str(parts_map[part].get("sha256", "")).strip()

        if ctx.lock_source_hashes and declared_sha == "PENDING":
            parts_map[part]["sha256"] = observed_sha
            declared_sha = observed_sha
            source_changed = True

        if declared_sha == "PENDING" and not ctx.lock_source_hashes:
            raise IngestError(f"required part {part} hash is PENDING outside --lock-source-hashes flow")
        if declared_sha and declared_sha != "PENDING" and declared_sha != observed_sha:
            raise IngestError(
                f"hash mismatch for {part}: declared={declared_sha} observed={observed_sha} path={path}"
            )

        input_hashes[part] = observed_sha
        resolved[part] = {
            "hash_status": "LOCKED" if declared_sha == observed_sha else "PENDING",
            "resolved_path": str(path),
            "sha256": observed_sha,
            "match_mode": match_mode,
        }

    if source_changed:
        _write_source_pdfset(ctx.source_pdfset_path, source_pdfset)

    now = utc_now()
    summary = {
        "run_id": ctx.run_id,
        "mode": ctx.mode,
        "required_parts": required_parts,
        "pdf_root": str(pdf_root),
        "source_pdfset_path": str(ctx.source_pdfset_path),
        "relevant_policy_path": str(ctx.relevant_policy_path),
        "extraction_policy_path": str(ctx.extraction_policy_path),
        "resolved_parts": resolved,
        "required_parts_completeness": f"{len(resolved)}/{len(required_parts)}",
        "pending_hashes": sum(1 for info in resolved.values() if info["hash_status"] != "LOCKED"),
        "timestamp_utc": now,
    }

    control_summary = ctx.paths.control_run_root / "artifacts" / "ingest" / "ingest-summary.json"
    data_summary = ctx.paths.run_root / "ingest" / "ingest-summary.json"
    write_json(control_summary, summary)
    write_json(data_summary, summary)

    source_evidence = ctx.paths.control_run_root / "artifacts" / "ingest" / "source-hash-evidence.json"
    write_json(
        source_evidence,
        {
            "run_id": ctx.run_id,
            "required_parts": required_parts,
            "hashes": {part: resolved[part]["sha256"] for part in required_parts},
            "timestamp_utc": now,
        },
    )

    from .stages import StageResult

    return StageResult(outputs=[control_summary, data_summary, source_evidence], input_hashes=input_hashes)
