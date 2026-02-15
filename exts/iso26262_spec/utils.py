from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def _statement_anchor_from_irm_id(irm_id: str) -> str:
    return irm_id.strip()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_jsonc(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8")
    stripped = re.sub(r"//.*$", "", raw, flags=re.MULTILINE)
    return json.loads(stripped)
