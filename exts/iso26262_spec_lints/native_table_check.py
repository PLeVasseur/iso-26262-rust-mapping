from __future__ import annotations

from pathlib import Path

NATIVE_TABLE_DIRECTIVES = ("```{table}", "```{list-table}", "```{csv-table}")


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
