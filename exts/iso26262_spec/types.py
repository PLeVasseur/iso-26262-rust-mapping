from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PrefaceMetadata:
    irm_id: str
    trace_status: str
    anchor_ids: list[str]
    relation: str
    inline_body: str
