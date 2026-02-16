from __future__ import annotations

import re

from sphinx.environment import BuildEnvironment


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
