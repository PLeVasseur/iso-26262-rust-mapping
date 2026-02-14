from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

project = "ISO 26262 Rust Mapping"
author = "Safety-Critical Rust Consortium"
copyright = "2026, Safety-Critical Rust Consortium"

extensions = [
    "myst_parser",
    "exts.iso26262_spec",
    "exts.iso26262_spec_lints",
]

source_suffix = {
    ".md": "markdown",
}

master_doc = "index"
exclude_patterns = [
    "_build",
]

nitpicky = True
show_warning_types = True
suppress_warnings: list[str] = []

html_theme = "alabaster"
html_static_path: list[str] = []

myst_enable_extensions = [
    "colon_fence",
]

iso26262_trace_statuses = [
    "mapped",
    "unmapped_with_rationale",
    "out_of_scope_with_rationale",
]

iso26262_trace_schema_path = str(
    REPO_ROOT / "traceability" / "iso26262" / "schema" / "anchor-registry.schema.json"
)
iso26262_anchor_registry_path = str(
    REPO_ROOT / "traceability" / "iso26262" / "index" / "anchor-registry.jsonc"
)
iso26262_table_root = str(REPO_ROOT / "src" / "tables")

iso26262_run_root = os.environ.get("SPHINX_MIGRATION_RUN_ROOT", "")
iso26262_opencode_config_dir = os.environ.get("OPENCODE_CONFIG_DIR", "")
