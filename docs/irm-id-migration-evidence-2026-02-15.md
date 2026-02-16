# IRM ID Migration Evidence (2026-02-15)

This note records the one-time cutover from legacy statement identifiers to
ISO 26262 Rust Mapping IDs (IRM IDs).

## Scope

- Markdown statement metadata (`{dp}` role values) now uses IRM IDs.
- Table trace metadata now stores `irm_id` and no longer stores `source_id`.
- Strict validation now rejects legacy `SRCN-*` identifiers and `source_id` keys.

## Migration artifacts

- Dry-run summary: `$SPHINX_MIGRATION_RUN_ROOT/artifacts/s3/backfill-dry-run-summary.json`
- Mapping ledger: `$SPHINX_MIGRATION_RUN_ROOT/artifacts/s4/id-mapping.json`
- Rewrite summary: `$SPHINX_MIGRATION_RUN_ROOT/artifacts/s4/rewrite-summary.json`
- Validation summary: `$SPHINX_MIGRATION_RUN_ROOT/artifacts/s4/validation-summary.json`

## Post-cutover assertions

- All statement metadata IDs match `^irm_[A-Za-z0-9]{12}$`.
- Paragraph/list anchors use exact IRM ID strings.
- Legacy key `source_id` is rejected by strict schema/runtime gates.
- Reapplying the same mapping is idempotent (no file changes).
