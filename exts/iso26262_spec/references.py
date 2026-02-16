from __future__ import annotations

from docutils import nodes
from sphinx.environment import BuildEnvironment

from .nodes import a_node, p_node
from .record_store import _record_error


def _resolve_statement_references(
    env: BuildEnvironment, doctree: nodes.document, docname: str
) -> None:
    for ref in list(doctree.traverse(p_node)):
        target_id = ref.astext().strip()
        href = env.iso26262_statement_locations.get(target_id, "")
        if not href:
            _record_error(
                env, f"unresolved statement reference '{{p}}`{target_id}`' in {docname}"
            )
            ref.replace_self(nodes.literal(text=target_id))
            continue
        reference = nodes.reference(text=target_id, refuri=href)
        ref.replace_self(reference)


def _resolve_anchor_references(
    env: BuildEnvironment, doctree: nodes.document, docname: str
) -> None:
    for anchor_ref in list(doctree.traverse(a_node)):
        target_anchor = anchor_ref.astext().strip()
        if target_anchor and target_anchor not in env.iso26262_anchor_registry_ids:
            _record_error(
                env,
                f"unknown ISO anchor reference '{{a}}`{target_anchor}`' in {docname}",
            )
        anchor_ref.replace_self(nodes.literal(text=target_anchor))
