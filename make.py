#!/usr/bin/env python3
"""
make.py — single entrypoint for validating and building the ISO 26262 ↔ Rust mapping document.

Usage (with uv):
  uv run python make.py validate
  uv run python make.py build
  uv run python make.py verify    # build + compare vs baseline + render quick QA

Without uv (system Python):
  python make.py build

Project layout:
  src/iso26262_rust_mapping.md         Narrative markdown with {{TABLE: table-XX}} placeholders
  src/tables/table-XX.yaml             Table data (YAML)
  src/schemas/table-XX.schema.json     Per-table JSON schemas
  src/schemas/table_common.schema.json Common schema referenced by per-table schemas
  templates/base.docx                  Style/template source (copied from baseline)
  ref/baseline_enriched.docx           Baseline to compare against
  out/                                 Build outputs
"""
from __future__ import annotations

import argparse
from pathlib import Path

from build.validate import validate_all_tables
from build.docx_builder import build_docx
from build.compare import compare_docx_text
from build.render import render_docx_to_pngs

ROOT = Path(__file__).resolve().parent

def cmd_validate(_: argparse.Namespace) -> None:
    validate_all_tables(
        src_tables_dir=ROOT / "src" / "tables",
        src_schemas_dir=ROOT / "src" / "schemas",
    )

def cmd_build(args: argparse.Namespace) -> None:
    out_docx = ROOT / "out" / args.output
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    validate_all_tables(
        src_tables_dir=ROOT / "src" / "tables",
        src_schemas_dir=ROOT / "src" / "schemas",
    )
    build_docx(
        template_docx=ROOT / "templates" / "base.docx",
        narrative_md=ROOT / "src" / "iso26262_rust_mapping.md",
        tables_dir=ROOT / "src" / "tables",
        schemas_dir=ROOT / "src" / "schemas",
        out_docx=out_docx,
    )
    print(f"Wrote: {out_docx}")

def cmd_verify(args: argparse.Namespace) -> None:
    # Build
    cmd_build(argparse.Namespace(output=args.output))

    baseline = ROOT / "ref" / "baseline_enriched.docx"
    generated = ROOT / "out" / args.output

    # Compare (text + table content)
    report_path = ROOT / "out" / "compare_report.md"
    report = compare_docx_text(baseline_docx=baseline, generated_docx=generated)
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote: {report_path}")

    # Quick render QA (first N pages)
    if args.render_pages > 0:
        render_dir = ROOT / "out" / "render_compare"
        render_dir.mkdir(parents=True, exist_ok=True)
        render_docx_to_pngs(baseline, render_dir / "baseline", max_pages=args.render_pages)
        render_docx_to_pngs(generated, render_dir / "generated", max_pages=args.render_pages)
        print(f"Wrote renders to: {render_dir}")

def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="Validate all table YAML files against their JSON schemas.")
    p_val.set_defaults(func=cmd_validate)

    p_build = sub.add_parser("build", help="Build the DOCX from src/ into out/.")
    p_build.add_argument("--output", default="iso26262_rust_mapping_generated.docx")
    p_build.set_defaults(func=cmd_build)

    p_verify = sub.add_parser("verify", help="Build + compare against baseline + render quick QA.")
    p_verify.add_argument("--output", default="iso26262_rust_mapping_generated.docx")
    p_verify.add_argument("--render-pages", type=int, default=2, help="Render first N pages to PNG for visual QA (0 to skip).")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
