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

Cross-session sync: rate limits are account-level, but each Claude Code session
only refreshes its own payload. Whichever session has the freshest rate_limits
publishes them to ~/.cache/claude-statusline/shared-rate-limits.json; sessions
holding staler data render from that file instead (marked with a dim ⇄).
Freshness is derived from the data itself — (resets_at, used_percentage) never
decreases within an account — so concurrent writers can't regress the cache.
Pair this with statusLine.refreshInterval in settings.json so idle sessions
poll the cache.
"""
__version__ = "1.1.1"

import sys
import os
import re
import json
import math
import time
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


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

# Printable allowlist for untrusted labels: drop C0 (0x00-0x1F incl.
# ESC/newline/BEL), DEL (0x7F), and C1 (0x80-0x9F, the 8-bit escape range).
# Whatever survives is inert text that cannot steer the terminal (CWE-150).
_LABEL_DISALLOWED = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize_label(name, limit=64):
    """Allowlist an untrusted label to printable characters, length-bounded."""
    cleaned = _LABEL_DISALLOWED.sub("", str(name))
    return cleaned[:limit] if cleaned else "?"


def _dict_get(d, key):
    """Return d[key] only if it is itself a dict, else {}.

    The stdin payload is untrusted: a key may legitimately parse to a non-dict
    (e.g. context_window: 5, rate_limits: [1, 2]). The old `d.get(k) or {}`
    idiom only handles falsy values — a wrong non-falsy type sails through and
    crashes the subsequent .get(). Type-checking here keeps every nested access
    total (CWE-20 robustness).
    """
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}

payload = sys.stdin.read()
try:
    data = json.loads(payload)
except Exception:
    data = {}
# Valid JSON need not be an object: null, [1,2,3], "hi", 42 all parse fine.
if not isinstance(data, dict):
    data = {}

CACHE_DIR = os.path.expanduser("~/.cache/claude-statusline")
SHARED_RL = os.path.join(CACHE_DIR, "shared-rate-limits.json")
CCUSAGE_CACHE = os.path.join(CACHE_DIR, "ccusage.json")


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def atomic_write(path, obj):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception:
        pass


def rl_freshness(rl):
    """Monotone freshness key for a rate_limits blob.

    Within a rate-limit window used_percentage only grows; when a window rolls
    over, resets_at jumps forward. So (resets_at, pct) per window sorts any two
    snapshots of the same account by recency, regardless of which session saw
    them or when.
    """
    def num(v):
        return float(v) if isinstance(v, (int, float)) else -1.0

    key = []
    for w in ("five_hour", "seven_day"):
        win = (rl or {}).get(w) or {}
        key += [num(win.get("resets_at")), num(win.get("used_percentage"))]
    return key


# Plausibility bound for resets_at, PER WINDOW: a rolling window can never
# reset further out than its own length (plus slack for clock skew / rollover).
# A far-future resets_at sorts first in the freshness key, so a flat bound wide
# enough to be safe (e.g. 30d) would still let a poison with resets_at inside
# that bound win forever and pin a red alarm; keying the bound to each window's
# real length is what actually makes poison overwritable by a legit session.
_RESET_HORIZON = {"five_hour": 6 * 3600, "seven_day": 8 * 24 * 3600}


def sanitize_rl(rl, now):
    """Return a rate_limits blob with only trustworthy values (CS-003).

    For each of five_hour / seven_day: drop non-finite numbers (rejects NaN and
    Infinity, which json.loads happily accepts), clamp used_percentage to
    [0,100], and keep resets_at only if it falls within that window's own
    plausible horizon (now <= resets_at <= now + horizon). Any field failing
    its check is dropped.

    Applied identically on BOTH sides of the sync — the cache contents on read
    and the live payload before publish — so poison can neither be trusted nor
    written, and the lock-free freshness invariant (same transform both sides)
    is preserved.
    """
    out = {}
    for w in ("five_hour", "seven_day"):
        win = rl.get(w) if isinstance(rl, dict) else None
        if not isinstance(win, dict):
            continue
        clean = {}
        pct = win.get("used_percentage")
        if isinstance(pct, (int, float)) and math.isfinite(pct):
            clean["used_percentage"] = max(0.0, min(100.0, float(pct)))
        reset = win.get("resets_at")
        if (isinstance(reset, (int, float)) and math.isfinite(reset)
                and now <= reset <= now + _RESET_HORIZON[w]):
            clean["resets_at"] = float(reset)
        if clean:
            out[w] = clean
    return out


def sync_rate_limits(rl):
    """Publish rl if it's the freshest known; return (rl_to_render, from_shared).

    Both the live payload and the shared-cache contents are sanitized before
    they are compared, rendered, or published (CS-003), so a poisoned cache can
    neither win the monotone freshness comparison nor be written back.
    """
    now = time.time()
    rl = sanitize_rl(rl, now)
    shared = load_json(SHARED_RL) or {}
    shared_rl = sanitize_rl(shared.get("rate_limits"), now)
    mine, theirs = rl_freshness(rl), rl_freshness(shared_rl)
    if mine > theirs:
        atomic_write(SHARED_RL, {"rate_limits": rl})
        return rl, False
    if theirs > mine:
        return shared_rl, True
    return rl, False


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
cw = _dict_get(data, "context_window")
ctx_tokens = cw.get("total_input_tokens")
if not isinstance(ctx_tokens, (int, float)):
    cu = _dict_get(cw, "current_usage")
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
rl, from_shared = sync_rate_limits(_dict_get(data, "rate_limits"))
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
if used_rl and from_shared:
    parts[-1] += f" {DIM}⇄{RESET}"

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
        # ccusage is slow; with refreshInterval polling, reuse its output for 60s.
        cached = load_json(CCUSAGE_CACHE) or {}
        if time.time() - cached.get("ts", 0) < 60:
            out = cached.get("out", "")
        else:
            out = subprocess.run(
                [shutil.which("ccusage") or "ccusage", "blocks", "--json"],
                capture_output=True, text=True, timeout=15,
            ).stdout
            atomic_write(CCUSAGE_CACHE, {"ts": time.time(), "out": out})
        parsed = json.loads(out)
        blocks = parsed.get("blocks", []) if isinstance(parsed, dict) else []
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
md = _dict_get(data, "model")
parts.append(f"\U0001f916 {sanitize_label(md.get('display_name') or md.get('id') or '?')}")

prefix = "⚠️  " if any_warn else ""
print(prefix + " | ".join(parts))
