"""Durable control-plane state and checklist management."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from pathlib import Path

from .constants import CHECKLIST_KEYS, DEFAULT_REQUIRED_PARTS, DONE_FLAGS, STAGES
from .envfiles import parse_env, write_env
from .framework import utc_now


class ContractDriftError(RuntimeError):
    """Raised when immutable state keys drift on resume."""


class StopConditionError(RuntimeError):
    """Raised when a mandatory stop condition is encountered."""


IMMUTABLE_KEYS = (
    "RUN_ID",
    "TASK_NAME",
    "REPO_ROOT",
    "PLAN_PATH",
    "RUN_ROOT",
    "PDF_ROOT",
    "CONTROL_RUN_ROOT",
    "ARTIFACT_ROOT",
    "LOCK_FILE",
    "BASE_BRANCH",
    "TARGET_BRANCH",
    "BASE_PIN_SHA",
    "SOURCE_PDFSET_PATH",
    "RELEVANT_POLICY_PATH",
    "EXTRACTION_POLICY_PATH",
    "VERBATIM_PREWARM_ENABLED",
    "VERBATIM_CACHE_ROOT",
    "VERBATIM_SCHEMA_VERSION",
    "PAGE_TEXT_SCHEMA_PATH",
    "UNIT_SLICE_SCHEMA_PATH",
    "ANCHOR_TEXT_LINK_SCHEMA_PATH",
    "QUERY_TOOL_PATH",
    "QUERY_INDEX_SCHEMA_VERSION",
    "QUERY_INDEX_MANIFEST_PATH",
    "TS_GUIDELINES_PATH",
    "MAKEPY_VERIFY_COMMAND",
    "SRC_INTEGRATION_MANIFEST_PATH",
    "PROBESET_FREEZE_MANIFEST_PATH",
    "PROBESET_FREEZE_SIGNATURE",
    "RETAIN_PROBE_INSERTIONS",
    "MODE",
    "REQUIRED_PARTS",
)

OPTIONAL_GUARDRAIL_KEYS = (
    "RESOURCE_GUARDRAILS_VERSION",
    "QUERY_INDEX_MAX_SHARD_BYTES",
    "QUERY_INDEX_MAX_POSTINGS_PER_TOKEN",
    "QUERY_MAX_HITS",
    "QUERY_MAX_QUOTE_BYTES",
    "MAKEPY_VERIFY_TIMEOUT_SECONDS",
)


@dataclasses.dataclass(frozen=True)
class StatePaths:
    state_file: Path
    checklist_file: Path
    run_log: Path
    checkpoint_dir: Path


def _git_head(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _stage_index(stage: str) -> int:
    return STAGES.index(stage)


def _next_stage(stage: str) -> str:
    idx = _stage_index(stage)
    return STAGES[min(idx + 1, len(STAGES) - 1)]


def _required_parts_csv(value: str) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return ",".join(parts) if parts else ",".join(DEFAULT_REQUIRED_PARTS)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_stage_artifacts(state: dict[str, str], stage: str) -> tuple[Path, ...]:
    control_root = Path(state["CONTROL_RUN_ROOT"])
    run_root = Path(state["RUN_ROOT"])
    by_stage: dict[str, tuple[Path, ...]] = {
        "ingest": (control_root / "artifacts" / "ingest" / "ingest-summary.json",),
        "extract": (
            control_root / "artifacts" / "extract" / "extract-page-decisions.jsonl",
            run_root / "extract" / "verbatim" / "page-text.jsonl",
            run_root / "extract" / "verbatim" / "page-blocks.jsonl",
            run_root / "extract" / "verbatim" / "page-index.json",
            run_root / "extract" / "verbatim" / "page-signatures.jsonl",
        ),
        "normalize": (
            control_root / "artifacts" / "normalize" / "normalize-summary.json",
            run_root / "normalize" / "verbatim" / "unit-slices.jsonl",
            run_root / "normalize" / "verbatim" / "unit-text-links.jsonl",
            run_root / "query" / "query-source-rows.jsonl",
        ),
        "anchor": (
            control_root / "artifacts" / "anchor" / "anchor-summary.json",
            run_root / "anchor" / "verbatim" / "anchor-text-links.jsonl",
            run_root / "anchor" / "verbatim" / "anchor-link-index.json",
        ),
        "publish": (
            control_root / "artifacts" / "publish" / "publish-summary.json",
            control_root / "artifacts" / "publish" / "publish.commit",
        ),
        "verify": (control_root / "artifacts" / "verify" / "verify-summary.json",),
        "finalize": (
            control_root / "artifacts" / "checkpoints" / "finalize.done.json",
        ),
    }
    return by_stage.get(stage, ())


def _jsonl_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            count += 1
    return count


def _probe_signature_matches(state: dict[str, str]) -> bool:
    manifest_path = Path(state["PROBESET_FREEZE_MANIFEST_PATH"])
    expected = state.get("PROBESET_FREEZE_SIGNATURE", "UNSET")
    if expected in {"", "UNSET"}:
        return True
    if not manifest_path.exists():
        return False
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    observed = str(payload.get("signature", ""))
    return observed == expected


def _source_integration_manifest_checksum_pass(state: dict[str, str]) -> bool:
    manifest_path = Path(state["SRC_INTEGRATION_MANIFEST_PATH"])
    if not manifest_path.exists():
        return True

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = payload.get("files", [])
    if not isinstance(checks, list):
        return False
    for row in checks:
        if not isinstance(row, dict):
            return False
        rel = row.get("path")
        sha = row.get("sha256")
        if not isinstance(rel, str) or not isinstance(sha, str):
            return False
        path = Path(state["REPO_ROOT"]) / rel
        if not path.exists():
            return False
        if _sha256_file(path) != sha:
            return False
    return True


def bootstrap_state(
    *,
    paths: StatePaths,
    run_id: str,
    repo_root: Path,
    run_root: Path,
    pdf_root: Path,
    control_run_root: Path,
    plan_path: Path,
    source_pdfset_path: Path,
    relevant_policy_path: Path,
    extraction_policy_path: Path,
    base_branch: str,
    target_branch: str,
    base_pin_sha: str,
    mode: str,
    required_parts_csv: str,
) -> tuple[dict[str, str], dict[str, str]]:
    state = parse_env(paths.state_file)
    checklist = parse_env(paths.checklist_file)

    defaults = {
        "STATE_SCHEMA_VERSION": "1",
        "RUN_ID": run_id,
        "TASK_NAME": state.get("TASK_NAME", "iso26262-mining-verbatim")
        or "iso26262-mining-verbatim",
        "REPO_ROOT": str(repo_root),
        "PLAN_PATH": str(plan_path),
        "RUN_ROOT": str(run_root),
        "PDF_ROOT": str(pdf_root),
        "CONTROL_RUN_ROOT": str(control_run_root),
        "ARTIFACT_ROOT": str(control_run_root / "artifacts"),
        "LOCK_FILE": str(control_run_root / "lock" / "active.lock"),
        "BASE_BRANCH": base_branch,
        "TARGET_BRANCH": target_branch,
        "BASE_PIN_SHA": base_pin_sha,
        "SOURCE_PDFSET_PATH": str(source_pdfset_path),
        "RELEVANT_POLICY_PATH": str(relevant_policy_path),
        "EXTRACTION_POLICY_PATH": str(extraction_policy_path),
        "VERBATIM_PREWARM_ENABLED": state.get("VERBATIM_PREWARM_ENABLED", "1") or "1",
        "VERBATIM_CACHE_ROOT": state.get("VERBATIM_CACHE_ROOT", str(run_root))
        or str(run_root),
        "VERBATIM_SCHEMA_VERSION": state.get("VERBATIM_SCHEMA_VERSION", "1") or "1",
        "PAGE_TEXT_SCHEMA_PATH": state.get(
            "PAGE_TEXT_SCHEMA_PATH",
            str(
                repo_root
                / "traceability"
                / "iso26262"
                / "schema"
                / "page-text.schema.json"
            ),
        )
        or str(
            repo_root / "traceability" / "iso26262" / "schema" / "page-text.schema.json"
        ),
        "UNIT_SLICE_SCHEMA_PATH": state.get(
            "UNIT_SLICE_SCHEMA_PATH",
            str(
                repo_root
                / "traceability"
                / "iso26262"
                / "schema"
                / "unit-slice.schema.json"
            ),
        )
        or str(
            repo_root
            / "traceability"
            / "iso26262"
            / "schema"
            / "unit-slice.schema.json"
        ),
        "ANCHOR_TEXT_LINK_SCHEMA_PATH": state.get(
            "ANCHOR_TEXT_LINK_SCHEMA_PATH",
            str(
                repo_root
                / "traceability"
                / "iso26262"
                / "schema"
                / "anchor-text-link.schema.json"
            ),
        )
        or str(
            repo_root
            / "traceability"
            / "iso26262"
            / "schema"
            / "anchor-text-link.schema.json"
        ),
        "QUERY_TOOL_PATH": state.get(
            "QUERY_TOOL_PATH",
            str(repo_root / "tools" / "traceability" / "query_iso_prewarm_cache.py"),
        )
        or str(repo_root / "tools" / "traceability" / "query_iso_prewarm_cache.py"),
        "QUERY_INDEX_SCHEMA_VERSION": state.get("QUERY_INDEX_SCHEMA_VERSION", "1")
        or "1",
        "QUERY_INDEX_MANIFEST_PATH": state.get(
            "QUERY_INDEX_MANIFEST_PATH",
            str(run_root / "query" / "index-manifest.json"),
        )
        or str(run_root / "query" / "index-manifest.json"),
        "TS_GUIDELINES_PATH": state.get(
            "TS_GUIDELINES_PATH",
            str(repo_root / "docs" / "traceability-ts-and-quotation-guidelines.md"),
        )
        or str(repo_root / "docs" / "traceability-ts-and-quotation-guidelines.md"),
        "MAKEPY_VERIFY_COMMAND": state.get(
            "MAKEPY_VERIFY_COMMAND",
            "SPHINX_MIGRATION_RUN_ROOT=$CONTROL_RUN_ROOT ./make.py verify",
        )
        or "SPHINX_MIGRATION_RUN_ROOT=$CONTROL_RUN_ROOT ./make.py verify",
        "SRC_INTEGRATION_MANIFEST_PATH": state.get(
            "SRC_INTEGRATION_MANIFEST_PATH",
            str(
                control_run_root
                / "artifacts"
                / "source-integration"
                / "src-integration-manifest.json"
            ),
        )
        or str(
            control_run_root
            / "artifacts"
            / "source-integration"
            / "src-integration-manifest.json"
        ),
        "PROBESET_FREEZE_MANIFEST_PATH": state.get(
            "PROBESET_FREEZE_MANIFEST_PATH",
            str(
                control_run_root
                / "artifacts"
                / "probes"
                / "probeset-freeze-manifest.json"
            ),
        )
        or str(
            control_run_root / "artifacts" / "probes" / "probeset-freeze-manifest.json"
        ),
        "PROBESET_FREEZE_SIGNATURE": state.get("PROBESET_FREEZE_SIGNATURE", "UNSET")
        or "UNSET",
        "RETAIN_PROBE_INSERTIONS": state.get("RETAIN_PROBE_INSERTIONS", "0") or "0",
        "MODE": mode,
        "REQUIRED_PARTS": _required_parts_csv(required_parts_csv),
        "CURRENT_PHASE": state.get("CURRENT_PHASE", "0") or "0",
        "CURRENT_STAGE": state.get("CURRENT_STAGE", "ingest") or "ingest",
        "LAST_COMMITTED_PHASE": state.get("LAST_COMMITTED_PHASE", "") or "",
        "LAST_COMMITTED_SHA": state.get("LAST_COMMITTED_SHA", "") or "",
        "LAST_COMMITTED_CHECKPOINT": state.get("LAST_COMMITTED_CHECKPOINT", "") or "",
        "CANONICAL_STATE_UPDATED": state.get("CANONICAL_STATE_UPDATED", "0") or "0",
        "REPORT_APPENDED": state.get("REPORT_APPENDED", "0") or "0",
        "RUN_SUMMARY_UPDATED": state.get("RUN_SUMMARY_UPDATED", "0") or "0",
        "STARTED_AT_UTC": state.get("STARTED_AT_UTC", utc_now()) or utc_now(),
        "LAST_UPDATED_AT_UTC": utc_now(),
    }
    for stage in STAGES:
        defaults[DONE_FLAGS[stage]] = state.get(DONE_FLAGS[stage], "0") or "0"

    for key in OPTIONAL_GUARDRAIL_KEYS:
        if key in state:
            defaults[key] = state.get(key, "")

    for key, value in defaults.items():
        if (
            key in IMMUTABLE_KEYS
            and key in state
            and state[key]
            and state[key] != value
        ):
            raise ContractDriftError(
                f"immutable contract drift for {key}: {state[key]} != {value}"
            )
        state[key] = value

    checklist.setdefault("CHECKLIST_SCHEMA_VERSION", "1")
    checklist.setdefault("RUN_ID", run_id)
    for stage, keys in CHECKLIST_KEYS.items():
        for key in keys:
            checklist[key] = checklist.get(key, "0") or "0"

    write_env(paths.state_file, state)
    write_env(paths.checklist_file, checklist)
    return state, checklist


def reconcile_resume(
    *,
    state: dict[str, str],
    checklist: dict[str, str],
    paths: StatePaths,
) -> tuple[dict[str, str], dict[str, str], str]:
    control_root = Path(state["CONTROL_RUN_ROOT"])
    earliest_stage = "finalize"

    for stage in STAGES:
        done_key = DONE_FLAGS[stage]
        if state.get(done_key, "0") != "1":
            earliest_stage = stage
            break

        checkpoint = control_root / "artifacts" / "checkpoints" / f"{stage}.done.json"
        required_ok = all(
            checklist.get(key, "0") == "1" for key in CHECKLIST_KEYS[stage]
        )
        required_artifacts = _required_stage_artifacts(state, stage)
        missing_artifacts = [path for path in required_artifacts if not path.exists()]
        if not checkpoint.exists() or not required_ok or missing_artifacts:
            state[done_key] = "0"
            for key in CHECKLIST_KEYS[stage]:
                checklist[key] = checklist.get(key, "0") if checkpoint.exists() else "0"
            earliest_stage = stage
            break

    marker_sha = state.get("LAST_COMMITTED_SHA", "")
    marker_ckpt = state.get("LAST_COMMITTED_CHECKPOINT", "")
    if marker_sha:
        head = _git_head(Path(state["REPO_ROOT"]))
        if head != marker_sha:
            raise StopConditionError(
                f"LAST_COMMITTED_SHA mismatch: state={marker_sha} head={head}"
            )
    if marker_ckpt and not Path(marker_ckpt).exists():
        raise StopConditionError(
            f"missing committed checkpoint artifact: {marker_ckpt}"
        )

    run_root = Path(state["RUN_ROOT"])
    unit_link_rows = _jsonl_row_count(
        run_root / "normalize" / "verbatim" / "unit-text-links.jsonl"
    )
    anchor_link_rows = _jsonl_row_count(
        run_root / "anchor" / "verbatim" / "anchor-text-links.jsonl"
    )
    if state.get("S_ANCHOR_DONE", "0") == "1" and unit_link_rows != anchor_link_rows:
        raise StopConditionError(
            "unit-link/anchor-link count mismatch: "
            f"unit_text_links={unit_link_rows} "
            f"anchor_text_links={anchor_link_rows}"
        )

    last_phase = int(state.get("LAST_COMMITTED_PHASE", "0") or "0")
    if (
        last_phase >= 19
        and state.get("S_ANCHOR_DONE", "0") == "1"
        and not Path(state["QUERY_INDEX_MANIFEST_PATH"]).exists()
    ):
        raise StopConditionError(
            "query index manifest missing for completed query phase: "
            f"{state['QUERY_INDEX_MANIFEST_PATH']}"
        )

    source_tx_root = control_root / "artifacts" / "source-integration"
    source_begin = source_tx_root / "src-integration.begin"
    source_commit = source_tx_root / "src-integration.commit"
    if source_begin.exists() and not source_commit.exists():
        raise StopConditionError(
            "source integration transaction is open (begin present without commit)"
        )

    if not _source_integration_manifest_checksum_pass(state):
        raise StopConditionError(
            "source integration manifest checksum mismatch at resume boundary"
        )

    if not _probe_signature_matches(state):
        raise StopConditionError("probe freeze signature mismatch at resume boundary")

    state["CURRENT_STAGE"] = earliest_stage
    state["LAST_UPDATED_AT_UTC"] = utc_now()
    write_env(paths.state_file, state)
    write_env(paths.checklist_file, checklist)
    return state, checklist, earliest_stage


def stage_checklist_complete(stage: str, checklist: dict[str, str]) -> bool:
    return all(checklist.get(key, "0") == "1" for key in CHECKLIST_KEYS[stage])


def reset_stage_checklist(stage: str, checklist: dict[str, str]) -> None:
    for key in CHECKLIST_KEYS[stage]:
        checklist[key] = "0"


def complete_stage(
    *,
    stage: str,
    state: dict[str, str],
    checklist: dict[str, str],
    paths: StatePaths,
) -> tuple[dict[str, str], dict[str, str]]:
    if not stage_checklist_complete(stage, checklist):
        raise StopConditionError(
            f"cannot mark stage done with incomplete checklist: {stage}"
        )

    state[DONE_FLAGS[stage]] = "1"
    state["CURRENT_STAGE"] = _next_stage(stage)
    state["LAST_UPDATED_AT_UTC"] = utc_now()
    write_env(paths.state_file, state)
    write_env(paths.checklist_file, checklist)
    return state, checklist
