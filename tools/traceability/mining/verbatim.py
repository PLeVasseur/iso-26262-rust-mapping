"""Deterministic helpers for run-scoped verbatim cache artifacts."""

from __future__ import annotations

import hashlib
import re


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def page_record_id(part: str, page: int, method: str, content_sha256: str) -> str:
    raw = f"{part}:{page}:{method}:{content_sha256}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def block_id(record_id: str, block_ordinal: int, content_sha256: str) -> str:
    raw = f"{record_id}:{block_ordinal}:{content_sha256}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_for_query(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def split_page_blocks(text: str) -> list[tuple[int, int, str]]:
    if not text:
        return [(0, 0, "")]

    blocks: list[tuple[int, int, str]] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        start = offset
        end = offset + len(line)
        if line.strip():
            blocks.append((start, end, line))
        offset += len(raw_line)

    if not blocks:
        blocks.append((0, 0, ""))
    return blocks
