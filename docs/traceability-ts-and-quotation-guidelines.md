# Traceability {ts} and Quotation Guidelines

This document defines required guardrails for query output that is used to author traceability metadata.

## 1) Allowed `{ts}` values

- `mapped`
- `unmapped_with_rationale`
- `out_of_scope_with_rationale`

Any other value is invalid.

## 2) Required companion roles

For markdown/MyST role prefaces:

- `mapped` requires: `{dp}` + `{ts}` + `{rel}` + `{a}`.
- `unmapped_with_rationale` requires: `{dp}` + `{ts}` and a rationale in nearby prose.
- `out_of_scope_with_rationale` requires: `{dp}` + `{ts}` and a rationale in nearby prose.

Canonical mapped form:

```md
{dp}`<source_id>` {ts}`mapped` {rel}`direct` {a}`<anchor_id>`
```

For table YAML updates (`src/tables/*.yaml`), the equivalent mapping is:

- `{ts}` -> `cell_trace.<column>.trace_status`
- `{a}` -> `cell_trace.<column>.anchor_ids[]`
- `{rel}` -> `cell_trace.<column>.relation`
- `{dp}` source identity remains tied to the cell `irm_id` field (preserve existing value unless explicit regeneration workflow is invoked)

## 3) Checked-in lookup pointers

Query output must include concrete checked-in lookup pointers for each actionable hit:

- `traceability/iso26262/index/anchor-registry.jsonc`
- `traceability/iso26262/index/corpus-manifest.jsonc`
- per-part manifest/shard path under `traceability/iso26262/corpus/2018-ed2/<part>/...`
- one of:
  - `jsonl_row_hint` for `.jsonl` files
  - `json_pointer_hint` for `.jsonc` files

## 4) Quote mode and fair-use guardrails

Quote output is disabled by default and must be explicitly requested.

If quote mode is enabled, all of the following are required:

- include fair-use marker: `fair_use_brief_quote=true`
- at most one quote per query hit
- max 240 characters per quote
- max 2 lines per quote

If any quote exceeds these limits, the query output is invalid.

## 5) Required compliance preface

Before showing any locations or quote snippets, query output must include a preface that states:

1. `{ts}` must be used appropriately in downstream authored output.
2. These guidelines are located at `docs/traceability-ts-and-quotation-guidelines.md`.

## 6) End-to-end validation command

When validating query-driven insertions into `src/`, use:

```bash
SPHINX_MIGRATION_RUN_ROOT="$CONTROL_RUN_ROOT" ./make.py verify
```

Treat any validation failure as a hard stop.

## 7) Probe insertion policy

Query-driven insertion used for e2e validation is fixture-oriented by default.

- default: `RETAIN_PROBE_INSERTIONS=0` (auto-revert probe edits after evidence capture)
- optional: `RETAIN_PROBE_INSERTIONS=1` for explicit debug/promotion workflows

This policy does not forbid normal source evolution in `src/`; it only prevents accidental persistence of temporary validation fixtures.
