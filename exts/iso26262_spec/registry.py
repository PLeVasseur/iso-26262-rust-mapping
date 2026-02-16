from __future__ import annotations

from pathlib import Path

from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment

from .record_store import _ensure_env, _record_error
from .utils import _read_jsonc


def _load_anchor_registry(app: Sphinx, env: BuildEnvironment) -> None:
    _ensure_env(env)
    registry_path = Path(app.config.iso26262_anchor_registry_path)
    if not registry_path.exists():
        _record_error(env, f"anchor registry missing: {registry_path}")
        return

    try:
        payload = _read_jsonc(registry_path)
    except Exception as exc:
        _record_error(env, f"failed to parse anchor registry {registry_path}: {exc}")
        return

    anchors: set[str] = set()
    for item in payload.get("anchors", []):
        if isinstance(item, dict):
            anchor_id = str(item.get("anchor_id", "")).strip()
            if anchor_id:
                anchors.add(anchor_id)

    env.iso26262_anchor_registry_ids = anchors
