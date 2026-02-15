from __future__ import annotations

from typing import Any

from sphinx.application import Sphinx

from .constants import TRACE_STATUSES
from .directives import TraceMetaDirective
from .domain import TraceDomain
from .events import (
    _on_builder_inited,
    _on_build_finished,
    _on_doctree_read,
    _on_doctree_resolved,
    _on_env_merge_info,
    _on_env_purge_doc,
)
from .roles import ARole, DpRole, PRole, RelRole, TsRole
from .table_directive import IsoTableDirective


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_config_value("iso26262_trace_statuses", sorted(TRACE_STATUSES), "env")
    app.add_config_value("iso26262_trace_schema_path", "", "env")
    app.add_config_value("iso26262_anchor_registry_path", "", "env")
    app.add_config_value("iso26262_table_root", "", "env")
    app.add_config_value("iso26262_run_root", "", "env")
    app.add_config_value("iso26262_irm_id_strict_mode", False, "env")

    app.add_domain(TraceDomain)

    app.add_role("dp", DpRole())
    app.add_role("ts", TsRole())
    app.add_role("trace-status", TsRole())
    app.add_role("a", ARole())
    app.add_role("rel", RelRole())
    app.add_role("p", PRole())

    app.add_directive("trace-meta", TraceMetaDirective)
    app.add_directive("iso-table", IsoTableDirective)

    app.connect("builder-inited", _on_builder_inited)
    app.connect("env-purge-doc", _on_env_purge_doc)
    app.connect("env-merge-info", _on_env_merge_info)
    app.connect("doctree-read", _on_doctree_read)
    app.connect("doctree-resolved", _on_doctree_resolved)
    app.connect("build-finished", _on_build_finished)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
        "env_version": 1,
    }
