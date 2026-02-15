"""Canonical constants for mining stages and policies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

STAGES = ("ingest", "extract", "normalize", "anchor", "publish", "verify", "finalize")

CHECKLIST_KEYS: dict[str, tuple[str, ...]] = {
    "ingest": (
        "CB_INGEST_SOURCE_PDFSET_VALID",
        "CB_INGEST_REQUIRED_PARTS_FOUND",
        "CB_INGEST_HASHES_VERIFIED",
        "CB_INGEST_STATE_INITIALIZED",
        "CB_INGEST_SUMMARY_WRITTEN",
    ),
    "extract": (
        "CB_EXTRACT_PRIMARY_EVAL_COMPLETE",
        "CB_EXTRACT_FALLBACK_COMPLETE",
        "CB_EXTRACT_PAGE_DECISIONS_WRITTEN",
        "CB_EXTRACT_SUMMARY_WRITTEN",
    ),
    "normalize": (
        "CB_NORMALIZE_UNITS_WRITTEN",
        "CB_NORMALIZE_COVERAGE_COMPUTED",
        "CB_NORMALIZE_QA_QUEUE_WRITTEN",
        "CB_NORMALIZE_SUMMARY_WRITTEN",
    ),
    "anchor": (
        "CB_ANCHOR_IDS_WRITTEN",
        "CB_ANCHOR_DEDUP_CHECK_PASS",
        "CB_ANCHOR_SUMMARY_WRITTEN",
    ),
    "publish": (
        "CB_PUBLISH_SHARDS_WRITTEN",
        "CB_PUBLISH_REGISTRY_WRITTEN",
        "CB_PUBLISH_QA_GATE_PASS",
        "CB_PUBLISH_TRANSACTION_COMMIT",
    ),
    "verify": (
        "CB_VERIFY_SCHEMA_PASS",
        "CB_VERIFY_INTEGRITY_PASS",
        "CB_VERIFY_REQUIRED_PARTS_PASS",
        "CB_VERIFY_REPORT_CONTENT_PASS",
        "CB_VERIFY_SUMMARY_WRITTEN",
    ),
    "finalize": (
        "CB_FINALIZE_REPORT_APPENDED",
        "CB_FINALIZE_STATE_FLAGS_WRITTEN",
        "CB_FINALIZE_LOCK_RELEASED",
    ),
}

DONE_FLAGS: dict[str, str] = {
    "ingest": "S_INGEST_DONE",
    "extract": "S_EXTRACT_DONE",
    "normalize": "S_NORMALIZE_DONE",
    "anchor": "S_ANCHOR_DONE",
    "publish": "S_PUBLISH_DONE",
    "verify": "S_VERIFY_DONE",
    "finalize": "S_FINALIZE_DONE",
}

DEFAULT_REQUIRED_PARTS = ("P06", "P08", "P09")

PREFERRED_FILENAMES: dict[str, str] = {
    "P06": "ISO 26262-6;2018 ed.2 (en).pdf",
    "P08": "ISO 26262-8;2018 ed.2 (en).pdf",
    "P09": "ISO 26262-9;2018 ed.2 (en).pdf",
}

FALLBACK_PATTERNS: dict[str, str] = {
    "P06": r"(?i)^ISO\s*26262[-; ]6.*2018.*ed\.?\s*2.*\.pdf$",
    "P08": r"(?i)^ISO\s*26262[-; ]8.*2018.*ed\.?\s*2.*\.pdf$",
    "P09": r"(?i)^ISO\s*26262[-; ]9.*2018.*ed\.?\s*2.*\.pdf$",
}


@dataclass(frozen=True)
class DefaultPaths:
    """Default runtime paths relative to repo root."""

    source_pdfset: Path
    relevant_policy: Path
    extraction_policy: Path
