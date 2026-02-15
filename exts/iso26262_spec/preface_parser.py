from __future__ import annotations

import re

from docutils import nodes

from .nodes import a_node, dp_node, p_node, rel_node, ts_node
from .types import PrefaceMetadata

IRM_ID_RE = re.compile(r"^irm_[A-Za-z0-9]{12}$")


def _is_valid_irm_id(value: str) -> bool:
    return bool(IRM_ID_RE.match(value))


def _extract_preface(
    paragraph: nodes.paragraph, *, strict_mode: bool = False
) -> PrefaceMetadata | None:
    _ = strict_mode
    irm_ids: list[str] = []
    statuses: list[str] = []
    anchor_ids: list[str] = []
    relations: list[str] = []
    has_non_metadata_content = False
    has_any_metadata = False

    for child in paragraph.children:
        if isinstance(child, dp_node):
            has_any_metadata = True
            irm_ids.append(child.astext().strip())
            continue
        if isinstance(child, ts_node):
            has_any_metadata = True
            statuses.append(child.astext().strip())
            continue
        if isinstance(child, a_node):
            has_any_metadata = True
            value = child.astext().strip()
            if value:
                anchor_ids.append(value)
            continue
        if isinstance(child, rel_node):
            has_any_metadata = True
            value = child.astext().strip()
            if value:
                relations.append(value)
            continue
        if isinstance(child, p_node):
            has_any_metadata = True
            has_non_metadata_content = True
            continue
        if isinstance(child, nodes.Text):
            if child.astext().strip():
                has_non_metadata_content = True
            continue
        has_non_metadata_content = True

    if (
        has_any_metadata
        and (not has_non_metadata_content)
        and len(irm_ids) == 1
        and len(statuses) == 1
    ):
        return PrefaceMetadata(
            irm_id=irm_ids[0],
            trace_status=statuses[0],
            anchor_ids=anchor_ids,
            relation=relations[0] if relations else "",
            inline_body="",
        )

    raw = (paragraph.rawsource or "").strip()
    role_preface_pattern = (
        r"^\{dp\}`(?P<sid>[^`]+)`\s+\{ts\}`(?P<status>[^`]+)`"
        r"(?:\s+\{rel\}`(?P<rel>[^`]+)`)?"
        r"(?:\s+\{a\}`(?P<aid>[^`]+)`)?"
        r"(?:\n(?P<body>[\s\S]+))?$"
    )
    role_preface = re.match(role_preface_pattern, raw)
    if role_preface:
        sid = role_preface.group("sid").strip()
        status = role_preface.group("status").strip()
        relation = (role_preface.group("rel") or "").strip()
        anchor = (role_preface.group("aid") or "").strip()
        body = (role_preface.group("body") or "").strip()
        return PrefaceMetadata(
            irm_id=sid,
            trace_status=status,
            anchor_ids=[anchor] if anchor else [],
            relation=relation,
            inline_body=body,
        )

    text = paragraph.astext().strip()
    plain_preface_pattern = (
        r"^(?P<sid>SRCN-[A-Za-z0-9-]+)\s+"
        r"(?P<status>mapped|unmapped_with_rationale|out_of_scope_with_rationale)"
        r"(?:\n(?P<body>[\s\S]+)|\s+(?P<rest>.+))?$"
    )
    plain_preface = re.match(plain_preface_pattern, text)
    if plain_preface:
        sid = plain_preface.group("sid").strip()
        status = plain_preface.group("status").strip()
        rest = (plain_preface.group("rest") or "").strip()
        body = (plain_preface.group("body") or "").strip()
        return PrefaceMetadata(
            irm_id=sid,
            trace_status=status,
            anchor_ids=[],
            relation=rest,
            inline_body=body,
        )

    return None
