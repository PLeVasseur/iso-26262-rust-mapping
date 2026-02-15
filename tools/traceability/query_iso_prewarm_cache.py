#!/usr/bin/env python3
"""Deterministic query CLI over run-scoped ISO 26262 prewarm caches."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


GUIDELINES_PATH = "docs/traceability-ts-and-quotation-guidelines.md"
ANCHOR_REGISTRY_PATH = "traceability/iso26262/index/anchor-registry.jsonc"
CORPUS_MANIFEST_PATH = "traceability/iso26262/index/corpus-manifest.jsonc"
TS_ALLOWED = {"mapped", "unmapped_with_rationale", "out_of_scope_with_rationale"}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_slice_rows(run_root: Path) -> list[dict[str, Any]]:
    return _read_jsonl(run_root / "normalize" / "verbatim" / "unit-slices.jsonl")


def _load_anchor_map(run_root: Path) -> dict[str, str]:
    rows = _read_jsonl(run_root / "anchor" / "verbatim" / "anchor-text-links.jsonl")
    mapping: dict[str, str] = {}
    for row in rows:
        unit_id = str(row.get("unit_id", ""))
        anchor_id = str(row.get("anchor_id", ""))
        if unit_id and anchor_id:
            mapping[unit_id] = anchor_id
    return mapping


def _load_unit_locator_map(run_root: Path) -> dict[str, dict[str, Any]]:
    path = run_root / "normalize" / "anchored-units.jsonl"
    if not path.exists():
        return {}
    rows = _read_jsonl(path)
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        unit_id = str(row.get("unit_id", ""))
        if unit_id:
            mapping[unit_id] = row
    return mapping


def _posting_key(row: dict[str, Any]) -> tuple[Any, ...]:
    locator = row.get("source_locator", {})
    return (
        str(row.get("part", "")),
        int(row.get("page", 0)),
        str(row.get("unit_type", "")),
        str(row.get("anchor_id", "")),
        str(row.get("unit_id", "")),
        str(row.get("slice_id", "")),
        str(locator.get("clause", "")),
    )


def _build_rows(run_root: Path) -> list[dict[str, Any]]:
    slices = _load_slice_rows(run_root)
    anchors = _load_anchor_map(run_root)
    unit_map = _load_unit_locator_map(run_root)

    rows: list[dict[str, Any]] = []
    for row in slices:
        unit_id = str(row.get("unit_id", ""))
        anchor_id = anchors.get(unit_id, "")
        unit_info = unit_map.get(unit_id, {})
        source_locator = row.get("source_locator", unit_info.get("source_locator", {}))
        normalized_text = _normalize(str(row.get("text", "")))
        posting = {
            "anchor_id": anchor_id,
            "unit_id": unit_id,
            "part": str(row.get("part", "")),
            "page": int(row.get("page", 0)),
            "unit_type": str(row.get("unit_type", "")),
            "slice_id": str(row.get("slice_id", "")),
            "source_locator": source_locator,
            "normalized_text": normalized_text,
            "text": str(row.get("text", "")),
        }
        rows.append(posting)

    rows.sort(key=_posting_key)
    return rows


def _build_index(args: argparse.Namespace) -> int:
    run_root = Path(args.run_root).resolve()
    query_root = run_root / "query"
    inverted_dir = query_root / "inverted-index"
    phrase_dir = query_root / "phrase-index"
    inverted_dir.mkdir(parents=True, exist_ok=True)
    phrase_dir.mkdir(parents=True, exist_ok=True)

    rows = _build_rows(run_root)

    token_postings: dict[str, list[dict[str, Any]]] = {}
    phrase_postings: dict[str, list[dict[str, Any]]] = {}

    for posting in rows:
        tokens = _tokens(posting["normalized_text"])
        seen_tokens: set[str] = set()
        for token in tokens:
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)
            token_postings.setdefault(token, []).append(posting)

        token_limit = min(len(tokens), 40)
        for n in (2, 3):
            if token_limit < n:
                continue
            seen_phrases: set[str] = set()
            for i in range(0, token_limit - n + 1):
                phrase = " ".join(tokens[i : i + n])
                if phrase in seen_phrases:
                    continue
                seen_phrases.add(phrase)
                phrase_postings.setdefault(phrase, []).append(posting)

        full_phrase = posting["normalized_text"]
        if full_phrase:
            phrase_postings.setdefault(full_phrase, []).append(posting)

    token_rows: list[dict[str, Any]] = []
    for token in sorted(token_postings.keys()):
        postings = sorted(token_postings[token], key=_posting_key)
        serialized = json.dumps(postings, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        token_rows.append(
            {
                "token": token,
                "posting_count": len(postings),
                "checksum": _sha256_text(serialized),
                "postings": postings,
            }
        )

    phrase_rows: list[dict[str, Any]] = []
    for phrase in sorted(phrase_postings.keys()):
        postings = sorted(phrase_postings[phrase], key=_posting_key)
        serialized = json.dumps(postings, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        phrase_rows.append(
            {
                "phrase": phrase,
                "posting_count": len(postings),
                "checksum": _sha256_text(serialized),
                "postings": postings,
            }
        )

    inverted_shard = inverted_dir / "tokens-0001.jsonl"
    phrase_shard = phrase_dir / "phrases-0001.jsonl"
    _write_jsonl(inverted_shard, token_rows)
    _write_jsonl(phrase_shard, phrase_rows)

    signature_payload = {
        "schema_version": 1,
        "inverted_shards": [str(inverted_shard.relative_to(run_root))],
        "phrase_shards": [str(phrase_shard.relative_to(run_root))],
        "token_count": len(token_rows),
        "phrase_count": len(phrase_rows),
    }
    signature = _sha256_text(json.dumps(signature_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    manifest = {
        **signature_payload,
        "run_root": str(run_root),
        "signature": signature,
    }
    manifest_path = query_root / "index-manifest.json"
    _write_json(manifest_path, manifest)

    print(json.dumps({"manifest": str(manifest_path), "token_count": len(token_rows), "phrase_count": len(phrase_rows)}, sort_keys=True))
    return 0


def _load_manifest(run_root: Path) -> dict[str, Any]:
    manifest_path = run_root / "query" / "index-manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"missing index manifest: {manifest_path}")
    return _read_json(manifest_path)


def _load_posting_map(run_root: Path, key_name: str) -> dict[str, list[dict[str, Any]]]:
    manifest = _load_manifest(run_root)
    shard_key = "inverted_shards" if key_name == "token" else "phrase_shards"
    postings: dict[str, list[dict[str, Any]]] = {}
    for rel in manifest.get(shard_key, []):
        shard_path = run_root / str(rel)
        for row in _read_jsonl(shard_path):
            key = str(row.get(key_name, ""))
            if not key:
                continue
            postings[key] = list(row.get("postings", []))
    return postings


def _filter_hit(hit: dict[str, Any], args: argparse.Namespace) -> bool:
    locator = hit.get("source_locator", {})
    if args.part and str(hit.get("part", "")) != args.part:
        return False
    if args.unit_type and str(hit.get("unit_type", "")) != args.unit_type:
        return False
    if args.page is not None and int(hit.get("page", 0)) != args.page:
        return False
    if args.anchor_id and str(hit.get("anchor_id", "")) != args.anchor_id:
        return False
    if args.clause and str(locator.get("clause", "")) != args.clause:
        return False
    return True


def _row_hint(repo_root: Path, part: str, unit_type: str, anchor_id: str) -> tuple[int, str]:
    part_lower = part.lower()
    shard_name = f"{unit_type}-0001.jsonl"
    shard_path = repo_root / "traceability" / "iso26262" / "corpus" / "2018-ed2" / part_lower / shard_name
    if not shard_path.exists():
        return 1, f"traceability/iso26262/corpus/2018-ed2/{part_lower}/{shard_name}"

    line_number = 0
    for line in shard_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        line_number += 1
        row = json.loads(line)
        if str(row.get("anchor_id", "")) == anchor_id:
            return line_number, f"traceability/iso26262/corpus/2018-ed2/{part_lower}/{shard_name}"
    return 1, f"traceability/iso26262/corpus/2018-ed2/{part_lower}/{shard_name}"


def _ts_bundle(anchor_id: str, unit_id: str) -> dict[str, Any]:
    ts_token = "mapped"
    if ts_token not in TS_ALLOWED:
        raise SystemExit("invalid ts token configuration")
    dp_value = f"auto_{unit_id}"
    return {
        "ts_token": ts_token,
        "companion_roles": {
            "dp": dp_value,
            "rel": "direct",
            "a": anchor_id,
        },
        "myst_snippet": f"{{dp}}`{dp_value}` {{ts}}`mapped` {{rel}}`direct` {{a}}`{anchor_id}`",
    }


def _guarded_quote(text: str, enabled: bool) -> tuple[str, bool]:
    if not enabled:
        return "", False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", True
    quote = "\n".join(lines[:2])
    if len(quote) > 240:
        quote = quote[:240]
    return quote, True


def _search(args: argparse.Namespace) -> int:
    run_root = Path(args.run_root).resolve()
    repo_root = Path(args.repo_root).resolve()
    term = _normalize(args.term) if args.term else ""
    phrase = _normalize(args.phrase) if args.phrase else ""

    if bool(term) == bool(phrase):
        raise SystemExit("exactly one of --term or --phrase is required")

    token_map = _load_posting_map(run_root, "token")
    phrase_map = _load_posting_map(run_root, "phrase")
    candidate_hits: list[dict[str, Any]]

    if term:
        candidate_hits = list(token_map.get(term, []))
    else:
        candidate_hits = list(phrase_map.get(phrase, []))
        if not candidate_hits:
            candidate_hits = [row for row in _build_rows(run_root) if phrase in str(row.get("normalized_text", ""))]

    filtered = [hit for hit in candidate_hits if _filter_hit(hit, args)]
    filtered.sort(key=_posting_key)

    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for hit in filtered:
        key = (str(hit.get("anchor_id", "")), str(hit.get("unit_id", "")), str(hit.get("slice_id", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)

    max_hits = max(1, int(args.max_hits))
    deduped = deduped[:max_hits]

    result_hits: list[dict[str, Any]] = []
    for rank, hit in enumerate(deduped, start=1):
        part = str(hit.get("part", ""))
        anchor_id = str(hit.get("anchor_id", ""))
        unit_type = str(hit.get("unit_type", "paragraph"))
        row_hint, shard_rel = _row_hint(repo_root, part, unit_type, anchor_id)
        quote, fair_use = _guarded_quote(str(hit.get("text", "")), args.quote)

        out_hit: dict[str, Any] = {
            "rank": rank,
            "anchor_id": anchor_id,
            "unit_id": str(hit.get("unit_id", "")),
            "part": part,
            "page": int(hit.get("page", 0)),
            "unit_type": unit_type,
            "source_locator": hit.get("source_locator", {}),
            "cache_refs": {
                "slice_id": str(hit.get("slice_id", "")),
                "record_id": f"{part}:{int(hit.get('page', 0))}",
            },
            "lookup_pointers": {
                "anchor_registry_path": ANCHOR_REGISTRY_PATH,
                "corpus_manifest_path": CORPUS_MANIFEST_PATH,
                "part_manifest_path": f"traceability/iso26262/corpus/2018-ed2/{part.lower()}/part-manifest.jsonc",
                "part_shard_path": shard_rel,
                "jsonl_row_hint": row_hint,
                "json_pointer_hint": f"/anchors/{max(0, row_hint - 1)}",
            },
            "ts_authoring_bundle": _ts_bundle(anchor_id=anchor_id, unit_id=str(hit.get("unit_id", ""))),
        }

        if args.quote:
            out_hit["quote"] = quote
            out_hit["fair_use_brief_quote"] = fair_use

        result_hits.append(out_hit)

    payload = {
        "compliance_preface": {
            "ts_usage_reminder": "Use {ts} tokens appropriately in downstream authored outputs.",
            "guideline_pointer_path": GUIDELINES_PATH,
        },
        "query": {
            "mode": "term" if term else "phrase",
            "value": term if term else phrase,
            "quote_mode": bool(args.quote),
            "fair_use_brief_quote": bool(args.quote),
        },
        "hit_count": len(result_hits),
        "hits": result_hits,
    }
    print(json.dumps(payload, indent=2, sort_keys=False))
    return 0


def _explain(args: argparse.Namespace) -> int:
    run_root = Path(args.run_root).resolve()
    if bool(args.anchor_id) == bool(args.unit_id):
        raise SystemExit("exactly one of --anchor-id or --unit-id is required")

    anchor_rows = _read_jsonl(run_root / "anchor" / "verbatim" / "anchor-text-links.jsonl")
    slice_rows = _read_jsonl(run_root / "normalize" / "verbatim" / "unit-slices.jsonl")
    by_unit: dict[str, list[dict[str, Any]]] = {}
    for row in slice_rows:
        by_unit.setdefault(str(row.get("unit_id", "")), []).append(row)

    target: dict[str, Any] | None = None
    for row in anchor_rows:
        if args.anchor_id and str(row.get("anchor_id", "")) == args.anchor_id:
            target = row
            break
        if args.unit_id and str(row.get("unit_id", "")) == args.unit_id:
            target = row
            break

    if target is None:
        print(json.dumps({"found": False}, indent=2, sort_keys=True))
        return 0

    unit_id = str(target.get("unit_id", ""))
    slices = sorted(by_unit.get(unit_id, []), key=lambda row: str(row.get("slice_id", "")))
    payload = {
        "found": True,
        "guideline_pointer_path": GUIDELINES_PATH,
        "lineage": {
            "anchor_id": str(target.get("anchor_id", "")),
            "unit_id": unit_id,
            "part": str(target.get("part", "")),
            "unit_type": str(target.get("unit_type", "")),
            "slice_ids": list(target.get("slice_ids", [])),
            "text_sha256_set": list(target.get("text_sha256_set", [])),
            "slices": slices,
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query run-scoped ISO 26262 prewarm cache artifacts")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Build deterministic token and phrase index shards")
    p_index.add_argument("--run-root", required=True)
    p_index.set_defaults(func=_build_index)

    p_search = sub.add_parser("search", help="Search indexed words or phrases")
    p_search.add_argument("--run-root", required=True)
    p_search.add_argument("--repo-root", required=True)
    p_search.add_argument("--term", default="")
    p_search.add_argument("--phrase", default="")
    p_search.add_argument("--part", default="")
    p_search.add_argument("--unit-type", default="")
    p_search.add_argument("--clause", default="")
    p_search.add_argument("--page", type=int)
    p_search.add_argument("--anchor-id", default="")
    p_search.add_argument("--quote", action="store_true")
    p_search.add_argument("--max-hits", type=int, default=20)
    p_search.set_defaults(func=_search)

    p_explain = sub.add_parser("explain", help="Explain query lineage from anchor or unit")
    p_explain.add_argument("--run-root", required=True)
    p_explain.add_argument("--anchor-id", default="")
    p_explain.add_argument("--unit-id", default="")
    p_explain.set_defaults(func=_explain)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
