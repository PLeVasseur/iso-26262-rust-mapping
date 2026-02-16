# Traceability Prewarm Query Contract

This contract defines deterministic query behavior over run-scoped prewarmed verbatim caches.

## CLI entrypoint

- Path: `tools/traceability/query_iso_prewarm_cache.py`
- Required subcommands: `index`, `search`, `explain`

## Data-plane index inputs

- `extract/verbatim/page-text.jsonl`
- `extract/verbatim/page-blocks.jsonl`
- `normalize/verbatim/unit-slices.jsonl`
- `normalize/verbatim/unit-text-links.jsonl`
- `anchor/verbatim/anchor-text-links.jsonl`

All verbatim-bearing payloads stay under `.cache/iso26262/mining/runs/<run_id>/...`.

## Search output contract

Before locations or quotes, output must include:

1. `{ts}` usage reminder for downstream authored output.
2. Guidelines path: `docs/traceability-ts-and-quotation-guidelines.md`.

Each actionable hit must include deterministic checked-in pointers:

- `traceability/iso26262/index/anchor-registry.jsonc`
- `traceability/iso26262/index/corpus-manifest.jsonc`
- per-part manifest/shard under `traceability/iso26262/corpus/2018-ed2/<part>/...`
- `jsonl_row_hint` or `json_pointer_hint`

## `{ts}` authoring bundle

`search` output includes a `ts_authoring_bundle` for each actionable hit.

- Allowed `ts_token`: `mapped`, `unmapped_with_rationale`, `out_of_scope_with_rationale`
- Mapped hits include parser-compatible role bundle:
  - `{dp}` + `{ts}` + `{rel}` + `{a}`
- Unmapped/out-of-scope hits include rationale placeholder and no false anchor claim.

## Quote guardrails

- Quote mode is opt-in only.
- Quote mode output is brief and fair-use bounded.
- Output includes `fair_use_brief_quote=true` marker.

Limits are defined and enforced per `docs/traceability-ts-and-quotation-guidelines.md`.
