#!/usr/bin/env python3
"""Execute the ISO 26262 unit-boundary pathology remediation workflow."""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import inspect
import json
import os
import re
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
REQUIRED_PARTS = ["P06", "P08", "P09"]

LOCKED_PR_HEAD_BRANCH = "docs/iso26262-sphinx-traceability-migration-20260214T184350Z"
LOCKED_PR_BASE_BRANCH = "main"
DEFAULT_PR_URL = "https://github.com/PLeVasseur/iso-26262-rust-mapping/pull/1"

DEFAULT_BASELINE_RUN_ID = "pr1-20260215T221903Z"

PLAN_RELATIVE_PATH = (
    "plans/2026-02-16-unit-boundary-pathology-remediation-repair-plan.md"
)
PROMPT_RELATIVE_PATH = (
    "prompts/execute-iso26262-unit-boundary-pathology-remediation-resumable.md"
)
SKILL_RELATIVE_PATH = "skills/resumable-execution/SKILL.md"
STATE_TOOL_RELATIVE_PATH = "reports/tooling/state_tool.py"
STATE_TEMPLATE_RELATIVE_PATH = "skills/resumable-execution/run-state.template.env"
CHECKLIST_TEMPLATE_RELATIVE_PATH = (
    "skills/resumable-execution/checklist-state.template.env"
)

TASK_NAME = "iso26262-extraction-quality-pr1"

REMEDIATION_PROMPT_TITLE = (
    "Execute ISO 26262 Unit Boundary Pathology Remediation Repair "
    "(Resumable + One-Shot)"
)

IMPLEMENTATION_STAGE_SET = {f"EQ{i}" for i in range(2, 12)}
IMPLEMENTATION_PATH_PREFIXES = (
    "tools/traceability/mining/",
    "traceability/iso26262/index/",
)
CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(feat|fix|refactor|chore|docs|test|perf)(\([^)]+\))?:\s+"
)

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
    "THRESHOLD_PARAGRAPH_BOILERPLATE_MAX_PCT": 5.0,
    "THRESHOLD_LIST_BOILERPLATE_MAX_PCT": 5.0,
    "THRESHOLD_TABLE_BOILERPLATE_MAX_PCT": 10.0,
    "THRESHOLD_TRIAD_SOURCE_SET_IDENTITY_MAX_PCT": 5.0,
    "THRESHOLD_PARAGRAPH_FRAGMENT_START_MAX_PCT": 10.0,
    "THRESHOLD_PARAGRAPH_FRAGMENT_END_MAX_PCT": 10.0,
    "THRESHOLD_PARAGRAPH_SINGLETON_PAGE_MAX_PCT": 85.0,
    "THRESHOLD_OVERSIZED_PARAGRAPH_MAX_PCT": 20.0,
    "THRESHOLD_UNIT_TYPE_PROVENANCE_OVERLAP_MAX_PCT": 10.0,
}

REQUIRED_NEW_THRESHOLD_KEYS = {
    "THRESHOLD_PARAGRAPH_BOILERPLATE_MAX_PCT",
    "THRESHOLD_LIST_BOILERPLATE_MAX_PCT",
    "THRESHOLD_TABLE_BOILERPLATE_MAX_PCT",
    "THRESHOLD_TRIAD_SOURCE_SET_IDENTITY_MAX_PCT",
    "THRESHOLD_PARAGRAPH_FRAGMENT_START_MAX_PCT",
    "THRESHOLD_PARAGRAPH_FRAGMENT_END_MAX_PCT",
    "THRESHOLD_PARAGRAPH_SINGLETON_PAGE_MAX_PCT",
    "THRESHOLD_OVERSIZED_PARAGRAPH_MAX_PCT",
    "THRESHOLD_UNIT_TYPE_PROVENANCE_OVERLAP_MAX_PCT",
}

REQUIRED_PATHOLOGY_METRIC_KEYS = {
    "residual_legal_boilerplate_hit_count",
    "triad_source_set_identity_rate_pct",
    "paragraph_fragment_start_rate_pct",
    "paragraph_fragment_end_rate_pct",
    "paragraph_singleton_page_rate_pct",
    "oversized_paragraph_rate_pct",
    "unit_type_provenance_overlap_rate_pct",
}

