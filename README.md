# Claude Code live statusline

A one-line statusline for Claude Code that shows, in real time:

```
🧠 ctx 62.7k (6%) | 🕐 5h 12% →4h55m | 📅 7d 10% →53h15m ⇄ | 🤖 Opus 4.8 (1M context)
```

- **🧠 ctx** — context tokens used, colored against a soft target (default 100k) so you
  can keep sessions lean. The `(6%)` is the real fill of the full context window.
- **🕐 5h / 📅 7d** — your actual Anthropic rate-limit usage, with time-until-reset —
  **kept in sync across all your open terminals** (see below).
- **⇄** — shown when the rate-limit numbers came from another, more active session.
- **🤖** — the active model.

Colors: green → under target, yellow at 60%+, red + ⚠️ at 85%+.

Everything comes straight from the JSON payload Claude Code pipes to the statusline on
every render, so it's always current — no background jobs, no log parsing.

## Cross-terminal sync (v1.1)

Rate limits are account-level, but Claude Code only refreshes a session's statusline
when *that session* is active — so with several terminals open, the idle ones show
stale 5h/7d numbers while another session burns tokens.

Claude Code has no cross-session push, so this script syncs pull-based:

- The session that receives fresher `rate_limits` publishes them to
  `~/.cache/claude-statusline/shared-rate-limits.json`.
- Sessions holding staler data render from that file instead, marked with a dim `⇄`.
- Freshness comes from the data itself — `(resets_at, used_percentage)` per window
  never decreases for an account — so concurrent writers can never regress the cache.
  No locks, no per-session state files.

