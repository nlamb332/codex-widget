from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass


# The current Windows Codex desktop shell is packaged as ChatGPT.exe. Older
# builds and the command host use codex.exe, so both names are intentional.
_CODEX_EXECUTABLE_NAMES = {"codex.exe", "chatgpt.exe"}
_PACKAGED_SHELL_CLASS = "applicationframewindow"
_CODEX_TITLE_TOKENS = ("codex", "chatgpt")


@dataclass(frozen=True)
class CodexWindowState:
    """The part of the Codex desktop lifecycle visible to the widget."""

    supported: bool
    running: bool
    window_found: bool
    minimized: bool

    @property
    def should_show_widget(self) -> bool:
        if not self.supported:
            return True
        # A background codex.exe helper can outlive the desktop shell. Require
        # a matching top-level window so closing Codex hides the rings and a
        # newly opened shell can trigger them to return.
        return self.running and self.window_found and not self.minimized


def get_codex_window_state() -> CodexWindowState:
    """Find Codex processes and their top-level windows on Windows.

    The desktop app's visible shell is currently ``ChatGPT.exe`` even though
    the product is Codex. Matching only ``codex.exe`` finds command helpers but
    misses the window that actually changes to the minimized state.
    """

    if sys.platform != "win32":
        return CodexWindowState(supported=False, running=False, window_found=False, minimized=False)

    process_ids = _codex_process_ids()
    if not process_ids:
        return CodexWindowState(supported=True, running=False, window_found=False, minimized=False)

    windows = _codex_windows(process_ids)
    minimized = bool(windows) and all(_USER32.IsIconic(hwnd) for hwnd in windows)
    return CodexWindowState(
        supported=True,
        running=True,
        window_found=bool(windows),
        minimized=minimized,
    )


def _codex_process_ids() -> set[int]:
    kernel32 = _KERNEL32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot in (0, -1):
        return set()

    process_ids: set[int] = set()
    entry = _ProcessEntry32W(dwSize=ctypes.sizeof(_ProcessEntry32W))
    try:
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            name = entry.szExeFile.lower()
            if name in _CODEX_EXECUTABLE_NAMES:
                process_ids.add(int(entry.th32ProcessID))
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return process_ids


def _codex_windows(process_ids: set[int]) -> list[int]:
    windows: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def collect(hwnd, _lparam):
        process_id = ctypes.c_ulong()
        _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        title = ctypes.create_unicode_buffer(256)
        window_class = ctypes.create_unicode_buffer(256)
        _USER32.GetWindowTextW(hwnd, title, len(title))
        _USER32.GetClassNameW(hwnd, window_class, len(window_class))
        owned_by_codex = process_id.value in process_ids
        # MSIX-packaged Windows apps can put their top-level frame in
        # ApplicationFrameHost.exe instead of the app process. In that case
        # the frame class and title are the reliable lifecycle signals.
        packaged_codex_frame = (
            window_class.value.lower() == _PACKAGED_SHELL_CLASS
            and any(token in title.value.lower() for token in _CODEX_TITLE_TOKENS)
        )
        if (owned_by_codex or packaged_codex_frame) and (
            _USER32.IsWindowVisible(hwnd) or _USER32.IsIconic(hwnd)
        ):
            windows.append(int(hwnd))
        return True

    _USER32.EnumWindows(collect, 0)
    return windows


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


if sys.platform == "win32":
    _KERNEL32 = ctypes.windll.kernel32
    _USER32 = ctypes.windll.user32
else:
    _KERNEL32 = None
    _USER32 = None
