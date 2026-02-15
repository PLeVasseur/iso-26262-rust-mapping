from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sphinx.environment import BuildEnvironment


def _ensure_env(env: BuildEnvironment) -> None:
    if not hasattr(env, "iso26262_trace_errors"):
        env.iso26262_trace_errors = []
    if not hasattr(env, "iso26262_trace_records"):
        env.iso26262_trace_records = {}
    if not hasattr(env, "iso26262_doc_missing_units"):
        env.iso26262_doc_missing_units = {}


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
