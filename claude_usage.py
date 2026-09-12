#!/usr/bin/env python3
"""Read Claude subscription plan usage and report it as two numbers.

Runs `claude -p /usage`. That is a local command of Claude Code itself: it
costs no tokens and does not count against your limits. The text it prints
carries the current session (the five hour window) and the week, both as
percent used. The same numbers as on claude.ai/settings/usage.

Usage:
  claude-usage          14 50
  claude-usage --json   {"current": 14, "weekly": 50, ...}

Also imported as a module by server.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Why these flags:
# --no-session-persistence  otherwise every call leaves a session file behind
# --strict-mcp-config       do not start MCP servers, saves time
# disableAllHooks           otherwise your hooks run too (a Stop hook would fire)
# --bare cannot be used: it skips the subscription login.
CLAUDE_ARGS = [
    "-p", "/usage",
    "--no-session-persistence",
    "--strict-mcp-config",
    "--settings", '{"disableAllHooks": true}',
]

TIMEOUT_SECONDS = 60

MONTHS = {name: nr for nr, name in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

# Example lines from /usage:
#   Current session: 14% used · resets Sep 11 at 10:10pm (Europe/Amsterdam)    (2.1.268)
#   Current week (all models): 50% used · resets Sep 15, 12am (Europe/Amsterdam) (2.1.267)
LINES = {
    "current": re.compile(r"^Current session:\s*(?P<pct>\d+(?:\.\d+)?)%\s*used(?P<rest>.*)$", re.M),
    "weekly": re.compile(r"^Current week(?: \(all models\))?:\s*(?P<pct>\d+(?:\.\d+)?)%\s*used(?P<rest>.*)$", re.M),
}

RESET = re.compile(
    r"resets\s+"
    r"(?:(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})(?:,?\s*(?P<year>\d{4}))?(?:,|\s+at)?\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ampm>[ap]m)"
    r"(?:\s*\((?P<tz>[^)]+)\))?"
)


class UsageError(Exception):
    pass


def find_claude() -> str:
    candidates = [os.environ.get("CLAUDE_BIN"), shutil.which("claude"),
                  os.path.expanduser("~/.local/bin/claude")]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    raise UsageError("claude not found; set CLAUDE_BIN or install Claude Code")


def run_usage() -> str:
    env = dict(os.environ)
    # With an API key in the environment Claude Code would spend credits instead of the subscription.
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    try:
        proc = subprocess.run(
            [find_claude(), *CLAUDE_ARGS],
            stdin=subprocess.DEVNULL,  # `claude -p` reads stdin empty otherwise
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
            env=env, cwd=os.path.expanduser("~"),
        )
    except subprocess.TimeoutExpired:
        raise UsageError(f"claude did not answer within {TIMEOUT_SECONDS} s") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip() or "no output"
        raise UsageError(f"claude exited with code {proc.returncode}: {detail}")
    return proc.stdout


def _zone(name: str | None, fallback: tzinfo) -> tzinfo:
    if not name:
        return fallback
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return fallback


def parse_reset(rest: str, now: datetime) -> datetime | None:
    m = RESET.search(rest)
    if not m:
        return None
    zone = _zone(m["tz"], now.tzinfo)
    local_now = now.astimezone(zone)
    hour = int(m["hour"]) % 12 + (12 if m["ampm"] == "pm" else 0)
    minute = int(m["min"] or 0)

    if not m["mon"]:
        # Only a time: today, or tomorrow when that time has already passed.
        moment = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return moment if moment >= local_now - timedelta(minutes=1) else moment + timedelta(days=1)

    # /usage names no year. A reset always lies in the future, so around new year
    # "Jan 2" belongs to the next one.
    years = [int(m["year"])] if m["year"] else [local_now.year, local_now.year + 1]
    for year in years:
        moment = datetime(year, MONTHS[m["mon"]], int(m["day"]), hour, minute, tzinfo=zone)
        if moment >= local_now - timedelta(days=1):
            return moment
    return moment


def parse(text: str, now: datetime | None = None) -> dict:
    now = now or datetime.now().astimezone()
    result: dict = {}
    for key, pattern in LINES.items():
        m = pattern.search(text)
        if not m:
            raise UsageError(
                "no subscription data in the output of /usage. Is Claude Code signed in with a "
                "subscription account, or did the format change? Output was:\n" + text.strip())
        pct = float(m["pct"])
        result[key] = int(pct) if pct.is_integer() else pct
        reset = parse_reset(m["rest"], now)
        result[f"{key}_resets_at"] = reset.isoformat() if reset else None
    result["fetched_at"] = now.isoformat(timespec="seconds")
    return result


def fetch() -> dict:
    return parse(run_usage())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claude-usage",
        description="Claude subscription plan usage: current session and week, as percent used.")
    parser.add_argument("--json", action="store_true",
                        help="everything as JSON, including the reset times")
    args = parser.parse_args(argv)
    try:
        usage = fetch()
    except UsageError as e:
        print(f"claude-usage: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(usage, indent=2))
    else:
        print(usage["current"], usage["weekly"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
