from __future__ import annotations

import base64
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_AUTH_FILE = Path.home() / ".codex" / "auth.json"
DEFAULT_BASE_URL = "https://chatgpt.com/backend-api"
# Codex renews the sign-in, not the widget (see _renew_with_codex_guarded).
# Ask at most once per cooldown window so a persistently rejected token cannot
# start Codex on every refresh tick.
RENEWAL_COOLDOWN_SECONDS = 600
CODEX_RENEWAL_TIMEOUT_SECONDS = 60
# Keep Codex's console window hidden when the widget runs under pythonw.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_LAST_RENEWAL_ATTEMPT = 0.0


class CodexUsageError(RuntimeError):
    pass


class CodexNetworkError(CodexUsageError):
    """No connection was made (for example, Wi-Fi is down), so nothing changed server-side."""


@dataclass(frozen=True)
class UsageWindow:
    used_percent: float | None
    reset_at: int | None
    window_seconds: int | None

    @property
    def remaining_percent(self) -> float | None:
        if self.used_percent is None:
            return None
        return max(0.0, 100.0 - self.used_percent)


@dataclass(frozen=True)
class CodexUsage:
    five_hour: UsageWindow | None
    weekly: UsageWindow | None
    plan_type: str | None


def load_auth(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise CodexUsageError(f"Auth file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CodexUsageError(f"Invalid auth file: {path}") from exc
    if not isinstance(data, dict):
        raise CodexUsageError("Auth file does not contain a JSON object")
    return data


def extract_access_token(auth: dict[str, Any]) -> str:
    tokens = auth.get("tokens")
    if isinstance(tokens, dict):
        for key in ("access_token", "accessToken"):
            value = tokens.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise CodexUsageError("Could not find tokens.access_token in auth.json")


def extract_account_id(auth: dict[str, Any]) -> str:
    tokens = auth.get("tokens")
    if isinstance(tokens, dict):
        for key in ("account_id", "accountId"):
            value = tokens.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        id_token = tokens.get("id_token") or tokens.get("idToken")
        if isinstance(id_token, str):
            account_id = _account_id_from_id_token(id_token)
            if account_id:
                return account_id

    raise CodexUsageError("Could not find chatgpt-account-id in auth.json")


def fetch_usage(access_token: str, account_id: str, base_url: str, timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/wham/usage"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = _safe_error_body(exc)
        raise CodexUsageError(f"HTTP {exc.code} while fetching usage: {detail}") from exc
    except URLError as exc:
        raise CodexNetworkError(f"Network error while fetching usage: {exc.reason}") from exc
    except TimeoutError as exc:
        raise CodexNetworkError("Timed out while fetching usage") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise CodexUsageError("Usage response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise CodexUsageError("Usage response does not contain a JSON object")
    return data


def fetch_usage_with_auth_refresh(auth_file: Path, base_url: str, timeout: float) -> dict[str, Any]:
    # Try the stored token first: a rejected request proves the network is up,
    # while an offline one raises CodexNetworkError and never reaches renewal.
    try:
        return _fetch_with_stored_auth(auth_file, base_url, timeout)
    except CodexUsageError as exc:
        if not _is_auth_failure(exc):
            raise

    _renew_with_codex_guarded()
    try:
        return _fetch_with_stored_auth(auth_file, base_url, timeout)
    except CodexUsageError as exc:
        if not _is_auth_failure(exc):
            raise
        raise CodexUsageError(
            "Codex still rejects the sign-in after Codex tried to renew it. Run `codex login`."
        ) from exc


def _fetch_with_stored_auth(auth_file: Path, base_url: str, timeout: float) -> dict[str, Any]:
    auth = load_auth(auth_file)
    return fetch_usage(extract_access_token(auth), extract_account_id(auth), base_url, timeout)


def _renew_with_codex_guarded() -> None:
    """Have Codex renew its own sign-in, at most once per cooldown window.

    The widget never renews or writes auth.json itself. The Codex app keeps the
    same refresh token in memory and OpenAI rotates it on every renewal, so a
    renewal by the widget could leave Codex holding a spent token and sign it
    out. Instead the widget asks Codex's app server for the account with
    refreshToken=true, which runs Codex's normal refresh flow without a model
    call, and the caller then reads auth.json again.
    """

    global _LAST_RENEWAL_ATTEMPT

    now = time.monotonic()
    since = now - _LAST_RENEWAL_ATTEMPT
    if _LAST_RENEWAL_ATTEMPT and since < RENEWAL_COOLDOWN_SECONDS:
        raise CodexUsageError(
            f"Codex rejected the access token; Codex was asked to renew it {int(since)}s ago. "
            f"Trying again in {int(RENEWAL_COOLDOWN_SECONDS - since)}s; run `codex login` if this persists."
        )
    cli = find_codex_cli()
    if cli is None:
        raise CodexUsageError(
            "The sign-in needs renewing but the Codex CLI was not found. "
            "Run `codex login`, or set CODEX_USAGE_CLI to codex.exe."
        )
    _LAST_RENEWAL_ATTEMPT = now
    reply = _request_account_refresh(_codex_app_server_command(cli))
    if "error" in reply:
        error = reply.get("error")
        message = error.get("message") if isinstance(error, dict) else error
        raise CodexUsageError(f"Codex could not renew the sign-in: {str(message or 'unknown error')[:200]}")
    result = reply.get("result")
    if not isinstance(result, dict) or not result.get("account"):
        raise CodexUsageError("Codex is signed out. Run `codex login`.")


def _codex_app_server_command(cli: str) -> list[str]:
    return [cli, "app-server"]


def _request_account_refresh(command: list[str]) -> dict[str, Any]:
    """Speak just enough of the app-server protocol to request account/read."""

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path.home()),
            creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        raise CodexUsageError(f"Could not start Codex to renew the sign-in ({type(exc).__name__})") from exc

    messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
    threading.Thread(target=_pump_messages, args=(process.stdout, messages), daemon=True).start()
    deadline = time.monotonic() + CODEX_RENEWAL_TIMEOUT_SECONDS
    try:
        _send_message(
            process,
            {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "codex-usage-rings", "version": "1"}}},
        )
        _await_reply(messages, 1, deadline)
        _send_message(process, {"method": "initialized"})
        _send_message(process, {"id": 2, "method": "account/read", "params": {"refreshToken": True}})
        return _await_reply(messages, 2, deadline)
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _send_message(process: subprocess.Popen, message: dict[str, Any]) -> None:
    try:
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
    except OSError as exc:
        raise CodexUsageError("Codex exited before the sign-in could be renewed") from exc


def _pump_messages(stream, messages: queue.Queue) -> None:
    for line in stream:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            messages.put(message)
    messages.put(None)


def _await_reply(messages: queue.Queue, request_id: int, deadline: float) -> dict[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexUsageError("Timed out waiting for Codex to renew the sign-in")
        try:
            message = messages.get(timeout=remaining)
        except queue.Empty:
            continue
        if message is None:
            raise CodexUsageError("Codex exited before the sign-in could be renewed")
        if message.get("id") == request_id and ("result" in message or "error" in message):
            return message


def find_codex_cli() -> str | None:
    """Locate the Codex CLI: an override, PATH, then the Codex app's copy."""

    configured = os.environ.get("CODEX_USAGE_CLI")
    if configured and Path(configured).is_file():
        return configured
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    bundled = Path(local_app_data, "OpenAI", "Codex", "bin")
    if (bundled / "codex.exe").is_file():
        return str(bundled / "codex.exe")
    versions = sorted(bundled.glob("*/codex.exe"), key=lambda path: path.stat().st_mtime)
    return str(versions[-1]) if versions else None


def parse_usage_payload(payload: dict[str, Any], now: int | None = None) -> CodexUsage:
    now_epoch = int(time.time()) if now is None else now
    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        return CodexUsage(five_hour=None, weekly=None, plan_type=_plan_type(payload))

    primary = _parse_window(rate_limit.get("primary_window"), now_epoch)
    secondary = _parse_window(rate_limit.get("secondary_window"), now_epoch)

    five_hour = None
    weekly = None
    for window in (primary, secondary):
        if window is None:
            continue
        if window.window_seconds == 604800:
            weekly = window
        elif window.window_seconds == 18000:
            five_hour = window

    if five_hour is None and primary is not None and primary.window_seconds != 604800:
        five_hour = primary
    if weekly is None and secondary is not None:
        weekly = secondary

    return CodexUsage(five_hour=five_hour, weekly=weekly, plan_type=_plan_type(payload))


def _account_id_from_id_token(id_token: str) -> str | None:
    parts = id_token.split(".")
    if len(parts) < 2:
        return None
    try:
        payload = parts[1] + ("=" * (-len(parts[1]) % 4))
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        claims = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(claims, dict):
        return None

    auth_claims = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claims, dict):
        value = auth_claims.get("chatgpt_account_id")
        if isinstance(value, str) and value.strip():
            return value.strip()

    value = claims.get("chatgpt_account_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _safe_error_body(exc: HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return exc.reason or "error without details"
    if not raw:
        return exc.reason or "error without details"
    return raw[:500]


def _is_auth_failure(exc: CodexUsageError) -> bool:
    return str(exc).startswith("HTTP 401 ") or str(exc).startswith("HTTP 403 ")


def _parse_window(raw: Any, now: int) -> UsageWindow | None:
    if not isinstance(raw, dict):
        return None

    used_percent = _as_float(raw.get("used_percent"))
    reset_at = _as_int(raw.get("reset_at"))
    reset_after = _as_int(raw.get("reset_after_seconds"))
    if reset_at is None and reset_after is not None:
        reset_at = now + reset_after

    return UsageWindow(
        used_percent=used_percent,
        reset_at=reset_at,
        window_seconds=_as_int(raw.get("limit_window_seconds")),
    )


def _plan_type(payload: dict[str, Any]) -> str | None:
    value = payload.get("plan_type")
    return value if isinstance(value, str) and value else None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
