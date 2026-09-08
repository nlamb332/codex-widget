from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path

from PyQt6 import QtWidgets

from .account_usage import DEFAULT_AUTH_FILE, DEFAULT_BASE_URL

from .rings_window import UsageRingsWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone Windows app for Codex usage rings.")
    parser.add_argument("--auth-file", type=Path, default=Path(os.environ.get("CODEX_AUTH_FILE", DEFAULT_AUTH_FILE)))
    parser.add_argument("--base-url", default=os.environ.get("CODEX_USAGE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--refresh-seconds", type=int, default=60)
    parser.add_argument(
        "--start-visible",
        action="store_true",
        help="Show the widget immediately before lifecycle synchronization takes over.",
    )
    args = parser.parse_args(argv)
    instance_mutex = _acquire_single_instance()
    if instance_mutex == 0:
        return 0

    app = QtWidgets.QApplication(sys.argv[:1])
    # Hiding the rings while Codex is closed must not terminate the listener.
    app.setQuitOnLastWindowClosed(False)
    widget = UsageRingsWindow(
        auth_file=args.auth_file,
        base_url=args.base_url,
        refresh_seconds=args.refresh_seconds,
    )
    if args.start_visible:
        widget.show()
        widget._raise_without_focus()
    else:
        # Resolve the initial state before entering the event loop. The timer
        # continues polling, but startup no longer depends on its first tick
        # to make the widget visible beside an already-open Codex window.
        widget._sync_with_codex()
    app.aboutToQuit.connect(lambda: _release_single_instance(instance_mutex))
    return app.exec()


def _acquire_single_instance() -> int | None:
    """Keep startup and manual launches from creating duplicate widgets."""

    if sys.platform != "win32":
        return None
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, True, "Local\\CodexUsageRings")
    if not mutex:
        return None
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(mutex)
        return 0
    return mutex


def _release_single_instance(mutex: int | None) -> None:
    if mutex:
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
