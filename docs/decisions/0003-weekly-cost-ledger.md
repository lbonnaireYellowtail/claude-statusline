# ADR-0003 — Weekly dollar cost in the status line, and a layout for API-key users

- **Status:** Proposed (investigation + experiment complete; implementation tracked as CS-008, CS-009). Direction taken on the user's "test out the experiment" go-ahead of 2026-09-03; the three layout/scope choices below are recorded as assumptions and are cheap to reverse before CS-008 starts.
- **Date:** 2026-09-03
- **Method:** ping-pong (research ↔ experiment). Every claim about Claude Code behaviour below was checked against the official docs or observed on Claude Code 2.1.259; every design claim is validated in `experiments/cost-ledger/` (see `results/report.md`).

## Context

Two related asks:

1. Show a rolling **7-day dollar figure** next to the existing 5h / 7d percentage gauges.
2. Make the plugin useful for **API-key (pay-as-you-go) users**, who get no `rate_limits` at all and therefore see nothing but the context gauge and the model today (or, on older Claude Code, the ccusage fallback).

The premise the ask started from was that `/usage` shows a *precise* per-session cost that could simply be accumulated across sessions. Research corrected the premise and kept the idea:

- **There is no precise cost anywhere locally.** `/usage`'s session figure and the `cost.total_cost_usd` field Claude Code already puts on the statusline's stdin are the same number, and the docs describe it as computed *locally from token counts at list price* (or at contracted rates when an organisation sets the `modelPricing` managed setting). It is not read back from billing. Every possible data source is therefore an estimate; the question is only whose price table does the estimating.
- **Claude Code's own estimate is still the best one available**, because Claude Code ships a current price table with every release. The alternatives are worse on exactly that axis: ccusage's embedded (offline) table knows none of the current models (Opus 5, Sonnet 5, Fable 5.1) and silently excludes them with a warning, so our existing fallback already under-reports; its online mode is correct but takes 0.75 s and a network round-trip against our ~30 ms tick; a transcript scan of our own needs a price table we would have to maintain forever.
- Facts that shape the design: `rate_limits` is sent only to Pro/Max (and gateway) users, and only after the first API response; API-key users never get it. There is no documented auth-mode field. Transcript `costUSD` is null on every current message. Subagent transcripts live in nested `subagents/` folders. No local file holds an account-level or weekly spend (`stats-cache.json` holds counts only; `usage-data/` holds an HTML insights report). The OpenTelemetry metric `claude_code.cost.usage` exists but needs a metrics backend.
- Constraints carried over: stdlib-only, ~30 ms per tick at `refreshInterval: 2`, untrusted stdin (ADR-0001 / CS-001..003 hardening must extend to any new cached number), and a shared cache whose current "monotone freshness" trick is built for a *latest-value* quantity and cannot be reused for a *sum*.

## Decision drivers

