#!/usr/bin/env python3
"""
make.py — single entrypoint for validating and building the ISO 26262 ↔ Rust mapping document.

Usage (with uv):
  uv run python make.py validate
  uv run python make.py build
  uv run python make.py verify    # build + compare vs baseline + render quick QA (default 2 pages)

Without uv (system Python):
  python make.py build

Project layout:
  docgen/*.py                     Build/compare/render source modules
  src/iso26262_rust_mapping.md         Narrative markdown with {{TABLE: table-XX}} placeholders
  src/tables/table-XX.yaml             Table data (YAML)
  src/schemas/table-XX.schema.json     Per-table JSON schemas
  src/schemas/table_common.schema.json Common schema referenced by per-table schemas
  templates/base.docx                  Style/template source (copied from baseline)
  ref/baseline_enriched.docx           Baseline to compare against
  build/docx/                          Generated DOCX outputs
  build/reports/                       Compare reports
  build/render_compare/                Optional rendered PNG/PDF QA outputs
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from docgen.validate import validate_all_tables
from docgen.docx_builder import build_docx
from docgen.compare import compare_docx_text
from docgen.render import render_docx_to_pngs

ROOT = Path(__file__).resolve().parent
OUT_DOCX = ROOT / "build" / "docx" / "iso26262_rust_mapping_generated.docx"
COMPARE_REPORT = ROOT / "build" / "reports" / "compare_report.md"
RENDER_COMPARE_DIR = ROOT / "build" / "render_compare"


def _missing_render_tools() -> list[str]:
    required = ("soffice", "pdftoppm")
    return [tool for tool in required if shutil.which(tool) is None]

def cmd_validate(_: argparse.Namespace) -> None:
    validate_all_tables(
        src_tables_dir=ROOT / "src" / "tables",
        src_schemas_dir=ROOT / "src" / "schemas",
    )

def cmd_build(_: argparse.Namespace) -> None:
    OUT_DOCX.parent.mkdir(parents=True, exist_ok=True)
    validate_all_tables(
        src_tables_dir=ROOT / "src" / "tables",
        src_schemas_dir=ROOT / "src" / "schemas",
    )
    build_docx(
        template_docx=ROOT / "templates" / "base.docx",
        narrative_md=ROOT / "src" / "iso26262_rust_mapping.md",
        tables_dir=ROOT / "src" / "tables",
        schemas_dir=ROOT / "src" / "schemas",
        out_docx=OUT_DOCX,
    )
    print(f"Wrote: {OUT_DOCX}")

def cmd_verify(args: argparse.Namespace) -> None:
    # Build
    cmd_build(args)

    baseline = ROOT / "ref" / "baseline_enriched.docx"
    generated = OUT_DOCX

    # Compare (text + table content)
    COMPARE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = compare_docx_text(baseline_docx=baseline, generated_docx=generated)
    COMPARE_REPORT.write_text(report, encoding="utf-8")
    print(f"Wrote: {COMPARE_REPORT}")

    # Quick render QA (first N pages)
    if args.render_pages > 0:
        missing = _missing_render_tools()
        if missing:
            missing_csv = ", ".join(missing)
            raise SystemExit(
                "Render QA requested but required tools are missing from PATH: "
                f"{missing_csv}. Install LibreOffice + Poppler "
                "(Ubuntu/Debian: `sudo apt-get install -y libreoffice-writer poppler-utils`) "
                "or run `uv run python make.py verify --render-pages 0` to skip rendering."
            )
        RENDER_COMPARE_DIR.mkdir(parents=True, exist_ok=True)
        render_docx_to_pngs(baseline, RENDER_COMPARE_DIR / "baseline", max_pages=args.render_pages)
        render_docx_to_pngs(generated, RENDER_COMPARE_DIR / "generated", max_pages=args.render_pages)
        print(f"Wrote renders to: {RENDER_COMPARE_DIR}")

def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="Validate all table YAML files against their JSON schemas.")
    p_val.set_defaults(func=cmd_validate)

    p_build = sub.add_parser(
        "build",
        help="Build DOCX from src/ into build/docx/iso26262_rust_mapping_generated.docx.",
    )
    p_build.set_defaults(func=cmd_build)

    p_verify = sub.add_parser(
        "verify",
        help="Build + compare + render (default 2 pages; requires soffice and pdftoppm).",
    )
    p_verify.add_argument(
        "--render-pages",
        type=int,
        default=2,
        help="Render first N pages to PNG for visual QA (default: 2; 0 to skip).",
    )
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
