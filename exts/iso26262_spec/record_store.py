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
    if not hasattr(env, "iso26262_statement_anchor_ids"):
        env.iso26262_statement_anchor_ids = {}


def _record_error(env: BuildEnvironment, message: str) -> None:
    _ensure_env(env)
    env.iso26262_trace_errors.append(message)


def _register_record(
    env: BuildEnvironment, record: dict[str, Any], source_context: str
) -> None:
    _ensure_env(env)
    irm_id = record["id"]
    existing = env.iso26262_trace_records.get(irm_id)
    if existing is not None:
        existing_doc = existing.get("doc", "<unknown>")
        _record_error(
            env,
            f"duplicate IRM ID '{irm_id}' in {source_context}; "
            f"first seen in {existing_doc}",
        )
        return

    env.iso26262_trace_records[irm_id] = record
    env.iso26262_trace_order.append(irm_id)
    href = record.get("href", "")
    env.iso26262_statement_locations[irm_id] = href


def _register_statement_anchor(
    env: BuildEnvironment, anchor_id: str, irm_id: str, source_context: str
) -> None:
    _ensure_env(env)
    existing = env.iso26262_statement_anchor_ids.get(anchor_id)
    if existing is not None and existing != irm_id:
        _record_error(
            env,
            "duplicate statement anchor "
            f"'{anchor_id}' from distinct IRM IDs '{existing}' and '{irm_id}' "
            f"in {source_context}",
        )
        return
    env.iso26262_statement_anchor_ids[anchor_id] = irm_id
