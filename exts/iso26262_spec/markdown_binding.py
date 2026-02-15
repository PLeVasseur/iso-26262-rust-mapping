from __future__ import annotations

from typing import Any

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment

from .constants import TRACE_STATUSES
from .preface_parser import _extract_preface
from .record_store import _record_error, _register_record
from .utils import _sha256_text, _statement_anchor_from_source_id


def _is_markdown_statement_node(node: nodes.Node) -> bool:
    if isinstance(node, nodes.paragraph):
        if isinstance(node.parent, nodes.entry):
            return False
        return bool(node.astext().strip())
    if isinstance(node, nodes.list_item):
        return bool(node.astext().strip())
    return False


def _set_paragraph_text(paragraph: nodes.paragraph, text: str) -> None:
    paragraph.children = []
    for index, line in enumerate(text.splitlines()):
        if index > 0:
            paragraph += nodes.Text("\n")
        paragraph += nodes.Text(line)


def _bind_prefaces(
    app: Sphinx, env: BuildEnvironment, docname: str, container: nodes.Element
) -> None:
    if not hasattr(container, "children"):
        return

    children = list(container.children)
    rebuilt: list[nodes.Node] = []
    idx = 0

    while idx < len(children):
        node = children[idx]
        if isinstance(node, nodes.paragraph):
            metadata = _extract_preface(node)
            if metadata is not None:
                inline_target = isinstance(node, nodes.paragraph) and bool(
                    metadata.inline_body
                )
                if inline_target:
                    _set_paragraph_text(node, metadata.inline_body)
                    target = node
                    source_id = metadata.source_id
                    trace_status = metadata.trace_status
                    if trace_status not in TRACE_STATUSES:
                        _record_error(
                            env,
                            f"invalid trace status '{trace_status}' "
                            f"for {source_id} in {docname}",
                        )

                    if trace_status == "mapped" and not metadata.anchor_ids:
                        _record_error(
                            env,
                            f"mapped statement '{source_id}' in {docname} "
                            "has no anchor_ids",
                        )
                    if trace_status == "mapped" and not metadata.relation:
                        _record_error(
                            env,
                            f"mapped statement '{source_id}' in {docname} "
                            "has no relation",
                        )

                    anchor_id = _statement_anchor_from_source_id(source_id)
                    target_ids = target.setdefault("ids", [])
                    if anchor_id not in target_ids:
                        target_ids.append(anchor_id)

                    target["trace_source_id"] = source_id
                    target["trace_status"] = trace_status
                    target["trace_anchor_ids"] = metadata.anchor_ids
                    target["trace_relation"] = metadata.relation

                    statement_text = target.astext().strip()
                    record: dict[str, Any] = {
                        "id": source_id,
                        "unit_type": "paragraph",
                        "display_number": "",
                        "doc": docname,
                        "href": f"{docname}.html#{anchor_id}",
                        "checksum": _sha256_text(statement_text),
                        "trace_status": trace_status,
                        "anchor_ids": metadata.anchor_ids,
                        "relation": metadata.relation,
                        "source_locator": {
                            "kind": "markdown",
                            "path": f"src/{docname}.md",
                        },
                    }
                    _register_record(env, record, f"{docname} inline metadata preface")
                    env.iso26262_doc_statement_ids.setdefault(docname, []).append(
                        source_id
                    )

                    rebuilt.append(node)
                    idx += 1
                    continue

                if idx + 1 >= len(children):
                    _record_error(env, f"orphan metadata preface in {docname}")
                    idx += 1
                    continue

                target = children[idx + 1]
                if not _is_markdown_statement_node(target):
                    _record_error(
                        env,
                        f"metadata preface in {docname} is not directly above a "
                        "markdown statement unit",
                    )
                    idx += 1
                    continue

                source_id = metadata.source_id
                trace_status = metadata.trace_status
                if trace_status not in TRACE_STATUSES:
                    _record_error(
                        env,
                        f"invalid trace status '{trace_status}' "
                        f"for {source_id} in {docname}",
                    )

                if trace_status == "mapped" and not metadata.anchor_ids:
                    _record_error(
                        env,
                        f"mapped statement '{source_id}' in {docname} "
                        "has no anchor_ids",
                    )
                if trace_status == "mapped" and not metadata.relation:
                    _record_error(
                        env,
                        f"mapped statement '{source_id}' in {docname} "
                        "has no relation",
                    )

                anchor_id = _statement_anchor_from_source_id(source_id)
                target_ids = target.setdefault("ids", [])
                if anchor_id not in target_ids:
                    target_ids.append(anchor_id)

                target["trace_source_id"] = source_id
                target["trace_status"] = trace_status
                target["trace_anchor_ids"] = metadata.anchor_ids
                target["trace_relation"] = metadata.relation

                unit_type = (
                    "paragraph" if isinstance(target, nodes.paragraph) else "list_item"
                )
                statement_text = target.astext().strip()
                href = f"{docname}.html#{anchor_id}"

                record = {
                    "id": source_id,
                    "unit_type": unit_type,
                    "display_number": "",
                    "doc": docname,
                    "href": href,
                    "checksum": _sha256_text(statement_text),
                    "trace_status": trace_status,
                    "anchor_ids": metadata.anchor_ids,
                    "relation": metadata.relation,
                    "source_locator": {
                        "kind": "markdown",
                        "path": f"src/{docname}.md",
                    },
                }
                _register_record(env, record, f"{docname} markdown preface")
                env.iso26262_doc_statement_ids.setdefault(docname, []).append(source_id)

                idx += 1
                continue

        if isinstance(node, nodes.Element):
            _bind_prefaces(app, env, docname, node)
        rebuilt.append(node)
        idx += 1

    container.children = rebuilt


def _collect_missing_units(
    env: BuildEnvironment, docname: str, doctree: nodes.document
) -> None:
    missing: list[str] = []
    for paragraph in doctree.traverse(nodes.paragraph):
        if isinstance(paragraph.parent, nodes.entry):
            continue
        text = paragraph.astext().strip()
        if not text:
            continue
        if paragraph.get("trace_source_id"):
            continue
        missing.append(text)

    for list_item in doctree.traverse(nodes.list_item):
        text = list_item.astext().strip()
        if not text:
            continue
        if list_item.get("trace_source_id"):
            continue
        traced_child = any(
            isinstance(child, nodes.paragraph) and child.get("trace_source_id")
            for child in list_item.children
        )
        if not traced_child:
            missing.append(text)

    env.iso26262_doc_missing_units[docname] = missing
