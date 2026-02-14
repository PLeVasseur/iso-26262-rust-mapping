#!/usr/bin/env -S uv run
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONF_DIR = ROOT / "docs"
SOURCE_DIR = ROOT / "src"
OUT_DIR = ROOT / "build" / "html"
DOCTREE_DIR = ROOT / "build" / "doctrees"

LEGACY_TOKENS = ("{{TABLE:", "{{PAGE_BREAK}}", "{{BLANK}}")
TRACE_ENV_VARS = ("OPENCODE_CONFIG_DIR", "SPHINX_MIGRATION_RUN_ROOT")


def _draft202012_validator(schema: dict):
    from jsonschema import Draft202012Validator

    return Draft202012Validator(schema)


def _validate_all_tables() -> None:
    try:
        from docgen.validate import validate_all_tables
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "missing Python dependencies for validation; run via ./make.py "
            "(uv launcher) or `uv sync` first"
        ) from exc

    validate_all_tables(
        src_tables_dir=ROOT / "src" / "tables",
        src_schemas_dir=ROOT / "src" / "schemas",
    )


def _require_trace_env(command_name: str) -> None:
    missing = [key for key in TRACE_ENV_VARS if not os.environ.get(key)]
    if not missing:
        return

    missing_csv = ", ".join(missing)

    details = [
        f"missing required environment variables for '{command_name}': {missing_csv}",
        "",
        "Export and retry, for example:",
        "  export OPENCODE_CONFIG_DIR=<path-to-opencode-config>",
        "  export SPHINX_MIGRATION_RUN_ROOT=<path-to-run-root>",
    ]
    raise SystemExit("\n".join(details))


def _run_sphinx_html() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DOCTREE_DIR.mkdir(parents=True, exist_ok=True)

    build_module = importlib.import_module("sphinx.cmd.build")

    args = [
        "-b",
        "html",
        "-W",
        "--keep-going",
        "-T",
        "-d",
        str(DOCTREE_DIR),
        str(SOURCE_DIR),
        str(OUT_DIR),
        "-c",
        str(CONF_DIR),
    ]
    code = build_module.build_main(args)
    if code != 0:
        raise SystemExit(code)


