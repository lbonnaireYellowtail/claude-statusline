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

## Live verification (`live/`)

Three questions in ADR-0003 can only be answered by a running Claude Code:
does `total_cost_usd` continue or reset across `--resume`, is subagent spend
folded into the parent session's total, and does an API-key login really send
`cost` without `rate_limits`.

1. **Install the capture wrapper** for the duration of the test. In
   `~/.claude/settings.json`, change `statusLine.command` from the installed
   `statusline.py` to `python3 <repo>/experiments/cost-ledger/live/capture.py`
   (leave `refreshInterval` as is). Every tick still renders through the real
   statusline; whenever a session's cost or its `rate_limits` presence changes,
   one line is appended to `~/.cache/claude-statusline/capture.jsonl`.
2. **Drop markers** as you go so the log can be read later:
   `python3 live/capture.py --mark "about to /exit and --resume"`.
3. **Resume test:** in a session, do a couple of turns, note `/usage`, mark,
   `/exit`, then `claude --resume` (or `--continue`) and do one more turn.
4. **Subagent test:** in one session, spawn a deliberately large subagent
   (e.g. ask for a "very thorough" Explore of a big repo). The scan needs the
   subagent to cost clearly more than a few cents to discriminate.
5. **API-key test:** in a fresh terminal `export ANTHROPIC_API_KEY=...` for a
   Console key, start `claude`, confirm the auth mode with `/status`, do one
   turn. Skip if you have no Console key; the docs are explicit on this one.
6. **Read the log:** `python3 live/analyze.py`. It prints per-session cost
   trajectories with RESET / CONTINUED events, a list-price scan of each
   session's transcript with and without its `subagents/` files next to the
   payload total, and flags sessions carrying `cost` without `rate_limits`.
7. **Uninstall:** restore `statusLine.command`; delete `capture.jsonl` and
   `capture-state.json` from the cache dir.

`analyze.py` carries a small price table purely to separate the two subagent
hypotheses. The product never will (ADR-0003 D1).
