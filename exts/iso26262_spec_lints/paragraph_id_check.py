from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment

IRM_ID_RE = re.compile(r"^irm_[A-Za-z0-9]{12}$")


def _extract_anchor(href: str) -> str:
    if "#" not in href:
        return ""
    return href.split("#", 1)[1].strip()


def _collect_findings(env: BuildEnvironment) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    anchor_map: dict[str, set[str]] = {}
    records = getattr(env, "iso26262_trace_records", {})
    trace_errors = getattr(env, "iso26262_trace_errors", [])

    for statement_id, record in records.items():
        if not IRM_ID_RE.match(statement_id):
            findings.append(
                {
                    "code": "invalid_irm_id_format",
                    "id": statement_id,
                    "message": (
                        "Statement ID is not a valid IRM ID "
                        "(expected pattern: irm_[A-Za-z0-9]{12})."
                    ),
                }
            )

        href = str(record.get("href", "")).strip()
        anchor = _extract_anchor(href)
        if anchor:
            anchor_map.setdefault(anchor, set()).add(statement_id)

    for anchor, statement_ids in anchor_map.items():
        if len(statement_ids) > 1:
            findings.append(
                {
                    "code": "duplicate_anchor",
                    "id": ",".join(sorted(statement_ids)),
                    "message": (
                        "Multiple statements resolve to the same anchor "
                        f"'{anchor}', which violates the exact IRM ID anchor policy."
                    ),
                }
            )

    for message in trace_errors:
        if "duplicate" in message and "source_id" in message:
            findings.append(
                {
                    "code": "duplicate_id",
                    "id": "",
                    "message": message,
                }
            )
        if "unresolved statement reference" in message:
            findings.append(
                {
                    "code": "unresolved_reference",
                    "id": "",
                    "message": message,
                }
            )

    return findings


def _write_shadow_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _run_paragraph_id_check(
    app: Sphinx, env: BuildEnvironment
) -> tuple[dict[str, Any], list[str]]:
    strict_mode = bool(getattr(app.config, "iso26262_irm_id_strict_mode", False))
    findings = _collect_findings(env)

    payload: dict[str, Any] = {
        "status": "pass" if not findings else "report_only",
        "strict_mode": strict_mode,
        "finding_count": len(findings),
        "findings": findings,
    }

    run_root_raw = getattr(app.config, "iso26262_run_root", "")
    if run_root_raw:
        shadow_path = (
            Path(run_root_raw)
            / "artifacts"
            / "lints"
            / "paragraph-id-check-shadow.json"
        )
        _write_shadow_artifact(shadow_path, payload)
        payload["shadow_report_path"] = str(shadow_path)

    if not strict_mode:
        return payload, []

    errors: list[str] = [
        f"{item.get('code', 'paragraph_id_check')}: {item.get('message', '').strip()}"
        for item in findings
    ]
    payload["status"] = "pass" if not errors else "fail"
    return payload, errors
