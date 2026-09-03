"""Candidate designs for the weekly-cost ledger (ADR-0003).

Two independent axes, one class per candidate on each:

  Policies  - *what* a statusline tick contributes to the ledger and how the
              weekly figure is read back.  Pure functions over a ledger dict.
  Storages  - *where* the ledger lives and how concurrent statusline
              processes (one per Claude Code session, ticking every 2 s)
              coordinate their writes.

Stdlib-only, mirrors statusline.py's constraints.
"""
import fcntl
import json
import math
import os
import re
import time

HOUR = 3600
WEEK_HOURS = 168
CAP_TOTAL = 10_000.0          # a single session's cumulative cost ($) - beyond this: poison
CAP_DELTA = 100.0             # the most one tick may contribute ($)
CAP_BUCKET = 1e5              # the most one hourly bucket may hold on read ($)
SESSION_TTL = 30 * 24 * HOUR  # remember a session's last total this long (resume-after-prune)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ---------------------------------------------------------------- policies --
class NaiveTotals:
    """The literal proposal: keep each session's latest cumulative total and
    sum the totals of every session seen in the last 7 days."""
    name = "naive-totals"
    guarded = False

    def tick(self, ledger, now, sid, total):
        if isinstance(total, bool) or not isinstance(total, (int, float)):
            return
        ledger.setdefault("sessions", {})[sid] = {"total": float(total), "seen": now}

    def weekly(self, ledger, now):
        return sum(s["total"] for s in ledger.get("sessions", {}).values()
                   if now - s["seen"] < WEEK_HOURS * HOUR)


class HourBuckets:
    """Per-session deltas of the cumulative total, dropped into hourly buckets.
    weekly = sum of the last 168 buckets. Unguarded: trusts the payload."""
    name = "hour-buckets"
    guarded = False

    def tick(self, ledger, now, sid, total):
        if isinstance(total, bool) or not isinstance(total, (int, float)):
            return
        total = float(total)
        if self.guarded and not (math.isfinite(total) and 0.0 <= total <= CAP_TOTAL):
            return
        sess = ledger.setdefault("sessions", {})
        last = sess.get(sid, {}).get("total")
        delta = total if last is None else max(0.0, total - last)
        if self.guarded:
            delta = min(delta, CAP_DELTA)
        sess[sid] = {"total": total, "seen": now}
        h = str(int(now // HOUR))
        buckets = ledger.setdefault("buckets", {})
        buckets[h] = buckets.get(h, 0.0) + delta
        self.prune(ledger, now)

    def prune(self, ledger, now):
        cutoff_h = int(now // HOUR) - WEEK_HOURS
        b = ledger.get("buckets", {})
        for h in [h for h in b if int(h) <= cutoff_h]:
            del b[h]
        ttl = SESSION_TTL if self.guarded else WEEK_HOURS * HOUR
        s = ledger.get("sessions", {})
        for k in [k for k, v in s.items() if now - v["seen"] >= ttl]:
            del s[k]

    def weekly(self, ledger, now):
        cutoff_h = int(now // HOUR) - WEEK_HOURS
        return sum(v for h, v in ledger.get("buckets", {}).items() if int(h) > cutoff_h)


class HourBucketsGuarded(HourBuckets):
    """HourBuckets + CS-003-style sanitisation on both sides of the file:
    finite, non-negative, capped totals; capped per-tick delta; 30-day session
    memory; every value re-validated when the ledger is read back."""
    name = "hour-buckets-guarded"
    guarded = True


def sanitize_ledger(obj):
    """Trust nothing read from disk (CS-002/CS-003 applied to the new file)."""
    if not isinstance(obj, dict):
        return {}
    out = {"buckets": {}, "sessions": {}}
    b = obj.get("buckets")
    if isinstance(b, dict):
        for h, v in b.items():
            if isinstance(h, str) and h.isdigit() and _num(v) and 0.0 <= v <= CAP_BUCKET:
                out["buckets"][h] = float(v)
    s = obj.get("sessions")
    if isinstance(s, dict):
        for k, v in s.items():
            if (isinstance(k, str) and isinstance(v, dict) and _num(v.get("total"))
                    and 0.0 <= v["total"] <= CAP_TOTAL and _num(v.get("seen"))):
                out["sessions"][k] = {"total": float(v["total"]), "seen": float(v["seen"])}
    return out


# ---------------------------------------------------------------- storages --
def _load(path, sanitize):
    try:
        with open(path) as f:
            obj = json.load(f)
    except Exception:
        return {}
    if sanitize:
        return sanitize_ledger(obj)
    return obj if isinstance(obj, dict) else {}


def _atomic_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


class SingleFileReplace:
    """One ledger file, read-modify-write, atomic os.replace, NO lock
    (the pattern the rate-limit cache uses today)."""
    name = "single-file/replace"

    def __init__(self, cache_dir, sanitize):
        self.path = os.path.join(cache_dir, "cost-ledger.json")
        self.sanitize = sanitize

    def update(self, sid, fn):
        ledger = _load(self.path, self.sanitize)
        fn(ledger)
        _atomic_write(self.path, ledger)

    def ledgers(self):
        return [_load(self.path, self.sanitize)]


class SingleFileFlock(SingleFileReplace):
    """One ledger file; the read-modify-write is serialised with fcntl.flock
    on a sidecar lock file (POSIX only)."""
    name = "single-file/flock"

    def update(self, sid, fn):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                super().update(sid, fn)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


_SID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class PerSessionFiles:
    """One ledger file per session_id; only that session's process ever writes
    it, so no lock is needed. Readers sum every file in the directory."""
    name = "per-session-files"

    def __init__(self, cache_dir, sanitize):
        self.dir = os.path.join(cache_dir, "cost")
        self.sanitize = sanitize

    def _path(self, sid):
        sid = sid if isinstance(sid, str) and _SID_OK.match(sid) else "unknown"
        return os.path.join(self.dir, f"{sid}.json")

    def update(self, sid, fn):
        path = self._path(sid)
        ledger = _load(path, self.sanitize)
        fn(ledger)
        _atomic_write(path, ledger)

    def ledgers(self, now=None):
        """Sum only files written inside the window: a session file that has not
        been touched for 7 days cannot hold an in-window bucket (buckets are only
        written on tick), so a stat() replaces a full JSON parse for stale ones."""
        try:
            names = [n for n in os.listdir(self.dir) if n.endswith(".json")]
        except FileNotFoundError:
            return []
        cutoff = (now if now is not None else time.time()) - (WEEK_HOURS + 1) * HOUR
        out = []
        for n in names:
            path = os.path.join(self.dir, n)
            try:
                if os.stat(path).st_mtime < cutoff:
                    continue
            except OSError:
                continue
            out.append(_load(path, self.sanitize))
        return out


POLICIES = [NaiveTotals(), HourBuckets(), HourBucketsGuarded()]
STORAGES = [SingleFileReplace, SingleFileFlock, PerSessionFiles]