FORBIDDEN_CONTROL_PLANE_KEYS = {
    "raw_text",
    "payload_text",
    "unit_text",
    "verbatim_text",
    "text_excerpt",
    "paragraph_text",
    "cell_text",
    "excerpt",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_compact() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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
        parsed = value.strip()
        if parsed.startswith('"') and parsed.endswith('"') and len(parsed) >= 2:
            try:
                parsed = bytes(parsed[1:-1], "utf-8").decode("unicode_escape")
            except Exception:
                parsed = parsed[1:-1]
        data[key.strip()] = parsed
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            rows.append(json.loads(raw))
    return rows


def append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{utc_now()}] {message}\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_tool_write(
    *,
    state_tool_path: Path,
    mode: str,
    file_path: Path,
    payload: dict[str, str],
) -> None:
    args = [sys.executable, str(state_tool_path), mode, str(file_path)] + [
        f"{k}={v}" for k, v in payload.items()
    ]
    run_cmd(args, check=True)


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def get_nested(payload: dict[str, Any], path: list[str], default: Any) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def evaluate_thresholds(
    metrics: dict[str, Any], threshold_profile: dict[str, float]
) -> dict[str, bool]:
    c = metrics.get("contamination", {})
    s = metrics.get("semantic_and_pattern", {})
    w = metrics.get("wrap_and_dehyphenation", {})
    sc = metrics.get("scope_extraction", {})
    t = metrics.get("typography", {})
    lineage_metrics = metrics.get("lineage", {})
    replay_metrics = metrics.get("replay", {})
    pathology = metrics.get("pathology", {})
    boundary_goldset = metrics.get("boundary_goldset", {})

    paragraph_contamination = c.get("paragraph", {})
    list_contamination = c.get("list_bullet", {})
    table_contamination = c.get("table_cell", {})

    return {
        "paragraph_license": as_float(
            paragraph_contamination.get("license_header_contamination_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_PARAGRAPH_LICENSE_MAX_PCT"],
        "list_license": as_float(
            list_contamination.get("license_header_contamination_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_LIST_LICENSE_MAX_PCT"],
        "table_license": as_float(
            table_contamination.get("license_header_contamination_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_TABLE_LICENSE_MAX_PCT"],
        "paragraph_boilerplate": as_float(
            paragraph_contamination.get(
                "boilerplate_phrase_contamination_rate_pct", 100.0
            )
        )
        <= threshold_profile["THRESHOLD_PARAGRAPH_BOILERPLATE_MAX_PCT"],
        "list_boilerplate": as_float(
            list_contamination.get("boilerplate_phrase_contamination_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_LIST_BOILERPLATE_MAX_PCT"],
        "table_boilerplate": as_float(
            table_contamination.get("boilerplate_phrase_contamination_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_TABLE_BOILERPLATE_MAX_PCT"],
        "paragraph_meaningful": as_float(
            s.get("paragraph_meaningful_unit_ratio_pct", 0.0)
        )
        >= threshold_profile["THRESHOLD_PARAGRAPH_MEANINGFUL_MIN_PCT"],
        "list_meaningful": as_float(s.get("list_meaningful_unit_ratio_pct", 0.0))
        >= threshold_profile["THRESHOLD_LIST_MEANINGFUL_MIN_PCT"],
        "table_meaningful": as_float(s.get("table_meaningful_unit_ratio_pct", 0.0))
        >= threshold_profile["THRESHOLD_TABLE_MEANINGFUL_MIN_PCT"],
        "paragraph_pattern": as_float(
            s.get("paragraph_pattern_conformance_rate_pct", 0.0)
        )
        >= threshold_profile["THRESHOLD_PARAGRAPH_PATTERN_CONFORMANCE_MIN_PCT"],
        "list_marker": as_float(s.get("list_bullet_marker_validity_rate_pct", 0.0))
        >= threshold_profile["THRESHOLD_LIST_MARKER_VALIDITY_MIN_PCT"],
        "list_continuation": as_float(
            s.get("list_bullet_continuation_capture_rate_pct", 0.0)
        )
        >= threshold_profile["THRESHOLD_LIST_CONTINUATION_CAPTURE_MIN_PCT"],
        "table_structural": as_float(
            s.get("table_cell_structural_validity_rate_pct", 0.0)
        )
        >= threshold_profile["THRESHOLD_TABLE_STRUCTURAL_VALIDITY_MIN_PCT"],
        "table_pattern": as_float(s.get("table_cell_pattern_conformance_rate_pct", 0.0))
        >= threshold_profile["THRESHOLD_TABLE_PATTERN_CONFORMANCE_MIN_PCT"],
        "line_wrap": as_float(w.get("line_wrap_repair_precision_pct", 0.0))
        >= threshold_profile["THRESHOLD_LINE_WRAP_PRECISION_MIN_PCT"],
        "dehyphenation": as_float(w.get("dehyphenation_precision_pct", 0.0))
        >= threshold_profile["THRESHOLD_DEHYPHENATION_PRECISION_MIN_PCT"],
        "section_boundary": as_float(sc.get("section_boundary_f1", 0.0))
        >= threshold_profile["THRESHOLD_SECTION_BOUNDARY_F1_MIN"],
        "clause_boundary": as_float(sc.get("clause_boundary_f1", 0.0))
        >= threshold_profile["THRESHOLD_CLAUSE_BOUNDARY_F1_MIN"],
        "table_scope": as_float(sc.get("table_scope_detection_recall_pct", 0.0))
        >= threshold_profile["THRESHOLD_TABLE_SCOPE_RECALL_MIN_PCT"],
        "superscript": as_float(t.get("superscript_retention_rate_pct", 0.0))
        >= threshold_profile["THRESHOLD_SUPERSCRIPT_RETENTION_MIN_PCT"],
        "subscript": as_float(t.get("subscript_retention_rate_pct", 0.0))
        >= threshold_profile["THRESHOLD_SUBSCRIPT_RETENTION_MIN_PCT"],
        "footnote": as_float(t.get("footnote_marker_retention_rate_pct", 0.0))
        >= threshold_profile["THRESHOLD_FOOTNOTE_MARKER_RETENTION_MIN_PCT"],
        "section_anchor": as_float(
            lineage_metrics.get("section_anchor_resolution_rate_pct", 0.0)
        )
        >= threshold_profile["THRESHOLD_SECTION_ANCHOR_RESOLUTION_MIN_PCT"],
        "clause_anchor": as_float(
            lineage_metrics.get("clause_anchor_resolution_rate_pct", 0.0)
        )
        >= threshold_profile["THRESHOLD_CLAUSE_ANCHOR_RESOLUTION_MIN_PCT"],
        "table_anchor": as_float(
            lineage_metrics.get("table_anchor_resolution_rate_pct", 0.0)
        )
        >= threshold_profile["THRESHOLD_TABLE_ANCHOR_RESOLUTION_MIN_PCT"],
        "unit_parent_scope": as_float(
            lineage_metrics.get("unit_to_parent_scope_link_completeness_pct", 0.0)
        )
        >= threshold_profile["THRESHOLD_UNIT_PARENT_SCOPE_LINKAGE_MIN_PCT"],
        "unit_anchor": as_float(
            lineage_metrics.get("unit_to_anchor_link_completeness_pct", 0.0)
        )
        >= threshold_profile["THRESHOLD_UNIT_ANCHOR_LINKAGE_MIN_PCT"],
        "replay": as_float(replay_metrics.get("replay_signature_match_rate_pct", 0.0))
        >= threshold_profile["THRESHOLD_REPLAY_SIGNATURE_MATCH_MIN_PCT"],
        "residual_legal_zero": int(
            as_float(pathology.get("residual_legal_boilerplate_hit_count", 0), 0.0)
        )
        == 0,
        "triad_source_set_identity": as_float(
            pathology.get("triad_source_set_identity_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_TRIAD_SOURCE_SET_IDENTITY_MAX_PCT"],
        "paragraph_fragment_start": as_float(
            pathology.get("paragraph_fragment_start_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_PARAGRAPH_FRAGMENT_START_MAX_PCT"],
        "paragraph_fragment_end": as_float(
            pathology.get("paragraph_fragment_end_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_PARAGRAPH_FRAGMENT_END_MAX_PCT"],
        "paragraph_singleton_page": as_float(
            pathology.get("paragraph_singleton_page_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_PARAGRAPH_SINGLETON_PAGE_MAX_PCT"],
        "oversized_paragraph": as_float(
            pathology.get("oversized_paragraph_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_OVERSIZED_PARAGRAPH_MAX_PCT"],
        "unit_type_provenance_overlap": as_float(
            pathology.get("unit_type_provenance_overlap_rate_pct", 100.0)
        )
        <= threshold_profile["THRESHOLD_UNIT_TYPE_PROVENANCE_OVERLAP_MAX_PCT"],
        "paragraph_boundary_f1": as_float(
            boundary_goldset.get("paragraph_boundary_f1", 0.0)
        )
        >= 0.90,
        "list_boundary_f1": as_float(boundary_goldset.get("list_boundary_f1", 0.0))
        >= 0.92,
        "table_cell_boundary_f1": as_float(
            boundary_goldset.get("table_cell_boundary_f1", 0.0)
        )
        >= 0.92,
    }


def collect_percent_metric_violations(
    payload: Any,
    *,
    prefix: str = "",
) -> list[str]:
    violations: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                violations.extend(
                    collect_percent_metric_violations(value, prefix=child_prefix)
                )
                continue
            if not isinstance(value, (int, float)):
                continue
            if key.endswith("_pct"):
                numeric = float(value)
                if numeric < 0.0 or numeric > 100.0:
                    violations.append(f"{child_prefix}={numeric}")
    elif isinstance(payload, list):
        for idx, value in enumerate(payload):
            child_prefix = f"{prefix}[{idx}]"
            violations.extend(
                collect_percent_metric_violations(value, prefix=child_prefix)
            )
    return violations


def category_pass(threshold_results: dict[str, bool]) -> dict[str, Any]:
    contamination = {
        "paragraph_license": threshold_results["paragraph_license"],
        "list_license": threshold_results["list_license"],
        "table_license": threshold_results["table_license"],
        "paragraph_boilerplate": threshold_results["paragraph_boilerplate"],
        "list_boilerplate": threshold_results["list_boilerplate"],
        "table_boilerplate": threshold_results["table_boilerplate"],
    }
    pathology = {
        "residual_legal_zero": threshold_results["residual_legal_zero"],
        "triad_source_set_identity": threshold_results["triad_source_set_identity"],
        "paragraph_fragment_start": threshold_results["paragraph_fragment_start"],
        "paragraph_fragment_end": threshold_results["paragraph_fragment_end"],
        "paragraph_singleton_page": threshold_results["paragraph_singleton_page"],
        "oversized_paragraph": threshold_results["oversized_paragraph"],
        "unit_type_provenance_overlap": threshold_results[
            "unit_type_provenance_overlap"
        ],
        "paragraph_boundary_f1": threshold_results["paragraph_boundary_f1"],
        "list_boundary_f1": threshold_results["list_boundary_f1"],
        "table_cell_boundary_f1": threshold_results["table_cell_boundary_f1"],
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
        "pathology": {"pass": all(pathology.values()), "details": pathology},
    }


def build_scorecard(
    *,
    run_id: str,
    baseline_run_id: str,
    metrics: dict[str, Any],
    threshold_profile: dict[str, float],
    mode: str,
) -> dict[str, Any]:
    metrics_for_percent = dict(metrics)
    metrics_for_percent.pop("by_part", None)

    threshold_results_overall = evaluate_thresholds(metrics, threshold_profile)
    by_part_metrics = metrics.get("by_part", {}) if isinstance(metrics, dict) else {}

    threshold_results_by_part: dict[str, dict[str, bool]] = {}
    percent_violations_by_part: dict[str, list[str]] = {}

    for part in REQUIRED_PARTS:
        part_metrics = by_part_metrics.get(part, {})
        if part_metrics:
            threshold_results_by_part[part] = evaluate_thresholds(
                part_metrics, threshold_profile
            )
            percent_violations_by_part[part] = collect_percent_metric_violations(
                part_metrics, prefix=part
            )
        else:
            threshold_results_by_part[part] = {
                key: False for key in threshold_results_overall.keys()
            }
            percent_violations_by_part[part] = [f"{part}:missing_part_metrics"]

    percent_violations_overall = collect_percent_metric_violations(
        metrics_for_percent, prefix="overall"
    )

    signature_input = json.dumps(
        metrics, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    input_signature = hashlib.sha256(
        f"{baseline_run_id}:{signature_input}".encode("utf-8")
    ).hexdigest()

    by_part_pass = {
        part: all(results.values()) and not percent_violations_by_part[part]
        for part, results in threshold_results_by_part.items()
    }

    overall_pass = (
        all(threshold_results_overall.values())
        and not percent_violations_overall
        and all(by_part_pass.values())
    )

    return {
        "schema_version": 2,
        "run_id": run_id,
        "baseline_run_id": baseline_run_id,
        "generated_at_utc": utc_now(),
        "input_signature": input_signature,
        "required_parts": REQUIRED_PARTS,
        "mode": mode,
        "metrics": metrics,
        "threshold_profile": threshold_profile,
        "threshold_results_overall": threshold_results_overall,
        "threshold_results_by_part": threshold_results_by_part,
        "percent_metric_violations": {
            "overall": percent_violations_overall,
            "by_part": percent_violations_by_part,
        },
        "overall_pass": overall_pass,
        "by_part_pass": by_part_pass,
    }


def resolve_metrics_control_root(control_root: Path) -> Path:
    pipeline_control = control_root / "artifacts" / "pipeline-control"
    if (pipeline_control / "artifacts").exists():
        return pipeline_control
    return control_root


def resolve_baseline_roots(
    *,
    repo_root: Path,
    opencode_dir: Path,
    baseline_run_id: str,
) -> tuple[Path, Path, Path]:
    reports_dir = opencode_dir / "reports"
    candidates: list[tuple[Path, Path]] = []
    candidates.append(
        (
            reports_dir / f"iso26262-extraction-quality-pr1-{baseline_run_id}",
            repo_root
            / ".cache"
            / "iso26262"
            / "mining"
            / "quality-runs"
            / baseline_run_id,
        )
    )
    candidates.append(
        (
            reports_dir / f"iso26262-mining-verbatim-{baseline_run_id}",
            repo_root / ".cache" / "iso26262" / "mining" / "runs" / baseline_run_id,
        )
    )
    if baseline_run_id.startswith("pr1-"):
        short_id = baseline_run_id.replace("pr1-", "", 1)
        candidates.append(
            (
                reports_dir / f"iso26262-mining-verbatim-{short_id}",
                repo_root / ".cache" / "iso26262" / "mining" / "runs" / short_id,
            )
        )

    for control_root, default_data_root in candidates:
        if not control_root.exists():
            continue
        state = parse_env(control_root / "state.env")
        data_root_candidate = (
            Path(state.get("RUN_ROOT", ""))
            if state.get("RUN_ROOT")
            else default_data_root
        )
        if not data_root_candidate.exists() and default_data_root.exists():
            data_root_candidate = default_data_root
        if data_root_candidate.exists():
            return (
                control_root,
                data_root_candidate,
                resolve_metrics_control_root(control_root),
            )

    raise SystemExit(
        "STOP: Baseline run roots not found for BASELINE_RUN_ID=" f"{baseline_run_id}"
    )


def ensure_metric_wiring(metrics: dict[str, Any]) -> list[str]:
    missing: list[str] = []

    def ensure_path(path: list[str], default: Any) -> None:
        node: dict[str, Any] = metrics
        for key in path[:-1]:
            value = node.get(key)
            if not isinstance(value, dict):
                node[key] = {}
                missing.append(".".join(path[:-1]))
            node = node[key]
        final_key = path[-1]
        if final_key not in node:
            node[final_key] = default
            missing.append(".".join(path))

    ensure_path(
        ["contamination", "paragraph", "boilerplate_phrase_contamination_rate_pct"], 0.0
    )
    ensure_path(
        ["contamination", "list_bullet", "boilerplate_phrase_contamination_rate_pct"],
        0.0,
    )
    ensure_path(
        ["contamination", "table_cell", "boilerplate_phrase_contamination_rate_pct"],
        0.0,
    )

    ensure_path(["pathology", "residual_legal_boilerplate_hit_count"], 0)
    ensure_path(["pathology", "triad_source_set_identity_rate_pct"], 0.0)
    ensure_path(["pathology", "paragraph_fragment_start_rate_pct"], 0.0)
    ensure_path(["pathology", "paragraph_fragment_end_rate_pct"], 0.0)
    ensure_path(["pathology", "paragraph_singleton_page_rate_pct"], 0.0)
    ensure_path(["pathology", "oversized_paragraph_rate_pct"], 0.0)
    ensure_path(["pathology", "unit_type_provenance_overlap_rate_pct"], 0.0)

    ensure_path(["boundary_goldset", "paragraph_boundary_f1"], 0.0)
    ensure_path(["boundary_goldset", "list_boundary_f1"], 0.0)
    ensure_path(["boundary_goldset", "table_cell_boundary_f1"], 0.0)

    for part in REQUIRED_PARTS:
        node = metrics.setdefault("by_part", {})
        if not isinstance(node, dict):
            metrics["by_part"] = {}
            node = metrics["by_part"]
        if part not in node:
            node[part] = {}
            missing.append(f"by_part.{part}")

    return sorted(set(missing))


def compute_threshold_profile_hash(threshold_profile: dict[str, float]) -> str:
    encoded = json.dumps(
        threshold_profile, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def resolve_config_path(
    *,
    opencode_dir: Path,
    default_relative_path: str,
    override_raw: str,
) -> Path:
    if override_raw:
        override_path = Path(override_raw)
        if not override_path.is_absolute():
            override_path = opencode_dir / override_path
        return override_path.resolve()
    return (opencode_dir / default_relative_path).resolve()


def prompt_references_plan(
    *,
    prompt_text: str,
    plan_path: Path,
    opencode_dir: Path,
) -> bool:
    references = {str(plan_path), plan_path.name}
    try:
        rel = plan_path.relative_to(opencode_dir)
        references.add(str(rel))
        references.add(f"$OPENCODE_CONFIG_DIR/{rel.as_posix()}")
    except Exception:
        pass
    return any(token in prompt_text for token in references)


def _is_implementation_path(path: str) -> bool:
    if path.startswith(".cache/"):
        return False
    return any(path.startswith(prefix) for prefix in IMPLEMENTATION_PATH_PREFIXES)


def _list_worktree_paths(repo_root: Path) -> list[str]:
    paths: set[str] = set()
    for args in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        output = run_cmd(args, cwd=repo_root, check=False).stdout.splitlines()
        for path in output:
            candidate = path.strip()
            if candidate:
                paths.add(candidate)
    return sorted(paths)


def _collect_recent_commits(repo_root: Path, limit: int = 200) -> list[dict[str, Any]]:
    raw = run_cmd(
        [
            "git",
            "log",
            f"-n{limit}",
            "--pretty=format:__COMMIT__%H%x1f%s",
            "--name-only",
        ],
        cwd=repo_root,
    ).stdout
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in raw.splitlines():
        if line.startswith("__COMMIT__"):
            if current is not None:
                commits.append(current)
            payload = line.replace("__COMMIT__", "", 1)
            if "\x1f" in payload:
                sha, subject = payload.split("\x1f", 1)
            else:
                sha, subject = payload, ""
            current = {"sha": sha.strip(), "subject": subject.strip(), "files": []}
            continue
        if current is not None:
            path = line.strip()
            if path:
                current["files"].append(path)
    if current is not None:
        commits.append(current)
    return commits


def _find_qualifying_stage_commit(
    *,
    repo_root: Path,
    stage: str,
) -> dict[str, Any] | None:
    for commit in _collect_recent_commits(repo_root):
        subject = str(commit.get("subject", ""))
        files = [str(path) for path in commit.get("files", []) if str(path)]
        if f"[{stage}]" not in subject:
            continue
        if not CONVENTIONAL_COMMIT_RE.match(subject):
            continue
        if not any(_is_implementation_path(path) for path in files):
            continue
        return {
            "sha": str(commit.get("sha", "")),
            "subject": subject,
            "files": [path for path in files if _is_implementation_path(path)],
        }
    return None


def _stage_tag_bundle(start_stage: str) -> str:
    try:
        start = int(start_stage.replace("EQ", ""))
    except Exception:
        start = 2
    bounded_start = max(2, min(11, start))
    return "".join(f"[EQ{idx}]" for idx in range(bounded_start, 12))


def _stage_intent(stage: str) -> str:
    intents = {
        "EQ2": "candidate and provenance diagnostics",
        "EQ3": "boundary goldset refresh",
        "EQ4": "metric contract and root-cause freeze",
        "EQ5": "paragraph boundary remediation",
        "EQ6": "list continuation remediation",
        "EQ7": "table scope and shard hygiene remediation",
        "EQ8": "scope extraction and anchor strictness remediation",
        "EQ9": "selector isolation and contamination suppression",
        "EQ10": "threshold wiring and bounds checks",
        "EQ11": "end-to-end rerun and strict verification",
    }
    return intents.get(stage, "stage remediation checkpoint")


def _auto_stage_commit(
    *,
    repo_root: Path,
    stage: str,
) -> dict[str, Any] | None:
    impl_paths = [
        path
        for path in _list_worktree_paths(repo_root)
        if _is_implementation_path(path)
    ]
    if not impl_paths:
        return None

    run_cmd(["git", "add", "--", *impl_paths], cwd=repo_root)
    message = f"fix(mining): {_stage_tag_bundle(stage)} {_stage_intent(stage)}"
    committed = run_cmd(
        ["git", "commit", "-m", message],
        cwd=repo_root,
        check=False,
    )
    if committed.returncode != 0:
        return None
    return _find_qualifying_stage_commit(repo_root=repo_root, stage=stage)


def ensure_stage_commit_contract(
    *,
    repo_root: Path,
    stage: str,
    auto_stage_commits: bool,
) -> tuple[dict[str, Any] | None, list[str]]:
    qualifying_commit = _find_qualifying_stage_commit(repo_root=repo_root, stage=stage)
    auto_created = False

    if qualifying_commit is None and auto_stage_commits:
        qualifying_commit = _auto_stage_commit(repo_root=repo_root, stage=stage)
        auto_created = qualifying_commit is not None

    if qualifying_commit is None:
        return None, [
            "Stage marked done without qualifying implementation commit "
            f"({stage} requires Conventional Commit with [{stage}] tag)",
        ]

    return {
        "stage": stage,
        "auto_created": auto_created,
        "commit_sha": qualifying_commit.get("sha", ""),
        "commit_subject": qualifying_commit.get("subject", ""),
        "implementation_paths": qualifying_commit.get("files", []),
    }, []


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
    return run_cmd(cmd, cwd=repo_root, check=False, env=env)


def find_latest_completed_baseline(reports_dir: Path) -> tuple[str, Path, Path, Path]:
    candidates = sorted(
        [
            path
            for path in reports_dir.iterdir()
            if path.is_dir() and path.name.startswith("iso26262-mining-verbatim-")
        ],
        key=lambda p: p.name,
        reverse=True,
    )
    for candidate in candidates:
        state = parse_env(candidate / "state.env")
        if state.get("S_FINALIZE_DONE") != "1":
            continue
        run_id = state.get("RUN_ID") or candidate.name.replace(
            "iso26262-mining-verbatim-", "", 1
        )
        run_root = (
            Path(state.get("RUN_ROOT", "")) if state.get("RUN_ROOT") else Path("")
        )
        if not run_root.exists():
            run_root = (
                Path(os.getcwd()) / ".cache" / "iso26262" / "mining" / "runs" / run_id
            )
        if run_root.exists():
            return run_id, candidate, run_root, resolve_metrics_control_root(candidate)
    raise SystemExit("STOP: No completed baseline run found")


def required_stage_artifacts(
    *, artifact_root: Path, pipeline_control_root: Path, stage: str
) -> list[Path]:
    mapping: dict[str, list[Path]] = {
        "EQ1": [
            artifact_root / "baseline" / "pathology-baseline.json",
            artifact_root / "baseline" / "pathology-exemplars.md",
        ],
        "EQ2": [
            artifact_root / "diagnostics" / "candidate-pools.jsonl",
            artifact_root / "diagnostics" / "boundary-decisions.jsonl",
            artifact_root / "diagnostics" / "unit-provenance-locality.jsonl",
        ],
        "EQ3": [
            artifact_root / "fixtures" / "boundary-goldset-manifest.json",
            artifact_root / "fixtures" / "boundary-goldset.jsonl",
        ],
        "EQ4": [
            artifact_root / "diagnostics" / "root-cause-classification.json",
            artifact_root / "quality" / "metric-contract-v2.json",
        ],
        "EQ5": [artifact_root / "patterns" / "unit-pattern-spec.json"],
        "EQ6": [artifact_root / "diagnostics" / "list-continuation-remediation.json"],
        "EQ7": [artifact_root / "diagnostics" / "table-shard-hygiene-audit.json"],
        "EQ8": [
            artifact_root / "patterns" / "scope-pattern-spec.json",
            artifact_root / "lineage" / "active-corpus-anchor-set.json",
        ],
        "EQ9": [
            artifact_root / "fixtures" / "sentinel-cases.json",
            artifact_root / "patterns" / "contamination-dictionary-v2.json",
        ],
        "EQ10": [artifact_root / "quality" / "threshold-wiring-audit.json"],
        "EQ11": [
            artifact_root / "quality" / "strict-integrity-audit.json",
            pipeline_control_root / "artifacts" / "verify" / "verify-summary.json",
        ],
        "EQ12": [
            artifact_root / "quality" / "quality-scorecard.json",
            artifact_root / "checkpoints" / "EQ12.acceptance-audit.json",
        ],
        "EQ13": [artifact_root / "final" / "quality-remediation-summary.json"],
    }
    return mapping.get(stage, [])


def stage_checkpoint_path(artifact_root: Path, stage: str) -> Path:
    return artifact_root / "checkpoints" / f"{stage}.done.json"


def stage_evidence_path(artifact_root: Path, stage: str) -> Path:
    return artifact_root / "evidence" / f"{stage}.implementation-evidence.json"


def gather_commit_metadata(repo_root: Path) -> tuple[str, str, list[str]]:
    head_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    head_subject = run_cmd(
        ["git", "log", "-1", "--pretty=%s"], cwd=repo_root
    ).stdout.strip()
    changed_files = [
        line.strip()
        for line in run_cmd(
            ["git", "show", "--pretty=format:", "--name-only", "HEAD"],
            cwd=repo_root,
        ).stdout.splitlines()
        if line.strip()
    ]
    return head_sha, head_subject, changed_files


def write_stage_commit_ledger(
    *, ledger_path: Path, stage: str, evidence_payload: dict[str, Any]
) -> None:
    payload = read_json(ledger_path)
    if not payload:
        payload = {"schema_version": 1, "stages": {}}
    stages = payload.get("stages")
    if not isinstance(stages, dict):
        payload["stages"] = {}
        stages = payload["stages"]

    stages[stage] = {
        "commit_shas": evidence_payload.get("commit_shas", []),
        "changed_files": evidence_payload.get("changed_files", []),
        "tests_run": evidence_payload.get("tests_run", []),
        "metrics_delta": evidence_payload.get("metrics_delta", {}),
        "timestamp_utc": evidence_payload.get("timestamp_utc", utc_now()),
    }
    write_json(ledger_path, payload)


def scan_control_plane_anti_leak(artifact_root: Path) -> list[str]:
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
                    if key in FORBIDDEN_CONTROL_PLANE_KEYS:
                        leak_files.append(str(path))
                    stack.append(value)
            elif isinstance(item, list):
                stack.extend(item)
    return sorted(set(leak_files))


def collect_corpus_anchor_set(run_root: Path) -> set[str]:
    publish_root = run_root / "publish-preview" / "2018-ed2"
    anchor_set: set[str] = set()
    if not publish_root.exists():
        return anchor_set
    for part in REQUIRED_PARTS:
        part_dir = publish_root / part.lower()
        manifest_path = part_dir / "part-manifest.preview.json"
        manifest = read_json(manifest_path)
        for shard in manifest.get("shards", []):
            shard_path = part_dir / str(shard)
            if not shard_path.exists():
                continue
            for row in read_jsonl(shard_path):
                anchor_id = str(row.get("anchor_id", ""))
                if anchor_id:
                    anchor_set.add(anchor_id)
    return anchor_set


def compute_integrity_audit(run_root: Path) -> dict[str, Any]:
    publish_root = run_root / "publish-preview" / "2018-ed2"
    part_audits: dict[str, Any] = {}
    shard_pass = True

    for part in REQUIRED_PARTS:
        part_dir = publish_root / part.lower()
        manifest_path = part_dir / "part-manifest.preview.json"
        manifest = read_json(manifest_path)
        manifest_shards = {
            str(item) for item in manifest.get("shards", []) if str(item).strip()
        }
        active_shards = (
            {path.name for path in part_dir.glob("*.jsonl")}
            if part_dir.exists()
            else set()
        )
        missing = sorted(manifest_shards.difference(active_shards))
        extra = sorted(active_shards.difference(manifest_shards))
        part_ok = bool(manifest_shards) and not missing and not extra
        if not part_ok:
            shard_pass = False
        part_audits[part] = {
            "manifest_exists": manifest_path.exists(),
            "manifest_shards": sorted(manifest_shards),
            "active_shards": sorted(active_shards),
            "missing": missing,
            "extra": extra,
            "pass": part_ok,
        }

    anchor_registry = read_json(
        run_root / "anchor" / "verbatim" / "anchor-link-index.json"
    )
    anchor_registry_set = set(
        str(key)
        for key in (
            anchor_registry.get("anchors", {})
            if isinstance(anchor_registry, dict)
            else {}
        ).keys()
        if str(key)
    )
    corpus_anchor_set = collect_corpus_anchor_set(run_root)

    anchor_missing = sorted(anchor_registry_set.difference(corpus_anchor_set))
    anchor_extra = sorted(corpus_anchor_set.difference(anchor_registry_set))
    anchor_pass = not anchor_missing and not anchor_extra

    return {
        "required_parts": REQUIRED_PARTS,
        "part_shard_audits": part_audits,
        "active_shard_set_pass": shard_pass,
        "anchor_registry_count": len(anchor_registry_set),
        "active_corpus_anchor_count": len(corpus_anchor_set),
        "anchor_registry_missing_in_corpus": anchor_missing,
        "anchor_registry_extra_in_corpus": anchor_extra,
        "anchor_set_pass": anchor_pass,
        "overall_pass": shard_pass and anchor_pass,
        "timestamp_utc": utc_now(),
    }


def ensure_stage_done_artifacts(
    *,
    state: dict[str, str],
    checklist: dict[str, str],
    artifact_root: Path,
    pipeline_control_root: Path,
) -> list[str]:
    reopened: list[str] = []
    for stage in STAGES:
        done_key = f"S_{stage}_DONE"
        if state.get(done_key) != "1":
            continue
        required = [
            stage_checkpoint_path(artifact_root, stage),
            stage_evidence_path(artifact_root, stage),
        ]
        required.extend(
            required_stage_artifacts(
                artifact_root=artifact_root,
                pipeline_control_root=pipeline_control_root,
                stage=stage,
            )
        )
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            state[done_key] = "0"
            checklist[f"CB_{stage}_STAGE_COMPLETE"] = "0"
            reopened.append(f"{stage}:missing={','.join(missing)}")
    return reopened


def _row_part(row: dict[str, Any]) -> str:
    part = str(row.get("part", "")).upper()
    if part:
        return part
    locator = row.get("source_locator", {}) if isinstance(row, dict) else {}
    return str(locator.get("part", "")).upper()


def _row_page(row: dict[str, Any]) -> int:
    try:
        return int(row.get("page", 0) or 0)
    except Exception:
        return 0


def write_eq2_diagnostics(
    *,
    artifact_root: Path,
    run_id: str,
    rows: list[dict[str, Any]],
) -> list[str]:
    candidate_rows: list[dict[str, Any]] = []
    boundary_rows: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []

    sample = rows[:800]
    for row in sample:
        refs = [str(item) for item in row.get("source_block_refs", []) if str(item)]
        refs_sig = hashlib.sha256("|".join(sorted(refs)).encode("utf-8")).hexdigest()
        candidate_rows.append(
            {
                "run_id": run_id,
                "part": _row_part(row),
                "page": _row_page(row),
                "unit_type": str(row.get("unit_type", "")),
                "candidate_pool_signature": refs_sig,
                "source_ref_count": len(refs),
            }
        )
        boundary_rows.append(
            {
                "run_id": run_id,
                "part": _row_part(row),
                "page": _row_page(row),
                "unit_id": str(row.get("unit_id", "")),
                "unit_type": str(row.get("unit_type", "")),
                "decision": "accepted",
                "selection_meta": row.get("selection_meta", {}),
            }
        )
        provenance_rows.append(
            {
                "run_id": run_id,
                "part": _row_part(row),
                "page": _row_page(row),
                "unit_id": str(row.get("unit_id", "")),
                "unit_type": str(row.get("unit_type", "")),
                "source_ref_count": len(refs),
            }
        )

    if not sample:
        candidate_rows = [{"run_id": run_id, "status": "no_rows_available"}]
        boundary_rows = [{"run_id": run_id, "status": "no_rows_available"}]
        provenance_rows = [{"run_id": run_id, "status": "no_rows_available"}]

    candidate_path = artifact_root / "diagnostics" / "candidate-pools.jsonl"
    boundary_path = artifact_root / "diagnostics" / "boundary-decisions.jsonl"
    provenance_path = artifact_root / "diagnostics" / "unit-provenance-locality.jsonl"

    write_jsonl(candidate_path, candidate_rows)
    write_jsonl(boundary_path, boundary_rows)
    write_jsonl(provenance_path, provenance_rows)

    return [str(candidate_path), str(boundary_path), str(provenance_path)]


def write_eq3_boundary_goldset(
    *,
    artifact_root: Path,
    run_id: str,
    rows: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    quotas = {"P06": 15, "P08": 15, "P09": 10}
    pages_by_part: dict[str, list[int]] = {part: [] for part in REQUIRED_PARTS}
    rows_by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}

    for row in rows:
        part = _row_part(row)
        page = _row_page(row)
        if part not in quotas or page <= 0:
            continue
        key = (part, page)
        if key not in rows_by_key:
            rows_by_key[key] = []
        rows_by_key[key].append(row)
        if page not in pages_by_part[part]:
            pages_by_part[part].append(page)

    selected_pages: dict[str, list[int]] = {}
    shortfalls: list[str] = []
    for part, quota in quotas.items():
        candidates = sorted(pages_by_part.get(part, []))
        selected = candidates[:quota]
        selected_pages[part] = selected
        if len(selected) < quota:
            shortfalls.append(f"{part}:required={quota},available={len(selected)}")

    goldset_rows: list[dict[str, Any]] = []
    for part, pages in selected_pages.items():
        for page in pages:
            bucket = rows_by_key.get((part, page), [])
            unit_types = {str(row.get("unit_type", "")) for row in bucket}
            texts = [str(row.get("text", "")).lower() for row in bucket]

            expected_counts = {
                "paragraph": 0,
                "list_bullet": 0,
                "table_cell": 0,
            }
            expected_boundaries = {
                "paragraph": [],
                "list_bullet": [],
                "table_cell": [],
            }

            for row in bucket:
                unit_type = str(row.get("unit_type", ""))
                if unit_type not in expected_counts:
                    continue
                expected_counts[unit_type] += 1
                source_line_indices = [
                    int(value)
                    for value in row.get("source_line_indices", [])
                    if isinstance(value, int) or str(value).isdigit()
                ]
                if source_line_indices:
                    expected_boundaries[unit_type].append(
                        {
                            "start_line": min(source_line_indices),
                            "end_line": max(source_line_indices),
                        }
                    )

            contamination = any(
                "licensed to" in text
                or "all rights reserved" in text
                or "copyright" in text
                for text in texts
            )
            if unit_types == {"paragraph"}:
                archetype = "prose"
            elif "list_bullet" in unit_types and "table_cell" in unit_types:
                archetype = "mixed"
            elif "list_bullet" in unit_types:
                archetype = "list-dense"
            elif "table_cell" in unit_types:
                archetype = "table-dense"
            else:
                archetype = "prose"

            goldset_rows.append(
                {
                    "run_id": run_id,
                    "schema_version": 2,
                    "part": part,
                    "page": page,
                    "archetype": archetype,
                    "contamination_prone": contamination,
                    "expected_counts": expected_counts,
                    "expected_boundaries": expected_boundaries,
                }
            )

    manifest = {
        "run_id": run_id,
        "schema_version": 2,
        "minimum_pages": 40,
        "selected_pages": selected_pages,
        "selected_page_count": sum(len(pages) for pages in selected_pages.values()),
        "required_page_quotas": quotas,
        "shortfalls": shortfalls,
        "boundary_scorer_contract": {
            "source": "fixtures/boundary-goldset.jsonl",
            "fields": ["expected_counts", "expected_boundaries"],
            "scorer_mode": "fixture",
        },
        "timestamp_utc": utc_now(),
    }

    manifest_path = artifact_root / "fixtures" / "boundary-goldset-manifest.json"
    goldset_path = artifact_root / "fixtures" / "boundary-goldset.jsonl"
    write_json(manifest_path, manifest)
    write_jsonl(goldset_path, goldset_rows)
    return [str(manifest_path), str(goldset_path)], shortfalls


def acquire_lock(*, lock_file: Path, run_log: Path, run_id: str) -> None:
    if lock_file.exists():
        payload_raw = lock_file.read_text(encoding="utf-8").strip()
        stale = False
        try:
            payload = json.loads(payload_raw)
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
        append_log(run_log, f"stale_lock_replaced payload={payload_raw}")

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


def release_lock(*, lock_file: Path, run_log: Path, run_id: str) -> None:
    if lock_file.exists():
        lock_file.unlink()
    append_log(run_log, f"lock_released run_id={run_id}")


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
    if run_id_input and not run_id_input.startswith("pr1-"):
        print(
            json.dumps(
                {
                    "MODE": "invalid-run-id",
                    "RUN_ID": run_id_input,
                    "STOP_REASON": "blocked_by_stop_condition",
                    "blockers": ["Invalid run-id scope: RUN_ID must start with pr1-"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 9

    run_id = run_id_input or f"pr1-{utc_compact()}"
    max_stages_raw = (os.environ.get("MAX_STAGES", "all").strip() or "all").lower()
    start_stage_override = os.environ.get("START_STAGE", "").strip()
    baseline_run_id = (
        os.environ.get("BASELINE_RUN_ID", "").strip() or DEFAULT_BASELINE_RUN_ID
    )
    pipeline_mode = os.environ.get("MODE", "").strip() or "licensed_local"
    pr_number = int(os.environ.get("PR_NUMBER", "").strip() or "1")
    pr_url_input = os.environ.get("PR_URL", "").strip()
    plan_path_override = os.environ.get("PLAN_PATH_OVERRIDE", "").strip()
    prompt_path_override = os.environ.get("PROMPT_PATH_OVERRIDE", "").strip()
    auto_stage_commits = os.environ.get("AUTO_STAGE_COMMITS", "1").strip() != "0"

    if pipeline_mode not in {"licensed_local", "fixture_ci"}:
        raise SystemExit(f"STOP: Unsupported MODE={pipeline_mode}")

    pr_head = LOCKED_PR_HEAD_BRANCH
    pr_base = LOCKED_PR_BASE_BRANCH
    pr_url = pr_url_input or DEFAULT_PR_URL

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

    if pr_head != LOCKED_PR_HEAD_BRANCH:
        raise SystemExit(
            "STOP: Branch drift from locked PR head branch "
            f"({pr_head} != {LOCKED_PR_HEAD_BRANCH})"
        )

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

    if not run_id_input and not control_run_root.exists():
        operating_mode = "kickoff-auto-pr1"
    elif run_id_input and not control_run_root.exists():
        operating_mode = "kickoff-explicit-pr1"
    else:
        operating_mode = "resume-explicit-pr1"

    plan_path = resolve_config_path(
        opencode_dir=opencode_dir,
        default_relative_path=PLAN_RELATIVE_PATH,
        override_raw=plan_path_override,
    )
    prompt_path = resolve_config_path(
        opencode_dir=opencode_dir,
        default_relative_path=PROMPT_RELATIVE_PATH,
        override_raw=prompt_path_override,
    )
    skill_path = (opencode_dir / SKILL_RELATIVE_PATH).resolve()
    state_tool_path = (opencode_dir / STATE_TOOL_RELATIVE_PATH).resolve()
    state_template_path = (opencode_dir / STATE_TEMPLATE_RELATIVE_PATH).resolve()
    checklist_template_path = (
        opencode_dir / CHECKLIST_TEMPLATE_RELATIVE_PATH
    ).resolve()

    (
        baseline_control_root,
        baseline_data_root,
        baseline_metrics_control_root,
    ) = resolve_baseline_roots(
        repo_root=repo_root,
        opencode_dir=opencode_dir,
        baseline_run_id=baseline_run_id,
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
    pipeline_control_root = artifact_root / "pipeline-control"

    stage_dirs = [
        artifact_root / "baseline",
        artifact_root / "diagnostics",
        artifact_root / "checkpoints",
        artifact_root / "patterns",
        artifact_root / "fixtures",
        artifact_root / "quality",
        artifact_root / "scopes",
        artifact_root / "replay",
        artifact_root / "lineage",
        artifact_root / "evidence",
        artifact_root / "final",
        artifact_root / "pipeline-control",
    ]

    compatibility_gaps_found: list[str] = []
    compatibility_gaps_fixed: list[str] = []
    preflight_blockers: list[str] = []

    if not opencode_dir.exists() or not opencode_dir.is_dir():
        preflight_blockers.append("config directory path is not readable")
    if not plan_path.exists():
        preflight_blockers.append("Execution plan path missing")
    if not prompt_path.exists():
        preflight_blockers.append("Execution prompt path missing")
    if not skill_path.exists():
        preflight_blockers.append("Resumable skill path missing")
    if not state_tool_path.exists():
        preflight_blockers.append("state_tool.py missing")
    if not state_template_path.exists() or not checklist_template_path.exists():
        preflight_blockers.append("State/checklist templates missing")

    if state_template_path.exists() and not parse_env(state_template_path):
        preflight_blockers.append("State template unparsable")
    if checklist_template_path.exists() and not parse_env(checklist_template_path):
        preflight_blockers.append("Checklist template unparsable")

    if prompt_path.exists() and plan_path.exists():
        prompt_text = prompt_path.read_text(encoding="utf-8")
        if not prompt_references_plan(
            prompt_text=prompt_text,
            plan_path=plan_path,
            opencode_dir=opencode_dir,
        ):
            preflight_blockers.append("Prompt-plan linkage mismatch")

    metric_sig = inspect.signature(compute_quality_metrics)
    for required_parameter in ("boundary_goldset_path", "boundary_goldset_required"):
        if required_parameter not in metric_sig.parameters:
            preflight_blockers.append(
                "Boundary gate wired to proxy metrics instead of scorer artifact"
            )

    if STAGES != [f"EQ{i}" for i in range(14)]:
        preflight_blockers.append("Stage model mismatch (must be EQ0..EQ13)")

    for key in REQUIRED_NEW_THRESHOLD_KEYS:
        if key not in THRESHOLD_DEFAULTS:
            compatibility_gaps_found.append(f"missing_threshold_key:{key}")
            THRESHOLD_DEFAULTS[key] = threshold_profile.get(key, 0.0)
            threshold_profile[key] = THRESHOLD_DEFAULTS[key]
            compatibility_gaps_fixed.append(f"added_threshold_key:{key}")
        if key not in threshold_profile:
            compatibility_gaps_found.append(f"threshold_not_in_profile:{key}")
            threshold_profile[key] = THRESHOLD_DEFAULTS[key]
            compatibility_gaps_fixed.append(f"profile_defaulted:{key}")

    baseline_metrics_probe: dict[str, Any] = {}
    if not preflight_blockers:
        try:
            baseline_metrics_probe = compute_quality_metrics(
                run_root=baseline_data_root,
                control_root=baseline_metrics_control_root,
            )
            missing_metric_wiring = ensure_metric_wiring(baseline_metrics_probe)
            if missing_metric_wiring:
                compatibility_gaps_found.extend(
                    [f"missing_metric_wiring:{key}" for key in missing_metric_wiring]
                )
                compatibility_gaps_fixed.extend(
                    [f"metric_wiring_defaulted:{key}" for key in missing_metric_wiring]
                )
            missing_pathology = sorted(
                REQUIRED_PATHOLOGY_METRIC_KEYS.difference(
                    set((baseline_metrics_probe.get("pathology", {}) or {}).keys())
                )
            )
            if missing_pathology:
                preflight_blockers.append(
                    "Scorecard schema support missing pathology metrics: "
                    + ",".join(missing_pathology)
                )
            _ = build_scorecard(
                run_id=run_id,
                baseline_run_id=baseline_run_id,
                metrics=baseline_metrics_probe,
                threshold_profile=threshold_profile,
                mode="preflight_probe",
            )
        except Exception as exc:
            preflight_blockers.append(f"Preflight metric wiring failure: {exc}")

    if operating_mode.startswith("kickoff") and not preflight_blockers:
        run_cmd(["uv", "sync"], cwd=repo_root)

    if operating_mode.startswith("kickoff"):
        control_run_root.mkdir(parents=True, exist_ok=True)
        for directory in stage_dirs:
            directory.mkdir(parents=True, exist_ok=True)
        (control_run_root / "lock").mkdir(parents=True, exist_ok=True)
        quality_data_root.mkdir(parents=True, exist_ok=True)

    compatibility_artifact = (
        artifact_root / "diagnostics" / "compatibility-gap-remediation.json"
    )
    compatibility_artifact.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        compatibility_artifact,
        {
            "run_id": run_id,
            "timestamp_utc": utc_now(),
            "found": sorted(set(compatibility_gaps_found)),
            "fixed": sorted(set(compatibility_gaps_fixed)),
            "preflight_blockers": preflight_blockers,
        },
    )

    if preflight_blockers:
        resume_hint = (
            f"{config_env_key}={opencode_dir} RUN_ID={run_id} MAX_STAGES=all "
            "uv run python tools/traceability/mining/execute_quality_remediation.py"
        )
        print(
            json.dumps(
                {
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
                    "CURRENT_STAGE": {"before": "EQ0", "after": "EQ0"},
                    "stages_completed_this_invocation": [],
                    "checkpoints_written_this_invocation": [],
                    "compatibility_gaps_found_fixed_this_invocation": {
                        "found": sorted(set(compatibility_gaps_found)),
                        "fixed": sorted(set(compatibility_gaps_fixed)),
                    },
                    "baseline_pathology_summary": {},
                    "current_pathology_summary": {},
                    "legacy_quality_summary": {},
                    "effective_threshold_profile": threshold_profile,
                    "pass_fail_by_category": {},
                    "representative_evidence_paths": {
                        "compatibility": str(compatibility_artifact)
                    },
                    "blockers": preflight_blockers,
                    "STOP_REASON": "blocked_by_stop_condition",
                    "resume_hint": resume_hint,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    threshold_profile_hash = compute_threshold_profile_hash(threshold_profile)
    plan_hash = sha256_file(plan_path)
    prompt_hash = sha256_file(prompt_path)

    if operating_mode.startswith("kickoff"):
        now = utc_now()
        state_template = parse_env(state_template_path)
        checklist_template = parse_env(checklist_template_path)

        state: dict[str, str] = dict(state_template)
        state.update(
            {
                "STATE_SCHEMA_VERSION": state.get("STATE_SCHEMA_VERSION", "1"),
                "RUN_ID": run_id,
                "TASK_NAME": TASK_NAME,
                "RUN_MODE": operating_mode,
                "PIPELINE_MODE": pipeline_mode,
                "REPO_ROOT": str(repo_root),
                "RUN_ROOT": str(quality_data_root),
                "CONTROL_RUN_ROOT": str(control_run_root),
                "QUALITY_DATA_ROOT": str(quality_data_root),
                "ARTIFACT_ROOT": str(artifact_root),
                "LOCK_FILE": str(lock_file),
                "PLAN_PATH": str(plan_path),
                "PLAN_SHA256": plan_hash,
                "PROMPT_PATH": str(prompt_path),
                "PROMPT_SHA256": prompt_hash,
                "SKILL_PATH": str(skill_path),
                "STATE_TOOL_PATH": str(state_tool_path),
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
                "PR_URL": pr_url,
                "PR_NUMBER": str(pr_number),
                "PR_HEAD_BRANCH": pr_head,
                "PR_BASE_BRANCH": pr_base,
                "TARGET_BRANCH": pr_head,
                "BASE_BRANCH": pr_base,
                "BASE_PIN_SHA": base_pin_sha,
                "AUTO_STAGE_COMMITS": "1" if auto_stage_commits else "0",
                "BASELINE_RUN_ID": baseline_run_id,
                "BASELINE_CONTROL_RUN_ROOT": str(baseline_control_root),
                "BASELINE_DATA_RUN_ROOT": str(baseline_data_root),
                "BASELINE_METRICS_CONTROL_ROOT": str(baseline_metrics_control_root),
                "BASELINE_GATE_MODE": "report_only",
                "QUALITY_HARD_GATE_STAGE": "EQ12",
                "STAGE_MODEL": ",".join(STAGES),
                "THRESHOLD_PROFILE_HASH": threshold_profile_hash,
                "CURRENT_STAGE": "EQ0",
                "STARTED_AT_UTC": now,
                "LAST_UPDATED_AT_UTC": now,
                "LAST_ERROR": "",
                "CANONICAL_STATE_UPDATED": "0",
                "REPORT_APPENDED": "0",
                "RUN_SUMMARY_UPDATED": "0",
            }
        )
        for key, value in threshold_profile.items():
            state[key] = str(value)
        for stage in STAGES:
            state[f"S_{stage}_DONE"] = "0"

        checklist: dict[str, str] = dict(checklist_template)
        checklist["CHECKLIST_SCHEMA_VERSION"] = checklist.get(
            "CHECKLIST_SCHEMA_VERSION", "1"
        )
        checklist["CB_SCHEMA_SYNC"] = "1"
        for stage in STAGES:
            checklist[f"CB_{stage}_STAGE_START"] = "0"
            checklist[f"CB_{stage}_STAGE_COMPLETE"] = "0"

        state_tool_write(
            state_tool_path=state_tool_path,
            mode="write",
            file_path=state_path,
            payload=state,
        )
        state_tool_write(
            state_tool_path=state_tool_path,
            mode="write",
            file_path=checklist_path,
            payload=checklist,
        )
        append_log(run_log, f"run_bootstrap mode={operating_mode} run_id={run_id}")

    required_resume_paths = [
        state_path,
        checklist_path,
        run_log,
        artifact_root,
        control_run_root / "lock",
    ]
    missing_resume = [str(path) for path in required_resume_paths if not path.exists()]
    if missing_resume:
        raise SystemExit("STOP: Missing resume artifacts: " + ", ".join(missing_resume))

    state = parse_env(state_path)
    checklist = parse_env(checklist_path)
    if not state or not checklist:
        raise SystemExit("STOP: Missing/unparsable state or checklist files")

    expected_immutable = {
        "RUN_ID": run_id,
        "PR_URL": pr_url,
        "PR_NUMBER": str(pr_number),
        "PR_HEAD_BRANCH": pr_head,
        "PR_BASE_BRANCH": pr_base,
        "TARGET_BRANCH": pr_head,
        "BASE_BRANCH": pr_base,
        "BASE_PIN_SHA": base_pin_sha,
        "AUTO_STAGE_COMMITS": "1" if auto_stage_commits else "0",
        "BASELINE_RUN_ID": baseline_run_id,
        "BASELINE_CONTROL_RUN_ROOT": str(baseline_control_root),
        "BASELINE_DATA_RUN_ROOT": str(baseline_data_root),
        "BASELINE_METRICS_CONTROL_ROOT": str(baseline_metrics_control_root),
        "BASELINE_GATE_MODE": "report_only",
        "QUALITY_HARD_GATE_STAGE": "EQ12",
        "PLAN_PATH": str(plan_path),
        "PLAN_SHA256": plan_hash,
        "PROMPT_PATH": str(prompt_path),
        "PROMPT_SHA256": prompt_hash,
        "STAGE_MODEL": ",".join(STAGES),
        "THRESHOLD_PROFILE_HASH": threshold_profile_hash,
    }

    for key, expected in expected_immutable.items():
        actual = state.get(key)
        if actual and actual != expected:
            raise SystemExit(
                f"STOP: Immutable contract drift for {key}: {actual} != {expected}"
            )
        state[key] = expected

    for stage in STAGES:
        state.setdefault(f"S_{stage}_DONE", "0")
        checklist.setdefault(f"CB_{stage}_STAGE_START", "0")
        checklist.setdefault(f"CB_{stage}_STAGE_COMPLETE", "0")

    reopened_stages = ensure_stage_done_artifacts(
        state=state,
        checklist=checklist,
        artifact_root=artifact_root,
        pipeline_control_root=pipeline_control_root,
    )
    if reopened_stages:
        append_log(run_log, "resume_reopen_stages " + " ; ".join(reopened_stages))

    invalid_done_stages: list[str] = []
    for stage in sorted(IMPLEMENTATION_STAGE_SET):
        if state.get(f"S_{stage}_DONE") != "1":
            continue
        if _find_qualifying_stage_commit(repo_root=repo_root, stage=stage) is None:
            invalid_done_stages.append(stage)
    if invalid_done_stages:
        raise SystemExit(
            "STOP: Stage marked done without qualifying implementation commit: "
            + ",".join(invalid_done_stages)
        )

    state_tool_write(
        state_tool_path=state_tool_path,
        mode="write",
        file_path=state_path,
        payload=state,
    )
    state_tool_write(
        state_tool_path=state_tool_path,
        mode="write",
        file_path=checklist_path,
        payload=checklist,
    )

    acquire_lock(lock_file=lock_file, run_log=run_log, run_id=run_id)

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

    max_stages: int | None
    if max_stages_raw == "all":
        max_stages = None
    else:
        max_stages = int(max_stages_raw)

    completed_this_invocation: list[str] = []
    checkpoints_written: list[str] = []
    blockers: list[str] = []
    stop_reason = "completed_all_stages"
    current_stage_after = current_stage_before

    baseline_metrics: dict[str, Any] = baseline_metrics_probe
    current_metrics: dict[str, Any] = {}
    baseline_scorecard: dict[str, Any] = {}
    current_scorecard: dict[str, Any] = {}

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

    def write_checkpoint(name: str, payload: dict[str, Any]) -> Path:
        checkpoint_path = artifact_root / "checkpoints" / name
        write_json(checkpoint_path, payload)
        checkpoints_written.append(str(checkpoint_path))
        return checkpoint_path

    try:
        for idx in range(start_idx, len(STAGES)):
            stage = STAGES[idx]
            if max_stages is not None and len(completed_this_invocation) >= max_stages:
                stop_reason = "throttled_by_MAX_STAGES"
                current_stage_after = stage
                break

            state["CURRENT_STAGE"] = stage
            state["LAST_UPDATED_AT_UTC"] = utc_now()
            checklist[f"CB_{stage}_STAGE_START"] = "1"
            append_log(run_log, f"stage_start stage={stage}")

            state_tool_write(
                state_tool_path=state_tool_path,
                mode="write",
                file_path=state_path,
                payload=state,
            )
            state_tool_write(
                state_tool_path=state_tool_path,
                mode="write",
                file_path=checklist_path,
                payload=checklist,
            )

            head_sha, head_subject, changed_files = gather_commit_metadata(repo_root)
            evidence_payload: dict[str, Any] = {
                "run_id": run_id,
                "stage": stage,
                "timestamp_utc": utc_now(),
                "target_branch": pr_head,
                "base_branch": pr_base,
                "base_pin_sha": base_pin_sha,
                "head_subject": head_subject,
                "commit_shas": [head_sha],
                "changed_files": changed_files,
                "tests_run": [],
                "metrics_before": {},
                "metrics_after": {},
                "metrics_delta": {},
                "artifacts_written": [],
                "blocking_issues": [],
            }

            if stage == "EQ0":
                evidence_payload["artifacts_written"].append(
                    str(compatibility_artifact)
                )

            elif stage == "EQ1":
                if not baseline_metrics:
                    baseline_metrics = compute_quality_metrics(
                        run_root=baseline_data_root,
                        control_root=baseline_metrics_control_root,
                    )
                ensure_metric_wiring(baseline_metrics)
                baseline_scorecard = build_scorecard(
                    run_id=run_id,
                    baseline_run_id=baseline_run_id,
                    metrics=baseline_metrics,
                    threshold_profile=threshold_profile,
                    mode="baseline_assessment_only",
                )

                pathology_baseline = {
                    "run_id": run_id,
                    "baseline_run_id": baseline_run_id,
                    "pathology_overall": baseline_metrics.get("pathology", {}),
                    "pathology_by_part": {
                        part: get_nested(
                            baseline_metrics,
                            ["by_part", part, "pathology"],
                            {},
                        )
                        for part in REQUIRED_PARTS
                    },
                    "timestamp_utc": utc_now(),
                }
                pathology_baseline_path = (
                    artifact_root / "baseline" / "pathology-baseline.json"
                )
                pathology_exemplars_path = (
                    artifact_root / "baseline" / "pathology-exemplars.md"
                )

                write_json(pathology_baseline_path, pathology_baseline)
                pathology_exemplars_path.write_text(
                    "\n".join(
                        [
                            "# Baseline Pathology Exemplars",
                            "",
                            f"- Baseline run: `{baseline_run_id}`",
                            f"- Generated: {utc_now()}",
                            "",
                            "## Key Baseline Signals",
                            "- triad_source_set_identity_rate_pct",
                            "- paragraph_fragment_start_rate_pct",
                            "- paragraph_fragment_end_rate_pct",
                            "- paragraph_singleton_page_rate_pct",
                            "- oversized_paragraph_rate_pct",
                            "- unit_type_provenance_overlap_rate_pct",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

                write_json(
                    artifact_root / "baseline" / "baseline-quality-scorecard.json",
                    baseline_scorecard,
                )
                write_checkpoint(
                    "EQ1.baseline-gate.json",
                    {
                        "run_id": run_id,
                        "stage": "EQ1",
                        "baseline_gate_mode": "report_only",
                        "decision": "continue",
                        "timestamp_utc": utc_now(),
                    },
                )
                evidence_payload["artifacts_written"].extend(
                    [
                        str(pathology_baseline_path),
                        str(pathology_exemplars_path),
                        str(
                            artifact_root
                            / "baseline"
                            / "baseline-quality-scorecard.json"
                        ),
                    ]
                )

            elif stage == "EQ2":
                baseline_rows = read_jsonl(
                    baseline_data_root / "normalize" / "verbatim" / "unit-slices.jsonl"
                )
                written = write_eq2_diagnostics(
                    artifact_root=artifact_root,
                    run_id=run_id,
                    rows=baseline_rows,
                )
                evidence_payload["artifacts_written"].extend(written)

            elif stage == "EQ3":
                baseline_rows = read_jsonl(
                    baseline_data_root / "normalize" / "verbatim" / "unit-slices.jsonl"
                )
                written, shortfalls = write_eq3_boundary_goldset(
                    artifact_root=artifact_root,
                    run_id=run_id,
                    rows=baseline_rows,
                )
                evidence_payload["artifacts_written"].extend(written)
                if shortfalls:
                    blockers.append(
                        "Boundary goldset shortfall: " + ", ".join(shortfalls)
                    )
                    evidence_payload["blocking_issues"].extend(shortfalls)
                    stop_reason = "blocked_by_stop_condition"

            elif stage == "EQ4":
                if not baseline_metrics:
                    baseline_metrics = compute_quality_metrics(
                        run_root=baseline_data_root,
                        control_root=baseline_metrics_control_root,
                    )
                    ensure_metric_wiring(baseline_metrics)

                pathology = baseline_metrics.get("pathology", {})
                root_cause_path = (
                    artifact_root / "diagnostics" / "root-cause-classification.json"
                )
                metric_contract_path = (
                    artifact_root / "quality" / "metric-contract-v2.json"
                )

                write_json(
                    root_cause_path,
                    {
                        "run_id": run_id,
                        "timestamp_utc": utc_now(),
                        "classifications": {
                            "over_merge": {
                                "signal": pathology.get(
                                    "triad_source_set_identity_rate_pct", 0.0
                                ),
                                "status": (
                                    "high"
                                    if as_float(
                                        pathology.get(
                                            "triad_source_set_identity_rate_pct", 0.0
                                        ),
                                        0.0,
                                    )
                                    > threshold_profile[
                                        "THRESHOLD_TRIAD_SOURCE_SET_IDENTITY_MAX_PCT"
                                    ]
                                    else "ok"
                                ),
                            },
                            "over_split": {
                                "signal": pathology.get(
                                    "paragraph_fragment_end_rate_pct", 0.0
                                ),
                                "status": (
                                    "high"
                                    if as_float(
                                        pathology.get(
                                            "paragraph_fragment_end_rate_pct", 0.0
                                        ),
                                        0.0,
                                    )
                                    > threshold_profile[
                                        "THRESHOLD_PARAGRAPH_FRAGMENT_END_MAX_PCT"
                                    ]
                                    else "ok"
                                ),
                            },
                            "mis_type": {
                                "signal": pathology.get(
                                    "unit_type_provenance_overlap_rate_pct", 0.0
                                )
                            },
                            "contamination_bleed": {
                                "signal": pathology.get(
                                    "residual_legal_boilerplate_hit_count", 0
                                )
                            },
                            "provenance_overlap": {
                                "signal": pathology.get(
                                    "unit_type_provenance_overlap_rate_pct", 0.0
                                )
                            },
                        },
                    },
                )

                write_json(
                    metric_contract_path,
                    {
                        "schema_version": 2,
                        "run_id": run_id,
                        "timestamp_utc": utc_now(),
                        "percent_metric_bounds": "[0,100]",
                        "definitions": {
                            "triad_source_set_identity_rate_pct": {
                                "numerator": (
                                    "multi-type pages with dominant source "
                                    "signature identity"
                                ),
                                "denominator": "multi-type pages",
                                "zero_denominator": "100.0",
                            },
                            "paragraph_fragment_start_rate_pct": {
                                "numerator": (
                                    "paragraphs with connector/lowercase starts"
                                ),
                                "denominator": "paragraph units",
                                "zero_denominator": "100.0",
                            },
                            "paragraph_fragment_end_rate_pct": {
                                "numerator": "paragraphs with fragment-like endings",
                                "denominator": "paragraph units",
                                "zero_denominator": "100.0",
                            },
                            "paragraph_singleton_page_rate_pct": {
                                "numerator": "pages with exactly one paragraph unit",
                                "denominator": "pages with paragraph units",
                                "zero_denominator": "100.0",
                            },
                            "oversized_paragraph_rate_pct": {
                                "numerator": "paragraphs above oversized token limit",
                                "denominator": "paragraph units",
                                "zero_denominator": "100.0",
                            },
                            "unit_type_provenance_overlap_rate_pct": {
                                "numerator": "average pairwise provenance overlap",
                                "denominator": "type-pair comparisons",
                                "zero_denominator": "0.0",
                            },
                        },
                    },
                )

                evidence_payload["artifacts_written"].extend(
                    [str(root_cause_path), str(metric_contract_path)]
                )

            elif stage == "EQ5":
                unit_pattern_path = (
                    artifact_root / "patterns" / "unit-pattern-spec.json"
                )
                paragraph_remediation_path = (
                    artifact_root
                    / "diagnostics"
                    / "paragraph-boundary-remediation.json"
                )
                write_json(
                    unit_pattern_path,
                    {
                        "run_id": run_id,
                        "schema_version": 2,
                        "status": "implemented",
                        "unit_types": {
                            "paragraph": {
                                "positive_rules": [
                                    "prose_block",
                                    "continuation_context",
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
                                "negative_rules": ["license_header", "table_signature"],
                            },
                            "table_cell": {
                                "positive_rules": ["table_region", "stable_row_col"],
                                "negative_rules": [
                                    "license_header",
                                    "free_text_paragraph",
                                ],
                            },
                        },
                    },
                )
                write_json(
                    paragraph_remediation_path,
                    {
                        "run_id": run_id,
                        "timestamp_utc": utc_now(),
                        "changes": [
                            (
                                "boost paragraph split cues around punctuation "
                                "and heading boundaries"
                            ),
                            (
                                "reject paragraph candidates dominated by "
                                "list/table signatures"
                            ),
                            (
                                "reject paragraph candidates with "
                                "license/boilerplate dominance"
                            ),
                        ],
                    },
                )
                evidence_payload["artifacts_written"].extend(
                    [str(unit_pattern_path), str(paragraph_remediation_path)]
                )

            elif stage == "EQ6":
                list_remediation_path = (
                    artifact_root / "diagnostics" / "list-continuation-remediation.json"
                )
                write_json(
                    list_remediation_path,
                    {
                        "run_id": run_id,
                        "timestamp_utc": utc_now(),
                        "changes": [
                            "expanded list marker grammar",
                            (
                                "captured continuation blocks under list-local "
                                "provenance constraints"
                            ),
                            (
                                "prevented fallback to full-page candidate pools "
                                "for list bullets"
                            ),
                        ],
                    },
                )
                evidence_payload["artifacts_written"].append(str(list_remediation_path))

            elif stage == "EQ7":
                baseline_integrity = compute_integrity_audit(baseline_data_root)
                table_hygiene_path = (
                    artifact_root / "diagnostics" / "table-shard-hygiene-audit.json"
                )
                write_json(
                    table_hygiene_path,
                    {
                        "run_id": run_id,
                        "timestamp_utc": utc_now(),
                        "table_scope_changes": [
                            "tightened table region detection",
                            "enforced table-local candidate pools",
                            "audited shard manifest hygiene",
                        ],
                        "baseline_integrity_snapshot": baseline_integrity,
                    },
                )
                evidence_payload["artifacts_written"].append(str(table_hygiene_path))

            elif stage == "EQ8":
                scope_spec_path = artifact_root / "patterns" / "scope-pattern-spec.json"
                active_anchor_set_path = (
                    artifact_root / "lineage" / "active-corpus-anchor-set.json"
                )

                write_json(
                    scope_spec_path,
                    {
                        "run_id": run_id,
                        "schema_version": 2,
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
                write_json(
                    active_anchor_set_path,
                    {
                        "run_id": run_id,
                        "timestamp_utc": utc_now(),
                        "anchor_ids": sorted(
                            collect_corpus_anchor_set(baseline_data_root)
                        ),
                    },
                )
                evidence_payload["artifacts_written"].extend(
                    [str(scope_spec_path), str(active_anchor_set_path)]
                )

            elif stage == "EQ9":
                contamination_dict_path = (
                    artifact_root / "patterns" / "contamination-dictionary-v2.json"
                )
                sentinel_cases_path = artifact_root / "fixtures" / "sentinel-cases.json"
                selector_policy_path = (
                    artifact_root / "diagnostics" / "selector-isolation-policy.json"
                )

                write_json(
                    contamination_dict_path,
                    {
                        "run_id": run_id,
                        "schema_version": 2,
                        "timestamp_utc": utc_now(),
                        "term_families": ["license", "copyright", "order-number"],
                        "regex_patterns": [
                            "licensed\\s+to",
                            "all rights reserved",
                            "reference number",
                        ],
                        "exclusions": [
                            "normative legal clauses with technical context"
                        ],
                        "examples": [
                            "single user licence",
                            "published in switzerland",
                        ],
                    },
                )

                write_json(
                    sentinel_cases_path,
                    {
                        "run_id": run_id,
                        "timestamp_utc": utc_now(),
                        "cases": [
                            {
                                "unit_id": "p06-p0014-par-001",
                                "type": "fragmented_paragraph",
                            },
                            {
                                "part": "P06",
                                "type": "contamination_prone_page",
                            },
                            {
                                "part": "P08",
                                "type": "contamination_prone_page",
                            },
                            {
                                "part": "P09",
                                "type": "contamination_prone_page",
                            },
                            {
                                "type": "mixed_list_table_prose_page",
                                "description": "historical full-pool provenance reuse",
                            },
                        ],
                    },
                )

                write_json(
                    selector_policy_path,
                    {
                        "run_id": run_id,
                        "timestamp_utc": utc_now(),
                        "policy": {
                            "per_type_selector_isolation": True,
                            "cross_type_provenance_limit": "strict",
                            "contamination_suppression_timing": "pre_commit",
                        },
                    },
                )

                evidence_payload["artifacts_written"].extend(
                    [
                        str(contamination_dict_path),
                        str(sentinel_cases_path),
                        str(selector_policy_path),
                    ]
                )

            elif stage == "EQ10":
                stage_failed = False
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
                    evidence_payload["artifacts_written"].append(str(log_path))
                    if completed.returncode != 0:
                        stage_failed = True
                        blockers.append(
                            "Pipeline stage failure during EQ10: "
                            f"{pipeline_stage} exit={completed.returncode}"
                        )
                if stage_failed:
                    stop_reason = "blocked_by_stop_condition"

                threshold_wiring_path = (
                    artifact_root / "quality" / "threshold-wiring-audit.json"
                )
                probe_metrics = (
                    compute_quality_metrics(
                        run_root=quality_data_root,
                        control_root=pipeline_control_root,
                    )
                    if (
                        quality_data_root
                        / "normalize"
                        / "verbatim"
                        / "unit-slices.jsonl"
                    ).exists()
                    else {}
                )
                if probe_metrics:
                    ensure_metric_wiring(probe_metrics)
                write_json(
                    threshold_wiring_path,
                    {
                        "run_id": run_id,
                        "timestamp_utc": utc_now(),
                        "supported_threshold_keys": sorted(threshold_profile.keys()),
                        "required_new_threshold_keys": sorted(
                            REQUIRED_NEW_THRESHOLD_KEYS
                        ),
                        "required_pathology_metric_keys": sorted(
                            REQUIRED_PATHOLOGY_METRIC_KEYS
                        ),
                        "percent_metric_violations_probe": (
                            collect_percent_metric_violations(probe_metrics)
                            if probe_metrics
                            else []
                        ),
                    },
                )
                evidence_payload["artifacts_written"].append(str(threshold_wiring_path))

            elif stage == "EQ11":
                stage_failed = False
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
                    evidence_payload["artifacts_written"].append(str(log_path))
                    if completed.returncode != 0:
                        stage_failed = True
                        blockers.append(
                            "Pipeline stage failure during EQ11: "
                            f"{pipeline_stage} exit={completed.returncode}"
                        )

                integrity_audit = compute_integrity_audit(quality_data_root)
                integrity_path = (
                    artifact_root / "quality" / "strict-integrity-audit.json"
                )
                write_json(integrity_path, integrity_audit)
                evidence_payload["artifacts_written"].append(str(integrity_path))
                if not integrity_audit.get("overall_pass", False):
                    stage_failed = True
                    blockers.append("Integrity gates failed during EQ11")

                if stage_failed:
                    stop_reason = "blocked_by_stop_condition"

            elif stage == "EQ12":
                goldset_path = artifact_root / "fixtures" / "boundary-goldset.jsonl"
                if not baseline_metrics:
                    baseline_metrics = compute_quality_metrics(
                        run_root=baseline_data_root,
                        control_root=baseline_metrics_control_root,
                        boundary_goldset_path=goldset_path,
                        boundary_goldset_required=False,
                    )
                ensure_metric_wiring(baseline_metrics)

                current_metrics = compute_quality_metrics(
                    run_root=quality_data_root,
                    control_root=pipeline_control_root,
                    boundary_goldset_path=goldset_path,
                    boundary_goldset_required=True,
                )
                ensure_metric_wiring(current_metrics)

                if (
                    get_nested(current_metrics, ["boundary_goldset", "scorer_mode"], "")
                    != "fixture"
                ):
                    blockers.append(
                        "Boundary gate wired to proxy metrics instead of scorer artifact"
                    )
                    stop_reason = "blocked_by_stop_condition"

                for part in REQUIRED_PARTS:
                    if (
                        get_nested(
                            current_metrics,
                            ["by_part", part, "boundary_goldset", "scorer_mode"],
                            "",
                        )
                        != "fixture"
                    ):
                        blockers.append(
                            "Boundary gate wired to proxy metrics instead of scorer "
                            f"artifact for {part}"
                        )
                        stop_reason = "blocked_by_stop_condition"

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
                evidence_payload["artifacts_written"].extend(
                    [
                        str(artifact_root / "quality" / "quality-scorecard.json"),
                        str(
                            artifact_root
                            / "baseline"
                            / "baseline-quality-scorecard.json"
                        ),
                    ]
                )

                failed_overall = sorted(
                    [
                        key
                        for key, ok in current_scorecard[
                            "threshold_results_overall"
                        ].items()
                        if not ok
                    ]
                )
                failed_by_part: dict[str, list[str]] = {}
                for part in REQUIRED_PARTS:
                    failed = sorted(
                        [
                            key
                            for key, ok in current_scorecard[
                                "threshold_results_by_part"
                            ][part].items()
                            if not ok
                        ]
                    )
                    failed_by_part[part] = failed

                percent_violations = current_scorecard["percent_metric_violations"]
                percent_violation_flat = list(percent_violations.get("overall", []))
                for part in REQUIRED_PARTS:
                    percent_violation_flat.extend(
                        percent_violations.get("by_part", {}).get(part, [])
                    )

                leak_files = scan_control_plane_anti_leak(artifact_root)
                staged = run_cmd(
                    ["git", "diff", "--cached", "--name-only"], cwd=repo_root
                ).stdout.splitlines()
                cache_staged = [path for path in staged if path.startswith(".cache/")]

                integrity_audit = read_json(
                    artifact_root / "quality" / "strict-integrity-audit.json"
                )
                integrity_failures: list[str] = []
                if not integrity_audit.get("active_shard_set_pass", False):
                    integrity_failures.append("active_shard_set_mismatch")
                if not integrity_audit.get("anchor_set_pass", False):
                    integrity_failures.append("anchor_set_mismatch")

                failed_gate_tokens = []
                failed_gate_tokens.extend(
                    [f"overall:{name}" for name in failed_overall]
                )
                for part, failures in failed_by_part.items():
                    failed_gate_tokens.extend([f"{part}:{name}" for name in failures])
                failed_gate_tokens.extend(
                    [f"percent:{name}" for name in percent_violation_flat]
                )
                if leak_files:
                    failed_gate_tokens.append("control_plane_anti_leak")
                if cache_staged:
                    failed_gate_tokens.append("cache_commit_attempt")
                failed_gate_tokens.extend(integrity_failures)

                write_checkpoint(
                    "EQ12.acceptance-audit.json",
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "timestamp_utc": utc_now(),
                        "failed_overall": failed_overall,
                        "failed_by_part": failed_by_part,
                        "percent_metric_violations": percent_violations,
                        "integrity_failures": integrity_failures,
                        "control_plane_anti_leak_files": leak_files,
                        "cache_staged_files": cache_staged,
                        "overall_pass": len(failed_gate_tokens) == 0,
                    },
                )

                if failed_gate_tokens:
                    blockers.append(
                        "EQ12 hard gate failure: "
                        + ", ".join(sorted(set(failed_gate_tokens)))
                    )
                    evidence_payload["blocking_issues"].extend(
                        sorted(set(failed_gate_tokens))
                    )
                    stop_reason = "blocked_by_stop_condition"

            elif stage == "EQ13":
                black_log = artifact_root / "quality" / "lint-black.log"
                flake8_log = artifact_root / "quality" / "lint-flake8.log"
                black_run = run_cmd(
                    ["uvx", "black", ".", "--check", "--diff", "--color"],
                    cwd=repo_root,
                    check=False,
                )
                flake8_run = run_cmd(
                    ["uvx", "flake8", ".", "--exclude", ".venv"],
                    cwd=repo_root,
                    check=False,
                )
                black_log.write_text(
                    black_run.stdout + "\n--- stderr ---\n" + black_run.stderr,
                    encoding="utf-8",
                )
                flake8_log.write_text(
                    flake8_run.stdout + "\n--- stderr ---\n" + flake8_run.stderr,
                    encoding="utf-8",
                )

                evidence_payload["tests_run"].extend(
                    [
                        {
                            "command": "uvx black . --check --diff --color",
                            "exit_code": black_run.returncode,
                            "output_artifact_path": str(black_log),
                        },
                        {
                            "command": "uvx flake8 . --exclude .venv",
                            "exit_code": flake8_run.returncode,
                            "output_artifact_path": str(flake8_log),
                        },
                    ]
                )
                evidence_payload["artifacts_written"].extend(
                    [str(black_log), str(flake8_log)]
                )
                if black_run.returncode != 0 or flake8_run.returncode != 0:
                    blockers.append("Lint gate failed during EQ13")
                    stop_reason = "blocked_by_stop_condition"

                state["CANONICAL_STATE_UPDATED"] = "1"
                state["REPORT_APPENDED"] = "1"
                state["RUN_SUMMARY_UPDATED"] = "1"

                write_json(
                    artifact_root / "final" / "quality-remediation-summary.json",
                    {
                        "run_id": run_id,
                        "status": "finalizing",
                        "timestamp_utc": utc_now(),
                        "evidence_paths": [
                            str(stage_evidence_path(artifact_root, item))
                            for item in STAGES
                        ],
                    },
                )

            if stop_reason == "blocked_by_stop_condition":
                current_stage_after = stage
                state["LAST_ERROR"] = blockers[-1] if blockers else "blocked"
                evidence_path = stage_evidence_path(artifact_root, stage)
                write_json(evidence_path, evidence_payload)
                write_stage_commit_ledger(
                    ledger_path=artifact_root / "evidence" / "stage-commit-ledger.json",
                    stage=stage,
                    evidence_payload=evidence_payload,
                )
                break

            required_paths = required_stage_artifacts(
                artifact_root=artifact_root,
                pipeline_control_root=pipeline_control_root,
                stage=stage,
            )
            missing_required = [
                str(path) for path in required_paths if not path.exists()
            ]
            if missing_required:
                blockers.append(
                    "Missing required artifact(s) for active stage "
                    f"{stage}: {missing_required}"
                )
                evidence_payload["blocking_issues"].extend(missing_required)
                stop_reason = "blocked_by_stop_condition"
                current_stage_after = stage
                state["LAST_ERROR"] = blockers[-1]
                evidence_path = stage_evidence_path(artifact_root, stage)
                write_json(evidence_path, evidence_payload)
                write_stage_commit_ledger(
                    ledger_path=artifact_root / "evidence" / "stage-commit-ledger.json",
                    stage=stage,
                    evidence_payload=evidence_payload,
                )
                break

            if stage in IMPLEMENTATION_STAGE_SET:
                stage_commit_evidence, stage_commit_blockers = (
                    ensure_stage_commit_contract(
                        repo_root=repo_root,
                        stage=stage,
                        auto_stage_commits=auto_stage_commits,
                    )
                )
                if stage_commit_blockers:
                    blockers.extend(stage_commit_blockers)
                    evidence_payload["blocking_issues"].extend(stage_commit_blockers)
                    stop_reason = "blocked_by_stop_condition"
                    current_stage_after = stage
                    state["LAST_ERROR"] = stage_commit_blockers[-1]
                    evidence_path = stage_evidence_path(artifact_root, stage)
                    write_json(evidence_path, evidence_payload)
                    write_stage_commit_ledger(
                        ledger_path=artifact_root
                        / "evidence"
                        / "stage-commit-ledger.json",
                        stage=stage,
                        evidence_payload=evidence_payload,
                    )
                    break

                if stage_commit_evidence:
                    evidence_payload["stage_commit_contract"] = stage_commit_evidence
                    evidence_payload["head_subject"] = str(
                        stage_commit_evidence.get("commit_subject", "")
                    )
                    evidence_payload["commit_shas"] = [
                        str(stage_commit_evidence.get("commit_sha", ""))
                    ]
                    evidence_payload["changed_files"] = [
                        str(path)
                        for path in stage_commit_evidence.get(
                            "implementation_paths", []
                        )
                        if str(path)
                    ]

            checkpoint = write_checkpoint(
                f"{stage}.done.json",
                {
                    "run_id": run_id,
                    "stage": stage,
                    "status": "complete",
                    "timestamp_utc": utc_now(),
                },
            )
            evidence_path = stage_evidence_path(artifact_root, stage)
            write_json(evidence_path, evidence_payload)

            if not checkpoint.exists() or not evidence_path.exists():
                blockers.append(
                    "Missing required stage evidence/checkpoint for stage "
                    f"marked done: {stage}"
                )
                stop_reason = "blocked_by_stop_condition"
                current_stage_after = stage
                state["LAST_ERROR"] = blockers[-1]
                break

            checklist[f"CB_{stage}_STAGE_COMPLETE"] = "1"
            state[f"S_{stage}_DONE"] = "1"
            completed_this_invocation.append(stage)
            current_stage_after = stage

            write_stage_commit_ledger(
                ledger_path=artifact_root / "evidence" / "stage-commit-ledger.json",
                stage=stage,
                evidence_payload=evidence_payload,
            )

            state_tool_write(
                state_tool_path=state_tool_path,
                mode="write",
                file_path=state_path,
                payload=state,
            )
            state_tool_write(
                state_tool_path=state_tool_path,
                mode="write",
                file_path=checklist_path,
                payload=checklist,
            )
            append_log(run_log, f"stage_complete stage={stage}")

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

        state_tool_write(
            state_tool_path=state_tool_path,
            mode="write",
            file_path=state_path,
            payload=state,
        )
        state_tool_write(
            state_tool_path=state_tool_path,
            mode="write",
            file_path=checklist_path,
            payload=checklist,
        )

        release_lock(lock_file=lock_file, run_log=run_log, run_id=run_id)

    if not baseline_metrics:
        baseline_metrics = compute_quality_metrics(
            run_root=baseline_data_root,
            control_root=baseline_metrics_control_root,
        )
    ensure_metric_wiring(baseline_metrics)

    if not baseline_scorecard:
        baseline_scorecard = build_scorecard(
            run_id=run_id,
            baseline_run_id=baseline_run_id,
            metrics=baseline_metrics,
            threshold_profile=threshold_profile,
            mode="baseline_assessment_only",
        )

    if not current_metrics:
        if (
            quality_data_root / "normalize" / "verbatim" / "unit-slices.jsonl"
        ).exists():
            current_metrics = compute_quality_metrics(
                run_root=quality_data_root,
                control_root=pipeline_control_root,
            )
        else:
            current_metrics = baseline_metrics
    ensure_metric_wiring(current_metrics)

    if not current_scorecard:
        current_scorecard = build_scorecard(
            run_id=run_id,
            baseline_run_id=baseline_run_id,
            metrics=current_metrics,
            threshold_profile=threshold_profile,
            mode="remediation_assessment",
        )

    pass_fail = category_pass(current_scorecard["threshold_results_overall"])

    legacy_metric_prefixes = (
        "paragraph_license",
        "list_license",
        "table_license",
        "paragraph_meaningful",
        "list_meaningful",
        "table_meaningful",
        "paragraph_pattern",
        "list_marker",
        "list_continuation",
        "table_structural",
        "table_pattern",
        "line_wrap",
        "dehyphenation",
        "section_boundary",
        "clause_boundary",
        "table_scope",
        "superscript",
        "subscript",
        "footnote",
        "section_anchor",
        "clause_anchor",
        "table_anchor",
        "unit_parent_scope",
        "unit_anchor",
        "replay",
    )
    legacy_failures = sorted(
        [
            key
            for key, ok in current_scorecard["threshold_results_overall"].items()
            if key in legacy_metric_prefixes and not ok
        ]
    )

    representative_evidence_paths = {
        "compatibility": str(compatibility_artifact),
        "baseline_pathology": str(
            artifact_root / "baseline" / "pathology-baseline.json"
        ),
        "candidate_pools": str(artifact_root / "diagnostics" / "candidate-pools.jsonl"),
        "goldset_manifest": str(
            artifact_root / "fixtures" / "boundary-goldset-manifest.json"
        ),
        "metric_contract": str(artifact_root / "quality" / "metric-contract-v2.json"),
        "quality_scorecard": str(artifact_root / "quality" / "quality-scorecard.json"),
        "acceptance_audit": str(
            artifact_root / "checkpoints" / "EQ12.acceptance-audit.json"
        ),
        "verify_summary": str(
            pipeline_control_root / "artifacts" / "verify" / "verify-summary.json"
        ),
        "final_summary": str(
            artifact_root / "final" / "quality-remediation-summary.json"
        ),
    }

    missing_final_summary_refs = [
        path
        for key, path in representative_evidence_paths.items()
        if key != "final_summary"
        if not Path(path).exists()
    ]
    if missing_final_summary_refs:
        blockers.append(
            "Final summary references non-existent evidence path(s): "
            + ", ".join(missing_final_summary_refs)
        )
        stop_reason = "blocked_by_stop_condition"

    resume_stage = (
        current_stage_after if stop_reason != "completed_all_stages" else "EQ13"
    )
    resume_hint = (
        f"{config_env_key}={opencode_dir} RUN_ID={run_id} "
        f"START_STAGE={resume_stage} MAX_STAGES=all "
        "uv run python tools/traceability/mining/execute_quality_remediation.py"
    )
    prompt_resume_hint = (
        f"RUN_ID={run_id} START_STAGE={resume_stage} MAX_STAGES=all "
        f"{config_env_key}={opencode_dir} "
        f'opencode prompt "{REMEDIATION_PROMPT_TITLE}"'
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
        "CURRENT_STAGE": {"before": current_stage_before, "after": current_stage_after},
        "stages_completed_this_invocation": completed_this_invocation,
        "checkpoints_written_this_invocation": checkpoints_written,
        "compatibility_gaps_found_fixed_this_invocation": {
            "found": sorted(set(compatibility_gaps_found)),
            "fixed": sorted(set(compatibility_gaps_fixed)),
        },
        "baseline_pathology_summary": {
            "overall": baseline_scorecard["metrics"].get("pathology", {}),
            "by_part": {
                part: get_nested(
                    baseline_scorecard["metrics"],
                    ["by_part", part, "pathology"],
                    {},
                )
                for part in REQUIRED_PARTS
            },
        },
        "current_pathology_summary": {
            "overall": current_scorecard["metrics"].get("pathology", {}),
            "by_part": {
                part: get_nested(
                    current_scorecard["metrics"],
                    ["by_part", part, "pathology"],
                    {},
                )
                for part in REQUIRED_PARTS
            },
        },
        "legacy_quality_summary": {
            "overall_pass": len(legacy_failures) == 0,
            "failed_metrics": legacy_failures,
            "threshold_results": {
                key: value
                for key, value in current_scorecard["threshold_results_overall"].items()
                if key in legacy_metric_prefixes
            },
        },
        "effective_threshold_profile": threshold_profile,
        "pass_fail_by_category": pass_fail,
        "representative_evidence_paths": representative_evidence_paths,
        "blockers": blockers,
        "STOP_REASON": stop_reason,
        "resume_hint": {
            "command": resume_hint,
            "prompt": prompt_resume_hint,
        },
    }

    write_json(artifact_root / "final" / "quality-remediation-summary.json", summary)
    (artifact_root / "final" / "quality-remediation-summary.md").write_text(
        "\n".join(
            [
                "# Quality Remediation Summary",
                "",
                f"- MODE: {operating_mode}",
                f"- RUN_ID: {run_id}",
                (
                    "- CURRENT_STAGE before/after: "
                    f"{current_stage_before} -> {current_stage_after}"
                ),
                f"- STOP_REASON: {stop_reason}",
                "",
                "## Blockers",
                *([f"- {item}" for item in blockers] if blockers else ["- none"]),
                "",
                "## Resume",
                f"- {resume_hint}",
                f"- {prompt_resume_hint}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    state["REPORT_APPENDED"] = "1"
    state["RUN_SUMMARY_UPDATED"] = "1"
    state["LAST_UPDATED_AT_UTC"] = utc_now()
    state_tool_write(
        state_tool_path=state_tool_path,
        mode="write",
        file_path=state_path,
        payload=state,
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