def _load_jsonc(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    stripped = re.sub(r"//.*$", "", raw, flags=re.MULTILINE)
    return json.loads(stripped)


def _validate_anchor_registry() -> None:
    registry_path = (
        ROOT / "traceability" / "iso26262" / "index" / "anchor-registry.jsonc"
    )
    schema_path = (
        ROOT / "traceability" / "iso26262" / "schema" / "anchor-registry.schema.json"
    )

    if not registry_path.exists():
        raise SystemExit(f"missing anchor registry: {registry_path}")
    if not schema_path.exists():
        raise SystemExit(f"missing anchor registry schema: {schema_path}")

    registry = _load_jsonc(registry_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = _draft202012_validator(schema)
    errors = sorted(
        validator.iter_errors(registry), key=lambda err: list(err.absolute_path)
    )
    if errors:
        details = "\n".join(f"- {err.message}" for err in errors)
        raise SystemExit(f"anchor registry schema validation failed:\n{details}")


def _find_legacy_tokens() -> list[str]:
    findings: list[str] = []
    for md_file in sorted(SOURCE_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        for token in LEGACY_TOKENS:
            if token in text:
                findings.append(f"{md_file}: contains {token}")
    return findings


def _validate_no_leak() -> list[str]:
    patterns = [
        r"order\s*number",
        r"for\s+internal\s+use\s+only",
        r"no\s+reproduction",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"raw_text",
        r"paragraph_text",
        r"cell_text",
    ]
    findings: list[str] = []

    scan_roots = [
        ROOT / "traceability",
        ROOT / "src",
    ]
    allowed_suffixes = {".md", ".json", ".jsonc", ".yaml", ".yml"}

    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in sorted(scan_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                continue
            rel_path = path.relative_to(ROOT)
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    findings.append(f"{rel_path}: matches no-leak pattern '{pattern}'")
                    break
    return findings


def _run_trace_validate() -> tuple[bool, list[str]]:
    diagnostics: list[str] = []

    paragraph_ids_path = OUT_DIR / "paragraph-ids.json"
    if not paragraph_ids_path.exists():
        diagnostics.append(f"missing paragraph-ids export: {paragraph_ids_path}")
    else:
        payload = json.loads(paragraph_ids_path.read_text(encoding="utf-8"))

        opencode_dir = os.environ.get("OPENCODE_CONFIG_DIR", "")
        if opencode_dir:
            schema_path = (
                Path(opencode_dir) / "reports" / "schemas" / "paragraph-ids.schema.json"
            )
            if schema_path.exists():
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                validator = _draft202012_validator(schema)
                errors = sorted(
                    validator.iter_errors(payload),
                    key=lambda err: list(err.absolute_path),
                )
                diagnostics.extend(
                    [f"paragraph-ids schema: {err.message}" for err in errors]
                )
            else:
                diagnostics.append(f"missing paragraph-ids schema: {schema_path}")

        records = payload.get("records", payload if isinstance(payload, list) else [])
        table_anchor_re = re.compile(r"^[a-z0-9-]+--r-[a-z0-9-]+--c-[a-z0-9-]+$")
        for record in records:
            if record.get("unit_type") != "table_cell":
                continue
            href = str(record.get("href", ""))
            if "#" not in href:
                record_id = record.get("id", "<unknown>")
                diagnostics.append(
                    f"table_cell record missing anchor in href: {record_id}"
                )
                continue
            anchor = href.split("#", 1)[1]
            if not table_anchor_re.match(anchor):
                diagnostics.append(
                    f"table_cell record has non-canonical anchor '{anchor}'"
                )

    diagnostics.extend(_find_legacy_tokens())
    diagnostics.extend(_validate_no_leak())
    return (len(diagnostics) == 0, diagnostics)


def _write_trace_validate_log(success: bool, diagnostics: list[str]) -> None:
    run_root = os.environ.get("SPHINX_MIGRATION_RUN_ROOT", "")
    if not run_root:
        return
    log_path = Path(run_root) / "artifacts" / "validation" / "trace-validate.log"
    lines = [
        "# trace-validate",
        "",
        f"status: {'pass' if success else 'fail'}",
        "",
    ]
    if diagnostics:
        lines.append("diagnostics:")
        lines.extend([f"- {item}" for item in diagnostics])
    else:
        lines.append("diagnostics: []")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_validate(_: argparse.Namespace) -> None:
    _validate_all_tables()
    _validate_anchor_registry()
    legacy = _find_legacy_tokens()
    if legacy:
        raise SystemExit(
            "legacy token check failed:\n" + "\n".join(f"- {item}" for item in legacy)
        )


def cmd_build(args: argparse.Namespace) -> None:
    cmd_validate(args)
    _run_sphinx_html()
    print(f"Wrote HTML build to: {OUT_DIR}")


def cmd_trace_validate(args: argparse.Namespace) -> None:
    _require_trace_env("trace-validate")
    cmd_build(args)
    success, diagnostics = _run_trace_validate()
    _write_trace_validate_log(success, diagnostics)
    if not success:
        raise SystemExit(
            "trace-validate failed:\n" + "\n".join(f"- {item}" for item in diagnostics)
        )
    print("trace-validate passed")


def cmd_trace_report(args: argparse.Namespace) -> None:
    _require_trace_env("trace-report")
    cmd_build(args)
    run_root = os.environ.get("SPHINX_MIGRATION_RUN_ROOT", "")
    if run_root:
        coverage_json_path = Path(run_root) / "traceability-statement-coverage.json"
        coverage_md_path = Path(run_root) / "traceability-statement-coverage.md"
        print(f"Run-scoped coverage JSON: {coverage_json_path}")
        print(f"Run-scoped coverage MD: {coverage_md_path}")
    else:
        print(
            "SPHINX_MIGRATION_RUN_ROOT is not set; "
            "only build-scoped outputs were generated"
        )


def cmd_verify(args: argparse.Namespace) -> None:
    _require_trace_env("verify")
    cmd_trace_validate(args)
    cmd_trace_report(args)


def cmd_migrate_sphinx(_: argparse.Namespace) -> None:
    repo_tools = ROOT / "tools" / "traceability"
    source_file = ROOT / "src" / "iso26262_rust_mapping.md"

    subprocess.run(
        [
            "python3",
            str(repo_tools / "migrate_to_myst.py"),
            "--source",
            str(source_file),
        ],
        check=True,
        cwd=str(ROOT),
    )

    subprocess.run(
        [
            "python3",
            str(repo_tools / "update_table_schemas.py"),
            "--schemas-dir",
            str(ROOT / "src" / "schemas"),
        ],
        check=True,
        cwd=str(ROOT),
    )

    subprocess.run(
        [
            "python3",
            str(repo_tools / "instrument_tables.py"),
            "--tables-dir",
            str(ROOT / "src" / "tables"),
        ],
        check=True,
        cwd=str(ROOT),
    )
    print("Migration to Sphinx/MyST contracts complete")


def main() -> None:
    parser_description = (
        "Sphinx migration make entrypoint "
        "(defaults to build when no command is provided)"
    )
    parser = argparse.ArgumentParser(
        description=parser_description,
    )
    sub = parser.add_subparsers(dest="cmd")
    parser.set_defaults(func=cmd_build, cmd="build")

    p_validate = sub.add_parser(
        "validate", help="Validate schema and migration invariants."
    )
    p_validate.set_defaults(func=cmd_validate)

    p_build = sub.add_parser("build", help="Run strict Sphinx HTML build.")
    p_build.set_defaults(func=cmd_build)

    p_trace_validate = sub.add_parser(
        "trace-validate", help="Run strict traceability gates."
    )
    p_trace_validate.set_defaults(func=cmd_trace_validate)

    p_trace_report = sub.add_parser(
        "trace-report", help="Generate/update coverage reports."
    )
    p_trace_report.set_defaults(func=cmd_trace_report)

    p_verify = sub.add_parser(
        "verify", help="Run validate + build + trace gates + reports."
    )
    p_verify.set_defaults(func=cmd_verify)

    p_migrate = sub.add_parser(
        "migrate-sphinx", help="One-shot deterministic source migration helper."
    )
    p_migrate.set_defaults(func=cmd_migrate_sphinx)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
