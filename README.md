# ISO 26262 ↔ Rust mapping — doc generator (prototype → full conversion)

This project treats the `.docx` as a **generated artifact**.

**Sources of truth**
- `docgen/*.py` — build/compare/render implementation modules
- `src/iso26262_rust_mapping.md` — narrative text + document structure (with `{{TABLE: table-XX}}` placeholders)
- `src/tables/table-XX.yaml` — table content in YAML
- `src/schemas/table-XX.schema.json` — per-table JSON Schema validation (refs `table_common.schema.json`)

**Build artifact**
- `build/docx/iso26262_rust_mapping_generated.docx`

## Requirements

- Python 3.11+ (recommended)
- [`uv`](https://github.com/astral-sh/uv)
- For default `make.py verify` behavior (render first 2 pages):
  - LibreOffice (`soffice`)
  - Poppler (`pdftoppm`)

If render dependencies are unavailable, you can still run compare-only verification with `make.py verify --render-pages 0`.

## Quickstart (with uv)

```bash
uv sync
uv run python make.py validate
uv run python make.py build
uv run python make.py verify
```

Outputs:
- `build/docx/iso26262_rust_mapping_generated.docx`
- `build/reports/compare_report.md`
- `build/render_compare/` (PNG renders of baseline + generated)

Migration note: artifact output has a hard cutover from `out/` to `build/`.

## Notes on markdown dialect

The narrative markdown uses a small, predictable subset:

- Headings: `#`, `##`, `###`, ...
- Paragraphs separated by blank lines
- Optional formatting hint for the *next* paragraph:

```md
<!-- fmt: style="List Paragraph" align=center size=24 bold=true italic=false -->
Some paragraph text...
```

- Table insertion placeholder:

```md
{{TABLE: table-01}}
```

- Explicit empty paragraph / page break markers:

```md
{{BLANK}}
{{PAGE_BREAK}}
```

This keeps the source readable while preserving Word styles/formatting where needed.
