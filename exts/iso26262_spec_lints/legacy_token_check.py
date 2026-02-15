from __future__ import annotations

from pathlib import Path

LEGACY_TOKENS = ("{{TABLE:", "{{PAGE_BREAK}}", "{{BLANK}}")


def _find_legacy_tokens(src_root: Path) -> list[str]:
    findings: list[str] = []
    for md_file in sorted(src_root.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        for token in LEGACY_TOKENS:
            if token in text:
                findings.append(f"{md_file}: contains {token}")
    return findings
