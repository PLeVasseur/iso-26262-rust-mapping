# ISO 26262 Rust Mapping (Sphinx Traceability Pipeline)

This repository uses Sphinx + MyST as the canonical document pipeline.

## Canonical sources

- `src/iso26262_rust_mapping.md` - narrative content with metadata preface lines.
- `src/tables/table-*.yaml` - YAML-backed tables with `row_id` and `cell_trace` metadata.
- `traceability/iso26262/**` - tracked ISO anchor registry metadata (non-verbatim).

## Build path contract

- Sphinx config directory: `docs/`
- Sphinx source directory: `src/`
- Build output: `build/html/`
- Doctrees: `build/doctrees/`

## Workflow commands

Run all commands through `uv`:

```bash
uv sync
uv run python make.py validate
uv run python make.py build
uv run python make.py trace-validate
uv run python make.py trace-report
uv run python make.py verify
```

Optional one-shot migration helper:

```bash
uv run python make.py migrate-sphinx
```

## Traceability outputs

- `build/html/paragraph-ids.json`
- `$OPENCODE_CONFIG_DIR/reports/sphinx-traceability-migration-<run-id>/traceability-statement-coverage.json`
- `$OPENCODE_CONFIG_DIR/reports/sphinx-traceability-migration-<run-id>/traceability-statement-coverage.md`
- `$OPENCODE_CONFIG_DIR/reports/traceability-statement-coverage-latest.json`
- `$OPENCODE_CONFIG_DIR/reports/traceability-statement-coverage-latest.md`

## Notes

- Legacy placeholders (`{{TABLE: ...}}`, `{{PAGE_BREAK}}`, `{{BLANK}}`) are not allowed.
- Direct `sphinx-build` use is internal only; operators use `uv run python make.py ...`.
