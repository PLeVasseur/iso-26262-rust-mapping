"""CLI scaffold for standalone ISO 26262 mining."""

from __future__ import annotations

import argparse
from pathlib import Path

from .constants import STAGES
from .framework import RunPaths
from .stages import HANDLERS, StageContext


def _repo_root_from_cwd() -> Path:
    return Path.cwd().resolve()


def _default_run_root(repo_root: Path, run_id: str) -> Path:
    return repo_root / ".cache" / "iso26262" / "mining" / "runs" / run_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mine_iso_corpus.py",
        description="Standalone ISO 26262 corpus mining pipeline",
    )
    parser.add_argument("--run-id", default="", help="Run identifier (UTC timestamp)")
    parser.add_argument("--run-root", default="", help="Data-plane run root path")
    parser.add_argument("--pdf-root", default="", help="PDF source root path")
    parser.add_argument(
        "--control-run-root",
        required=True,
        help="Control-plane run root path (required)",
    )
    parser.add_argument("--resume-run", default="", help="Resume token or explicit run root")
    parser.add_argument("--no-resume", action="store_true", help="Reject existing resumable state")
    parser.add_argument("--lock-timeout-seconds", type=int, default=120)
    parser.add_argument("--source-pdfset", default="traceability/iso26262/index/source-pdfset.jsonc")
    parser.add_argument("--relevant-policy", default="traceability/iso26262/index/relevant-pdf-policy.jsonc")
    parser.add_argument(
        "--extraction-policy",
        default="tools/traceability/mining/config/extraction_policy_v1.jsonc",
    )
    parser.add_argument("--lock-source-hashes", action="store_true")
    parser.add_argument("--edition", default="")
    parser.add_argument("--parts", default="")
    parser.add_argument("--mode", choices=("fixture_ci", "licensed_local"), default="licensed_local")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fail-on-qa", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--allow-partial-scope", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)
    for name in STAGES:
        sub.add_parser(name, help=f"Run {name} stage")

    sub.add_parser("replay", help="Replay from run manifest")
    sub.add_parser("qa-list", help="List unresolved QA items")
    sub.add_parser("qa-apply", help="Apply QA adjudication ledger")
    return parser


def _resolve_paths(args: argparse.Namespace) -> tuple[str, RunPaths]:
    repo_root = _repo_root_from_cwd()
    run_id = args.run_id or "adhoc"
    run_root = Path(args.run_root).resolve() if args.run_root else _default_run_root(repo_root, run_id)
    pdf_root = Path(args.pdf_root).resolve() if args.pdf_root else (repo_root / ".cache" / "iso26262")
    control_root = Path(args.control_run_root).resolve()
    paths = RunPaths(
        repo_root=repo_root,
        control_run_root=control_root,
        run_root=run_root,
        pdf_root=pdf_root,
    )
    return run_id, paths


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    run_id, paths = _resolve_paths(args)

    if args.command in HANDLERS:
        ctx = StageContext(run_id=run_id, phase=0, paths=paths, mode=args.mode)
        HANDLERS[args.command](ctx)
        return 0

    if args.command in {"replay", "qa-list", "qa-apply"}:
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2
