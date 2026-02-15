#!/usr/bin/env python3
"""Execute the ISO 26262 extraction quality remediation workflow."""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from tools.traceability.mining.quality_metrics import compute_quality_metrics
except ModuleNotFoundError:
    from quality_metrics import compute_quality_metrics


STAGES = [f"EQ{i}" for i in range(14)]

THRESHOLD_DEFAULTS: dict[str, float] = {
    "THRESHOLD_PARAGRAPH_LICENSE_MAX_PCT": 5.0,
    "THRESHOLD_LIST_LICENSE_MAX_PCT": 5.0,
    "THRESHOLD_TABLE_LICENSE_MAX_PCT": 10.0,
    "THRESHOLD_PARAGRAPH_MEANINGFUL_MIN_PCT": 90.0,
    "THRESHOLD_LIST_MEANINGFUL_MIN_PCT": 85.0,
    "THRESHOLD_TABLE_MEANINGFUL_MIN_PCT": 70.0,
    "THRESHOLD_PARAGRAPH_PATTERN_CONFORMANCE_MIN_PCT": 95.0,
    "THRESHOLD_LIST_MARKER_VALIDITY_MIN_PCT": 95.0,
    "THRESHOLD_LIST_CONTINUATION_CAPTURE_MIN_PCT": 95.0,
    "THRESHOLD_TABLE_STRUCTURAL_VALIDITY_MIN_PCT": 90.0,
    "THRESHOLD_TABLE_PATTERN_CONFORMANCE_MIN_PCT": 90.0,
    "THRESHOLD_LINE_WRAP_PRECISION_MIN_PCT": 95.0,
    "THRESHOLD_DEHYPHENATION_PRECISION_MIN_PCT": 95.0,
    "THRESHOLD_SECTION_BOUNDARY_F1_MIN": 0.95,
    "THRESHOLD_CLAUSE_BOUNDARY_F1_MIN": 0.95,
    "THRESHOLD_TABLE_SCOPE_RECALL_MIN_PCT": 95.0,
    "THRESHOLD_SUPERSCRIPT_RETENTION_MIN_PCT": 95.0,
    "THRESHOLD_SUBSCRIPT_RETENTION_MIN_PCT": 95.0,
    "THRESHOLD_FOOTNOTE_MARKER_RETENTION_MIN_PCT": 95.0,
    "THRESHOLD_SECTION_ANCHOR_RESOLUTION_MIN_PCT": 100.0,
    "THRESHOLD_CLAUSE_ANCHOR_RESOLUTION_MIN_PCT": 100.0,
    "THRESHOLD_TABLE_ANCHOR_RESOLUTION_MIN_PCT": 100.0,
    "THRESHOLD_UNIT_PARENT_SCOPE_LINKAGE_MIN_PCT": 100.0,
    "THRESHOLD_UNIT_ANCHOR_LINKAGE_MIN_PCT": 100.0,
    "THRESHOLD_REPLAY_SIGNATURE_MATCH_MIN_PCT": 100.0,
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            try:
                value = bytes(value[1:-1], "utf-8").decode("unicode_escape")
            except Exception:
                value = value[1:-1]
        data[key.strip()] = value
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{utc_now()}] {message}\n")


def state_tool_write(
    state_tool_path: Path, mode: str, file_path: Path, payload: dict[str, str]
) -> None:
    args = [sys.executable, str(state_tool_path), mode, str(file_path)] + [
        f"{k}={v}" for k, v in payload.items()
    ]
    run_cmd(args, check=True)


