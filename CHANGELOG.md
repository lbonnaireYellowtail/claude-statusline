# Changelog

Versions follow [semver](https://semver.org) and match `__version__` in `statusline.py`.

## [1.2.0] — 2026-08-26

### Changed
- **The `🧠 ctx` segment is now a bar.** The `ctx` label and bare token count are
  replaced by a fixed-width gauge filling toward `STATUSLINE_CTX_TARGET`, with the
  absolute token count kept to its right. Fill state is readable without parsing a
  number — the point of a statusline segment you glance at rather than read.
  Thresholds are unchanged (yellow at `CAUTION_PCT`, red + ⚠️ at `WARN_PCT`), and the
  bar clamps at full rather than overflowing past 100% of target.
- Bar colours are emitted as 24-bit RGB rather than ANSI 32/33/31. Fading the
  unfilled cells needs real channel values to scale, and terminals that remap the
  16-colour palette (Ghostty, custom themes) were repainting the gauge to a colour
  unrelated to its state. The other segments still use the ANSI palette.

### Added
- `STATUSLINE_CTX_BAR` (default `1`). Set to `0` to keep the compact `ctx 62.7k` label
  in ANSI colours — for narrow panes, or terminals without 24-bit colour support
  (macOS Terminal.app).
- `STATUSLINE_CTX_BAR_CELLS` (default `15`, clamped to 1–60) sets the bar width.
- `CtxBarTest` regression tests: constant width at every fill level including past
  100%, fill proportional to target, the three colour thresholds, the ⚠️ prefix
  surviving the label removal, and out-of-range `CTX_BAR_CELLS` values.

## [1.1.1] — 2026-07-16

### Security
- **F1 — terminal-escape injection (CWE-150).** `model.display_name` and the
  `model.id` fallback are now sanitized through a printable allowlist (drops C0,
  DEL, and C1 bytes; length-bounded), so a crafted model name can't inject
  OSC/CSI/clear-screen/clipboard escape sequences into the terminal. Same class
  as CVE-2025-55754 and CVE-2025-55193.
- **F2 — non-object JSON hardening.** Non-object top-level payloads and
  wrong-typed nested keys are coerced via a type-checked accessor, so a malformed
  stdin payload degrades gracefully (exit 0) instead of crashing.
- **F3 — shared-cache poisoning.** Rate-limit values are sanitized with one
  helper on both cache read and pre-publish write: non-finite numbers
  (`NaN`/`Infinity`) are dropped, `used_percentage` is clamped to `[0, 100]`, and
  `resets_at` is bounded to `now … now + ~30d`. A poisoned local cache can always
  be overwritten by a legitimate session and never yields a permanent red ⚠️.

### Added
- Stdlib-only regression test harness (`tests/test_statusline.py`) driving
  `statusline.py` black-box via subprocess with a sandboxed `HOME`/cache dir, plus
  regression tests for each F1–F3 adversarial input and a normal-path smoke test.
- README "Security" section documenting the trust boundaries; ADR-0001
  (`docs/decisions/0001-security-hardening.md`) records the rationale.

## [1.1.0] — 2026-07-15

### Added
- **Cross-terminal sync for rate limits.** The session with the freshest `rate_limits`
  publishes them to `~/.cache/claude-statusline/shared-rate-limits.json`; sessions
  holding staler data render from that cache, marked with a dim `⇄`. Lock-free:
  freshness derives from `(resets_at, used_percentage)` per window, which never
  decreases, so concurrent writers can't regress the cache.
- `refreshInterval: 2` in the recommended `settings.json` snippet and `install.sh`,
  so idle terminals poll the shared cache.
- 60-second cache around the `ccusage` fallback so timer polling stays cheap on old
  Claude Code versions.
- `__version__` in `statusline.py`.

## [1.0.0] — 2026-07-15

Baseline: context tokens vs soft target, real 5h/7d rate-limit percentages with
time-until-reset, active model. Includes the Windows fix (UTF-8 stdout, `ccusage`
resolved via `shutil.which`) from PR #1.
