# Codex Usage Rings

A standalone Windows desktop app that displays the remaining Codex capacity in
two nested rings. The outer ring is the 5-hour limit, the inner ring is the
weekly limit, and each ring changes from green to amber to red as capacity is
used.

The app follows the Codex desktop window: it appears when Codex is available,
hides when Codex is minimized or closed, restores its last position, and keeps
running across Codex restarts through a small watchdog process.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- PyQt6
- A signed-in Codex desktop app with `~/.codex/auth.json`

## Setup

From PowerShell, create an environment and install the app:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e .
```

For automatic startup, create a desktop shortcut and a Startup shortcut that
run `pythonw.exe` with `scripts\codex_usage_rings_watchdog.py` as the argument
and this repository as the working directory. The watchdog starts the app in
the background and restarts it after an unexpected exit.

## Usage

Run the app directly while developing:

```powershell
python scripts\launch_usage_rings.py
```

Show it immediately for a manual check:

```powershell
python scripts\launch_usage_rings.py --start-visible
```

After installation, the equivalent command is:

```powershell
codex-usage-rings
```

Optional arguments:

```text
--auth-file PATH
--base-url URL
--refresh-seconds SECONDS
--start-visible
```

## Interaction

- Drag the rings window with the left mouse button. Its position is saved and
  restored when it reappears.
- Click the window once, then use `Ctrl+-` to make it smaller or `Ctrl+=` /
  `Ctrl++` to make it larger.
- Press `Ctrl+T` to toggle the translucent glass background. The choice is
  saved for the next launch.
- The live rings icon stays in the Windows notification area instead of adding
  a taskbar button. Click it to show the window or right-click for controls.
- Hover over the window for full reset details when using the two smallest
  sizes.

## Codex lifecycle detection

On Windows, the app checks the current Codex and ChatGPT desktop processes and
the packaged application frame. It polls twice per second so the rings follow
open, minimized, and closed Codex states without a second manual launch.

## Authentication and data

The app reads the local authentication file used by Codex:

```text
~/.codex/auth.json
```

It extracts the access token, account ID, and refresh token as needed, then
requests usage from:

```http
GET https://chatgpt.com/backend-api/wham/usage
Authorization: Bearer <access_token>
chatgpt-account-id: <account_id>
Accept: application/json
```

The endpoint may change without notice. Credentials stay local and are sent
only with that usage request.

## Project structure

```text
scripts/launch_usage_rings.py             Development launcher
scripts/codex_usage_rings_watchdog.py   Startup supervisor
src/codex_usage_rings/app.py             Application entry point
src/codex_usage_rings/host_window.py    Codex process/window detection
src/codex_usage_rings/account_usage.py  Authentication and usage fetching
src/codex_usage_rings/models.py          Usage formatting
src/codex_usage_rings/rings_window.py   PyQt6 window and ring rendering
```
