#!/usr/bin/env python3
"""Statusline: real-time usage straight from Claude Code's stdin payload.

Claude Code (>= ~2.1.x) passes the statusline a rich JSON payload on stdin that
already contains the authoritative, live numbers — no ccusage, no transcript
parsing, no calibrated $ ceilings needed:

  context_window.used_percentage          -> session context fill %
  rate_limits.five_hour.used_percentage   -> real 5-hour rolling limit %
  rate_limits.seven_day.used_percentage   -> real 7-day rolling limit %

The rate-limit percentages are relative to YOUR plan (Pro / Max), so this works
on any subscription with no configuration. These refresh every render, so the
line is always current. If the payload is from an older Claude Code without
rate_limits, we fall back to ccusage's estimated dollars.

Config via env vars (legacy CCUSAGE_* names still honored):
  STATUSLINE_CTX_TARGET   soft context-token target for coloring  (default 100000)
  STATUSLINE_CAUTION_PCT  yellow at/above this %                  (default 60)
  STATUSLINE_WARN_PCT     red + warning at/above                  (default 85)
"""
import sys
import os
import re
import json
import time
import subprocess
from datetime import datetime, timedelta, timezone


def _env(name, default):
    """Read STATUSLINE_<name>, falling back to the legacy CCUSAGE_<name>."""
    return os.environ.get(f"STATUSLINE_{name}", os.environ.get(f"CCUSAGE_{name}", default))


WARN = float(_env("WARN_PCT", "85"))
CAUTION = float(_env("CAUTION_PCT", "60"))
# Soft context target — we like to keep sessions under this many tokens.
# The ctx segment shows absolute tokens, colored against this (not the full window).
CTX_TARGET = float(_env("CTX_TARGET", "100000"))

GREEN, YELLOW, RED, DIM, RESET = (
    "\033[32m", "\033[33m", "\033[1;31m", "\033[2m", "\033[0m",
)
ANSI = re.compile(r"\x1b\[[0-9;]*m")

payload = sys.stdin.read()
try:
    data = json.loads(payload)
except Exception:
    data = {}


def color_for(pct):
    if pct >= WARN:
        return RED
    if pct >= CAUTION:
        return YELLOW
    return GREEN


def pct_gauge(icon, label, pct, suffix=""):
    c = color_for(pct)
    return f"{c}{icon} {label} {pct:.0f}%{suffix}{RESET}", pct >= WARN


def fmt_tokens(t):
    """60541 -> '60.5k', 850 -> '850'."""
    return f"{t / 1000:.1f}k" if t >= 1000 else str(int(t))


def fmt_reset(epoch):
    """'→3h12m' until the given unix timestamp, or '' if unusable."""
    try:
        secs = int(epoch) - int(time.time())
    except Exception:
        return ""
    if secs <= 0:
        return ""
    h, m = secs // 3600, (secs % 3600) // 60
    return f" {DIM}→{h}h{m:02d}m{RESET}" if h else f" {DIM}→{m}m{RESET}"


parts = []
any_warn = False

# ---- context window (absolute tokens vs soft target) ------------------------
cw = data.get("context_window") or {}
ctx_tokens = cw.get("total_input_tokens")
if not isinstance(ctx_tokens, (int, float)):
    cu = cw.get("current_usage") or {}
    ctx_tokens = sum(
        cu.get(k, 0) or 0
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
if ctx_tokens:
    tgt_pct = (ctx_tokens / CTX_TARGET * 100) if CTX_TARGET > 0 else 0.0
    c = color_for(tgt_pct)
    win_pct = cw.get("used_percentage")
    tail = f" {DIM}({win_pct:.0f}%){RESET}" if isinstance(win_pct, (int, float)) else ""
    parts.append(f"{c}\U0001f9e0 ctx {fmt_tokens(ctx_tokens)}{RESET}{tail}")  # 🧠
    any_warn = any_warn or tgt_pct >= WARN

# ---- rate limits (the real 5h / 7d numbers) ---------------------------------
rl = data.get("rate_limits") or {}
used_rl = False
for key, icon, label in (
    ("five_hour", "\U0001f550", "5h"),   # 🕐
    ("seven_day", "\U0001f4c5", "7d"),   # 📅
):
    win = rl.get(key) or {}
    if isinstance(win.get("used_percentage"), (int, float)):
        seg, w = pct_gauge(
            icon, label, float(win["used_percentage"]), fmt_reset(win.get("resets_at"))
        )
        parts.append(seg)
        any_warn = any_warn or w
        used_rl = True

# ---- fallback: older Claude Code without rate_limits -> ccusage --------------
if not used_rl:
    def parse_ts(s):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    try:
        L5H = float(_env("5H_LIMIT", "50"))
        LWEEK = float(_env("WEEK_LIMIT", "500"))
        out = subprocess.run(
            ["ccusage", "blocks", "--json"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        blocks = (json.loads(out) or {}).get("blocks", [])
        now = datetime.now(timezone.utc)
        week_cutoff = now - timedelta(days=7)
        block_5h = week = 0.0
        for b in blocks:
            if b.get("isGap"):
                continue
            cost = b.get("costUSD") or 0.0
            start, end = parse_ts(b.get("startTime", "")), parse_ts(b.get("endTime", ""))
            if b.get("isActive") or (start and end and start <= now < end):
                block_5h = cost
            if end and end >= week_cutoff:
                week += cost
        for spent, limit, icon, label in (
            (block_5h, L5H, "\U0001f550", "5h"),
            (week, LWEEK, "\U0001f4c5", "wk"),
        ):
            pct = (spent / limit * 100) if limit > 0 else 0.0
            c = color_for(pct)
            parts.append(f"{c}{icon} {label} {pct:.0f}% (${spent:.0f}/${limit:.0f}){RESET}")
            any_warn = any_warn or pct >= WARN
    except Exception:
        parts.append(f"{DIM}⚠️ usage unavailable{RESET}")

# ---- model (last) -----------------------------------------------------------
md = data.get("model") or {}
parts.append(f"\U0001f916 {md.get('display_name') or md.get('id') or '?'}")

prefix = "⚠️  " if any_warn else ""
print(prefix + " | ".join(parts))
