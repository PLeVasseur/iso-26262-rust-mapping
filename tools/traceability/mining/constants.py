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
        "CB_INGEST_VERBATIM_ROOT_READY",
        "CB_INGEST_SCHEMA_PATHS_LOCKED",
    ),
    "extract": (
        "CB_EXTRACT_PRIMARY_EVAL_COMPLETE",
        "CB_EXTRACT_FALLBACK_COMPLETE",
        "CB_EXTRACT_PAGE_DECISIONS_WRITTEN",
        "CB_EXTRACT_PAGE_TEXT_WRITTEN",
        "CB_EXTRACT_PAGE_BLOCKS_WRITTEN",
        "CB_EXTRACT_PAGE_INDEX_WRITTEN",
    ),
    "normalize": (
        "CB_NORMALIZE_UNITS_WRITTEN",
        "CB_NORMALIZE_UNIT_SLICES_WRITTEN",
        "CB_NORMALIZE_UNIT_TEXT_LINKS_WRITTEN",
        "CB_NORMALIZE_QUERY_SOURCE_ROWS_WRITTEN",
        "CB_NORMALIZE_COVERAGE_COMPUTED",
        "CB_NORMALIZE_QA_QUEUE_WRITTEN",
    ),
    "anchor": (
        "CB_ANCHOR_IDS_WRITTEN",
        "CB_ANCHOR_TEXT_LINKS_WRITTEN",
        "CB_ANCHOR_LINK_INDEX_WRITTEN",
        "CB_ANCHOR_QUERY_INDEX_BOUND",
        "CB_ANCHOR_LINK_BIJECTION_PASS",
        "CB_ANCHOR_SUMMARY_WRITTEN",
    ),
    "publish": (
        "CB_PUBLISH_SHARDS_WRITTEN",
        "CB_PUBLISH_REGISTRY_WRITTEN",
        "CB_PUBLISH_NON_VERBATIM_ONLY_PASS",
        "CB_PUBLISH_QA_GATE_PASS",
        "CB_PUBLISH_TRANSACTION_COMMIT",
    ),
    "verify": (
        "CB_VERIFY_SCHEMA_PASS",
        "CB_VERIFY_INTEGRITY_PASS",
        "CB_VERIFY_VERBATIM_CACHE_COMPLETENESS_PASS",
        "CB_VERIFY_PREWARM_TEXT_NORMALIZATION_PASS",
        "CB_VERIFY_PREWARM_ARTIFACT_HYGIENE_PASS",
        "CB_VERIFY_ANCHOR_LINK_COMPLETENESS_PASS",
        "CB_VERIFY_QUERY_INDEX_COMPLETENESS_PASS",
        "CB_VERIFY_QUERY_TOOL_SMOKE_PASS",
        "CB_VERIFY_QUERY_PROBESET_TABLES_PASS",
        "CB_VERIFY_QUERY_PROBESET_TEXT_PASS",
        "CB_VERIFY_QUERY_PROBESET_SRC_PASS",
        "CB_VERIFY_QUERY_PROBESET_NEGATIVE_PASS",
        "CB_VERIFY_PROBESET_FREEZE_PASS",
        "CB_VERIFY_QUERY_OUTPUT_GUARDRAILS_PASS",
        "CB_VERIFY_QUERY_QUOTE_FAIR_USE_PASS",
        "CB_VERIFY_TS_AUTHORING_BUNDLE_PASS",
        "CB_VERIFY_TS_JSON_LOOKUP_POINTERS_PASS",
        "CB_VERIFY_TS_GUIDELINES_PATH_PASS",
        "CB_VERIFY_SRC_PARAGRAPH_INTEGRATION_PASS",
        "CB_VERIFY_SRC_LIST_INTEGRATION_PASS",
        "CB_VERIFY_SRC_TABLE_INTEGRATION_PASS",
        "CB_VERIFY_SRC_INTEGRATION_MANIFEST_PASS",
        "CB_VERIFY_SRC_REVERT_CLEAN_PASS",
        "CB_VERIFY_MAKEPY_E2E_PASS",
        "CB_VERIFY_CONTROL_PLANE_NO_TEXT_PASS",
        "CB_VERIFY_NO_CACHE_TRACKED_PASS",
        "CB_VERIFY_REPLAY_SIGNATURE_PASS",
        "CB_VERIFY_SUMMARY_WRITTEN",
    ),
    "finalize": (
        "CB_FINALIZE_VERBATIM_SUMMARY_WRITTEN",
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
