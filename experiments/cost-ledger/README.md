# cost-ledger experiment

Validates the weekly-cost ledger design from **ADR-0003**: how to turn the
per-session `cost.total_cost_usd` that Claude Code puts on the statusline's
stdin into a rolling 7-day dollar figure shared by every session on the machine.

## Run

```sh
python3 run.py
```

Stdlib-only. Writes `results/report.md` and exits non-zero if the recommended
candidate (`hour-buckets-guarded` policy on `per-session-files` storage) fails
any check, so it doubles as a regression guard.

## What it does

Two independent axes are tested, one class per candidate in `candidates.py`.

**Part A, update policy** (`fixtures/scenarios.py`, 13 synthetic tick streams):

- `naive-totals`, the literal "accumulate all sessions" idea: keep each
  session's latest cumulative total, sum the totals of sessions seen in the
  last 7 days.
- `hour-buckets`: per-session deltas of the cumulative total dropped into
  hourly buckets; weekly = the last 168 buckets.
- `hour-buckets-guarded`: the same plus CS-003-style sanitisation on both
  sides of the file (finite, non-negative, capped totals; capped per-tick
  delta; 30-day session memory; re-validation on read).

Scenarios stress exactly the dimensions on which these differ: window
boundaries, long idle sessions, `/clear`, `--resume` with and without a
counter reset, duplicate ticks, poisoned payload values (absurd, plausible,
non-numeric), a session resumed after it aged out, and a mid-session install.

**Part B, storage layout** (guarded policy throughout):

- `single-file/replace`: one file, read-modify-write, atomic `os.replace`, no
  lock. This is the pattern the rate-limit cache uses today.
- `single-file/flock`: the same, serialised with `fcntl.flock`.
- `per-session-files`: one file per `session_id`, so each file has exactly one
  writer; readers sum the directory.

Checks: eight real concurrent processes ticking against the same cache
directory (lost updates and write latency), read latency with 200 live session
files and with 200 stale + 10 live, and seven garbage blobs on disk that must
read as $0 without crashing.

Ground truth for every scenario is the dollars actually spent in the 7 days
before the end tick. The dollar figures are Claude Code's own list-price
estimate replayed through the candidates; the experiment says nothing about how
close that estimate is to a bill.
