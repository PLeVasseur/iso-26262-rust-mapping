from __future__ import annotations

from sphinx.environment import BuildEnvironment


def _validate_missing_preface_units(env: BuildEnvironment) -> list[str]:
    findings: list[str] = []
    for docname, missing in env.iso26262_doc_missing_units.items():
        for snippet in missing:
            findings.append(
                f"{docname}: missing metadata preface for statement '{snippet[:100]}'"
            )
    return findings
