#!/usr/bin/env python3
"""Payload-capture wrapper for the live checks in ADR-0003 (open items 1-3).

Temporarily point Claude Code at this file instead of the real statusline:

    "statusLine": { "type": "command",
                    "command": "python3 /path/to/experiments/cost-ledger/live/capture.py", ... }

Every tick it hands the untouched payload to the real statusline (so the line
keeps rendering) and, when a session's `cost.total_cost_usd` or its
rate_limits/cost presence changed since the last tick, appends one JSON line to

    ~/.cache/claude-statusline/capture.jsonl

Add a marker line to correlate what you did in the terminal:

    python3 capture.py --mark "about to /exit and claude --resume"

Then read the log with analyze.py. Stdlib-only; never lets a capture problem
break the render. Overrides: STATUSLINE_CAPTURE_DIR (log location),
STATUSLINE_REAL (path of the real statusline.py).
"""
import json
import os
import subprocess
import sys
import time

CAP_DIR = os.environ.get("STATUSLINE_CAPTURE_DIR") or os.path.expanduser("~/.cache/claude-statusline")
LOG = os.path.join(CAP_DIR, "capture.jsonl")
STATE = os.path.join(CAP_DIR, "capture-state.json")
REAL = os.environ.get("STATUSLINE_REAL") or os.path.expanduser("~/.claude/scripts/statusline.py")


def append(obj):
    os.makedirs(CAP_DIR, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(obj) + "\n")


def _dict(d, k):
    v = d.get(k) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def capture(payload):
    data = json.loads(payload)
    if not isinstance(data, dict):
        return
    sid = data.get("session_id")
    cost = _dict(data, "cost")
    has_rl = bool(_dict(data, "rate_limits"))
    key = [cost.get("total_cost_usd"), has_rl, "cost" in data]
    try:
        with open(STATE) as f:
            state = json.load(f)
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}
    if state.get(str(sid)) == key:
        return
    state[str(sid)] = key
    append({
        "ts": time.time(),
        "session_id": sid,
        "version": data.get("version"),
        "model": _dict(data, "model").get("id"),
        "has_cost": "cost" in data,
        "cost": cost,
        "has_rate_limits": has_rl,
        "rate_limits": _dict(data, "rate_limits"),
        "transcript_path": data.get("transcript_path"),
        "cwd": _dict(data, "workspace").get("current_dir"),
        "keys": sorted(data.keys()),
    })
    os.makedirs(CAP_DIR, exist_ok=True)
    tmp = f"{STATE}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE)


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--mark":
        append({"ts": time.time(), "mark": " ".join(sys.argv[2:])})
        print(f"marked -> {LOG}")
        return
    payload = sys.stdin.read()
    try:
        capture(payload)
    except Exception:
        pass
    try:
        r = subprocess.run([sys.executable, REAL], input=payload, capture_output=True, text=True, timeout=10)
        sys.stdout.write(r.stdout)
    except Exception:
        print("⚠️ capture wrapper: real statusline failed")


if __name__ == "__main__":
    main()
