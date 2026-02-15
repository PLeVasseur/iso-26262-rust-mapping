"""Single-writer lock handling for control-plane run roots."""

from __future__ import annotations

import getpass
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from .framework import utc_now


class LockContentionError(RuntimeError):
    """Raised when a valid active lock exists."""


@dataclass(frozen=True)
class LockPayload:
    pid: int
    host: str
    user: str
    run_id: str
    acquired_at_utc: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "pid": self.pid,
                "host": self.host,
                "user": self.user,
                "run_id": self.run_id,
                "acquired_at_utc": self.acquired_at_utc,
            },
            sort_keys=True,
        )


def _append_log(run_log: Path, line: str) -> None:
    run_log.parent.mkdir(parents=True, exist_ok=True)
    with run_log.open("a", encoding="utf-8") as handle:
        handle.write(f"[{utc_now()}] {line}\n")


def _pid_active(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_lock(lock_file: Path, run_log: Path, run_id: str) -> LockPayload:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    if lock_file.exists() and lock_file.read_text(encoding="utf-8").strip():
        prior_raw = lock_file.read_text(encoding="utf-8").strip()
        prior_payload: dict[str, object]
        try:
            prior_payload = json.loads(prior_raw)
        except json.JSONDecodeError:
            prior_payload = {}

        prior_pid = int(prior_payload.get("pid", 0)) if str(prior_payload.get("pid", "")).isdigit() else 0
        if _pid_active(prior_pid):
            raise LockContentionError(
                f"active lock at {lock_file}: pid={prior_pid} host={prior_payload.get('host','?')} user={prior_payload.get('user','?')}"
            )

        _append_log(run_log, f"stale_lock_replaced payload={prior_raw}")

    payload = LockPayload(
        pid=os.getpid(),
        host=socket.gethostname(),
        user=getpass.getuser(),
        run_id=run_id,
        acquired_at_utc=utc_now(),
    )
    lock_file.write_text(payload.to_json() + "\n", encoding="utf-8")
    _append_log(run_log, f"lock_acquired pid={payload.pid} run_id={run_id}")
    return payload


def release_lock(lock_file: Path, run_log: Path, run_id: str) -> None:
    if not lock_file.exists():
        return
    try:
        raw = lock_file.read_text(encoding="utf-8").strip()
    except OSError:
        raw = ""

    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        payload_run = str(payload.get("run_id", ""))
        if payload_run and payload_run != run_id:
            return

    lock_file.unlink(missing_ok=True)
    _append_log(run_log, f"lock_released run_id={run_id}")