Combined with the `refreshInterval` setting (see install snippet), idle terminals pick
up any active session's update within a couple of seconds. An idle tick costs ~30 ms
(mostly Python startup — see [Performance](#performance)); the cache is only written
when the numbers actually advanced.
Context tokens and model stay per-session — those aren't shared state.

## Keeping context lean (why the 100k target)

The `🧠 ctx` segment is colored against a **100k-token soft target** on purpose: quality
and speed degrade as the context fills, so it's worth **clearing context around 100k**
rather than letting a session sprawl. The segment goes yellow as you approach it and
red + ⚠️ once you cross it — that's your cue to wrap up the current thread.

To clear context *without losing your place*, hand off to a fresh session with the
**[`/handoff`](https://github.com/mattpocock/skills/tree/main/skills/productivity/handoff)**
skill (by [@mattpocock](https://github.com/mattpocock)). It compacts the conversation
into a handoff document — referencing existing specs/plans/commits rather than restating
them, and redacting secrets — so the next session picks up exactly where you left off.
Invoke it with a short description of what the next session should focus on:

```
/handoff finish wiring the settings.json snippet and publish the repo
```

Then start a new session (`/clear` or a fresh window) and point it at the handoff doc.

## Works on any subscription

The **5h / 7d percentages come straight from Claude Code** (`rate_limits.used_percentage`),
which Anthropic computes against *your* plan's limits. So whether you're on **Pro ($20)**
or **Max ($100 / $200)**, the numbers are correct with **no configuration** — a Pro user
simply hits 100% sooner than a Max user, because the percentage is relative to their own
ceiling. Nothing in the primary path assumes a particular tier.

(The only tier-specific values are the `CCUSAGE_5H_LIMIT` / `CCUSAGE_WEEK_LIMIT` dollar
ceilings, and those are used *only* by the legacy fallback below.)

## Performance

Measured with [hyperfine](https://github.com/sharkdp/hyperfine) (3 warmup runs, sandboxed
`$HOME` so runs don't touch a live cache) on an Apple M3 Pro, macOS 26.5, Python 3.14.
Each render path was exercised with a fixture stdin payload; cache state was reset
between runs via `--prepare` so every iteration hits the intended path.

| Render path | Wall time (mean ± σ) | CPU time | Peak RSS |
| --- | --- | --- | --- |
| Idle tick (render from shared cache) | 30.2 ms ± 1.0 ms | 26.6 ms | 18 MB |
| Publish tick (write shared cache) | 31.0 ms ± 1.1 ms | 27.0 ms | 18 MB |
| Legacy fallback, warm 60 s `ccusage` cache | 31.8 ms ± 1.2 ms | 26.9 ms | 18 MB |
| Legacy fallback, cold (spawns `ccusage`) | 242 ms ± 22 ms | 304 ms | 112 MB |

Bare `python3 -c pass` starts in ~20 ms on the same machine, so interpreter startup is
two-thirds of a normal tick; the script's own work (parse payload, read/compare/write the
shared cache, render) adds ~10 ms. Interpreter choice dominates: the same idle tick under
the stock macOS Python 3.9 averages ~45–60 ms. The cold-fallback numbers are the Node
`ccusage` process, not this script — and it only runs on old Claude Code versions without
`rate_limits`, at most once per 60 s thanks to the cache.

**What a session costs.** With `refreshInterval` polling, per open terminal, on the
normal (rate-limits) path:

| `refreshInterval` | Ticks/hour | CPU time/hour | Avg. load (one core) | Est. energy/hour* |
| --- | --- | --- | --- | --- |
| `2` (recommended) | 1,800 | ~49 s | ~1.4% | ~0.07 Wh |
| `1` | 3,600 | ~97 s | ~2.7% | ~0.14 Wh |

\* Assumes ~5 W incremental CPU package power during the 30 ms bursts — an
order-of-magnitude estimate, not a measurement. At the recommended interval, a full
8-hour day of one session costs ~0.5 Wh, well under 1% of a MacBook battery. Cost scales
linearly with open terminals. On legacy Claude Code the fallback path (one cold `ccusage`
run per minute, warm cache in between) raises this to ~65 CPU-s/hour, still under 2% of
one core.

## Tests

Stdlib-only regression tests drive `statusline.py` black-box (as a subprocess,
feeding a JSON payload on stdin) with a sandboxed `HOME`, so runs never touch
your real `~/.cache/claude-statusline`. No dependencies needed:

```bash
python3 -m unittest discover -s tests
```

## Security

The statusline runs on every render with whatever data Claude Code and your
environment hand it, so it treats those inputs as untrusted. The trust boundaries,
and how v1.1.1 hardened each one, are:

- **Untrusted stdin JSON (sanitized).** The JSON payload Claude Code pipes in on
  every render is treated as attacker-controlled. Three fixes shipped in v1.1.1
  cover it:
  - **F1 — terminal-escape injection (CWE-150).** `model.display_name` (and the
    `model.id` fallback) is passed through a printable allowlist that strips C0
    (`\x00–\x1f`), DEL, and C1 (`\x80–\x9f`) bytes and length-bounds the result,
    so a crafted name can't emit OSC/CSI/clear-screen/clipboard escape sequences
    into your terminal. This is the same escape-injection class as
    [CVE-2025-55754](https://www.cve.org/CVERecord?id=CVE-2025-55754) (Tomcat) and
    [CVE-2025-55193](https://www.cve.org/CVERecord?id=CVE-2025-55193) (Rails).
  - **F2 — non-object JSON.** Valid-but-non-object payloads (`null`, arrays,
    scalars) and wrong-typed nested keys are coerced through a type-checked
    accessor, so a malformed payload degrades gracefully instead of crashing.
  - **F3 — see the shared cache below.**
- **Local-only shared cache (validated on read and write).** The cross-session
  cache at `~/.cache/claude-statusline/shared-rate-limits.json` is local to your
  machine, but any process running as you could poison it. Every rate-limit value
  is sanitized with the *same* transform on both cache read and pre-publish write
  (F3): non-finite numbers (`NaN`/`Infinity`, which `json.loads` otherwise
  accepts) are dropped, `used_percentage` is clamped to `[0, 100]`, and
  `resets_at` is bounded to a plausible window (`now … now + ~30d`). A poisoned
  entry can therefore always be overwritten by a legitimate session and never
  produces a permanent red ⚠️.
- **PATH-resolved `ccusage` (trusted PATH).** The legacy fallback resolves
  `ccusage` via `shutil.which`, so it runs whatever that name points to on your
  `PATH`. This assumes a trusted `PATH`; it only runs on old Claude Code versions
  that don't send `rate_limits`, and never on the primary stdin→render path.

**Install integrity.** The `curl … | bash` one-liner (Option A) executes a remote
script unverified over the network — convenient, but you are trusting the fetch.
Security-conscious users should prefer the **clone + installer** or **manual**
routes (Options B/C), which let you read the script before running it. When a
release publishes a SHA-256 for `install.sh`, verify it before piping to a shell
(e.g. `shasum -a 256 install.sh` and compare against the published digest).

The full analysis and rationale live in
[`docs/decisions/0001-security-hardening.md`](docs/decisions/0001-security-hardening.md)
(ADR-0001) and `SECURITY-ANALYSIS.md`.

## Requirements

- **Claude Code ≥ ~2.1** (provides `rate_limits` + `context_window` on stdin)
- **Python 3** on your PATH
- `ccusage` is **only** needed as a fallback on older Claude Code versions that don't
  send `rate_limits`. Modern versions need nothing extra.

## Install

**Option A — one-liner (no clone needed):**

```bash
curl -fsSL https://raw.githubusercontent.com/lbonnaireYellowtail/claude-statusline/main/install.sh | bash
```

**Option B — clone + installer:**

```bash
git clone https://github.com/lbonnaireYellowtail/claude-statusline.git
cd claude-statusline && ./install.sh
```

Both print the `settings.json` snippet to paste in (shown below).

**Option C — manual:**

1. Copy `statusline.py` to `~/.claude/scripts/statusline.py`
2. `chmod +x ~/.claude/scripts/statusline.py`
3. Add this block to `~/.claude/settings.json` (top level):

```json
"statusLine": {
  "type": "command",
  "command": "$HOME/.claude/scripts/statusline.py",
  "padding": 0,
  "refreshInterval": 2
}
```

Start a new Claude Code session (or reload) to see it.

`refreshInterval` re-runs the statusline every N seconds even when a session is idle —
that's what lets idle terminals pull synced rate limits. It needs Claude Code with
statusline timer support; on older versions the key is ignored and the statusline stays
event-driven (sync still works, idle terminals just update on their next event). Drop it
to `1` for snappier propagation at roughly double the (small) idle cost.

## Config (optional env vars)

| Var                      | Default  | Meaning                                  |
| ------------------------ | -------- | ---------------------------------------- |
| `STATUSLINE_CTX_TARGET`  | `100000` | Soft context-token target for coloring   |
| `STATUSLINE_CAUTION_PCT` | `60`     | Yellow at/above this % of target/limit   |
| `STATUSLINE_WARN_PCT`    | `85`     | Red + ⚠️ at/above this %                  |
| `STATUSLINE_5H_LIMIT`    | `50`     | (fallback only) $ ceiling for 5h block   |
| `STATUSLINE_WEEK_LIMIT`  | `500`    | (fallback only) $ ceiling for the week   |

Set them in your shell profile, e.g. `export STATUSLINE_CTX_TARGET=80000`.
The legacy `CCUSAGE_*` names are still honored for backward compatibility.

## Troubleshooting

- **Nothing shows / stale:** confirm `settings.json` path is correct and the script is
  executable. Test it directly:
  `echo '{"model":{"display_name":"test"},"context_window":{"total_input_tokens":50000,"used_percentage":5}}' | ~/.claude/scripts/statusline.py`
- **`$HOME` not expanding:** replace it with your full absolute path in `settings.json`.
- **5h/7d missing:** you're on an older Claude Code; either upgrade, or `npm i -g ccusage`
  to enable the estimated-dollars fallback.
- **⇄ never appears / sync seems off:** the shared cache lives at
  `~/.cache/claude-statusline/` — delete it to reset. Sessions opened before you added
  `refreshInterval` to settings.json need a restart to start polling.
