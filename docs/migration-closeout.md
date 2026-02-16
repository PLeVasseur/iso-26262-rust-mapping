# Migration Closeout

Sphinx + MyST is the canonical build path for this repository.

- Legacy placeholder syntax is retired from canonical source.
- Operator workflow is standardized on `uv run python make.py ...`.
- Coverage and statement-unit exports are generated as migration closeout outputs.
- Runtime dependencies for DOCX-only generation are retired from the active contract.

## Recorded assumptions

- Newly instrumented statement units default to `unmapped_with_rationale`.
- Anchor-level mapping depth will be expanded incrementally in subsequent runs.
