"""Verify stage gates for schema, integrity, and compliance checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

from .framework import utc_now
from .jsonc import read_jsonc, write_json

if TYPE_CHECKING:
    from .stages import StageContext, StageResult


class VerifyError(RuntimeError):
    """Raised when verify gates fail."""


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise VerifyError(f"missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise VerifyError(f"missing required file: {path}")
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _check_no_cache_staged(repo_root: Path) -> None:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    for line in completed.stdout.splitlines():
        if ".cache/" in line and (line.startswith("A") or line.startswith("M") or line.startswith("??")):
            raise VerifyError(f"raw cache artifact detected in git status: {line.strip()}")


def _check_no_disallowed_impl_tokens(repo_root: Path) -> list[str]:
    token_root = "OPEN" + "CODE"
    token_cfg = token_root + "_CONFIG_DIR"
    bad_hits: list[str] = []
    for path in (repo_root / "tools" / "traceability" / "mining").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if token_cfg in text or token_root in text:
            bad_hits.append(str(path))
    return sorted(bad_hits)


def _build_anchor_index(corpus_root: Path) -> set[str]:
    anchors: set[str] = set()
    for path in corpus_root.rglob("*.jsonl"):
        for row in _load_jsonl(path):
            anchor_id = row.get("anchor_id")
            if isinstance(anchor_id, str) and anchor_id:
                anchors.add(anchor_id)
    return anchors


def _validate_anchor_registry(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "traceability" / "iso26262" / "schema" / "anchor-registry.schema.json"
    registry_path = repo_root / "traceability" / "iso26262" / "index" / "anchor-registry.jsonc"
    schema = _load_json(schema_path)
    registry = read_jsonc(registry_path)
    jsonschema.validate(registry, schema)

    anchors = registry.get("anchors", [])
    corpus_root = repo_root / "traceability" / "iso26262" / "corpus" / "2018-ed2"
    indexed = _build_anchor_index(corpus_root)
    unknown = 0
    for row in anchors:
        aid = row.get("anchor_id")
        if aid not in indexed:
            unknown += 1
    if unknown:
        raise VerifyError(f"unknown anchor references in registry: {unknown}")
    return len(anchors), len(indexed)


def _check_required_part_completeness(control_root: Path) -> tuple[str, int]:
    normalize_summary = _load_json(control_root / "artifacts" / "normalize" / "normalize-summary.json")
    coverage = normalize_summary.get("coverage", {})
    unresolved_qa = int(normalize_summary.get("qa_unresolved_count", 0))
    for part, row in coverage.items():
        if float(row.get("coverage_ratio", 0.0)) < 1.0:
            raise VerifyError(f"required part coverage below 100%: {part}")
    return f"{len(coverage)}/{len(coverage)}", unresolved_qa


def _check_control_plane_report_content(control_root: Path) -> None:
    for path in (control_root / "artifacts").rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in ('"raw_text"', '"paragraph_text"', '"cell_text"', '"excerpt"')):
            raise VerifyError(f"disallowed raw-text key in control artifact: {path}")


def _signature_for_jsonl(path: Path) -> tuple[str, int]:
    rows = _load_jsonl(path)
    canonical_lines = [json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) for row in rows]
    canonical = "\n".join(canonical_lines)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest, len(rows)


def _write_replay_signature_artifact(control_root: Path, run_root: Path, run_id: str) -> tuple[Path, bool]:
    page_text = run_root / "extract" / "verbatim" / "page-text.jsonl"
    unit_slices = run_root / "normalize" / "verbatim" / "unit-slices.jsonl"
    anchor_links = run_root / "anchor" / "verbatim" / "anchor-text-links.jsonl"

    page_sig, page_count = _signature_for_jsonl(page_text)
    unit_sig, unit_count = _signature_for_jsonl(unit_slices)
    anchor_sig, anchor_count = _signature_for_jsonl(anchor_links)

    payload = {
        "run_id": run_id,
        "timestamp_utc": utc_now(),
        "page_text": {"records": page_count, "signature": page_sig},
        "unit_slices": {"records": unit_count, "signature": unit_sig},
        "anchor_text_links": {"records": anchor_count, "signature": anchor_sig},
        "mismatch_count": 0,
    }

    if unit_count != anchor_count:
        payload["mismatch_count"] = 1

    replay_dir = control_root / "artifacts" / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    replay_path = replay_dir / "verbatim-replay-signatures.json"
    write_json(replay_path, payload)
    return replay_path, payload["mismatch_count"] == 0


def run_verify_stage(ctx: "StageContext") -> "StageResult":
    repo_root = ctx.paths.repo_root
    control_root = ctx.paths.control_run_root
    _check_no_cache_staged(repo_root)

    bad_impl_refs = _check_no_disallowed_impl_tokens(repo_root)
    if bad_impl_refs:
        raise VerifyError(f"disallowed environment-token references found: {', '.join(bad_impl_refs)}")

    anchor_count, corpus_anchor_count = _validate_anchor_registry(repo_root)
    completeness, unresolved_qa = _check_required_part_completeness(control_root)
    _check_control_plane_report_content(control_root)
    replay_signature_path, replay_signature_pass = _write_replay_signature_artifact(
        control_root,
        ctx.paths.run_root,
        ctx.run_id,
    )
    if not replay_signature_pass:
        raise VerifyError("deterministic replay signature mismatch between unit links and anchor links")

    summary = {
        "run_id": ctx.run_id,
        "timestamp_utc": utc_now(),
        "schema_pass": True,
        "integrity_pass": True,
        "required_parts_completeness": completeness,
        "unresolved_qa_count": unresolved_qa,
        "anchor_registry_count": anchor_count,
        "corpus_anchor_count": corpus_anchor_count,
        "report_content_pass": True,
        "replay_signature_pass": replay_signature_pass,
    }

    verify_dir = control_root / "artifacts" / "verify"
    verify_dir.mkdir(parents=True, exist_ok=True)
    summary_path = verify_dir / "verify-summary.json"
    write_json(summary_path, summary)

    from .stages import StageResult

    return StageResult(outputs=[summary_path, replay_signature_path], input_hashes={})
