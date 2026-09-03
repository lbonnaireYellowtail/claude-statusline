#!/usr/bin/env python3
"""Run every ledger candidate against every fixture and regenerate results/report.md.

Stdlib-only. Usage: python3 run.py
Exits non-zero if the RECOMMENDED candidate (hour-buckets-guarded on
per-session-files) fails any check, so it doubles as a regression guard.

Part A - policy matrix: each policy replays each synthetic tick stream through a
         real (sequential) file store and reports its weekly figure at the end.
Part B - storage matrix: the guarded policy under real multi-process contention
         (8 statusline processes x 200 ticks), read latency with 200 sessions on
         disk, and garbage-on-disk robustness.
"""
import os
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
from candidates import POLICIES, STORAGES, HourBucketsGuarded, HOUR  # noqa: E402
from scenarios import scenarios  # noqa: E402
from scorer import score  # noqa: E402

RESULTS = os.path.join(HERE, "results", "report.md")
WORKERS, TICKS, PER_TICK = 8, 200, 0.01
RECOMMENDED_STORAGE = "per-session-files"


def weekly(policy, store, now):
    return sum(policy.weekly(l, now) for l in store.ledgers())


# ------------------------------------------------------------------ Part A --
def run_policies():
    rows = []
    for sc in scenarios():
        for pol in POLICIES:
            d = tempfile.mkdtemp(prefix="ledger-")
            store = STORAGES[0](d, sanitize=pol.guarded)
            try:
                for now, sid, total in sc["events"]:
                    store.update(sid, lambda l: pol.tick(l, now, sid, total))
                got = weekly(pol, store, sc["end"])
                ok, detail = score(sc["truth"], got, sc.get("tol"))
            except Exception as e:  # a crash is a failure, not an abort
                ok, detail = False, f"CRASH {type(e).__name__}: {e}"
            rows.append((sc, pol.name, ok, detail))
    return rows


# ------------------------------------------------------------------ Part B --
def worker(storage_name, cache_dir, sid, n):
    store = next(s for s in STORAGES if s.name == storage_name)(cache_dir, sanitize=True)
    pol, total, t0 = HourBucketsGuarded(), 0.0, time.perf_counter()
    for _ in range(n):
        total += PER_TICK
        now = time.time()
        store.update(sid, lambda l: pol.tick(l, now, sid, total))
    print(f"{(time.perf_counter() - t0) / n * 1000:.3f}")


