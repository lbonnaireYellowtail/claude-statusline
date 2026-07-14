# Claude Code live statusline

A one-line statusline for Claude Code that shows, in real time:

```
🧠 ctx 62.7k (6%) | 🕐 5h 0% →4h55m | 📅 7d 10% →53h15m | 🤖 Opus 4.8 (1M context)
```

- **🧠 ctx** — context tokens used, colored against a soft target (default 100k) so you
  can keep sessions lean. The `(6%)` is the real fill of the full context window.
- **🕐 5h / 📅 7d** — your actual Anthropic rate-limit usage, with time-until-reset.
- **🤖** — the active model.

Colors: green → under target, yellow at 60%+, red + ⚠️ at 85%+.

Everything comes straight from the JSON payload Claude Code pipes to the statusline on
every render, so it's always current — no background jobs, no log parsing.

## Works on any subscription

The **5h / 7d percentages come straight from Claude Code** (`rate_limits.used_percentage`),
which Anthropic computes against *your* plan's limits. So whether you're on **Pro ($20)**
or **Max ($100 / $200)**, the numbers are correct with **no configuration** — a Pro user
simply hits 100% sooner than a Max user, because the percentage is relative to their own
ceiling. Nothing in the primary path assumes a particular tier.

(The only tier-specific values are the `CCUSAGE_5H_LIMIT` / `CCUSAGE_WEEK_LIMIT` dollar
ceilings, and those are used *only* by the legacy fallback below.)

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
  "padding": 0
}
```

Start a new Claude Code session (or reload) to see it.

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
