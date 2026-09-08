#!/usr/bin/env python3
"""Read capture.jsonl (written by capture.py) and answer ADR-0003's live questions.

    python3 analyze.py [path/to/capture.jsonl]

(1) --resume   : per session, did total_cost_usd ever DROP (reset) or CONTINUE
                 across a gap longer than GAP_MIN minutes / a "resume" marker?
                 Also flags every process RESTART: total_duration_ms is the
                 process's own clock, so a restart shows up as the duration
                 advancing less than wall-clock (or going backwards), even when
                 the cost is restored and the session_id is unchanged.
(2) subagents  : compare the session's last payload total with a list-price scan
                 of its own transcript, main file only vs. including subagents/.
                 If the payload tracks the "incl. subagents" figure, subagent
                 spend is folded into the parent's total.
(3) API key    : sessions whose last line carries `cost` but no `rate_limits`.

The scan in (2) uses a price table (below) ONLY to tell the two hypotheses
apart; the product itself must never carry one (ADR-0003 D1). Stdlib-only.
"""
import glob
import json
import os
import sys
import time

GAP_MIN = 10
RESTART_LAG_S = 3   # duration counter fell this many seconds behind wall-clock => the process was down
PRICES = {  # $/MTok: input, output, cache write 5m, cache write 1h, cache read (2026-09-03)
    "claude-fable-5-1": (10, 50, 12.5, 20, 0.25),
    "claude-fable-5": (10, 50, 12.5, 20, 1.0),
    "claude-opus-5": (5, 25, 6.25, 10, 0.5),
    "claude-opus-4-8": (5, 25, 6.25, 10, 0.5),
    "claude-sonnet-5": (2, 10, 2.5, 4, 0.2),
    "claude-sonnet-4-6": (3, 15, 3.75, 6, 0.3),
    "claude-haiku-4-5": (1, 5, 1.25, 2, 0.1),
    "claude-haiku-4-5-20251001": (1, 5, 1.25, 2, 0.1),
}


def price(model, u):
    p = PRICES.get(model)
    if not p:
        return None
    cc = u.get("cache_creation") or {}
    w5, w1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        w5, w1 = u.get("cache_creation_input_tokens", 0) or 0, 0
    return ((u.get("input_tokens", 0) or 0) * p[0] + (u.get("output_tokens", 0) or 0) * p[1]
            + (w5 or 0) * p[2] + (w1 or 0) * p[3]
            + (u.get("cache_read_input_tokens", 0) or 0) * p[4]) / 1e6


def scan(files):
    seen, tot, unpriced = set(), 0.0, {}
    for f in files:
        try:
            fh = open(f, "rb")
        except OSError:
            continue
        with fh:
            for line in fh:
                if b'"assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "assistant":
                    continue
                m = d.get("message") or {}
                k = (m.get("id"), d.get("requestId"))
                if k in seen:
                    continue
                seen.add(k)
                c = price(m.get("model"), m.get("usage") or {})
                if c is None:
                    unpriced[m.get("model")] = unpriced.get(m.get("model"), 0) + 1
                else:
                    tot += c
    return tot, unpriced


def hms(ts):
    return time.strftime("%m-%d %H:%M:%S", time.localtime(ts))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.cache/claude-statusline/capture.jsonl")
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    marks = [r for r in rows if "mark" in r]
    sessions = {}
    for r in rows:
        if "session_id" in r:
            sessions.setdefault(r["session_id"], []).append(r)

    print(f"{len(rows)} lines, {len(sessions)} sessions, {len(marks)} markers  ({path})\n")
    if marks:
        print("Markers:")
        for m in marks:
            print(f"  {hms(m['ts'])}  {m['mark']}")
        print()

    print("Per session (chronological):")
    for sid, L in sorted(sessions.items(), key=lambda kv: kv[1][0]["ts"]):
        totals = [(r["ts"], r["cost"].get("total_cost_usd"), r["cost"].get("total_duration_ms"))
                  for r in L if isinstance(r.get("cost"), dict)]
        nums = [(t, v) for t, v, _ in totals if isinstance(v, (int, float))]
        drops, continues, restarts = [], [], []
        for (t0, v0), (t1, v1) in zip(nums, nums[1:]):
            if v1 < v0:
                drops.append((t1, v0, v1))
            elif t1 - t0 > GAP_MIN * 60:
                continues.append((t1, v0, v1, (t1 - t0) / 60))
        # Process restart detector. total_duration_ms is the process's own clock, so
        # while one process is alive it advances 1:1 with wall time. Claude Code
        # restores cost AND duration from the saved session on --resume/--continue
        # (same session_id, no drop), so the only trace of the restart is that the
        # duration counter advanced LESS than wall time by the seconds it was down.
        durs = [(t, v, d / 1000.0) for t, v, d in totals
                if isinstance(v, (int, float)) and isinstance(d, (int, float))]
        for (t0, v0, d0), (t1, v1, d1) in zip(durs, durs[1:]):
            lost = (t1 - t0) - (d1 - d0)
            if d1 < d0 or lost > RESTART_LAG_S:
                restarts.append((t1, v0, v1, lost, d1 < d0))
        last = L[-1]
        print(f"- {str(sid)[:8]}  v{last.get('version')}  {last.get('model')}  {hms(L[0]['ts'])} -> {hms(last['ts'])}"
              f"  lines={len(L)}  cost: {nums[0][1] if nums else None} -> {nums[-1][1] if nums else None}"
              f"  has_cost={last.get('has_cost')}  has_rate_limits={last.get('has_rate_limits')}")
        for t, a, b in drops:
            print(f"    RESET  at {hms(t)}: total dropped ${a:.2f} -> ${b:.2f}")
        for t, a, b, gap in continues:
            print(f"    CONTINUED across a {gap:.0f} min gap at {hms(t)}: ${a:.2f} -> ${b:.2f}")
        for t, a, b, lost, fresh in restarts:
            how = "duration counter reset" if fresh else f"duration lagged wall-clock by {lost:.0f}s"
            what = "RESET" if b < a else "CONTINUED"
            print(f"    RESTART at {hms(t)} ({how}): process came back and the total {what} ${a:.2f} -> ${b:.2f}")
        tp = last.get("transcript_path")
        if tp and nums and os.path.exists(tp):
            subs = glob.glob(os.path.join(tp[:-len(".jsonl")], "subagents", "*.jsonl")) if tp.endswith(".jsonl") else []
            main_only, unp1 = scan([tp])
            with_subs, unp2 = scan([tp] + subs)
            payload = nums[-1][1]
            verdict = ""
            if subs and abs(with_subs - main_only) > 0.05:
                verdict = ("  -> payload tracks INCL.-subagents (folded in)" if abs(payload - with_subs) < abs(payload - main_only)
                           else "  -> payload tracks MAIN-only (subagents NOT folded in)")
            elif subs:
                verdict = "  -> subagent spend too small to discriminate; run a bigger subagent"
            print(f"    list-price scan: main ${main_only:.2f} | incl. {len(subs)} subagent(s) ${with_subs:.2f}"
                  f" | payload ${payload:.2f}{verdict}")
            if unp2:
                print(f"    (unpriced models in scan: {unp2})")
        if last.get("has_cost") and not last.get("has_rate_limits"):
            print("    NO rate_limits on the last line: API-key/gateway session, or a subscriber before its first API response")
    print("\nHow to read: (1) any RESET line = --resume restarts the counter; CONTINUED = it carries on."
          " (2) the scan line says which hypothesis the payload tracks."
          " (3) has_rate_limits=False on a session that has clearly made API calls = API-key mode.")


if __name__ == "__main__":
    main()
