from __future__ import annotations

from pathlib import Path
from typing import Any

from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment
from sphinx.errors import ExtensionError

from .anchor_resolution_check import _validate_anchor_references
from .common import _ensure_env, _write_json, _write_text
from .legacy_token_check import _find_legacy_tokens
from .native_table_check import _find_native_table_usage
from .paragraph_id_check import _run_paragraph_id_check
from .preface_adjacency_check import _validate_missing_preface_units
from .table_anchor_check import _validate_table_anchor_format
from .trace_status_check import _validate_trace_status_values


def _run_lints(app: Sphinx, env: BuildEnvironment) -> None:
    _ensure_env(env)
    src_root = Path(app.srcdir)
    run_root_raw = getattr(app.config, "iso26262_run_root", "")
    lint_root = Path(run_root_raw) / "artifacts" / "lints" if run_root_raw else None
    paragraph_id_shadow_payload, paragraph_id_errors = _run_paragraph_id_check(app, env)

    findings: dict[str, list[str]] = {
        "no_legacy_tokens": _find_legacy_tokens(src_root),
        "traceable_table_usage": _find_native_table_usage(src_root),
        "anchor_resolution": _validate_anchor_references(env),
        "preface_adjacency": _validate_missing_preface_units(env),
        "table_anchor_targets": _validate_table_anchor_format(env),
        "trace_status_values": _validate_trace_status_values(env),
        "extension_errors": list(getattr(env, "iso26262_trace_errors", [])),
        "paragraph_id_check": paragraph_id_errors,
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
        _write_json(
            lint_root / "paragraph-id-check-shadow.json",
            paragraph_id_shadow_payload,
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