def run_storages():
    rows = []
    pol = HourBucketsGuarded()
    for S in STORAGES:
        # C1: real concurrent statusline processes
        d = tempfile.mkdtemp(prefix="ledger-race-")
        procs = [subprocess.Popen([sys.executable, __file__, "--worker", S.name, d, f"w{i}", str(TICKS)],
                                  stdout=subprocess.PIPE, text=True) for i in range(WORKERS)]
        per_tick_ms = [float(p.communicate()[0].strip() or "nan") for p in procs]
        truth = WORKERS * TICKS * PER_TICK
        got = weekly(pol, S(d, sanitize=True), time.time())
        ok, detail = score(truth, got)
        lost = max(0, round((truth - got) / PER_TICK))
        rows.append(("concurrency (8 procs x 200 ticks)", S.name, ok,
                     f"{detail}; lost updates: {lost}; write {statistics.median(per_tick_ms):.2f} ms/tick"))

        # C2: read latency with 200 sessions on disk
        d = tempfile.mkdtemp(prefix="ledger-read-")
        store, now = S(d, sanitize=True), time.time()
        for i in range(200):
            store.update(f"s{i}", lambda l, i=i: pol.tick(l, now, f"s{i}", 0.10))
        times = []
        for _ in range(50):
            t0 = time.perf_counter()
            got = weekly(pol, store, now)
            times.append((time.perf_counter() - t0) * 1000)
        ok, detail = score(20.0, got)
        rows.append(("read latency (200 live sessions)", S.name, ok,
                     f"{detail}; median read {statistics.median(times):.2f} ms"))

        # C4: realistic month - 200 stale sessions (last tick 10 days ago) + 10 live ones
        d = tempfile.mkdtemp(prefix="ledger-stale-")
        store = S(d, sanitize=True)
        stale_now = now - 10 * 24 * HOUR
        for i in range(200):
            store.update(f"old{i}", lambda l, i=i: pol.tick(l, stale_now, f"old{i}", 0.10))
        if hasattr(store, "dir"):
            for n in os.listdir(store.dir):
                os.utime(os.path.join(store.dir, n), (stale_now, stale_now))
        for i in range(10):
            store.update(f"live{i}", lambda l, i=i: pol.tick(l, now, f"live{i}", 0.10))
        times = []
        for _ in range(50):
            t0 = time.perf_counter()
            got = weekly(pol, store, now)
            times.append((time.perf_counter() - t0) * 1000)
        ok, detail = score(1.0, got)
        rows.append(("read latency (200 stale + 10 live)", S.name, ok,
                     f"{detail}; median read {statistics.median(times):.2f} ms"))

        # C3: garbage on disk must read as $0, never crash
        junk = [b'null', b'[1,2,3]', b'"hi"', b'\xff\xfe junk', b'{"buckets": 5, "sessions": []}',
                b'{"buckets": {"1": "x", "2": NaN, "3": -1e9, "4": 1e30, "abc": 1}}',
                b'{"buckets": {"%d": Infinity}}' % int(now // HOUR)]
        bad = []
        for i, blob in enumerate(junk):
            d = tempfile.mkdtemp(prefix="ledger-junk-")
            store = S(d, sanitize=True)
            path = store.path if hasattr(store, "path") else os.path.join(store.dir, f"j{i}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(blob)
            try:
                got = weekly(pol, store, now)
                if got != 0.0:
                    bad.append(f"{blob[:30]!r} -> {got}")
            except Exception as e:
                bad.append(f"{blob[:30]!r} -> CRASH {type(e).__name__}")
        rows.append(("garbage on disk (7 blobs)", S.name, not bad,
                     "all read as $0.00" if not bad else "; ".join(bad)))
    return rows


# ------------------------------------------------------------------ report --
def write_report(a_rows, b_rows):
    rec_pol_fail = [r for r in a_rows if r[1] == "hour-buckets-guarded" and not r[2]]
    rec_sto_fail = [r for r in b_rows if r[1] == RECOMMENDED_STORAGE and not r[2]]
    L = ["# Weekly-cost ledger experiment — results", "",
         "Generated by `run.py`. Validates the ledger design in ADR-0003. Ground truth is",
         "the dollars a session stream actually spent in the 7 days before the scenario's",
         "end tick; every figure is Claude Code's own list-price estimate replayed through",
         "the candidate.", "",
         f"- Recommended policy (`hour-buckets-guarded`) failures: **{len(rec_pol_fail)}**",
         f"- Recommended storage (`{RECOMMENDED_STORAGE}`) failures: **{len(rec_sto_fail)}**", "",
         "## Part A — update policy", "",
         "| Scenario | Candidate | Pass | Detail |", "| --- | --- | :---: | --- |"]
    for sc, name, ok, detail in a_rows:
        L.append(f"| {sc['name']} ({sc['desc']}) | `{name}` | {'✅' if ok else '❌'} | {detail} |")
    L += ["", "## Part B — storage layout (guarded policy)", "",
          "| Check | Candidate | Pass | Detail |", "| --- | --- | :---: | --- |"]
    for check, name, ok, detail in b_rows:
        L.append(f"| {check} | `{name}` | {'✅' if ok else '❌'} | {detail} |")
    L += ["", "## Reading", "",
          "- **naive-totals** (sum each session's latest total) cannot place spend in time: a",
          "  10-day session over-counts, an idle session never leaves the window, and a",
          "  resume that resets the counter loses money. It only agrees with the truth when",
          "  every session both starts and ends inside the window.",
          "- **hour-buckets** fixes the window arithmetic but trusts the payload: a single",
          "  NaN/Inf or absurd total poisons the file, and a session pruned after 7 days",
          "  re-counts its whole history when resumed.",
          "- **hour-buckets-guarded** passes every scenario. Two rows are honest residuals",
          "  rather than clean wins: `steady-10d` shows the one-bucket edge resolution (up",
          "  to one hour of spend may sit just outside the window), and `poison-plausible`",
          "  shows that a forged-but-plausible total is indistinguishable from real spend,",
          "  so its damage is capped (CAP_DELTA per tick) and ages out with its bucket, not",
          "  eliminated. `naive-totals` passes both poison rows because \"latest total wins\"",
          "  self-heals from a single bad tick - a real trade-off, recorded in ADR-0003.",
          "- Storage: `single-file/replace` (today's cache pattern) loses updates under",
          "  concurrent sessions; `flock` fixes it on POSIX only; `per-session-files` needs",
          "  no lock at all because each session is its file's only writer. Its read cost",
          "  scales with the number of *live* session files; stale files are skipped on an",
          "  mtime stat without being parsed.", ""]
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w") as f:
        f.write("\n".join(L))
    return len(rec_pol_fail) + len(rec_sto_fail)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
        return
    a_rows = run_policies()
    b_rows = run_storages()
    failures = write_report(a_rows, b_rows)
    for sc, name, ok, detail in a_rows:
        print(f"{'PASS' if ok else 'FAIL'}  {sc['name']:<22} {name:<22} {detail}")
    for check, name, ok, detail in b_rows:
        print(f"{'PASS' if ok else 'FAIL'}  {check:<34} {name:<22} {detail}")
    print(f"\nreport -> {RESULTS}\nrecommended-candidate failures: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
