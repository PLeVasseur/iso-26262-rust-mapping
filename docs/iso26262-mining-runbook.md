# ISO 26262 Mining Runbook

This runbook describes fresh-session bootstrap, resumable execution, and crash recovery for the standalone mining CLI.

## Preflight

```bash
uv sync
uv run python --version
uv run python tools/traceability/mine_iso_corpus.py --control-run-root /tmp/iso26262-mining-help --help
pdftotext -v
tesseract --version
```

- Select mode:
  - `fixture_ci`: shared CI, fixture-only.
  - `licensed_local`: controlled local/self-hosted runs with licensed PDFs.

## Paths and storage model

- Control-plane (metadata only): `$OPENCODE_CONFIG_DIR/reports/iso26262-mining-<RUN_ID>/`.
- Data-plane (licensed/raw/OCR/debug): `<REPO_ROOT>/.cache/iso26262/mining/runs/<RUN_ID>/`.
- Default PDF root: `<REPO_ROOT>/.cache/iso26262`.
- Do not commit any `.cache/...` artifact.

## Fresh kickoff

```bash
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
CONTROL_RUN_ROOT="$OPENCODE_CONFIG_DIR/reports/iso26262-mining-$RUN_ID"
REPO_ROOT=$(git rev-parse --show-toplevel)

uv run python tools/traceability/mine_iso_corpus.py \
  --run-id "$RUN_ID" \
  --control-run-root "$CONTROL_RUN_ROOT" \
  --pdf-root "$REPO_ROOT/.cache/iso26262" \
  --source-pdfset "$REPO_ROOT/traceability/iso26262/index/source-pdfset.jsonc" \
  --relevant-policy "$REPO_ROOT/traceability/iso26262/index/relevant-pdf-policy.jsonc" \
  --extraction-policy "$REPO_ROOT/tools/traceability/mining/config/extraction_policy_v1.jsonc" \
  --mode licensed_local \
  --lock-source-hashes \
  ingest
```

## Canonical phase order

1. `C0`: ingest hash-lock baseline.
2. `C1`..`C2`: scaffold CLI and resumable control-plane.
3. `C3`..`C5`: ingest + extraction + OCR fallback policy.
4. `C6`..`C8`: normalize + anchor + publish.
5. `C9`..`C12`: verify + operations/docs + pilot evidence.
6. `C13+`: repeatable required-part rollout batches.

## Verbatim prewarm phase order (`C14+`)

1. `C14`: extract-stage page prewarm cache writers (`page-text`, `page-blocks`, `page-index`, `page-signatures`).
2. `C15`: normalize-stage unit-slice and unit-text-link integration.
3. `C16`: anchor-stage anchor-to-verbatim linkage index integration.
4. `C17`: replay/checkpoint validation for prewarm lineage artifacts.
5. `C18`: query interface and lineage contracts + `{ts}`/quotation guardrail policy.
6. `C19`: query CLI (`index`, `search`, `explain`) for deterministic word/phrase lookups.
7. `C20`: prewarm normalization and artifact-hygiene verification gates.
8. `C21`: deterministic query probe-set verification + freeze manifest/signature.
9. `C22`: source insertion helper transactions for `ts_authoring_bundle` outputs.
10. `C23`: end-to-end query -> src insertion -> `make.py verify` validation with default auto-revert.
11. `C24`: CI + operator guidance hardening for canonical let-it-rip runs.

See `docs/traceability-prewarm-query-contract.md` for query schema/lineage details.

## Resume command

Use the same `RUN_ID` and `CONTROL_RUN_ROOT`; the CLI reopens from durable state and checkpoints.

```bash
uv run python tools/traceability/mine_iso_corpus.py \
  --run-id "$RUN_ID" \
  --control-run-root "$CONTROL_RUN_ROOT" \
  --pdf-root "$REPO_ROOT/.cache/iso26262" \
  --source-pdfset "$REPO_ROOT/traceability/iso26262/index/source-pdfset.jsonc" \
  --relevant-policy "$REPO_ROOT/traceability/iso26262/index/relevant-pdf-policy.jsonc" \
  --extraction-policy "$REPO_ROOT/tools/traceability/mining/config/extraction_policy_v1.jsonc" \
  --mode licensed_local \
  extract
```

## Locking behavior

