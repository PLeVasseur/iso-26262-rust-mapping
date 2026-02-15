"""Durable control-plane state and checklist management."""

from __future__ import annotations

import dataclasses
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
    "MODE",
    "REQUIRED_PARTS",
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
        "TASK_NAME": "iso26262-mining",
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

    for key, value in defaults.items():
        if key in IMMUTABLE_KEYS and key in state and state[key] and state[key] != value:
            raise ContractDriftError(f"immutable contract drift for {key}: {state[key]} != {value}")
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
        required_ok = all(checklist.get(key, "0") == "1" for key in CHECKLIST_KEYS[stage])
        if not checkpoint.exists() or not required_ok:
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
            raise StopConditionError(f"LAST_COMMITTED_SHA mismatch: state={marker_sha} head={head}")
    if marker_ckpt and not Path(marker_ckpt).exists():
        raise StopConditionError(f"missing committed checkpoint artifact: {marker_ckpt}")

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
        raise StopConditionError(f"cannot mark stage done with incomplete checklist: {stage}")

    state[DONE_FLAGS[stage]] = "1"
    state["CURRENT_STAGE"] = _next_stage(stage)
    state["LAST_UPDATED_AT_UTC"] = utc_now()
    write_env(paths.state_file, state)
    write_env(paths.checklist_file, checklist)
    return state, checklist
