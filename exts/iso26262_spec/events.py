from __future__ import annotations

from typing import Any

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment
from sphinx.errors import ExtensionError

from .markdown_binding import _bind_prefaces, _collect_missing_units
from .outputs import _emit_trace_outputs
from .record_store import _ensure_env, _register_record
from .references import _resolve_anchor_references, _resolve_statement_references
from .registry import _load_anchor_registry


def _on_builder_inited(app: Sphinx) -> None:
    _ensure_env(app.builder.env)
    _load_anchor_registry(app, app.builder.env)


def _on_env_purge_doc(app: Sphinx, env: BuildEnvironment, docname: str) -> None:
    _ensure_env(env)
    for source_id in list(env.iso26262_trace_records.keys()):
        record = env.iso26262_trace_records[source_id]
        if record.get("doc") == docname:
            env.iso26262_trace_records.pop(source_id, None)
            env.iso26262_statement_locations.pop(source_id, None)
            if source_id in env.iso26262_trace_order:
                env.iso26262_trace_order.remove(source_id)
    env.iso26262_doc_statement_ids.pop(docname, None)
    env.iso26262_doc_missing_units.pop(docname, None)


def _on_env_merge_info(
    app: Sphinx, env: BuildEnvironment, docnames: list[str], other: BuildEnvironment
) -> None:
    _ensure_env(env)
    _ensure_env(other)
    for source_id in other.iso26262_trace_order:
        record: dict[str, Any] = other.iso26262_trace_records[source_id]
        _register_record(env, record, "parallel-merge")
    env.iso26262_trace_errors.extend(other.iso26262_trace_errors)
    env.iso26262_doc_statement_ids.update(other.iso26262_doc_statement_ids)
    env.iso26262_doc_missing_units.update(other.iso26262_doc_missing_units)
    env.iso26262_statement_locations.update(other.iso26262_statement_locations)
    env.iso26262_anchor_registry_ids.update(other.iso26262_anchor_registry_ids)


def _on_doctree_read(app: Sphinx, doctree: nodes.document) -> None:
    env = app.builder.env
    _ensure_env(env)
    _bind_prefaces(app, env, env.docname, doctree)
    _collect_missing_units(env, env.docname, doctree)


def _on_doctree_resolved(app: Sphinx, doctree: nodes.document, docname: str) -> None:
    env = app.builder.env
    _ensure_env(env)
    _resolve_statement_references(env, doctree, docname)
    _resolve_anchor_references(env, doctree, docname)


def _on_build_finished(app: Sphinx, exception: Exception | None) -> None:
    env = app.builder.env
    _ensure_env(env)
    _emit_trace_outputs(app, env)

    if exception is None and env.iso26262_trace_errors:
        sample = "\n- " + "\n- ".join(env.iso26262_trace_errors[:10])
        raise ExtensionError(f"traceability errors detected:{sample}")
