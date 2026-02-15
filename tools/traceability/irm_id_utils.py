from __future__ import annotations

import re
import secrets
from typing import Iterable

IRM_ID_PATTERN = re.compile(r"^irm_[A-Za-z0-9]{12}$")
IRM_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def is_valid_irm_id(value: str) -> bool:
    return bool(IRM_ID_PATTERN.match(value))


def mint_irm_id(existing_ids: Iterable[str]) -> str:
    seen = set(existing_ids)
    while True:
        payload = "".join(secrets.choice(IRM_ID_ALPHABET) for _ in range(12))
        candidate = f"irm_{payload}"
        if candidate not in seen:
            return candidate
