# Changelog

Versions follow [semver](https://semver.org) and match `__version__` in `statusline.py`.

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
