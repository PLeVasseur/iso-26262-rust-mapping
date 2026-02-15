from __future__ import annotations

from typing import Any

from sphinx.environment import BuildEnvironment


def _ensure_env(env: BuildEnvironment) -> None:
    if not hasattr(env, "iso26262_trace_records"):
        env.iso26262_trace_records = {}
    if not hasattr(env, "iso26262_trace_order"):
        env.iso26262_trace_order = []
    if not hasattr(env, "iso26262_trace_errors"):
        env.iso26262_trace_errors = []
    if not hasattr(env, "iso26262_doc_statement_ids"):
        env.iso26262_doc_statement_ids = {}
    if not hasattr(env, "iso26262_doc_missing_units"):
        env.iso26262_doc_missing_units = {}
    if not hasattr(env, "iso26262_statement_locations"):
        env.iso26262_statement_locations = {}
    if not hasattr(env, "iso26262_anchor_registry_ids"):
        env.iso26262_anchor_registry_ids = set()


def _record_error(env: BuildEnvironment, message: str) -> None:
    _ensure_env(env)
    env.iso26262_trace_errors.append(message)


def _register_record(
    env: BuildEnvironment, record: dict[str, Any], source_context: str
) -> None:
    _ensure_env(env)
    source_id = record["id"]
    existing = env.iso26262_trace_records.get(source_id)
    if existing is not None:
        existing_doc = existing.get("doc", "<unknown>")
        _record_error(
            env,
            f"duplicate source_id '{source_id}' in {source_context}; "
            f"first seen in {existing_doc}",
        )
        return

    env.iso26262_trace_records[source_id] = record
    env.iso26262_trace_order.append(source_id)
    href = record.get("href", "")
    env.iso26262_statement_locations[source_id] = href
