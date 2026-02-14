#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FMT_RE = re.compile(r"^\s*<!--\s*(fmt:|style:)" )
TABLE_RE = re.compile(r"^\s*\{\{TABLE:\s*(table-\d{2})\s*\}\}\s*$")
ORDERED_LIST_RE = re.compile(r"^(\d+)\.\s+")


def _count_source(text: str) -> dict[str, int]:
    lines = text.splitlines()
    heading_count = sum(1 for line in lines if re.match(r"^\s{0,3}#{1,6}\s+\S", line))
    return {
        "line_count": len(lines),
        "heading_count": heading_count,
        "table_placeholders": text.count("{{TABLE:"),
        "page_break_tokens": text.count("{{PAGE_BREAK}}"),
        "blank_tokens": text.count("{{BLANK}}"),
        "fmt_hints": len([line for line in lines if FMT_RE.match(line)]),
    }


def _build_iso_table_block(table_id: str) -> list[str]:
    caption = f"ISO mapping {table_id}"
    return [
        f"```{{iso-table}} {table_id}",
        f":caption: {caption}",
        f":label: {table_id}",
        "```",
    ]


def migrate_text(text: str) -> tuple[str, dict[str, int]]:
    raw_lines = text.splitlines()

    cleaned: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if FMT_RE.match(line):
            continue
        if stripped in {"{{PAGE_BREAK}}", "{{BLANK}}"}:
            cleaned.append("")
            continue
        table_match = TABLE_RE.match(line)
        if table_match:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            cleaned.extend(_build_iso_table_block(table_match.group(1)))
            cleaned.append("")
            continue
        cleaned.append(line.rstrip())

    output: list[str] = []
    paragraph_buffer: list[str] = []
    in_fence = False
    statement_counter = 0

    def flush_paragraph() -> None:
        nonlocal statement_counter
        if not paragraph_buffer:
            return

        normalized = list(paragraph_buffer)
        if normalized:
            first = normalized[0]
            if ORDERED_LIST_RE.match(first):
                normalized[0] = first.replace(".", "\\.", 1)

        statement_counter += 1
        source_id = f"SRCN-{statement_counter:032X}"
        output.append(f"{{dp}}`{source_id}` {{ts}}`unmapped_with_rationale`")
        output.extend(normalized)
        paragraph_buffer.clear()

    for line in cleaned:
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            in_fence = not in_fence
            output.append(line)
            continue

        if in_fence:
            output.append(line)
            continue

        if not stripped:
            flush_paragraph()
            if not output or output[-1] != "":
                output.append("")
            continue

        if re.match(r"^\s{0,3}#{1,6}\s+\S", line):
            flush_paragraph()
            output.append(line)
            continue

        paragraph_buffer.append(line)

    flush_paragraph()

    while output and output[-1] == "":
        output.pop()

    migrated = "\n".join(output) + "\n"
    counts = {
        "statement_preface_count": statement_counter,
        "remaining_table_placeholders": migrated.count("{{TABLE:"),
        "remaining_page_break_tokens": migrated.count("{{PAGE_BREAK}}"),
        "remaining_blank_tokens": migrated.count("{{BLANK}}"),
    }
    return migrated, counts


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Convert legacy markdown source into MyST + preface syntax")
    parser.add_argument("--source", required=True)
    parser.add_argument("--report-json", default="")
    parser.add_argument("--report-md", default="")
    parser.add_argument("--prepost-json", default="")
    args = parser.parse_args(argv)

    source_path = Path(args.source)
    before = source_path.read_text(encoding="utf-8")
    pre_counts = _count_source(before)

    after, migration_counts = migrate_text(before)
    source_path.write_text(after, encoding="utf-8")

    post_counts = _count_source(after)
    summary = {
        "source": str(source_path),
        "pre_counts": pre_counts,
        "post_counts": post_counts,
        "migration_counts": migration_counts,
    }

    if args.prepost_json:
        prepost_path = Path(args.prepost_json)
        prepost_path.parent.mkdir(parents=True, exist_ok=True)
        prepost_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.report_json:
        report_json_path = Path(args.report_json)
        report_json_path.parent.mkdir(parents=True, exist_ok=True)
        report_json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.report_md:
        report_md_path = Path(args.report_md)
        report_md_path.parent.mkdir(parents=True, exist_ok=True)
        report_md = "\n".join(
            [
                "# MyST Conversion Report",
                "",
                f"- source: `{source_path}`",
                f"- pre table placeholders: {pre_counts['table_placeholders']}",
                f"- post table placeholders: {migration_counts['remaining_table_placeholders']}",
                f"- post page-break tokens: {migration_counts['remaining_page_break_tokens']}",
                f"- post blank tokens: {migration_counts['remaining_blank_tokens']}",
                f"- statement prefaces generated: {migration_counts['statement_preface_count']}",
            ]
        ) + "\n"
        report_md_path.write_text(report_md, encoding="utf-8")

    print(f"SOURCE={source_path}")
    print(f"STATEMENT_PREFACE_COUNT={migration_counts['statement_preface_count']}")
    print(f"REMAINING_TABLE_TOKENS={migration_counts['remaining_table_placeholders']}")
    print(f"REMAINING_PAGE_BREAK_TOKENS={migration_counts['remaining_page_break_tokens']}")
    print(f"REMAINING_BLANK_TOKENS={migration_counts['remaining_blank_tokens']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
