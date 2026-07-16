# Changelog

Versions follow [semver](https://semver.org) and match `__version__` in `statusline.py`.

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