- Never own a price table. The moment we do, every model launch is a bug.
- Correct across the window edge, across `/clear`, across `--resume` in both of its possible behaviours, and under many concurrent sessions ticking every 2 s.
- Poison from a bad payload must be bounded and must age out by itself (CS-003's lesson: the rate-limit cache let poison persist forever until we bounded it).
- Zero new trust boundaries: no new external binary, no network.
- Honest labelling: the figure is "what this would cost at API list price", never "your bill".

## Decisions

### D1 — Data source: the payload's own `cost.total_cost_usd`

Read `session_id` and `cost.total_cost_usd` from the stdin payload Claude Code already sends. Nothing else is consulted.

Rejected:

- **Transcript scan** (recursive, dedupe on `message.id` + `requestId`, own price table). Measured 50–90 ms for 7 days on this machine before any throttling, and it re-creates the price-maintenance burden the v1.1 docstring explicitly celebrates removing. *Do not use unless* Claude Code stops sending `cost` in the payload.
- **ccusage** (current fallback). Wrong offline for every current model; 0.75–3.7 s per run; PATH-resolved external binary is the one trust boundary the README has to apologise for. See D5.
- **OpenTelemetry** `claude_code.cost.usage`. Correct and cross-session, but needs a collector; not a statusline data source. *Do use* if a team already runs one and wants org-wide numbers.

### D2 — Aggregation: per-session deltas into hourly buckets, guarded

Each tick computes `delta = clamp(total − last_total_for_session, 0, CAP_DELTA)` and adds it to the bucket for the current hour. The weekly figure is the sum of the last 168 buckets. Guards, applied identically on write and on read (the CS-003 principle):

| Guard | Value | Why |
| --- | --- | --- |
| total must be finite, `0 ≤ total ≤ CAP_TOTAL` | 10 000 $ | rejects NaN/Inf (json accepts them), negatives, absurd totals |
| per-tick delta cap | 100 $ | bounds the blast radius of a plausible-looking forged total |
| bucket cap on read | 100 000 $ | a tampered file cannot inject more than this per hour |
| session memory | 30 days | a session resumed after it left the 7-day window must not re-count its whole history |
| first sighting counts the whole total | — | deliberate: installing mid-session attributes the pre-install spend to "now" rather than losing it |

Rejected: **naive totals** (keep each session's latest total; sum the sessions seen in the last week), which is the literal form of the original proposal. It fails 6 of 13 scenarios: it cannot place spend in time (a 10-day session over-counts by 43 %, an idle session never leaves the window, a resume that resets the counter *loses* money). It is the right model only when every session starts and ends inside the window. It does have one genuine advantage the buckets lack, recorded honestly: "latest total wins" self-heals from a single poisoned tick, whereas buckets integrate the poison until it ages out; D2's caps are what make that acceptable.

Resolution: one bucket. Up to one hour of spend can sit just outside the window (measured: −$0.83 on a steady $168 week). *Switch to 15-minute buckets* if anyone cares; the file format already supports it (bucket key = `floor(now / BUCKET)`).

### D3 — Storage: one ledger file per session, no lock

`~/.cache/claude-statusline/cost/<session_id>.json`, holding that session's `last_total`, `seen`, and its buckets. Only the session's own statusline process ever writes its file, so no lock is needed and the existing atomic `os.replace` is sufficient. Readers sum every file in the directory whose mtime is inside the window; older files are skipped on a `stat()` without being parsed, and deleted once older than the 30-day session memory. `session_id` is allow-listed to `[A-Za-z0-9_-]{1,64}` before it becomes a filename (an untrusted payload field must not be able to write outside the directory).

Rejected:

- **Single file, atomic replace, no lock** — today's rate-limit cache pattern. Under 8 concurrent sessions × 200 ticks it lost **38–50 % of updates** (612 and 802 of 1 600 across two runs). The rate-limit cache survives this pattern only because it stores a latest value under a monotone key; a sum has no such protection.
- **Single file with `fcntl.flock`** — correct (0 lost), 2.5 ms per write, fastest read (0.26 ms). Rejected for being POSIX-only (the script is otherwise portable) and for making one hot file the contention point of every session on the machine. *Switch to it* if live session files ever exceed a few hundred (see triggers).

### D4 — Display (assumption; reversible before CS-008)

- Subscribers keep the three gauges and gain a dim dollar tail on the 7-day gauge: `📅 7d 2% →5d4h $35`.
- API-key users (payload has `cost` but no `rate_limits`) get `💵 sess $1.20 | 7d $35`. If `STATUSLINE_WEEK_BUDGET` is set, the 7d figure is coloured with the existing caution/warn thresholds against it; otherwise it is plain.
- The README states the semantics in one sentence: *estimated at API list price by Claude Code itself; for subscribers this is what the week would have cost on the API, and becomes real money once extra usage kicks in; it counts only sessions where this statusline ran on this machine, starting from install.*

"No `rate_limits`" is the auth-mode signal. It is not a documented contract, but it is the documented *behaviour*, and mis-detecting it is harmless: before a subscriber's first API response there is nothing to gauge anyway. `~/.claude.json` carries `oauthAccount.billingType` if a hard signal is ever needed; we do not read it now (new file, new trust boundary, no need).

### D5 — Retire the ccusage fallback (CS-009)

The fallback exists for Claude Code builds that predate `rate_limits`. `cost` predates `rate_limits` in the payload, so every build that lacks `rate_limits` but is worth supporting has `cost`, and the D4 API-key layout is a strictly better fallback: correct prices, zero latency, no external binary. Removing it also deletes the PATH-resolved-binary trust boundary from the README's Security section. *Do not retire* if a supported Claude Code version turns out to send neither field; none is known.

## Experiment findings (2026-09-03, `experiments/cost-ledger/`)

Policy matrix, 13 scenarios: `naive-totals` 7/13, `hour-buckets` 11/13 (fails poison-huge by twelve orders of magnitude, poison-nonnumeric with `inf`), `hour-buckets-guarded` **13/13**. Storage matrix with the guarded policy:

| Storage | Lost updates (8 procs × 200) | Write / tick | Read, 200 live sessions | Read, 200 stale + 10 live | Garbage on disk |
| --- | --- | --- | --- | --- | --- |
| single-file/replace | 612 (38 %) | 2.83 ms | 0.26 ms | 0.28 ms | reads $0, no crash |
| single-file/flock | 0 | 2.54 ms | 0.26 ms | 0.27 ms | reads $0, no crash |
| **per-session-files** | **0** | **1.00 ms** | 5.90 ms | **0.92 ms** | reads $0, no crash |

The per-session read cost is the one number to watch: it scales with *live* session files, not with history (the stale-skip brings a realistic month from 5.9 ms to 0.9 ms).

## Consequences

- One new cache directory with one small JSON file per session; the rate-limit cache is untouched.
- Per tick: one `stat` per live session file, one JSON parse each, one atomic write of the session's own file. Well inside budget for tens of live sessions.
- The weekly figure starts at $0 on install and is complete after 7 days; the README says so. Sessions on other machines and sessions without this statusline are not counted.
- Every new number entering the process is validated on both sides of the file, so the CS-001..003 posture is preserved rather than eroded.

## Open items to verify live before CS-008 ships

Tooling: `experiments/cost-ledger/live/capture.py` (temporary statusline wrapper that logs payloads on cost change) and `live/analyze.py` (answers all three from the log). Procedure in the experiment README, "Live verification".

1. `--resume`: does `total_cost_usd` continue from the previous value or restart at 0? Both are handled (D2's clamp), so this only decides which fixture is the realistic one. **Circumstantial evidence for "restart at 0" (2026-09-03, first capture):** the moment the wrapper went live, two idle sessions whose transcripts are worth $16.55 and $1.21 at list price reported `total_cost_usd: 0` *and no `rate_limits`*, which is exactly what a resumed session looks like before its process has made an API call (rate limits arrive only after the first response). A third session went $0 → $0.23 while its transcript is worth $0.72. Cost therefore appears to be **per process**, not per session id. Pending: the deliberate mark / `/exit` / `--resume` run in the README. Consequence if confirmed: the ledger sees a drop on resume, clamps the delta to 0, and the pre-resume spend was already counted by the previous process, so nothing is lost or double counted.
2. Subagent spend: **answered, folded in** (2026-09-03, two sessions). Payload total vs list-price scan of the session transcript, main file only vs including `subagents/`:

   | session | main only | incl. subagents | payload |
   | --- | --- | --- | --- |
   | e7dfc7e5 | $27.20 | $30.91 | $33.56 |
   | cec5bf24 | $14.79 | $14.90 | $15.26 |

   The payload sits above the main-only figure and closest to the incl.-subagents one in both cases. It also runs 2–8 % above even that scan, so the ADR's own price table slightly underestimates what Claude Code charges itself; direction unaffected, and one more reason not to own a price table (D1).
3. API-key payload: confirm on an API-key login that `cost` arrives without `rate_limits`, as the docs state. Not yet tested (needs a Console key). Note the false positive to expect: a subscriber session *before its first API response* also shows `cost` without `rate_limits`, so judge from a session that has clearly made calls.

## Switch triggers

- Claude Code exposes an account-level or weekly spend, or a billing-authoritative cost → replace the ledger with it; keep the display.
- The payload gains an explicit auth-mode field → use it instead of the `rate_limits` presence heuristic.
- Live session files regularly exceed a few hundred (weekly read above ~15 ms) → move to single-file/flock, or add a compaction file.
- Users want finer than one-hour edge resolution → 15-minute buckets, same format.
- A supported Claude Code version sends neither `cost` nor `rate_limits` → keep a fallback (not necessarily ccusage).
