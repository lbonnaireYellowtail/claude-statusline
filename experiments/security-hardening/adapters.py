"""Candidate implementations for each security finding: the current ("vulnerable")
behaviour vs the proposed ("fixed") behaviour.

These are self-contained reproductions of the exact logic in statusline.py — NOT
imports of the script — so the experiment can compare before/after without editing
the production file. When CS-001..CS-003 are implemented, the `fixed_*` functions
here are the reference the swarm should match.
"""
import math
import re

# ---------------------------------------------------------------------------
# F1 / CS-001 — terminal escape injection in model.display_name (and model.id)
# ---------------------------------------------------------------------------

# The regex compiled at statusline.py:60 today — only matches SGR (colour) CSI.
LEGACY_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def vulnerable_display(name):
    """statusline.py:238 today — prints the field raw."""
    return str(name)


def legacy_regex_display(name):
    """What the existing line-60 regex would do if naively applied.

    Shown to demonstrate it is NOT a fix: it strips colours but leaves clear,
    OSC, C1, and C0 sequences intact.
    """
    return LEGACY_ANSI.sub("", str(name))


# Allowlist: keep printable text, drop everything that could steer the terminal.
# C0 (0x00-0x1F incl. ESC/newline/BEL), DEL (0x7F), and C1 (0x80-0x9F, the 8-bit
# escape range) are all removed. Whatever survives is inert text.
_DISALLOWED = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def fixed_display(name, limit=64):
    """Proposed CS-001 fix: allowlist to printable characters, length-bounded."""
    cleaned = _DISALLOWED.sub("", str(name))
    return cleaned[:limit] if cleaned else "?"


# ---------------------------------------------------------------------------
# F2 / CS-002 — crash on valid-but-non-object JSON (top-level AND nested)
# ---------------------------------------------------------------------------

def vulnerable_extract(data):
    """Mirrors the `data.get(k) or {}` idiom — crashes on wrong non-falsy types."""
    cw = data.get("context_window") or {}
    tokens = cw.get("total_input_tokens")  # AttributeError if cw is 5, "x", [..]
    md = data.get("model") or {}
    name = md.get("display_name")
    rl = data.get("rate_limits") or {}
    five = rl.get("five_hour")
    return (tokens, name, five)


def _dict_get(d, key):
    """Return d[key] only if it is itself a dict, else {}."""
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def fixed_extract(data):
    """Proposed CS-002 fix: top-level guard + type-checked nested access."""
    if not isinstance(data, dict):
        data = {}
    cw = _dict_get(data, "context_window")
    tokens = cw.get("total_input_tokens")
    md = _dict_get(data, "model")
    name = md.get("display_name")
    rl = _dict_get(data, "rate_limits")
    five = rl.get("five_hour")
    return (tokens, name, five)


# ---------------------------------------------------------------------------
# F3 / CS-003 — persistent shared-cache poisoning
# ---------------------------------------------------------------------------

def _freshness(rl):
    """The monotone key from statusline.py:92 — (resets_at, pct) per window."""
    def num(v):
        return float(v) if isinstance(v, (int, float)) else -1.0
    key = []
    for w in ("five_hour", "seven_day"):
        win = (rl or {}).get(w) or {}
        key += [num(win.get("resets_at")), num(win.get("used_percentage"))]
    return key


def vulnerable_can_overwrite(mine, cached):
    """Today's rule: publish only if strictly fresher. No validation."""
    return _freshness(mine) > _freshness(cached)


# Plausibility bound for resets_at: within the next ~30 days of `now`.
_MAX_RESET_HORIZON = 30 * 24 * 3600


def sanitize_rl(rl, now):
    """Proposed CS-003 fix: drop non-finite, clamp pct to [0,100], bound resets_at.

    Applied on BOTH cache read and before publish so poison can neither be
    trusted nor written.
    """
    out = {}
    for w in ("five_hour", "seven_day"):
        win = (rl or {}).get(w)
        if not isinstance(win, dict):
            continue
        clean = {}
        pct = win.get("used_percentage")
        if isinstance(pct, (int, float)) and math.isfinite(pct):
            clean["used_percentage"] = max(0.0, min(100.0, float(pct)))
        reset = win.get("resets_at")
        if (isinstance(reset, (int, float)) and math.isfinite(reset)
                and now <= reset <= now + _MAX_RESET_HORIZON):
            clean["resets_at"] = float(reset)
        if clean:
            out[w] = clean
    return out


def fixed_can_overwrite(mine, cached, now):
    """CS-003: compare only AFTER sanitizing both sides."""
    return _freshness(sanitize_rl(mine, now)) > _freshness(sanitize_rl(cached, now))
