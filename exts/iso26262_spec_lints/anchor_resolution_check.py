from __future__ import annotations

from sphinx.environment import BuildEnvironment


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