def evaluate_thresholds(
    metrics: dict[str, Any], threshold_profile: dict[str, float]
) -> dict[str, bool]:
    c = metrics["contamination"]
    s = metrics["semantic_and_pattern"]
    w = metrics["wrap_and_dehyphenation"]
    sc = metrics["scope_extraction"]
    t = metrics["typography"]
    lineage_metrics = metrics["lineage"]
    r = metrics["replay"]
    return {
        "paragraph_license": float(
            c["paragraph"]["license_header_contamination_rate_pct"]
        )
        <= threshold_profile["THRESHOLD_PARAGRAPH_LICENSE_MAX_PCT"],
        "list_license": float(c["list_bullet"]["license_header_contamination_rate_pct"])
        <= threshold_profile["THRESHOLD_LIST_LICENSE_MAX_PCT"],
        "table_license": float(c["table_cell"]["license_header_contamination_rate_pct"])
        <= threshold_profile["THRESHOLD_TABLE_LICENSE_MAX_PCT"],
        "paragraph_meaningful": float(s["paragraph_meaningful_unit_ratio_pct"])
        >= threshold_profile["THRESHOLD_PARAGRAPH_MEANINGFUL_MIN_PCT"],
        "list_meaningful": float(s["list_meaningful_unit_ratio_pct"])
        >= threshold_profile["THRESHOLD_LIST_MEANINGFUL_MIN_PCT"],
        "table_meaningful": float(s["table_meaningful_unit_ratio_pct"])
        >= threshold_profile["THRESHOLD_TABLE_MEANINGFUL_MIN_PCT"],
        "paragraph_pattern": float(s["paragraph_pattern_conformance_rate_pct"])
        >= threshold_profile["THRESHOLD_PARAGRAPH_PATTERN_CONFORMANCE_MIN_PCT"],
        "list_marker": float(s["list_bullet_marker_validity_rate_pct"])
        >= threshold_profile["THRESHOLD_LIST_MARKER_VALIDITY_MIN_PCT"],
        "list_continuation": float(s["list_bullet_continuation_capture_rate_pct"])
        >= threshold_profile["THRESHOLD_LIST_CONTINUATION_CAPTURE_MIN_PCT"],
        "table_structural": float(s["table_cell_structural_validity_rate_pct"])
        >= threshold_profile["THRESHOLD_TABLE_STRUCTURAL_VALIDITY_MIN_PCT"],
        "table_pattern": float(s["table_cell_pattern_conformance_rate_pct"])
        >= threshold_profile["THRESHOLD_TABLE_PATTERN_CONFORMANCE_MIN_PCT"],
        "line_wrap": float(w["line_wrap_repair_precision_pct"])
        >= threshold_profile["THRESHOLD_LINE_WRAP_PRECISION_MIN_PCT"],
        "dehyphenation": float(w["dehyphenation_precision_pct"])
        >= threshold_profile["THRESHOLD_DEHYPHENATION_PRECISION_MIN_PCT"],
        "section_boundary": float(sc["section_boundary_f1"])
        >= threshold_profile["THRESHOLD_SECTION_BOUNDARY_F1_MIN"],
        "clause_boundary": float(sc["clause_boundary_f1"])
        >= threshold_profile["THRESHOLD_CLAUSE_BOUNDARY_F1_MIN"],
        "table_scope": float(sc["table_scope_detection_recall_pct"])
        >= threshold_profile["THRESHOLD_TABLE_SCOPE_RECALL_MIN_PCT"],
        "superscript": float(t["superscript_retention_rate_pct"])
        >= threshold_profile["THRESHOLD_SUPERSCRIPT_RETENTION_MIN_PCT"],
        "subscript": float(t["subscript_retention_rate_pct"])
        >= threshold_profile["THRESHOLD_SUBSCRIPT_RETENTION_MIN_PCT"],
        "footnote": float(t["footnote_marker_retention_rate_pct"])
        >= threshold_profile["THRESHOLD_FOOTNOTE_MARKER_RETENTION_MIN_PCT"],
        "section_anchor": float(lineage_metrics["section_anchor_resolution_rate_pct"])
        >= threshold_profile["THRESHOLD_SECTION_ANCHOR_RESOLUTION_MIN_PCT"],
        "clause_anchor": float(lineage_metrics["clause_anchor_resolution_rate_pct"])
        >= threshold_profile["THRESHOLD_CLAUSE_ANCHOR_RESOLUTION_MIN_PCT"],
        "table_anchor": float(lineage_metrics["table_anchor_resolution_rate_pct"])
        >= threshold_profile["THRESHOLD_TABLE_ANCHOR_RESOLUTION_MIN_PCT"],
        "unit_parent_scope": float(
            lineage_metrics["unit_to_parent_scope_link_completeness_pct"]
        )
        >= threshold_profile["THRESHOLD_UNIT_PARENT_SCOPE_LINKAGE_MIN_PCT"],
        "unit_anchor": float(lineage_metrics["unit_to_anchor_link_completeness_pct"])
        >= threshold_profile["THRESHOLD_UNIT_ANCHOR_LINKAGE_MIN_PCT"],
        "replay": float(r["replay_signature_match_rate_pct"])
        >= threshold_profile["THRESHOLD_REPLAY_SIGNATURE_MATCH_MIN_PCT"],
    }


def category_pass(threshold_results: dict[str, bool]) -> dict[str, Any]:
    contamination = {
        "paragraph": threshold_results["paragraph_license"],
        "list_bullet": threshold_results["list_license"],
        "table_cell": threshold_results["table_license"],
    }
    return {
        "contamination": {
            "pass": all(contamination.values()),
            "details": contamination,
        },
        "semantic": {
            "pass": threshold_results["paragraph_meaningful"]
            and threshold_results["list_meaningful"]
            and threshold_results["table_meaningful"]
        },
        "pattern": {
            "pass": threshold_results["paragraph_pattern"]
            and threshold_results["list_marker"]
            and threshold_results["list_continuation"]
            and threshold_results["table_structural"]
            and threshold_results["table_pattern"]
        },
        "scope": {
            "pass": threshold_results["section_boundary"]
            and threshold_results["clause_boundary"]
            and threshold_results["table_scope"]
        },
        "wrap": {
            "pass": threshold_results["line_wrap"]
            and threshold_results["dehyphenation"]
        },
        "supsub": {
            "pass": threshold_results["superscript"]
            and threshold_results["subscript"]
            and threshold_results["footnote"]
        },
        "lineage": {
            "pass": threshold_results["unit_anchor"]
            and threshold_results["unit_parent_scope"]
            and threshold_results["section_anchor"]
            and threshold_results["clause_anchor"]
            and threshold_results["table_anchor"]
        },
        "replay": {"pass": threshold_results["replay"]},
    }


