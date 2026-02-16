from __future__ import annotations

from sphinx.environment import BuildEnvironment


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
