#!/usr/bin/env python3
"""Keep the standalone Codex usage rings app available across restarts."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIDGET_SCRIPT = PROJECT_ROOT / "scripts" / "launch_usage_rings.py"
_SUPERVISOR_MUTEX = "Local\\CodexUsageRingsSupervisor"
# Must match USER_QUIT_EXIT_CODE in src/codex_usage_rings/app.py.
USER_QUIT_EXIT_CODE = 10
_LOG_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "CodexUsageRings" / "watchdog.log"


def main() -> int:
    mutex = _acquire_supervisor_mutex()
    if mutex == 0:
        _log("supervisor already running")
        return 0

    try:
        while True:
            try:
                creationflags = 0
                if sys.platform == "win32":
                    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                child = subprocess.Popen(
                    [sys.executable, str(WIDGET_SCRIPT)],
                    cwd=str(PROJECT_ROOT),
                    close_fds=True,
                    creationflags=creationflags,
                )
                _log(f"widget started pid={child.pid}")
                return_code = child.wait()
                _log(f"widget exited code={return_code}")
            except Exception as exc:
                # Keep supervising if a transient process or filesystem error
                # prevents one child from starting. Only exception metadata is
                # logged; auth tokens and request contents are never written.
                _log(f"supervisor error {type(exc).__name__}")
                time.sleep(5)
                continue
            if return_code == USER_QUIT_EXIT_CODE:
                # The user quit on purpose; restarting would undo that.
                _log("widget quit by user; supervisor stopping")
                return 0
            # A normal close or a transient startup failure should not leave
            # the widget unavailable, but avoid a tight respawn loop.
            time.sleep(3)
    finally:
        _release_supervisor_mutex(mutex)


def _log(message: str) -> None:
    """Write minimal lifecycle diagnostics without credentials or payloads."""

    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with _LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except OSError:
        # Logging must never prevent supervision.
        pass


def _acquire_supervisor_mutex() -> int | None:
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, True, _SUPERVISOR_MUTEX)
    if not mutex:
        return None
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(mutex)
        return 0
    return mutex


def _release_supervisor_mutex(mutex: int | None) -> None:
    if mutex:
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
