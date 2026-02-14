from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment
from sphinx.errors import ExtensionError

LEGACY_TOKENS = ("{{TABLE:", "{{PAGE_BREAK}}", "{{BLANK}}")
NATIVE_TABLE_DIRECTIVES = ("```{table}", "```{list-table}", "```{csv-table}")


def _ensure_env(env: BuildEnvironment) -> None:
    if not hasattr(env, "iso26262_trace_errors"):
        env.iso26262_trace_errors = []
    if not hasattr(env, "iso26262_trace_records"):
        env.iso26262_trace_records = {}
    if not hasattr(env, "iso26262_doc_missing_units"):
        env.iso26262_doc_missing_units = {}


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _find_legacy_tokens(src_root: Path) -> list[str]:
    findings: list[str] = []
    for md_file in sorted(src_root.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        for token in LEGACY_TOKENS:
            if token in text:
                findings.append(f"{md_file}: contains {token}")
    return findings


def _find_native_table_usage(src_root: Path) -> list[str]:
    findings: list[str] = []
    for md_file in sorted(src_root.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        for directive in NATIVE_TABLE_DIRECTIVES:
            if directive in text:
                findings.append(
                    f"{md_file}: contains traceable native table directive {directive}"
                )
    return findings


def _validate_anchor_references(env: BuildEnvironment) -> list[str]:
    findings: list[str] = []
    known = getattr(env, "iso26262_anchor_registry_ids", set())
    for source_id, record in env.iso26262_trace_records.items():
        status = record.get("trace_status")
        anchors = record.get("anchor_ids") or []
        relation = str(record.get("relation", "")).strip()

        if status == "mapped":
            if not anchors:
                findings.append(f"{source_id}: mapped without anchor_ids")
            if not relation:
                findings.append(f"{source_id}: mapped without relation")

        for anchor_id in anchors:
            if anchor_id not in known:
                findings.append(f"{source_id}: unknown anchor_id {anchor_id}")
    return findings


def _validate_missing_preface_units(env: BuildEnvironment) -> list[str]:
    findings: list[str] = []
    for docname, missing in env.iso26262_doc_missing_units.items():
        for snippet in missing:
            findings.append(
                f"{docname}: missing metadata preface for statement '{snippet[:100]}'"
            )
    return findings


def _validate_table_anchor_format(env: BuildEnvironment) -> list[str]:
    findings: list[str] = []
    pattern = re.compile(r"^[a-z0-9-]+--r-[a-z0-9-]+--c-[a-z0-9-]+$")
    for source_id, record in env.iso26262_trace_records.items():
        if record.get("unit_type") != "table_cell":
            continue
        href = str(record.get("href", ""))
        if "#" not in href:
            findings.append(f"{source_id}: table cell href missing anchor")
            continue
        anchor = href.split("#", 1)[1]
        if not pattern.match(anchor):
            findings.append(f"{source_id}: non-canonical table cell anchor '{anchor}'")
    return findings


def _validate_trace_status_values(env: BuildEnvironment) -> list[str]:
    findings: list[str] = []
    allowed = {
        "mapped",
        "unmapped_with_rationale",
        "out_of_scope_with_rationale",
    }
    for source_id, record in env.iso26262_trace_records.items():
        status = record.get("trace_status")
        if status not in allowed:
            findings.append(f"{source_id}: invalid trace_status '{status}'")
    return findings


def _run_lints(app: Sphinx, env: BuildEnvironment) -> None:
    _ensure_env(env)
    src_root = Path(app.srcdir)
    run_root_raw = getattr(app.config, "iso26262_run_root", "")
    lint_root = Path(run_root_raw) / "artifacts" / "lints" if run_root_raw else None

    findings: dict[str, list[str]] = {
        "no_legacy_tokens": _find_legacy_tokens(src_root),
        "traceable_table_usage": _find_native_table_usage(src_root),
        "anchor_resolution": _validate_anchor_references(env),
        "preface_adjacency": _validate_missing_preface_units(env),
        "table_anchor_targets": _validate_table_anchor_format(env),
        "trace_status_values": _validate_trace_status_values(env),
        "extension_errors": list(env.iso26262_trace_errors),
    }

    if lint_root is not None:
        _write_text(
            lint_root / "no-legacy-token-lint.log",
            "\n".join(findings["no_legacy_tokens"]) + "\n",
        )
        _write_text(
            lint_root / "traceable-table-usage-lint.log",
            "\n".join(findings["traceable_table_usage"]) + "\n",
        )
        _write_text(
            lint_root / "anchor-resolution-lint.log",
            "\n".join(findings["anchor_resolution"]) + "\n",
        )
        _write_text(
            lint_root / "preface-adjacency-lint.log",
            "\n".join(findings["preface_adjacency"]) + "\n",
        )
        _write_text(
            lint_root / "table-anchor-targets-lint.log",
            "\n".join(findings["table_anchor_targets"]) + "\n",
        )
        _write_text(
            lint_root / "trace-status-values-lint.log",
            "\n".join(findings["trace_status_values"]) + "\n",
        )

        summary = {
            "lint_counts": {key: len(value) for key, value in findings.items()},
            "status": (
                "pass" if all(not values for values in findings.values()) else "fail"
            ),
        }
        _write_json(lint_root / "lint-summary.json", summary)
        _write_text(
            lint_root / "orphan-preface-lint.log",
            "\n".join(findings["preface_adjacency"]) + "\n",
        )
        _write_text(
            lint_root / "table-trace-coverage-lint.log",
            "\n".join(findings["extension_errors"]) + "\n",
        )
        _write_text(
            lint_root / "table-trace-precedence-lint.log",
            "\n".join(findings["extension_errors"]) + "\n",
        )

    all_findings = [item for values in findings.values() for item in values]
    if all_findings:
        sample = "\n- " + "\n- ".join(all_findings[:20])
        raise ExtensionError(f"env-check-consistency failed:{sample}")


def setup(app: Sphinx) -> dict[str, Any]:
    app.connect("env-check-consistency", _run_lints)
    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
        "env_version": 1,
    }