- Active lock payload fields: `pid`, `host`, `user`, `run_id`, `acquired_at_utc`.
- If lock holder is active, stop immediately.
- If lock is stale, append stale payload to `run.log`, then replace lock.
- Lock is released on normal and error exit.

## Crash-window reconciliation

- Window A (before mutation): rerun current stage from start.
- Window B (after mutation before verification): rerun verification then continue.
- Window C (publish interrupted): reconcile `publish.begin`/`publish.commit` and manifest checksums.
- Window D (after verify before finalize): rerun idempotent finalize only.

Additional prewarm windows:

- Window E: anchor-link files partially written.
- Window F: source insertion interrupted after partial `src/` edits.
- Window G: `SPHINX_MIGRATION_RUN_ROOT="$CONTROL_RUN_ROOT" ./make.py verify` outcome unknown.

## Extraction policy (primary vs OCR fallback)

- Primary extraction first (`pdftotext` layout extraction).
- OCR fallback is used only on deterministic hard-fail pages.

| Metric | Threshold | Effect |
| --- | --- | --- |
| `non_blank_ink_coverage_ratio_min` | `0.005` | sets non-blank page boundary |
| `primary_low_char_count_threshold` | `80` | low text hard-fail when text-bearing expected |
| `replacement_char_ratio_max` | `0.005` | hard-fail above threshold |
| `control_char_ratio_max` | `0.01` | hard-fail above threshold |
| `ocr_orientation_confidence_min` | `15.0` | auto-rotate only above threshold |

OCR quality bands:

- `pass`: mean >= 85, p25 >= 70, low-conf-ratio <= 0.10
- `needs_review`: mean >= 75, p25 >= 55, low-conf-ratio <= 0.25
- `fail`: anything below `needs_review`

For required parts (`P06`, `P08`, `P09`), unresolved `needs_review`/`fail` items block publish and verify.

## Dry-run and replay examples

```bash
uv run python tools/traceability/mine_iso_corpus.py \
  --run-id "$RUN_ID" \
  --control-run-root "$CONTROL_RUN_ROOT" \
  --mode fixture_ci \
  --dry-run \
  normalize

uv run python tools/traceability/mine_iso_corpus.py \
  --run-id "$RUN_ID" \
  --control-run-root "$CONTROL_RUN_ROOT" \
  replay
```

## Canonical let-it-rip operator mode (`C24`)

Use run-to-completion when no throttle is supplied.

- `MODE` default: `licensed_local`
- `START_PHASE` default: earliest incomplete safe phase
- `MAX_PHASES` default: `all` (run to completion)
- `RETAIN_PROBE_INSERTIONS` default: `0` (auto-revert probe fixtures)

One-shot kickoff (no existing incomplete run):

```bash
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
CONTROL_RUN_ROOT="$OPENCODE_CONFIG_DIR/reports/iso26262-mining-verbatim-$RUN_ID"
REPO_ROOT=$(git rev-parse --show-toplevel)

uv run python tools/traceability/mine_iso_corpus.py \
  --run-id "$RUN_ID" \
  --plan-path "$OPENCODE_CONFIG_DIR/plans/2026-02-16-verbatim-prewarm-cache-integration-plan.md" \
  --control-run-root "$CONTROL_RUN_ROOT" \
  --pdf-root "$REPO_ROOT/.cache/iso26262" \
  --source-pdfset "$REPO_ROOT/traceability/iso26262/index/source-pdfset.jsonc" \
  --relevant-policy "$REPO_ROOT/traceability/iso26262/index/relevant-pdf-policy.jsonc" \
  --extraction-policy "$REPO_ROOT/tools/traceability/mining/config/extraction_policy_v1.jsonc" \
  --mode licensed_local \
  verify
```

Resume explicit run:

```bash
uv run python tools/traceability/mine_iso_corpus.py \
  --run-id "$RUN_ID" \
  --plan-path "$OPENCODE_CONFIG_DIR/plans/2026-02-16-verbatim-prewarm-cache-integration-plan.md" \
  --control-run-root "$CONTROL_RUN_ROOT" \
  --mode licensed_local \
  verify
```

## Forbidden report content

Do not place any of the following under control-plane reports/artifacts:

- OCR text output
- extracted paragraph/list/table/cell verbatim text
- page images or raster dumps
