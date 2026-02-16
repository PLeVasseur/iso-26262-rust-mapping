# ISO 26262 Rust Mapping (Sphinx Traceability Pipeline)

This repository uses Sphinx + MyST as the canonical document pipeline.

Detailed operational guidance is available in `docs/makepy-runbook.md`.

## New-session preflight

Run this block from repository root:

```bash
pwd
uv --version
uv sync
./make.py --help
./make.py
```

Expected outcomes:

- `uv --version` prints a version string.
- `uv sync` finishes without errors.
- `./make.py --help` lists commands (`validate`, `build`, `trace-validate`, `trace-report`, `verify`, `migrate-sphinx`).
- `./make.py` completes a strict HTML build and writes output to `build/html/`.

Fallback if direct launcher is unavailable:

```bash
uv run python make.py --help
uv run python make.py build
```

## Command contract

Direct invocation (FLS-style default launcher):

```bash
./make.py
./make.py validate
./make.py build
./make.py trace-validate
./make.py trace-report
./make.py verify
./make.py migrate-sphinx
```

Explicit fallback remains supported:

```bash
uv run python make.py <command>
```

## Trace runtime environment contract

Strict trace commands require this environment variable:

```bash
export SPHINX_MIGRATION_RUN_ROOT=/path/to/sphinx-migration-run-root
```

Requires env var:

- `./make.py trace-validate`
- `./make.py trace-report`
- `./make.py verify`

Does not require trace env var:

- `./make.py --help`
- `./make.py validate`
- `./make.py build`

## Canonical sources

- `src/iso26262_rust_mapping.md` - narrative content with metadata preface lines.
- `src/tables/table-*.yaml` - YAML-backed tables with `row_id` and `cell_trace` metadata.
- `traceability/iso26262/**` - tracked ISO anchor registry metadata (non-verbatim).

## Build path contract

- Sphinx config directory: `docs/`
- Sphinx source directory: `src/`
- Build output: `build/html/`
- Doctrees: `build/doctrees/`

## Python style/lint parity checks

Local checks (same as CI):

```bash
uvx black . --check --diff --color
uvx flake8 . --exclude .venv
```

CI enforces these checks in `.github/workflows/ci.yml`.

Decision: style/lint checks are CI-enforced and documented as local operator commands; they are not currently exposed as `make.py` subcommands.

## Traceability outputs

- `build/paragraph-ids.json`
- `$SPHINX_MIGRATION_RUN_ROOT/traceability-statement-coverage.json`
- `$SPHINX_MIGRATION_RUN_ROOT/traceability-statement-coverage.md`
- `$SPHINX_MIGRATION_RUN_ROOT/artifacts/traceability/paragraph-ids-schema-validation.json`
- `$SPHINX_MIGRATION_RUN_ROOT/artifacts/traceability/paragraph-ids-table-entry-audit.json`

## IRM ID authoring workflow

Use the generator to mint new ISO 26262 Rust Mapping IDs (IRM IDs) and output
ready-to-paste snippets:

```bash
python3 tools/traceability/generate_irm_ids.py
python3 tools/traceability/generate_irm_ids.py --mode myst-preface --count 3 --trace-status unmapped_with_rationale --no-prompt
python3 tools/traceability/generate_irm_ids.py --mode yaml-cell --count 2 --trace-status mapped --relation maps_to --anchor iso_26262_clause_5 --no-prompt
```

Rules:

- Always mint IRM IDs with tooling; do not handcraft IDs.
- Move IRM IDs with the statement text when reordering content.
- Mint a new IRM ID only for genuinely new statements.

## Troubleshooting

- `ModuleNotFoundError` on `./make.py`: run from repo root and use uv launcher (`./make.py`), or fallback to `uv run python make.py <command>`.
- `env: uv: No such file or directory`: install uv, then rerun preflight.
- `permission denied` for `./make.py`: run `chmod +x make.py`.
- missing trace env var: export `SPHINX_MIGRATION_RUN_ROOT` before trace commands.
- dependency resolution failure: run `uv sync` and ensure `uv.lock` matches `pyproject.toml`.

## Notes

- Legacy placeholders (`{{TABLE: ...}}`, `{{PAGE_BREAK}}`, `{{BLANK}}`) are not allowed.
- Direct `sphinx-build` use is internal only; operators use `make.py` entrypoints.
