# make.py Runbook

This runbook defines new-session execution for `make.py` with FLS-style launcher
behavior and strict traceability command contracts.

## New-session preflight

```bash
pwd
uv --version
uv sync
./make.py --help
./make.py
```

Expected outcomes:

- `pwd` points to repository root.
- `uv --version` returns a valid version.
- `uv sync` succeeds without dependency resolution errors.
- `./make.py --help` prints available commands.
- `./make.py` performs strict HTML build and writes `build/html/`.

Fallback path if direct launcher is unavailable:

```bash
uv run python make.py --help
uv run python make.py build
```

## Runtime environment contract

Set this variable for strict traceability commands:

```bash
export SPHINX_MIGRATION_RUN_ROOT=/path/to/sphinx-traceability-migration-run-root
```

Commands requiring the trace env var:

- `./make.py trace-validate`
- `./make.py trace-report`
- `./make.py verify`

Commands not requiring the trace env var:

- `./make.py --help`
- `./make.py validate`
- `./make.py build`

New-session env verification checklist:

```bash
echo "$SPHINX_MIGRATION_RUN_ROOT"
```

- The command must print a non-empty value before running strict trace commands.

## Python style and lint checks

Use the same checks as CI:

```bash
uvx black . --check --diff --color
uvx flake8 . --exclude .venv
```

## Failure-handling matrix

- Missing uv executable: install uv, then rerun preflight.
- Direct launcher unavailable: use `uv run python make.py <command>`.
- Missing trace env var for trace commands: export the required var and rerun.
- CI lint failure: rerun local Black and Flake8 commands, fix, repeat.
- Dependency resolution failure: run `uv sync` and validate `uv.lock` is current.

## Evidence artifact map

Runtime transcripts:

- `artifacts/validation/makepy-direct-help.before.log`
- `artifacts/validation/makepy-direct-help.after.log`
- `artifacts/validation/makepy-direct-default.after.log`
- `artifacts/validation/makepy-direct-validate.after.log`
- `artifacts/validation/makepy-uv-fallback.after.log`

Style/lint evidence:

- `artifacts/validation/python-black-check.log`
- `artifacts/validation/python-flake8-check.log`
- `artifacts/validation/python-style-lint-summary.json`

## Compatibility constraints

- Preserve command set: `validate`, `build`, `trace-validate`, `trace-report`, `verify`, `migrate-sphinx`.
- Keep default no-arg behavior as strict build.
- Keep direct launcher support and explicit `uv run python make.py ...` fallback support.