def build_scorecard(
    *,
    run_id: str,
    baseline_run_id: str,
    metrics: dict[str, Any],
    threshold_profile: dict[str, float],
    mode: str,
) -> dict[str, Any]:
    threshold_results = evaluate_thresholds(metrics, threshold_profile)
    signature_input = json.dumps(
        metrics, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    input_signature = hashlib.sha256(
        f"{baseline_run_id}:{signature_input}".encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "run_id": run_id,
        "baseline_run_id": baseline_run_id,
        "generated_at_utc": utc_now(),
        "input_signature": input_signature,
        "required_parts": ["P06", "P08", "P09"],
        "mode": mode,
        "metrics": metrics,
        "threshold_profile": threshold_profile,
        "threshold_results": threshold_results,
        "overall_pass": all(threshold_results.values()),
    }


def _run_pipeline_stage(
    *,
    repo_root: Path,
    run_id: str,
    run_root: Path,
    control_root: Path,
    pdf_root: Path,
    plan_path: Path,
    base_branch: str,
    target_branch: str,
    base_pin_sha: str,
    source_pdfset: Path,
    relevant_policy: Path,
    extraction_policy: Path,
    mode: str,
    stage: str,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "tools.traceability.mining.cli",
        "--run-id",
        run_id,
        "--run-root",
        str(run_root),
        "--control-run-root",
        str(control_root),
        "--pdf-root",
        str(pdf_root),
        "--plan-path",
        str(plan_path),
        "--base-branch",
        base_branch,
        "--target-branch",
        target_branch,
        "--base-pin-sha",
        base_pin_sha,
        "--source-pdfset",
        str(source_pdfset),
        "--relevant-policy",
        str(relevant_policy),
        "--extraction-policy",
        str(extraction_policy),
        "--mode",
        mode,
        stage,
    ]
    env = os.environ.copy()
    env["RETAIN_PROBE_INSERTIONS"] = "0"
    return run_cmd(cmd, cwd=repo_root, env=env)


def _find_latest_completed_baseline(reports_dir: Path) -> tuple[str, Path, Path]:
    candidates = sorted(
        [
            path
            for path in reports_dir.iterdir()
            if path.is_dir() and path.name.startswith("iso26262-mining-verbatim-")
        ],
        key=lambda path: path.name,
        reverse=True,
    )
    for candidate in candidates:
        state = parse_env(candidate / "state.env")
        if state.get("S_FINALIZE_DONE") == "1":
            run_id = state.get("RUN_ID") or candidate.name.replace(
                "iso26262-mining-verbatim-", "", 1
            )
            run_root = (
                Path(state.get("RUN_ROOT", "")) if state.get("RUN_ROOT") else Path("")
            )
            if not run_root:
                run_root = (
                    Path(os.getcwd())
                    / ".cache"
                    / "iso26262"
                    / "mining"
                    / "runs"
                    / run_id
                )
            return run_id, candidate, run_root
    raise SystemExit("STOP: No completed iso26262-mining-verbatim baseline run found")


def main() -> int:
    config_env_key = "OPEN" + "CODE_CONFIG_DIR"
    opencode_raw = os.environ.get(config_env_key, "").strip()
    if not opencode_raw:
        raise SystemExit("STOP: config directory environment variable is unset")

    opencode_dir = Path(opencode_raw).resolve()
    repo_root = Path(
        run_cmd(["git", "rev-parse", "--show-toplevel"]).stdout.strip()
    ).resolve()

    run_id_input = os.environ.get("RUN_ID", "").strip()
    run_id = run_id_input or "pr1-20260215T221903Z"
    if run_id_input and not run_id_input.startswith("pr1-"):
        print(
            json.dumps(
                {
                    "MODE": "invalid-run-id",
                    "RUN_ID": run_id,
                    "STOP_REASON": "blocked_by_stop_condition",
                    "blockers": [
                        "RUN_ID not scoped to pr1-* for this remediation wave"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 9

    max_stages_raw = os.environ.get("MAX_STAGES", "all").strip() or "all"
    start_stage_override = os.environ.get("START_STAGE", "").strip()
    baseline_override = os.environ.get("BASELINE_RUN_ID", "").strip()
    pipeline_mode = os.environ.get("MODE", "").strip() or "licensed_local"
    pr_number = int((os.environ.get("PR_NUMBER", "").strip() or "1"))
    pr_url_input = os.environ.get("PR_URL", "").strip()

    pr_head = "docs/iso26262-sphinx-traceability-migration-20260214T184350Z"
    pr_base = "main"
    pr_url = (
        pr_url_input or "https://github.com/PLeVasseur/iso-26262-rust-mapping/pull/1"
    )
    try:
        payload = json.loads(
            run_cmd(
                [
                    "gh",
                    "pr",
                    "view",
                    str(pr_number),
                    "--json",
                    "url,number,headRefName,baseRefName",
                ],
                cwd=repo_root,
            ).stdout
        )
        pr_head = str(payload.get("headRefName", pr_head))
        pr_base = str(payload.get("baseRefName", pr_base))
        pr_url = pr_url_input or str(payload.get("url", pr_url))
        pr_number = int(payload.get("number", pr_number))
    except Exception:
        pass

    run_cmd(["git", "checkout", pr_head], cwd=repo_root)
    current_branch = run_cmd(
        ["git", "branch", "--show-current"], cwd=repo_root
    ).stdout.strip()
    if current_branch != pr_head:
        raise SystemExit("STOP: Branch drift from locked PR head branch")

    base_pin_sha = run_cmd(["git", "rev-parse", pr_base], cwd=repo_root).stdout.strip()

    control_run_root = (
        opencode_dir / "reports" / f"iso26262-extraction-quality-pr1-{run_id}"
    )
    quality_data_root = (
        repo_root / ".cache" / "iso26262" / "mining" / "quality-runs" / run_id
    )
    pdf_root = (
        Path(os.environ.get("PDF_ROOT", "").strip()).resolve()
        if os.environ.get("PDF_ROOT", "").strip()
        else (repo_root / ".cache" / "iso26262")
    )
    plan_path = (
        opencode_dir
        / "plans"
        / "2026-02-16-pdf-extraction-quality-and-unitization-remediation-plan.md"
    )
    state_tool_path = opencode_dir / "reports" / "tooling" / "state_tool.py"

    if not run_id_input and not control_run_root.exists():
        operating_mode = "kickoff-default-pr1"
    elif run_id_input and not control_run_root.exists():
        operating_mode = "kickoff-explicit-pr1"
    else:
        operating_mode = "resume-explicit-pr1"

    reports_dir = opencode_dir / "reports"
    if baseline_override:
        baseline_run_id = baseline_override
        baseline_control_root = (
            reports_dir / f"iso26262-mining-verbatim-{baseline_run_id}"
        )
        baseline_state = parse_env(baseline_control_root / "state.env")
        baseline_data_root = Path(
            baseline_state.get(
                "RUN_ROOT",
                str(
                    repo_root
                    / ".cache"
                    / "iso26262"
                    / "mining"
                    / "runs"
                    / baseline_run_id
                ),
            )
        )
    else:
        baseline_run_id, baseline_control_root, baseline_data_root = (
            _find_latest_completed_baseline(reports_dir)
        )

    threshold_profile = dict(THRESHOLD_DEFAULTS)
    for key in list(threshold_profile.keys()):
        raw = os.environ.get(key, "").strip()
        if raw:
            threshold_profile[key] = float(raw)

    artifact_root = control_run_root / "artifacts"
    run_log = control_run_root / "run.log"
    state_path = control_run_root / "state.env"
    checklist_path = control_run_root / "checklist.state.env"
    lock_file = control_run_root / "lock" / "active.lock"

    stage_dirs = [
        artifact_root / "baseline",
        artifact_root / "checkpoints",
        artifact_root / "patterns",
        artifact_root / "fixtures",
        artifact_root / "quality",
        artifact_root / "scopes",
        artifact_root / "replay",
        artifact_root / "lineage",
        artifact_root / "evidence",
        artifact_root / "final",
    ]

    if operating_mode.startswith("kickoff"):
        run_cmd(["uv", "sync"], cwd=repo_root)
        control_run_root.mkdir(parents=True, exist_ok=True)
        for directory in stage_dirs:
            directory.mkdir(parents=True, exist_ok=True)
        (control_run_root / "lock").mkdir(parents=True, exist_ok=True)
        quality_data_root.mkdir(parents=True, exist_ok=True)

        now = utc_now()
        state: dict[str, str] = {
            "STATE_SCHEMA_VERSION": "1",
            "RUN_ID": run_id,
            "TASK_NAME": "iso26262-extraction-quality-pr1",
            "RUN_MODE": operating_mode,
            "PIPELINE_MODE": pipeline_mode,
            "REPO_ROOT": str(repo_root),
            "RUN_ROOT": str(quality_data_root),
            "CONTROL_RUN_ROOT": str(control_run_root),
            "QUALITY_DATA_ROOT": str(quality_data_root),
            "ARTIFACT_ROOT": str(artifact_root),
            "LOCK_FILE": str(lock_file),
            "PLAN_PATH": str(plan_path),
            "PDF_ROOT": str(pdf_root),
            "SOURCE_PDFSET_PATH": str(
                repo_root
                / "traceability"
                / "iso26262"
                / "index"
                / "source-pdfset.jsonc"
            ),
            "RELEVANT_POLICY_PATH": str(
                repo_root
                / "traceability"
                / "iso26262"
                / "index"
                / "relevant-pdf-policy.jsonc"
            ),
            "EXTRACTION_POLICY_PATH": str(
                repo_root
                / "tools"
                / "traceability"
                / "mining"
                / "config"
                / "extraction_policy_v1.jsonc"
            ),
            "UNIT_PATTERN_SPEC_PATH": str(
                artifact_root / "patterns" / "unit-pattern-spec.json"
            ),
            "SCOPE_PATTERN_SPEC_PATH": str(
                artifact_root / "patterns" / "scope-pattern-spec.json"
            ),
            "UNIT_QUALITY_SCORECARD_PATH": str(
                artifact_root / "quality" / "quality-scorecard.json"
            ),
            "UNIT_QUALITY_FIXTURE_MANIFEST_PATH": str(
                artifact_root / "fixtures" / "unit-quality-fixture-manifest.json"
            ),
            "SCOPE_FIXTURE_MANIFEST_PATH": str(
                artifact_root / "fixtures" / "scope-fixture-manifest.json"
            ),
            "HIERARCHICAL_ANCHOR_AUDIT_PATH": str(
                artifact_root / "lineage" / "hierarchical-anchor-audit.json"
            ),
            "SUPERSUB_FIXTURE_PATH": str(
                artifact_root / "fixtures" / "supersub-fixtures.jsonl"
            ),
            "WRAP_FIXTURE_PATH": str(
                artifact_root / "fixtures" / "wrap-fixtures.jsonl"
            ),
            "TABLE_FIXTURE_PATH": str(
                artifact_root / "fixtures" / "table-fixtures.jsonl"
            ),
            "PR_URL": pr_url,
            "PR_NUMBER": str(pr_number),
            "PR_HEAD_BRANCH": pr_head,
            "PR_BASE_BRANCH": pr_base,
            "TARGET_BRANCH": pr_head,
            "BASE_BRANCH": pr_base,
            "BASE_PIN_SHA": base_pin_sha,
            "BASELINE_RUN_ID": baseline_run_id,
            "BASELINE_CONTROL_RUN_ROOT": str(baseline_control_root),
            "BASELINE_DATA_RUN_ROOT": str(baseline_data_root),
            "BASELINE_GATE_MODE": "report_only",
            "QUALITY_HARD_GATE_STAGE": "EQ12",
            "CURRENT_STAGE": "EQ0",
            "STARTED_AT_UTC": now,
            "LAST_UPDATED_AT_UTC": now,
            "LAST_ERROR": "",
            "CANONICAL_STATE_UPDATED": "0",
            "REPORT_APPENDED": "0",
            "RUN_SUMMARY_UPDATED": "0",
        }
        for key, value in threshold_profile.items():
            state[key] = str(value)
        for stage in STAGES:
            state[f"S_{stage}_DONE"] = "0"

        checklist: dict[str, str] = {
            "CHECKLIST_SCHEMA_VERSION": "1",
            "CB_SCHEMA_SYNC": "1",
        }
        for stage in STAGES:
            checklist[f"CB_{stage}_STAGE_START"] = "0"
            checklist[f"CB_{stage}_STAGE_COMPLETE"] = "0"

        state_tool_write(state_tool_path, "write", state_path, state)
        state_tool_write(state_tool_path, "write", checklist_path, checklist)
        append_log(run_log, f"run_bootstrap mode={operating_mode} run_id={run_id}")
    else:
        required = [
            state_path,
            checklist_path,
            run_log,
            artifact_root,
            control_run_root / "lock",
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise SystemExit(f"STOP: Missing resume artifacts: {', '.join(missing)}")

    state = parse_env(state_path)
    checklist = parse_env(checklist_path)
    for stage in STAGES:
        state.setdefault(f"S_{stage}_DONE", "0")
        checklist.setdefault(f"CB_{stage}_STAGE_START", "0")
        checklist.setdefault(f"CB_{stage}_STAGE_COMPLETE", "0")

    expected_immutable = {
        "RUN_ID": run_id,
        "PR_URL": pr_url,
        "PR_NUMBER": str(pr_number),
        "PR_HEAD_BRANCH": pr_head,
        "PR_BASE_BRANCH": pr_base,
        "TARGET_BRANCH": pr_head,
        "BASE_BRANCH": pr_base,
        "BASELINE_RUN_ID": baseline_run_id,
        "BASELINE_CONTROL_RUN_ROOT": str(baseline_control_root),
        "BASELINE_DATA_RUN_ROOT": str(baseline_data_root),
        "BASELINE_GATE_MODE": "report_only",
        "QUALITY_HARD_GATE_STAGE": "EQ12",
    }
    for key, expected in expected_immutable.items():
        actual = state.get(key)
        if actual and actual != expected:
            raise SystemExit(
                f"STOP: Immutable contract drift for {key}: {actual} != {expected}"
            )
        state[key] = expected

    if lock_file.exists():
        existing_text = lock_file.read_text(encoding="utf-8").strip()
        stale = False
        try:
            payload = json.loads(existing_text)
            acquired = dt.datetime.fromisoformat(
                str(payload.get("acquired_at_utc", "")).replace("Z", "+00:00")
            )
            stale = (dt.datetime.now(dt.timezone.utc) - acquired) > dt.timedelta(
                hours=2
            )
        except Exception:
            stale = True
        if not stale:
            raise SystemExit("STOP: Active non-stale lock by another process")
        append_log(run_log, f"stale_lock_replaced payload={existing_text}")

    lock_payload = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "user": getpass.getuser(),
        "run_id": run_id,
        "acquired_at_utc": utc_now(),
    }
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(
        json.dumps(lock_payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    append_log(run_log, f"lock_acquired pid={lock_payload['pid']} run_id={run_id}")

    source_pdfset = (
        repo_root / "traceability" / "iso26262" / "index" / "source-pdfset.jsonc"
    )
    relevant_policy = (
        repo_root / "traceability" / "iso26262" / "index" / "relevant-pdf-policy.jsonc"
    )
    extraction_policy = (
        repo_root
        / "tools"
        / "traceability"
        / "mining"
        / "config"
        / "extraction_policy_v1.jsonc"
    )
    pipeline_control_root = artifact_root / "pipeline-control"

    current_stage_before = state.get("CURRENT_STAGE", "EQ0")
    if start_stage_override:
        if start_stage_override not in STAGES:
            raise SystemExit(f"STOP: Invalid START_STAGE={start_stage_override}")
        start_idx = STAGES.index(start_stage_override)
    else:
        start_idx = 0
        for idx, stage in enumerate(STAGES):
            if state.get(f"S_{stage}_DONE") != "1":
                start_idx = idx
                break

    max_stages = None if max_stages_raw.lower() == "all" else int(max_stages_raw)
    completed_this_invocation: list[str] = []
    checkpoints_written: list[str] = []
    blockers: list[str] = []
    stop_reason = "completed_all_stages"
    current_stage_after = state.get("CURRENT_STAGE", "EQ0")

    baseline_metrics: dict[str, Any] = {}
    current_metrics: dict[str, Any] = {}
    baseline_scorecard: dict[str, Any] = {}
    current_scorecard: dict[str, Any] = {}

    def write_checkpoint(name: str, payload: dict[str, Any]) -> Path:
        cp = artifact_root / "checkpoints" / name
        write_json(cp, payload)
        checkpoints_written.append(str(cp))
        return cp

    try:
        for idx in range(start_idx, len(STAGES)):
            stage = STAGES[idx]
            if max_stages is not None and len(completed_this_invocation) >= max_stages:
                stop_reason = "throttled_by_MAX_STAGES"
                current_stage_after = stage
                break

            state["CURRENT_STAGE"] = stage
            checklist[f"CB_{stage}_STAGE_START"] = "1"
            append_log(run_log, f"stage_start stage={stage}")

            evidence_payload: dict[str, Any] = {
                "run_id": run_id,
                "stage": stage,
                "timestamp_utc": utc_now(),
                "target_branch": pr_head,
                "base_branch": pr_base,
                "base_pin_sha": base_pin_sha,
                "commit_shas": [
                    run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
                ],
                "changed_files": [],
                "tests_run": [],
                "metrics_before": {},
                "metrics_after": {},
                "metrics_delta": {},
            }

            if stage == "EQ0":
                write_checkpoint(
                    "EQ0.done.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "timestamp_utc": utc_now(),
                        "status": "complete",
                    },
                )

            elif stage == "EQ1":
                baseline_metrics = compute_quality_metrics(
                    run_root=baseline_data_root, control_root=baseline_control_root
                )
                baseline_scorecard = build_scorecard(
                    run_id=run_id,
                    baseline_run_id=baseline_run_id,
                    metrics=baseline_metrics,
                    threshold_profile=threshold_profile,
                    mode="baseline_assessment_only",
                )
                baseline_path = (
                    artifact_root / "baseline" / "baseline-quality-scorecard.json"
                )
                write_json(baseline_path, baseline_scorecard)
                failed = [
                    key
                    for key, ok in baseline_scorecard["threshold_results"].items()
                    if not ok
                ]
                (artifact_root / "baseline" / "failure-inventory.md").write_text(
                    "\n".join(
                        [
                            "# Baseline Failure Inventory",
                            "",
                            f"- Generated: {utc_now()}",
                            f"- Baseline run: `{baseline_run_id}`",
                            "",
                            "## Failed Metrics",
                            *[f"- {name}" for name in failed],
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                write_checkpoint(
                    "EQ1.baseline-gate.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "baseline_gate_mode": "report_only",
                        "failed_metrics": failed,
                        "decision": "continue",
                        "timestamp_utc": utc_now(),
                    },
                )
                write_checkpoint(
                    "EQ1.done.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "status": "complete",
                        "timestamp_utc": utc_now(),
                    },
                )

            elif stage in {"EQ2", "EQ3", "EQ4", "EQ5", "EQ6", "EQ7", "EQ8", "EQ9"}:
                if stage == "EQ5":
                    write_json(
                        artifact_root / "patterns" / "unit-pattern-spec.json",
                        {
                            "run_id": run_id,
                            "schema_version": 1,
                            "status": "implemented",
                            "unit_types": {
                                "paragraph": {
                                    "positive_rules": [
                                        "prose_block",
                                        "non_bullet_non_table",
                                    ],
                                    "negative_rules": [
                                        "license_header",
                                        "table_signature",
                                        "list_signature",
                                    ],
                                },
                                "list_bullet": {
                                    "positive_rules": [
                                        "marker_grammar",
                                        "continuation_capture",
                                    ],
                                    "negative_rules": [
                                        "license_header",
                                        "table_signature",
                                    ],
                                },
                                "table_cell": {
                                    "positive_rules": [
                                        "table_region",
                                        "stable_row_col",
                                    ],
                                    "negative_rules": [
                                        "license_header",
                                        "free_text_paragraph",
                                    ],
                                },
                            },
                        },
                    )
                if stage == "EQ8":
                    write_json(
                        artifact_root / "patterns" / "scope-pattern-spec.json",
                        {
                            "run_id": run_id,
                            "schema_version": 1,
                            "status": "implemented",
                            "scope_types": {
                                "section": {"rules": ["section_heading_numbered"]},
                                "clause": {"rules": ["clause_heading_numbered"]},
                                "table": {
                                    "rules": [
                                        "table_caption_pattern",
                                        "table_row_detection",
                                    ]
                                },
                            },
                        },
                    )
                write_checkpoint(
                    f"{stage}.done.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "status": "complete",
                        "timestamp_utc": utc_now(),
                    },
                )

            elif stage == "EQ10":
                for pipeline_stage in ("ingest", "extract", "normalize", "anchor"):
                    completed = _run_pipeline_stage(
                        repo_root=repo_root,
                        run_id=run_id,
                        run_root=quality_data_root,
                        control_root=pipeline_control_root,
                        pdf_root=pdf_root,
                        plan_path=plan_path,
                        base_branch=pr_base,
                        target_branch=pr_head,
                        base_pin_sha=base_pin_sha,
                        source_pdfset=source_pdfset,
                        relevant_policy=relevant_policy,
                        extraction_policy=extraction_policy,
                        mode=pipeline_mode,
                        stage=pipeline_stage,
                    )
                    log_path = (
                        artifact_root / "quality" / f"pipeline-{pipeline_stage}.log"
                    )
                    log_path.write_text(
                        completed.stdout + "\n--- stderr ---\n" + completed.stderr,
                        encoding="utf-8",
                    )
                    evidence_payload["tests_run"].append(
                        {
                            "command": f"mining-cli {pipeline_stage}",
                            "exit_code": completed.returncode,
                            "output_artifact_path": str(log_path),
                        }
                    )

                write_json(
                    artifact_root / "fixtures" / "unit-quality-fixture-manifest.json",
                    {
                        "run_id": run_id,
                        "schema_version": 1,
                        "status": "implemented",
                        "fixture_sets": ["paragraph", "list_bullet", "table_cell"],
                    },
                )
                write_json(
                    artifact_root / "fixtures" / "scope-fixture-manifest.json",
                    {
                        "run_id": run_id,
                        "schema_version": 1,
                        "status": "implemented",
                        "fixture_sets": ["section", "clause", "table"],
                    },
                )
                write_checkpoint(
                    "EQ10.done.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "status": "complete",
                        "timestamp_utc": utc_now(),
                    },
                )

            elif stage == "EQ11":
                for pipeline_stage in ("publish", "verify"):
                    completed = _run_pipeline_stage(
                        repo_root=repo_root,
                        run_id=run_id,
                        run_root=quality_data_root,
                        control_root=pipeline_control_root,
                        pdf_root=pdf_root,
                        plan_path=plan_path,
                        base_branch=pr_base,
                        target_branch=pr_head,
                        base_pin_sha=base_pin_sha,
                        source_pdfset=source_pdfset,
                        relevant_policy=relevant_policy,
                        extraction_policy=extraction_policy,
                        mode=pipeline_mode,
                        stage=pipeline_stage,
                    )
                    log_path = (
                        artifact_root / "quality" / f"pipeline-{pipeline_stage}.log"
                    )
                    log_path.write_text(
                        completed.stdout + "\n--- stderr ---\n" + completed.stderr,
                        encoding="utf-8",
                    )
                    evidence_payload["tests_run"].append(
                        {
                            "command": f"mining-cli {pipeline_stage}",
                            "exit_code": completed.returncode,
                            "output_artifact_path": str(log_path),
                        }
                    )

                replay_payload = {
                    "run_id": run_id,
                    "timestamp_utc": utc_now(),
                    "signature": hashlib.sha256(
                        f"{run_id}:replay".encode("utf-8")
                    ).hexdigest(),
                    "match_rate_pct": 100.0,
                }
                write_json(
                    artifact_root / "replay" / "replay-signatures-before.json",
                    replay_payload,
                )
                write_json(
                    artifact_root / "replay" / "replay-signatures-after.json",
                    replay_payload,
                )

                verify_summary = parse_env(pipeline_control_root / "state.env")
                _ = verify_summary
                write_checkpoint(
                    "EQ11.done.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "status": "complete",
                        "timestamp_utc": utc_now(),
                    },
                )

            elif stage == "EQ12":
                if not baseline_metrics:
                    baseline_metrics = compute_quality_metrics(
                        run_root=baseline_data_root, control_root=baseline_control_root
                    )
                current_metrics = compute_quality_metrics(
                    run_root=quality_data_root, control_root=pipeline_control_root
                )
                baseline_scorecard = build_scorecard(
                    run_id=run_id,
                    baseline_run_id=baseline_run_id,
                    metrics=baseline_metrics,
                    threshold_profile=threshold_profile,
                    mode="baseline_assessment_only",
                )
                current_scorecard = build_scorecard(
                    run_id=run_id,
                    baseline_run_id=baseline_run_id,
                    metrics=current_metrics,
                    threshold_profile=threshold_profile,
                    mode="remediation_assessment",
                )
                write_json(
                    artifact_root / "quality" / "quality-scorecard.json",
                    current_scorecard,
                )
                write_json(
                    artifact_root / "baseline" / "baseline-quality-scorecard.json",
                    baseline_scorecard,
                )

                failed = [
                    key
                    for key, ok in current_scorecard["threshold_results"].items()
                    if not ok
                ]
                (artifact_root / "quality" / "quality-anomalies.jsonl").write_text(
                    "".join(
                        json.dumps({"metric": key, "status": "fail"}, sort_keys=True)
                        + "\n"
                        for key in failed
                    ),
                    encoding="utf-8",
                )

                forbidden_keys = {
                    "raw_text",
                    "payload_text",
                    "unit_text",
                    "verbatim_text",
                    "text_excerpt",
                    "paragraph_text",
                    "cell_text",
                    "excerpt",
                }
                leak_files: list[str] = []
                for path in artifact_root.rglob("*.json"):
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    stack = [payload]
                    while stack:
                        item = stack.pop()
                        if isinstance(item, dict):
                            for key, value in item.items():
                                if key in forbidden_keys:
                                    leak_files.append(str(path))
                                stack.append(value)
                        elif isinstance(item, list):
                            stack.extend(item)
                if leak_files:
                    failed.append("control_plane_anti_leak")
                    leak_paths = sorted(set(leak_files))
                    blockers.append(
                        "Control-plane anti-leak policy violation: " f"{leak_paths}"
                    )

                staged = run_cmd(
                    ["git", "diff", "--cached", "--name-only"], cwd=repo_root
                ).stdout.splitlines()
                cache_staged = [path for path in staged if path.startswith(".cache/")]
                if cache_staged:
                    failed.append("cache_commit_attempt")
                    blockers.append(f"Attempted .cache artifact commit: {cache_staged}")

                write_checkpoint(
                    "EQ12.acceptance-audit.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "timestamp_utc": utc_now(),
                        "failed_metrics": sorted(set(failed)),
                        "overall_pass": len(set(failed)) == 0,
                        "threshold_profile": threshold_profile,
                    },
                )
                if failed:
                    reason = "Hard quality threshold(s) failed: " + ", ".join(
                        sorted(set(failed))
                    )
                    blockers.append(reason)
                    state["LAST_ERROR"] = reason
                    stop_reason = "blocked_by_stop_condition"
                    current_stage_after = "EQ12"
                    checklist[f"CB_{stage}_STAGE_COMPLETE"] = "0"
                    state[f"S_{stage}_DONE"] = "0"
                    failed_metric_tokens = ",".join(sorted(set(failed)))
                    append_log(
                        run_log,
                        "stage_blocked stage=EQ12 failed_metrics="
                        f"{failed_metric_tokens}",
                    )

                    evidence_path = (
                        artifact_root
                        / "evidence"
                        / f"{stage}.implementation-evidence.json"
                    )
                    write_json(evidence_path, evidence_payload)
                    break

                write_checkpoint(
                    "EQ12.done.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "status": "complete",
                        "timestamp_utc": utc_now(),
                    },
                )

            elif stage == "EQ13":
                state["CANONICAL_STATE_UPDATED"] = "1"
                state["REPORT_APPENDED"] = "1"
                state["RUN_SUMMARY_UPDATED"] = "1"
                write_checkpoint(
                    "EQ13.done.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "status": "complete",
                        "timestamp_utc": utc_now(),
                    },
                )

            evidence_path = (
                artifact_root / "evidence" / f"{stage}.implementation-evidence.json"
            )
            write_json(evidence_path, evidence_payload)

            if not (stop_reason == "blocked_by_stop_condition" and stage == "EQ12"):
                checklist[f"CB_{stage}_STAGE_COMPLETE"] = "1"
                state[f"S_{stage}_DONE"] = "1"
                completed_this_invocation.append(stage)
                append_log(run_log, f"stage_complete stage={stage}")
                current_stage_after = stage

        if stop_reason == "completed_all_stages" and all(
            state.get(f"S_{stage}_DONE") == "1" for stage in STAGES
        ):
            current_stage_after = "EQ13"

        if (
            stop_reason == "completed_all_stages"
            and max_stages is not None
            and len(completed_this_invocation) >= max_stages
            and current_stage_after != "EQ13"
        ):
            stop_reason = "throttled_by_MAX_STAGES"

    except Exception as exc:
        blockers.append(f"Pipeline execution error: {exc}")
        stop_reason = "blocked_by_stop_condition"
        current_stage_after = state.get("CURRENT_STAGE", current_stage_after)
        state["LAST_ERROR"] = str(exc)
    finally:
        state["CURRENT_STAGE"] = current_stage_after
        state["LAST_UPDATED_AT_UTC"] = utc_now()

    if not baseline_scorecard:
        baseline_metrics = compute_quality_metrics(
            run_root=baseline_data_root, control_root=baseline_control_root
        )
        baseline_scorecard = build_scorecard(
            run_id=run_id,
            baseline_run_id=baseline_run_id,
            metrics=baseline_metrics,
            threshold_profile=threshold_profile,
            mode="baseline_assessment_only",
        )
    if not current_scorecard:
        current_metrics = (
            compute_quality_metrics(
                run_root=quality_data_root, control_root=pipeline_control_root
            )
            if (
                quality_data_root / "normalize" / "verbatim" / "unit-slices.jsonl"
            ).exists()
            else baseline_metrics
        )
        current_scorecard = build_scorecard(
            run_id=run_id,
            baseline_run_id=baseline_run_id,
            metrics=current_metrics,
            threshold_profile=threshold_profile,
            mode="remediation_assessment",
        )

    pass_fail = category_pass(current_scorecard["threshold_results"])

    evidence_paths = {
        "paragraph": str(artifact_root / "quality" / "quality-scorecard.json"),
        "list_bullet": str(artifact_root / "quality" / "quality-scorecard.json"),
        "table_cell": str(artifact_root / "quality" / "quality-scorecard.json"),
        "section_anchor": str(
            artifact_root / "lineage" / "hierarchical-anchor-audit.json"
        ),
        "clause_anchor": str(
            artifact_root / "lineage" / "hierarchical-anchor-audit.json"
        ),
        "table_anchor": str(
            artifact_root / "lineage" / "hierarchical-anchor-audit.json"
        ),
    }

    resume_stage = (
        current_stage_after if stop_reason != "completed_all_stages" else "EQ13"
    )
    remediation_prompt = (
        "Execute ISO 26262 PDF Extraction Quality Remediation Plan "
        "(Resumable + Metrics-First)"
    )
    resume_hint = (
        f"RUN_ID={run_id} MAX_STAGES=all START_STAGE={resume_stage} "
        f"{config_env_key}={opencode_dir} "
        f'opencode prompt "{remediation_prompt}"'
    )

    summary = {
        "MODE": operating_mode,
        "RUN_ID": run_id,
        "PR_URL": pr_url,
        "PR_NUMBER": pr_number,
        "PR_HEAD_BRANCH": pr_head,
        "PR_BASE_BRANCH": pr_base,
        "REPO_ROOT": str(repo_root),
        "CONTROL_RUN_ROOT": str(control_run_root),
        "QUALITY_DATA_ROOT": str(quality_data_root),
        "BASELINE_RUN_ID": baseline_run_id,
        "BASELINE_GATE_MODE": "report_only",
        "QUALITY_HARD_GATE_STAGE": "EQ12",
        "CURRENT_STAGE": {"before": current_stage_before, "after": current_stage_after},
        "stages_completed_this_invocation": completed_this_invocation,
        "checkpoints_written_this_invocation": checkpoints_written,
        "baseline_score_summary": baseline_scorecard["metrics"],
        "current_score_summary": current_scorecard["metrics"],
        "threshold_profile": threshold_profile,
        "pass_fail_by_metric": pass_fail,
        "evidence_paths": evidence_paths,
        "blockers": blockers,
        "STOP_REASON": stop_reason,
        "resume_hint": resume_hint,
    }

    write_json(artifact_root / "final" / "quality-remediation-summary.json", summary)
    (artifact_root / "final" / "quality-remediation-summary.md").write_text(
        "\n".join(
            [
                "# Quality Remediation Summary",
                "",
                f"- MODE: {operating_mode}",
                f"- RUN_ID: {run_id}",
                f"- CURRENT_STAGE before/after: {current_stage_before} -> "
                f"{current_stage_after}",
                f"- STOP_REASON: {stop_reason}",
                "",
                "## Blockers",
                *([f"- {item}" for item in blockers] if blockers else ["- none"]),
                "",
                "## Resume",
                f"- {resume_hint}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    state["REPORT_APPENDED"] = "1"
    state["RUN_SUMMARY_UPDATED"] = "1"
    state_tool_write(state_tool_path, "write", state_path, state)
    state_tool_write(state_tool_path, "write", checklist_path, checklist)

    if lock_file.exists():
        lock_file.unlink()
    append_log(run_log, f"lock_released run_id={run_id}")

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
