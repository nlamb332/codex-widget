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
- Python 3.10 or newer on `PATH` (or available through the `py` launcher)
- A signed-in Codex desktop app

## Installation on another Windows system

Clone the public repository, create an isolated Python environment, and
install the widget:

```powershell
# Replace your-account with the GitHub owner of this repository.
git clone https://github.com/your-account/codex-widget.git
cd codex-widget
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e .
```

If `python` is not available, replace it with `py -3.11` (or another
installed Python 3.10+ version). Install the official ChatGPT desktop app,
which includes Codex, from the [ChatGPT download page](https://chatgpt.com/download/),
open Codex, and sign in before launching. The widget reads the local Codex credential at
`%USERPROFILE%\.codex\auth.json`; never copy that file into this repository.

Confirm that the credentials file exists before starting the widget:

```powershell
Test-Path "$env:USERPROFILE\.codex\auth.json"
```

To verify the installation immediately:

```powershell
.venv\Scripts\python.exe scripts\launch_usage_rings.py --start-visible
```

For automatic startup, create a desktop shortcut and a Startup shortcut that
run `pythonw.exe` with `scripts\start_with_update.py` as the argument and this
repository as the working directory. It pulls the latest `main` from GitHub,
then hands off to the watchdog, which starts the app in the background and
restarts it after an unexpected exit. Update results are logged to
`%LOCALAPPDATA%\CodexUsageRings\update.log`.

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
- The Codex and Claude widgets move freely during a drag. On mouse release,
  they snap together only when the final position is within 20 pixels and
  overlaps at least 75% along the alignment axis. The visible card borders
  touch when snapped. Left/right placements align their top or bottom edges;
  top/bottom placements align their left or right edges. Once snapped,
  dragging either card moves the connected pair together. Press `Ctrl+S` while
  a widget is focused to separate the pair.
- Click the window once, then use `Ctrl+-` to make it smaller or `Ctrl+=` /
  `Ctrl++` to make it larger.
- The app starts at the third-smallest size; press `Ctrl+-` once for the
  second-smallest setting and twice for the smallest.
- The title/status banner stays visible at every size. At the two smallest
  settings the refresh time is omitted and the footer uses compact
  percentage-only values so every element stays separated.
- Press `Ctrl+T` to toggle the translucent glass background. The choice is
  saved for the next launch.
- Press `Ctrl+Q` while a widget is focused, or choose **Quit usage rings** from
  its tray menu, to close that widget. Quitting also stops its watchdog, so it
  stays closed until the next sign-in or until you start it again.
- The live rings icon stays in the Windows notification area instead of adding
  a taskbar button. Click it to show the window or right-click for controls.
- Hover over the window for full reset details when using the two smallest
  sizes.
- The header status badge shows `LIVE`, `SYNCING`, or `ERROR`, and appends the
  time of the last successful refresh (for example `LIVE · 14:32`) once usage
  data has loaded.

## Codex lifecycle detection

On Windows, the app checks the current Codex and ChatGPT desktop processes and
the packaged application frame. It polls twice per second so the rings follow
open, minimized, and closed Codex states without a second manual launch.

## Authentication and data

The app reads the local authentication file used by Codex:

```text
~/.codex/auth.json
```

It extracts the access token and account ID, then requests usage from:

```http
GET https://chatgpt.com/backend-api/wham/usage
Authorization: Bearer <access_token>
chatgpt-account-id: <account_id>
Accept: application/json
```

The endpoint may change without notice. Credentials stay local and are sent
only with that usage request.

The widget only reads `auth.json`; it never renews or rewrites it. The Codex
app holds the same refresh token and OpenAI rotates it on every renewal, so a
renewal by the widget could sign Codex out. When a usage request is rejected,
the widget instead asks Codex's own app server for the account with a token
refresh (`codex app-server`, `account/read` with `refreshToken: true`), which
makes no model call, then reads the file again. It asks at most once every 10
minutes. The CLI is found on `PATH`, in the Codex app's install folder, or at
`CODEX_USAGE_CLI`.

Losing the network is not treated as a sign-in problem: offline refreshes
retry every 30 seconds and keep the last rings on screen. Other failures back
off from the normal interval up to 15 minutes and reset on the first success.

## Privacy and repository hygiene

The repository contains source code and installation documentation only. Do
not commit auth files, API keys, tokens, logs, screenshots, or machine-specific
paths. Local credential and environment files are ignored by `.gitignore`.

## Project structure

```text
scripts/launch_usage_rings.py             Development launcher
scripts/codex_usage_rings_watchdog.py   Startup supervisor
scripts/start_with_update.py            Startup entry: update, then supervise
src/codex_usage_rings/app.py             Application entry point
src/codex_usage_rings/host_window.py    Codex process/window detection
src/codex_usage_rings/account_usage.py  Authentication and usage fetching
src/codex_usage_rings/models.py          Usage formatting
src/codex_usage_rings/rings_window.py   PyQt6 window and ring rendering
```
