# Instrumentation Freeze

The migration closes with full-document statement-unit instrumentation frozen.

- Markdown statement units carry metadata prefaces with `dp` and `ts`.
- Table statement units carry `row_id` and `cell_trace` metadata.
- Existing IRM IDs are preserved after conversion and schema migration.
- Any newly introduced statement requires a new stable `irm_id`.
