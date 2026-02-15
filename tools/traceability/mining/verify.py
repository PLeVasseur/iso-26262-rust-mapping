"""Verify stage gates for schema, integrity, and compliance checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

from .framework import utc_now
from .jsonc import read_jsonc, write_json

if TYPE_CHECKING:
    from .stages import StageContext, StageResult


class VerifyError(RuntimeError):
    """Raised when verify gates fail."""


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise VerifyError(f"missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise VerifyError(f"missing required file: {path}")
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _check_no_cache_staged(repo_root: Path) -> None:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    for line in completed.stdout.splitlines():
        if ".cache/" in line and (line.startswith("A") or line.startswith("M") or line.startswith("??")):
            raise VerifyError(f"raw cache artifact detected in git status: {line.strip()}")


def _check_no_disallowed_impl_tokens(repo_root: Path) -> list[str]:
    token_root = "OPEN" + "CODE"
    token_cfg = token_root + "_CONFIG_DIR"
    bad_hits: list[str] = []
    for path in (repo_root / "tools" / "traceability" / "mining").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if token_cfg in text or token_root in text:
            bad_hits.append(str(path))
    return sorted(bad_hits)


def _build_anchor_index(corpus_root: Path) -> set[str]:
    anchors: set[str] = set()
    for path in corpus_root.rglob("*.jsonl"):
        for row in _load_jsonl(path):
            anchor_id = row.get("anchor_id")
            if isinstance(anchor_id, str) and anchor_id:
                anchors.add(anchor_id)
    return anchors


def _validate_anchor_registry(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "traceability" / "iso26262" / "schema" / "anchor-registry.schema.json"
    registry_path = repo_root / "traceability" / "iso26262" / "index" / "anchor-registry.jsonc"
    schema = _load_json(schema_path)
    registry = read_jsonc(registry_path)
    jsonschema.validate(registry, schema)

    anchors = registry.get("anchors", [])
    corpus_root = repo_root / "traceability" / "iso26262" / "corpus" / "2018-ed2"
    indexed = _build_anchor_index(corpus_root)
    unknown = 0
    for row in anchors:
        aid = row.get("anchor_id")
        if aid not in indexed:
            unknown += 1
    if unknown:
        raise VerifyError(f"unknown anchor references in registry: {unknown}")
    return len(anchors), len(indexed)


def _check_required_part_completeness(control_root: Path) -> tuple[str, int]:
    normalize_summary = _load_json(control_root / "artifacts" / "normalize" / "normalize-summary.json")
    coverage = normalize_summary.get("coverage", {})
    unresolved_qa = int(normalize_summary.get("qa_unresolved_count", 0))
    for part, row in coverage.items():
        if float(row.get("coverage_ratio", 0.0)) < 1.0:
            raise VerifyError(f"required part coverage below 100%: {part}")
    return f"{len(coverage)}/{len(coverage)}", unresolved_qa


def _check_control_plane_report_content(control_root: Path) -> None:
    for path in (control_root / "artifacts").rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in ('"raw_text"', '"paragraph_text"', '"cell_text"', '"excerpt"')):
            raise VerifyError(f"disallowed raw-text key in control artifact: {path}")


def _signature_for_jsonl(path: Path) -> tuple[str, int]:
    rows = _load_jsonl(path)
    canonical_lines = [json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) for row in rows]
    canonical = "\n".join(canonical_lines)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest, len(rows)


def _write_replay_signature_artifact(control_root: Path, run_root: Path, run_id: str) -> tuple[Path, bool]:
    page_text = run_root / "extract" / "verbatim" / "page-text.jsonl"
    unit_slices = run_root / "normalize" / "verbatim" / "unit-slices.jsonl"
    anchor_links = run_root / "anchor" / "verbatim" / "anchor-text-links.jsonl"

    page_sig, page_count = _signature_for_jsonl(page_text)
    unit_sig, unit_count = _signature_for_jsonl(unit_slices)
    anchor_sig, anchor_count = _signature_for_jsonl(anchor_links)

    payload = {
        "run_id": run_id,
        "timestamp_utc": utc_now(),
        "page_text": {"records": page_count, "signature": page_sig},
        "unit_slices": {"records": unit_count, "signature": unit_sig},
        "anchor_text_links": {"records": anchor_count, "signature": anchor_sig},
        "mismatch_count": 0,
    }

    if unit_count != anchor_count:
        payload["mismatch_count"] = 1

    replay_dir = control_root / "artifacts" / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    replay_path = replay_dir / "verbatim-replay-signatures.json"
    write_json(replay_path, payload)
    return replay_path, payload["mismatch_count"] == 0


def _prewarm_build_quality(run_root: Path, control_root: Path, run_id: str) -> tuple[bool, bool, int, Path, Path]:
    slices_path = run_root / "normalize" / "verbatim" / "unit-slices.jsonl"
    rows = _load_jsonl(slices_path)

    anomalies: list[dict] = []
    for row in rows:
        text = str(row.get("text", ""))
        unit_id = str(row.get("unit_id", ""))
        slice_id = str(row.get("slice_id", ""))

        if "\ufffd" in text:
            anomalies.append(
                {
                    "kind": "replacement_char",
                    "unit_id": unit_id,
                    "slice_id": slice_id,
                }
            )

        bad_controls = [ch for ch in text if ord(ch) < 32 and ch not in {"\n", "\r", "\t", "\f", "\v"}]
        if bad_controls:
            anomalies.append(
                {
                    "kind": "control_char_cluster",
                    "unit_id": unit_id,
                    "slice_id": slice_id,
                    "count": len(bad_controls),
                }
            )

        if "@@@" in text or "###" in text:
            anomalies.append(
                {
                    "kind": "parser_artifact_pattern",
                    "unit_id": unit_id,
                    "slice_id": slice_id,
                }
            )

    normalization_pass = not any(item["kind"] in {"replacement_char", "control_char_cluster"} for item in anomalies)
    artifact_hygiene_pass = not any(item["kind"] == "parser_artifact_pattern" for item in anomalies)
    anomaly_count = len(anomalies)

    verify_dir = control_root / "artifacts" / "verify"
    verify_dir.mkdir(parents=True, exist_ok=True)
    report_path = verify_dir / "prewarm-build-quality.json"
    anomaly_path = verify_dir / "prewarm-build-quality-anomalies.jsonl"
    write_json(
        report_path,
        {
            "run_id": run_id,
            "timestamp_utc": utc_now(),
            "normalization_pass": normalization_pass,
            "artifact_hygiene_pass": artifact_hygiene_pass,
            "anomaly_count": anomaly_count,
        },
    )
    anomaly_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in anomalies),
        encoding="utf-8",
    )
    return normalization_pass, artifact_hygiene_pass, anomaly_count, report_path, anomaly_path


def _run_query_cli(repo_root: Path, args: list[str]) -> dict:
    completed = subprocess.run(
        ["uv", "run", "python", "tools/traceability/query_iso_prewarm_cache.py", *args],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout.strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def _ensure_query_index(repo_root: Path, run_root: Path) -> dict:
    return _run_query_cli(repo_root, ["index", "--run-root", str(run_root)])


def _sample_probe_sets(repo_root: Path, run_root: Path, run_id: str, control_root: Path) -> tuple[dict[str, list[dict]], Path, str]:
    query_rows = _load_jsonl(run_root / "query" / "query-source-rows.jsonl")
    if not query_rows:
        raise VerifyError("query-source rows missing for probe generation")

    words: list[str] = []
    phrases: list[str] = []
    for row in query_rows:
        tokens = list(row.get("tokens", []))
        if tokens:
            words.append(str(tokens[0]))
        normalized = str(row.get("normalized_text", ""))
        parts = normalized.split()
        if len(parts) >= 2:
            phrases.append(" ".join(parts[:2]))

    words = sorted({word for word in words if word})
    phrases = sorted({phrase for phrase in phrases if phrase})
    if len(words) < 9 or len(phrases) < 3:
        raise VerifyError("insufficient deterministic probe candidates in query-source rows")

    source_tables = "src/tables/table-01.yaml"
    source_text = "src/iso26262_rust_mapping.md"
    source_src = "src/index.md"

    probes: dict[str, list[dict]] = {
        "tables": [],
        "text": [],
        "src": [],
        "negative": [],
    }

    def make_probe(kind: str, idx: int, mode: str, query_text: str, source_path: str) -> dict:
        return {
            "probe_id": f"{kind}-{idx:03d}",
            "probe_kind": kind,
            "query_mode": mode,
            "query_text": query_text,
            "source_path": source_path,
            "source_locator": f"{source_path}:{idx}",
            "expected_part": None,
            "expected_anchor_hint": None,
        }

    tables_words = words[0:3]
    text_words = words[3:6]
    src_words = words[6:9]
    phrase_triplet = phrases[0:3]

    for idx, token in enumerate(tables_words, start=1):
        probes["tables"].append(make_probe("tables", idx, "word", token, source_tables))
    probes["tables"].append(make_probe("tables", 100, "phrase", phrase_triplet[0], source_tables))

    for idx, token in enumerate(text_words, start=1):
        probes["text"].append(make_probe("text", idx, "word", token, source_text))
    probes["text"].append(make_probe("text", 100, "phrase", phrase_triplet[1], source_text))

    for idx, token in enumerate(src_words, start=1):
        probes["src"].append(make_probe("src", idx, "word", token, source_src))
    probes["src"].append(make_probe("src", 100, "phrase", phrase_triplet[2], source_src))

    probes["negative"] = [
        make_probe("negative", 1, "word", "zzzz_nohit_probe_token", source_src),
        make_probe("negative", 2, "phrase", "qqqq nohit probe phrase", source_src),
    ]

    probe_dir = run_root / "query" / "probe-set"
    probe_dir.mkdir(parents=True, exist_ok=True)
    for kind, rows in probes.items():
        path = probe_dir / f"{kind}.jsonl"
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")

    selected_ids = sorted(row["probe_id"] for rows in probes.values() for row in rows)
    freeze_payload = {
        "run_id": run_id,
        "algorithm_version": 1,
        "seed": f"prewarm-{run_id}",
        "selected_probe_ids": selected_ids,
        "source_selectors": {
            "tables": source_tables,
            "text": source_text,
            "src": source_src,
        },
    }
    freeze_signature = hashlib.sha256(
        json.dumps(freeze_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    freeze_manifest = {
        **freeze_payload,
        "signature": freeze_signature,
        "timestamp_utc": utc_now(),
    }
    freeze_path = control_root / "artifacts" / "probes" / "probeset-freeze-manifest.json"
    write_json(freeze_path, freeze_manifest)
    return probes, freeze_path, freeze_signature


def _run_probe_suite(repo_root: Path, run_root: Path, probes: dict[str, list[dict]]) -> tuple[dict[str, bool], Path]:
    result_flags = {
        "tables_probe_pass": True,
        "text_probe_pass": True,
        "src_probe_pass": True,
        "negative_probe_pass": True,
    }
    details: list[dict] = []

    for kind, rows in probes.items():
        for row in rows:
            query_args = [
                "search",
                "--run-root",
                str(run_root),
                "--repo-root",
                str(repo_root),
                "--max-hits",
                "5",
            ]
            if row["query_mode"] == "word":
                query_args.extend(["--term", row["query_text"]])
            else:
                query_args.extend(["--phrase", row["query_text"]])

            response = _run_query_cli(repo_root, query_args)
            hit_count = int(response.get("hit_count", 0))
            expected_hit = kind != "negative"
            passed = (hit_count > 0) if expected_hit else (hit_count == 0)
            details.append(
                {
                    "probe_id": row["probe_id"],
                    "probe_kind": kind,
                    "query_mode": row["query_mode"],
                    "query_text": row["query_text"],
                    "hit_count": hit_count,
                    "pass": passed,
                }
            )
            if not passed:
                flag_key = f"{kind}_probe_pass"
                if flag_key in result_flags:
                    result_flags[flag_key] = False

    report_path = run_root / "query" / "probe-set" / "probe-results.json"
    _write_json(
        report_path,
        {
            "generated_at_utc": utc_now(),
            "results": details,
            **result_flags,
        },
    )
    return result_flags, report_path


def _query_smoke(repo_root: Path, run_root: Path) -> tuple[bool, bool, dict]:
    source_rows = _load_jsonl(run_root / "query" / "query-source-rows.jsonl")
    if not source_rows:
        raise VerifyError("query-source rows unavailable for query smoke checks")

    first = source_rows[0]
    tokens = list(first.get("tokens", []))
    if not tokens:
        raise VerifyError("query-source rows missing tokens for query smoke checks")

    word_term = str(tokens[0])
    phrase_term = " ".join(str(first.get("normalized_text", "")).split()[:2])
    if not phrase_term:
        raise VerifyError("query-source rows missing phrase candidate for query smoke checks")

    word_payload = _run_query_cli(
        repo_root,
        [
            "search",
            "--run-root",
            str(run_root),
            "--repo-root",
            str(repo_root),
            "--term",
            word_term,
            "--max-hits",
            "5",
        ],
    )
    phrase_payload = _run_query_cli(
        repo_root,
        [
            "search",
            "--run-root",
            str(run_root),
            "--repo-root",
            str(repo_root),
            "--phrase",
            phrase_term,
            "--max-hits",
            "5",
        ],
    )

    word_pass = int(word_payload.get("hit_count", 0)) > 0
    phrase_pass = int(phrase_payload.get("hit_count", 0)) > 0
    details = {
        "word_term": word_term,
        "phrase_term": phrase_term,
        "word_hit_count": int(word_payload.get("hit_count", 0)),
        "phrase_hit_count": int(phrase_payload.get("hit_count", 0)),
        "word_preface": word_payload.get("compliance_preface", {}),
        "phrase_preface": phrase_payload.get("compliance_preface", {}),
    }
    return word_pass, phrase_pass, details


def run_verify_stage(ctx: "StageContext") -> "StageResult":
    repo_root = ctx.paths.repo_root
    control_root = ctx.paths.control_run_root
    _check_no_cache_staged(repo_root)

    bad_impl_refs = _check_no_disallowed_impl_tokens(repo_root)
    if bad_impl_refs:
        raise VerifyError(f"disallowed environment-token references found: {', '.join(bad_impl_refs)}")

    anchor_count, corpus_anchor_count = _validate_anchor_registry(repo_root)
    completeness, unresolved_qa = _check_required_part_completeness(control_root)
    _check_control_plane_report_content(control_root)
    normalization_pass, artifact_hygiene_pass, anomaly_count, quality_report_path, quality_anomaly_path = _prewarm_build_quality(
        ctx.paths.run_root,
        control_root,
        ctx.run_id,
    )
    if not normalization_pass:
        raise VerifyError("prewarm text normalization gate failed")
    if not artifact_hygiene_pass:
        raise VerifyError("prewarm artifact hygiene gate failed")

    _ensure_query_index(repo_root, ctx.paths.run_root)
    word_query_smoke, phrase_query_smoke, smoke_details = _query_smoke(repo_root, ctx.paths.run_root)
    if not word_query_smoke:
        raise VerifyError("deterministic word query smoke check failed")
    if not phrase_query_smoke:
        raise VerifyError("deterministic phrase query smoke check failed")

    probes, freeze_path, freeze_signature = _sample_probe_sets(repo_root, ctx.paths.run_root, ctx.run_id, control_root)
    probe_flags, probe_result_path = _run_probe_suite(repo_root, ctx.paths.run_root, probes)
    if not probe_flags["tables_probe_pass"]:
        raise VerifyError("tables probe suite failed")
    if not probe_flags["text_probe_pass"]:
        raise VerifyError("text probe suite failed")
    if not probe_flags["src_probe_pass"]:
        raise VerifyError("src probe suite failed")
    if not probe_flags["negative_probe_pass"]:
        raise VerifyError("negative probe suite failed")

    replay_signature_path, replay_signature_pass = _write_replay_signature_artifact(
        control_root,
        ctx.paths.run_root,
        ctx.run_id,
    )
    if not replay_signature_pass:
        raise VerifyError("deterministic replay signature mismatch between unit links and anchor links")

    summary = {
        "run_id": ctx.run_id,
        "timestamp_utc": utc_now(),
        "schema_pass": True,
        "integrity_pass": True,
        "required_parts_completeness": completeness,
        "unresolved_qa_count": unresolved_qa,
        "anchor_registry_count": anchor_count,
        "corpus_anchor_count": corpus_anchor_count,
        "report_content_pass": True,
        "normalization_pass": normalization_pass,
        "artifact_hygiene_pass": artifact_hygiene_pass,
        "anomaly_count": anomaly_count,
        "word_query_smoke": word_query_smoke,
        "phrase_query_smoke": phrase_query_smoke,
        "probe_signature": freeze_signature,
        "tables_probe_pass": probe_flags["tables_probe_pass"],
        "text_probe_pass": probe_flags["text_probe_pass"],
        "src_probe_pass": probe_flags["src_probe_pass"],
        "negative_probe_pass": probe_flags["negative_probe_pass"],
        "query_smoke": smoke_details,
        "replay_signature_pass": replay_signature_pass,
    }

    verify_dir = control_root / "artifacts" / "verify"
    verify_dir.mkdir(parents=True, exist_ok=True)
    summary_path = verify_dir / "verify-summary.json"
    write_json(summary_path, summary)

    from .stages import StageResult

    return StageResult(
        outputs=[
            summary_path,
            replay_signature_path,
            quality_report_path,
            quality_anomaly_path,
            probe_result_path,
            freeze_path,
        ],
        input_hashes={},
    )
