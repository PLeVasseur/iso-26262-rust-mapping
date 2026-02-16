"""CLI scaffold for standalone ISO 26262 mining."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from .constants import CHECKLIST_KEYS, STAGES
from .envfiles import parse_env, write_env
from .framework import RunPaths, write_phase_checkpoint, write_stage_checkpoint
from .locking import LockContentionError, acquire_lock, release_lock
from .state import (
    ContractDriftError,
    StatePaths,
    StopConditionError,
    bootstrap_state,
    complete_stage,
    reconcile_resume,
    reset_stage_checklist,
)
from .stages import HANDLERS, StageContext


class ExitCode:
    SUCCESS = 0
    USAGE = 2
    INGEST_OR_EXTRACT = 3
    SCHEMA = 4
    DETERMINISM = 5
    QA_BLOCK = 6
    LOCK_ACTIVE = 7
    CONTRACT_DRIFT = 8
    STOP_CONDITION = 9


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
        "--plan-path", default="plans/2026-02-15-hierarchical-pdf-mining-corpus-plan.md"
    )
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--target-branch", default="")
    parser.add_argument("--base-pin-sha", default="")
    parser.add_argument(
        "--control-run-root",
        required=True,
        help="Control-plane run root path (required)",
    )
    parser.add_argument(
        "--resume-run", default="", help="Resume token or explicit run root"
    )
    parser.add_argument(
        "--no-resume", action="store_true", help="Reject existing resumable state"
    )
    parser.add_argument("--lock-timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--source-pdfset", default="traceability/iso26262/index/source-pdfset.jsonc"
    )
    parser.add_argument(
        "--relevant-policy",
        default="traceability/iso26262/index/relevant-pdf-policy.jsonc",
    )
    parser.add_argument(
        "--extraction-policy",
        default="tools/traceability/mining/config/extraction_policy_v1.jsonc",
    )
    parser.add_argument("--lock-source-hashes", action="store_true")
    parser.add_argument("--edition", default="")
    parser.add_argument("--parts", default="")
    parser.add_argument(
        "--mode", choices=("fixture_ci", "licensed_local"), default="licensed_local"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fail-on-qa", action=argparse.BooleanOptionalAction, default=True
    )
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
    state_file = Path(args.control_run_root).resolve() / "state.env"
    existing_state = parse_env(state_file)
    run_id = args.run_id or existing_state.get("RUN_ID", "") or "adhoc"
    run_root = (
        Path(args.run_root).resolve()
        if args.run_root
        else _default_run_root(repo_root, run_id)
    )
    pdf_root = (
        Path(args.pdf_root).resolve()
        if args.pdf_root
        else (repo_root / ".cache" / "iso26262")
    )
    control_root = Path(args.control_run_root).resolve()
    paths = RunPaths(
        repo_root=repo_root,
        control_run_root=control_root,
        run_root=run_root,
        pdf_root=pdf_root,
    )
    return run_id, paths


def _git_value(repo_root: Path, args: list[str], fallback: str = "") -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
        value = completed.stdout.strip()
        return value or fallback
    except Exception:
        return fallback


def _ensure_roots(paths: RunPaths) -> None:
    paths.control_run_root.mkdir(parents=True, exist_ok=True)
    (paths.control_run_root / "artifacts" / "checkpoints").mkdir(
        parents=True, exist_ok=True
    )
    (paths.control_run_root / "lock").mkdir(parents=True, exist_ok=True)
    paths.run_root.mkdir(parents=True, exist_ok=True)


def _state_paths(paths: RunPaths) -> StatePaths:
    return StatePaths(
        state_file=paths.control_run_root / "state.env",
        checklist_file=paths.control_run_root / "checklist.state.env",
        run_log=paths.control_run_root / "run.log",
        checkpoint_dir=paths.control_run_root / "artifacts" / "checkpoints",
    )


def _phase_number_for_stage(stage: str) -> int:
    return {
        "ingest": 2,
        "extract": 2,
        "normalize": 3,
        "anchor": 3,
        "publish": 3,
        "verify": 4,
        "finalize": 4,
    }.get(stage, 0)


def _mark_checklist_stage_complete(stage: str, checklist: dict[str, str]) -> None:
    for key in CHECKLIST_KEYS[stage]:
        checklist[key] = "1"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    run_id, paths = _resolve_paths(args)
    _ensure_roots(paths)
    state_paths = _state_paths(paths)

    repo_root = paths.repo_root
    target_branch = args.target_branch or _git_value(
        repo_root, ["rev-parse", "--abbrev-ref", "HEAD"], ""
    )
    base_pin_sha = args.base_pin_sha or _git_value(
        repo_root, ["rev-parse", args.base_branch], ""
    )

    try:
        state, checklist = bootstrap_state(
            paths=state_paths,
            run_id=run_id,
            repo_root=repo_root,
            run_root=paths.run_root,
            pdf_root=paths.pdf_root,
            control_run_root=paths.control_run_root,
            plan_path=Path(args.plan_path).resolve(),
            source_pdfset_path=Path(args.source_pdfset).resolve(),
            relevant_policy_path=Path(args.relevant_policy).resolve(),
            extraction_policy_path=Path(args.extraction_policy).resolve(),
            base_branch=args.base_branch,
            target_branch=target_branch,
            base_pin_sha=base_pin_sha,
            mode=args.mode,
            required_parts_csv=args.parts,
        )
    except ContractDriftError as exc:
        print(str(exc))
        return ExitCode.CONTRACT_DRIFT

    lock_file = Path(state["LOCK_FILE"])
    lock_acquired = False
    try:
        acquire_lock(lock_file, state_paths.run_log, run_id)
        lock_acquired = True
    except LockContentionError as exc:
        print(str(exc))
        return ExitCode.LOCK_ACTIVE

    try:
        state, checklist, _ = reconcile_resume(
            state=state, checklist=checklist, paths=state_paths
        )
        if args.command in HANDLERS:
            stage = args.command

            reset_stage_checklist(stage, checklist)
            write_env(state_paths.checklist_file, checklist)

            phase = _phase_number_for_stage(stage)
            ctx = StageContext(
                run_id=run_id,
                phase=phase,
                paths=paths,
                mode=args.mode,
                source_pdfset_path=Path(args.source_pdfset).resolve(),
                relevant_policy_path=Path(args.relevant_policy).resolve(),
                extraction_policy_path=Path(args.extraction_policy).resolve(),
                lock_source_hashes=bool(args.lock_source_hashes),
            )
            result = HANDLERS[stage](ctx)

            _mark_checklist_stage_complete(stage, checklist)
            write_env(state_paths.checklist_file, checklist)

            output_paths = [str(path) for path in result.outputs]
            input_hashes = result.input_hashes
            stage_checkpoint = write_stage_checkpoint(
                paths=paths,
                run_id=run_id,
                stage=stage,
                phase=phase,
                input_hashes=input_hashes,
                outputs=output_paths,
            )
            phase_checkpoint = write_phase_checkpoint(
                paths=paths,
                run_id=run_id,
                phase=phase,
                stage=stage,
                input_hashes=input_hashes,
                outputs=[*output_paths, str(stage_checkpoint)],
            )

            state["LAST_COMMITTED_CHECKPOINT"] = str(phase_checkpoint)
            state["CURRENT_PHASE"] = str(phase)
            write_env(state_paths.state_file, state)
            state, checklist = complete_stage(
                stage=stage, state=state, checklist=checklist, paths=state_paths
            )
            print(f"stage={stage}")
            print(f"stage_checkpoint={stage_checkpoint}")
            print(f"phase_checkpoint={phase_checkpoint}")
            return ExitCode.SUCCESS

        if args.command in {"replay", "qa-list", "qa-apply"}:
            return ExitCode.SUCCESS

    except StopConditionError as exc:
        print(str(exc))
        return ExitCode.STOP_CONDITION
    finally:
        if lock_acquired:
            release_lock(lock_file, state_paths.run_log, run_id)

    parser.error(f"unsupported command: {args.command}")
    return ExitCode.USAGE


if __name__ == "__main__":
    raise SystemExit(main())
