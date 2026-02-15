#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from tools.traceability.irm_id_utils import is_valid_irm_id, mint_irm_id

TRACE_STATUSES = [
    "mapped",
    "unmapped_with_rationale",
    "out_of_scope_with_rationale",
]
MODES = ["myst-preface", "yaml-cell", "yaml-row", "raw"]


def _prompt_choice(prompt: str, options: list[str]) -> str:
    print(prompt)
    for idx, option in enumerate(options, start=1):
        print(f"  {idx}) {option}")
    while True:
        raw = input("> ").strip()
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(options):
                return options[index - 1]
        if raw in options:
            return raw
        print("Please choose a valid option.")


def _prompt_count() -> int:
    while True:
        raw = input("How many IRM IDs do you need? > ").strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("Enter a positive integer.")


def _prompt_status() -> str:
    return _prompt_choice("Choose trace status:", TRACE_STATUSES)


def _prompt_relation() -> str:
    return input("Relation value (required for mapped): > ").strip()


def _prompt_anchors() -> list[str]:
    raw = input("Anchor IDs (comma-separated for mapped statements): > ").strip()
    anchors = [item.strip() for item in raw.split(",") if item.strip()]
    return anchors


def _build_entries(
    count: int,
    trace_status: str | None,
    relation: str,
    anchors: list[str],
    no_prompt: bool,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    minted: set[str] = set()

    status_mode = "single"
    shared_status = trace_status
    if not no_prompt and trace_status is None:
        status_mode = _prompt_choice(
            "How should trace status be assigned?",
            ["single", "per-entry"],
        )
        if status_mode == "single":
            shared_status = _prompt_status()

    for index in range(count):
        irm_id = mint_irm_id(minted)
        minted.add(irm_id)

        if status_mode == "per-entry":
            print(f"Entry {index + 1}/{count}")
            entry_status = _prompt_status()
        else:
            entry_status = shared_status or "unmapped_with_rationale"

        entry_relation = relation
        entry_anchors = list(anchors)
        if entry_status == "mapped":
            if not no_prompt and not entry_relation:
                entry_relation = _prompt_relation()
            if not no_prompt and not entry_anchors:
                entry_anchors = _prompt_anchors()
            if not entry_relation:
                entry_relation = "maps_to"
            if not entry_anchors:
                entry_anchors = ["todo_anchor_id"]
        else:
            entry_relation = entry_relation or ""
            entry_anchors = []

        entries.append(
            {
                "irm_id": irm_id,
                "trace_status": entry_status,
                "relation": entry_relation,
                "anchor_ids": entry_anchors,
            }
        )

    return entries


def _render_myst(entries: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for entry in entries:
        irm_id = str(entry["irm_id"])
        status = str(entry["trace_status"])
        relation = str(entry["relation"])
        anchors = [str(item) for item in entry["anchor_ids"]]

        line = f"{{dp}}`{irm_id}` {{ts}}`{status}`"
        if status == "mapped":
            line += f" {{rel}}`{relation}`"
            for anchor in anchors:
                line += f" {{a}}`{anchor}`"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _render_yaml_cell(entries: list[dict[str, object]]) -> str:
    blocks: list[str] = []
    for entry in entries:
        anchors = ", ".join(f"'{item}'" for item in entry["anchor_ids"])
        blocks.extend(
            [
                "your_column_key:",
                f"  irm_id: {entry['irm_id']}",
                f"  trace_status: {entry['trace_status']}",
                f"  anchor_ids: [{anchors}]" if anchors else "  anchor_ids: []",
                f"  relation: '{entry['relation']}'",
                "",
            ]
        )
    if blocks and blocks[-1] == "":
        blocks.pop()
    return "\n".join(blocks) + "\n"


def _render_yaml_row(entries: list[dict[str, object]]) -> str:
    blocks: list[str] = []
    for entry in entries:
        anchors = ", ".join(f"'{item}'" for item in entry["anchor_ids"])
        blocks.extend(
            [
                "_trace:",
                f"  irm_id: {entry['irm_id']}",
                f"  trace_status: {entry['trace_status']}",
                f"  anchor_ids: [{anchors}]" if anchors else "  anchor_ids: []",
                f"  relation: '{entry['relation']}'",
                "",
            ]
        )
    if blocks and blocks[-1] == "":
        blocks.pop()
    return "\n".join(blocks) + "\n"


def _render_raw(entries: list[dict[str, object]]) -> str:
    return "\n".join(str(entry["irm_id"]) for entry in entries) + "\n"


def _render_output(mode: str, entries: list[dict[str, object]]) -> str:
    if mode == "myst-preface":
        return _render_myst(entries)
    if mode == "yaml-cell":
        return _render_yaml_cell(entries)
    if mode == "yaml-row":
        return _render_yaml_row(entries)
    return _render_raw(entries)


def _validate_entries(entries: list[dict[str, object]]) -> None:
    for entry in entries:
        irm_id = str(entry["irm_id"])
        status = str(entry["trace_status"])
        relation = str(entry["relation"])
        anchors = [str(item) for item in entry["anchor_ids"]]

        if not is_valid_irm_id(irm_id):
            raise ValueError(f"Invalid IRM ID generated: {irm_id}")
        if status not in TRACE_STATUSES:
            raise ValueError(f"Invalid trace status: {status}")
        if status == "mapped":
            if not relation:
                raise ValueError(f"Mapped IRM ID requires relation: {irm_id}")
            if not anchors:
                raise ValueError(f"Mapped IRM ID requires at least one anchor ID: {irm_id}")


def _write_output(output: str, destination: str) -> None:
    if destination == "stdout":
        print(output, end="")
        return
    output_path = Path(destination)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    print(f"Wrote IRM ID snippets to {output_path}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate ISO 26262 Rust Mapping IDs (IRM IDs) as MyST preface or YAML "
            "snippets for authoring workflows."
        )
    )
    parser.add_argument("--mode", choices=MODES, help="Output mode.")
    parser.add_argument("--count", type=int, help="How many IRM IDs to generate.")
    parser.add_argument(
        "--trace-status",
        choices=TRACE_STATUSES,
        help="Trace status value to apply. Defaults to interactive selection.",
    )
    parser.add_argument(
        "--relation",
        default="",
        help="Relation value used for mapped entries.",
    )
    parser.add_argument(
        "--anchor",
        action="append",
        default=[],
        help="Anchor ID value (repeat to provide multiple anchors).",
    )
    parser.add_argument(
        "--output",
        default="stdout",
        help="stdout or a destination file path.",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Disable prompts and require values from flags.",
    )
    args = parser.parse_args(argv)

    mode = args.mode
    count = args.count

    if args.no_prompt:
        if mode is None or count is None:
            raise SystemExit("--no-prompt requires --mode and --count")
    else:
        if mode is None:
            mode = _prompt_choice(
                "What output do you need?",
                ["myst-preface", "yaml-cell", "yaml-row", "raw"],
            )
        if count is None:
            count = _prompt_count()

    if count is None or count <= 0:
        raise SystemExit("Count must be a positive integer")

    entries = _build_entries(
        count=count,
        trace_status=args.trace_status,
        relation=args.relation,
        anchors=args.anchor,
        no_prompt=args.no_prompt,
    )
    _validate_entries(entries)
    output = _render_output(mode, entries)
    _write_output(output, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
