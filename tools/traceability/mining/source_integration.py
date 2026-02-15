"""Helpers for deterministic query-driven source insertion transactions."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _query_search(
    repo_root: Path, run_root: Path, *, term: str = "", phrase: str = ""
) -> dict[str, Any]:
    args = [
        "uv",
        "run",
        "python",
        "tools/traceability/query_iso_prewarm_cache.py",
        "search",
        "--run-root",
        str(run_root),
        "--repo-root",
        str(repo_root),
        "--max-hits",
        "1",
    ]
    if term:
        args.extend(["--term", term])
    elif phrase:
        args.extend(["--phrase", phrase])
    else:
        raise RuntimeError("query requires term or phrase")

    completed = subprocess.run(
        args, cwd=str(repo_root), check=True, capture_output=True, text=True
    )
    payload = json.loads(completed.stdout)
    return payload


def _best_hit(repo_root: Path, run_root: Path, seed_text: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", seed_text.strip().lower())
    tokens = re.findall(r"[a-z0-9_]+", normalized)
    if not tokens:
        raise RuntimeError("no query tokens available")

    term_payload = _query_search(repo_root, run_root, term=tokens[0])
    if int(term_payload.get("hit_count", 0)) > 0:
        return term_payload["hits"][0]

    if len(tokens) >= 2:
        phrase_payload = _query_search(repo_root, run_root, phrase=" ".join(tokens[:2]))
        if int(phrase_payload.get("hit_count", 0)) > 0:
            return phrase_payload["hits"][0]

    raise RuntimeError(f"no query hit available for seed text: {seed_text[:32]}")


def _markdown_insert(path: Path, selector: str, snippet: str) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines):
        if selector in line:
            if idx > 0 and lines[idx - 1].strip() == snippet:
                return False
            lines.insert(idx, snippet)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    raise RuntimeError(f"selector not found in markdown file: {path} :: {selector}")


def _table_insert(
    path: Path, row_id: str, column_key: str, bundle: dict[str, Any]
) -> bool:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    for row in rows:
        if str(row.get("row_id", "")) != row_id:
            continue
        cell_trace = row.setdefault("cell_trace", {})
        cell = cell_trace.setdefault(column_key, {})
        changed = False
        if cell.get("trace_status") != bundle["ts_token"]:
            cell["trace_status"] = bundle["ts_token"]
            changed = True
        anchors = [bundle["companion_roles"]["a"]]
        if cell.get("anchor_ids") != anchors:
            cell["anchor_ids"] = anchors
            changed = True
        relation = bundle["companion_roles"].get("rel", "direct")
        if cell.get("relation") != relation:
            cell["relation"] = relation
            changed = True
        if changed:
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return changed
    raise RuntimeError(f"row_id not found in table file: {path} :: {row_id}")


def run_source_integration(
    *,
    repo_root: Path,
    control_root: Path,
    run_root: Path,
) -> tuple[Path, Path, Path, list[dict[str, str]]]:
    tx_root = control_root / "artifacts" / "source-integration"
    tx_root.mkdir(parents=True, exist_ok=True)
    begin_marker = tx_root / "src-integration.begin"
    begin_marker.write_text(f"timestamp_utc={_utc_now()}\n", encoding="utf-8")

    paragraph_path = repo_root / "src" / "iso26262_rust_mapping.md"
    table_path = repo_root / "src" / "tables" / "table-01.yaml"

    paragraph_hit = _best_hit(repo_root, run_root, "This document maps ISO 26262")
    list_hit = _best_hit(repo_root, run_root, "ISO 26262-6:2018 clauses and tables")
    table_hit = _best_hit(
        repo_root, run_root, "General topics and modelling coding guideline topics"
    )

    paragraph_bundle = paragraph_hit["ts_authoring_bundle"]
    list_bundle = list_hit["ts_authoring_bundle"]
    table_bundle = table_hit["ts_authoring_bundle"]

    touched_paths = [paragraph_path, table_path]
    pre_checksums = {
        str(path.relative_to(repo_root)): _sha256_path(path) for path in touched_paths
    }

    paragraph_changed = _markdown_insert(
        paragraph_path,
        "This document maps ISO 26262:2018",
        paragraph_bundle["myst_snippet"],
    )
    list_changed = _markdown_insert(
        paragraph_path,
        "\u2022 ISO 26262-6:2018 clauses and tables",
        list_bundle["myst_snippet"],
    )
    table_changed = _table_insert(
        table_path,
        row_id="r0001",
        column_key="scope_notes",
        bundle=table_bundle,
    )

    post_checksums = {
        str(path.relative_to(repo_root)): _sha256_path(path) for path in touched_paths
    }

    manifest_rows: list[dict[str, str]] = []
    for rel in sorted(pre_checksums.keys()):
        manifest_rows.append(
            {
                "path": rel,
                "sha256": post_checksums[rel],
                "sha256_before": pre_checksums[rel],
                "sha256_after": post_checksums[rel],
            }
        )

    manifest_path = tx_root / "src-integration-manifest.json"
    manifest_payload = {
        "generated_at_utc": _utc_now(),
        "files": manifest_rows,
        "paragraph_insertion_changed": paragraph_changed,
        "list_insertion_changed": list_changed,
        "table_insertion_changed": table_changed,
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    commit_marker = tx_root / "src-integration.commit"
    commit_marker.write_text(f"timestamp_utc={_utc_now()}\n", encoding="utf-8")

    touched = [
        {
            "path": rel,
            "changed": pre_checksums[rel] != post_checksums[rel],
        }
        for rel in sorted(pre_checksums.keys())
    ]
    return begin_marker, commit_marker, manifest_path, touched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic source integration transaction"
    )
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--control-root", required=True)
    parser.add_argument("--run-root", required=True)
    args = parser.parse_args(argv)

    begin_marker, commit_marker, manifest_path, touched = run_source_integration(
        repo_root=Path(args.repo_root).resolve(),
        control_root=Path(args.control_root).resolve(),
        run_root=Path(args.run_root).resolve(),
    )
    print(
        json.dumps(
            {
                "begin_marker": str(begin_marker),
                "commit_marker": str(commit_marker),
                "manifest_path": str(manifest_path),
                "touched": touched,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
