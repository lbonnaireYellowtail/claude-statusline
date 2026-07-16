# Tickets — claude-statusline
<!-- prefix: CS -->

## In Progress

## Refined

### [CS-006] Don't trust cwd as the install source in `curl | bash` mode
**Priority:** medium

Refined via ping-pong 2026-07-16 → ADR-0002 (`docs/decisions/0002-install-integrity.md`, D1) + experiment (`experiments/install-integrity/`, validated 0/4 fixed failures). Reference impl: `candidates/fixed.sh`.

Acceptance criteria:
- [ ] `install.sh` only takes the local-copy branch when the script genuinely runs from a file on disk — guard on `[ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]`, never the `$0` fallback; `SRC_DIR` is derived from `BASH_SOURCE`, never from cwd
- [ ] In piped mode (`curl -fsSL … | bash`, where `BASH_SOURCE[0]` is unset) the installer always downloads `statusline.py` from `RAW_BASE` and never copies a `statusline.py` that happens to sit in the current working directory
- [ ] The `git clone && ./install.sh` local-install path still copies the repo's `statusline.py` as before
- [ ] Manual repro: running the piped one-liner from a directory containing a planted `statusline.py` installs the downloaded file, not the local one
- [ ] `experiments/install-integrity/run.py` passes (fixed candidate safe on every scenario)

Notes:
From the 2026-07-16 pre-release security review. In piped mode `dirname "${BASH_SOURCE[0]:-$0}"` resolves to `dirname bash` = `.` = the cwd, so the `[ -f "$SRC_DIR/statusline.py" ]` branch silently installs a cwd file and skips the trusted download (install.sh:11-20). Empirically confirmed by the experiment (vulnerable candidate installs the attacker file; fixed ignores cwd). Filtered to Medium/low-confidence (attacker must both plant a file in the victim's cwd and get them to run the one-liner there) — hardening, not a blocking vuln, but a genuine logic flaw: the local-copy branch is meant only for the clone-and-run mode. Pairs with CS-007. ADR-0002 D1 records the `sh install.sh` edge case (falls through to download — safe) and its switch trigger.

### [CS-007] Verify the downloaded `statusline.py` against a pinned SHA-256 (+ release automation)
**Priority:** medium

Refined via ping-pong 2026-07-16 → ADR-0002 (D2) + experiment (`experiments/install-integrity/`). Decision: pin statusline.py's digest **inside install.sh** (Option A), verify before `chmod`; keep the README manual note (Option C, repointed to statusline.py); reject same-origin `.sha256` fetch (Option B, theatre) and signing (Option D, disproportionate — switch trigger recorded). Reference impl: `candidates/fixed.sh`.

Acceptance criteria:
- [ ] `install.sh` carries a pinned `EXPECTED_SHA256` for `statusline.py`, verifies the download against it before `chmod +x`, and aborts with a clear message on mismatch
- [ ] No `shasum`/`sha256sum` available → **fail closed** (abort with a clear message), do not silently skip verification
- [ ] Local-copy (clone) path is not hashed against the pin — only the download is verified (no release pin exists mid-development)
- [ ] **Release automation** computes `statusline.py`'s SHA-256 and injects it into `install.sh` (and README/release notes) at release time — the pin is generated, never hand-edited. A stale/hand-typed pin is explicitly out (fails safe but breaks every install)
- [ ] Repoint the README install-integrity note (README.md:153-158) from `install.sh`'s own digest (chicken-and-egg in the pipe flow) to `statusline.py`'s digest
- [ ] `experiments/install-integrity/run.py` passes (tampered download aborts non-zero, honest download installs)

Notes:
From the 2026-07-16 pre-release security review + the long-parked CS-004 follow-up (README recommends verifying a SHA-256 but none is published and the installer verifies nothing). Threat model (per user, 2026-07-16): make the published package as safe as reasonably possible for its users — defend network tampering of the download hop, silent drift from the reviewed version, and accidental corruption; not repo-compromise (that needs signing, gated on the ADR-0002 switch trigger). Also closes the still-open v1.1.1 release task to publish the install digest. Superseded ADR-0001's "unverified curl|bash install = accepted risk" note.

## Ready

## Blocked

## Done

### [CS-004] Add README "Security" section documenting trust boundaries
**Priority:** medium

Acceptance criteria:
- [x] Document trust boundaries: untrusted stdin JSON, local-only shared cache, PATH-resolved `ccusage`
- [x] Note the `curl | bash` install risk and unverified download; publish a SHA-256 and point security-conscious users to clone+install
- [x] Cross-reference the F1–F3 fixes shipped in this release
- [x] Bump `__version__` to 1.1.1 and add a CHANGELOG entry

Notes:
Ships alongside CS-001..CS-003 as the v1.1.1 hardening release. Cross-reference ADR-0001 (docs/decisions) and cite CWE-150 precedent (CVE-2025-55754, CVE-2025-55193) as why F1 matters. Run /code-review and re-run the 2-session sync simulation before the PR.

Done: added a "## Security" section to README.md documenting the three trust boundaries — untrusted stdin JSON (sanitized via F1/F2/F3), the local-only shared cache (validated on read and write per F3), and PATH-resolved `ccusage` (trusted-PATH assumption, fallback-only) — plus a curl|bash install-integrity note recommending SHA-256 verification and the clone/manual routes (Options B/C), and cross-references to ADR-0001 and SECURITY-ANALYSIS.md. Cited CWE-150 with CVE-2025-55754/CVE-2025-55193 as precedent for F1. Bumped `__version__` 1.1.0 → 1.1.1 and added the `[1.1.1] — 2026-07-16` CHANGELOG entry summarizing F1–F3 + the new test harness.

### [CS-003] Validate shared-cache values to stop persistent poisoning
**Priority:** medium

Acceptance criteria:
- [x] Sanitize rate_limits with a single helper applied on **both** cache read and pre-publish: drop non-finite values (`math.isfinite`), clamp `used_percentage` to [0,100], and **bound `resets_at` to a plausible window** (`now <= resets_at <= now + ~30d`), dropping the field otherwise
- [x] Bounding `resets_at` is required, not optional: the freshness key compares `resets_at` first, so clamping the percentage alone leaves the poison winning (verified). Sanitizing `resets_at` is what actually restores overwritability
- [x] Poisoned caches — `used_percentage: 1e308`, `Infinity`, `NaN`, and a far-future `resets_at` — can each be overwritten by a legitimate session and produce no permanent red ⚠️
- [x] Add regression tests for the poison-then-recover scenario across all four poison shapes

Notes:
F3 in SECURITY-ANALYSIS.md — Low/Medium local availability. Monotone key `(resets_at, used_percentage)`; max-valued poison is never overwritten (`mine > theirs` never true). Ping-pong found **percentage-clamp alone is insufficient** and that `json.loads` accepts `NaN`/`Infinity` (extra poison paths, killed by `isfinite`). Reference impl: `sanitize_rl()` + `fixed_can_overwrite()` in experiments/security-hardening. Re-run the 2-session sync simulation after the change (STANDARDS.md).

Done: added `_MAX_RESET_HORIZON` (~30d) and a `sanitize_rl(rl, now)` helper (stdlib `math.isfinite`) in statusline.py that, per window, drops non-finite numbers, clamps `used_percentage` to [0,100], and keeps `resets_at` only within `[now, now+30d]`. Wired it into `sync_rate_limits` on **both** sides — the live payload before publish and the shared-cache contents on read — so the freshness comparison and the published blob are both sanitized, keeping the lock-free invariant (identical transform both sides). Regression tests in `SharedCachePoisonTest` seed a poisoned cache (far-future `resets_at` paired with `1e308`/`Infinity`/`NaN`, plus a far-future-`resets_at`-only shape) and assert a legitimate session overwrites it, renders its own 42% figure, and raises no permanent red ⚠️. Verified the tests fail without the fix.

---

### [CS-002] Guard against valid-but-non-object JSON to prevent crash
**Priority:** high

Acceptance criteria:
- [x] Add top-level `if not isinstance(data, dict): data = {}` after json parsing (statusline.py:66)
- [x] **Also guard nested access**: the `data.get(k) or {}` idiom still crashes when a key holds a wrong non-falsy type. Use a type-checked accessor (only return the value if it is a dict) at the `context_window`, `model`, `rate_limits`, and nested `current_usage` sites
- [x] Both top-level (`null`, `[1,2,3]`, `"hi"`, `42`) **and nested** (`{"model":"hi"}`, `{"context_window":5}`, `{"rate_limits":[1,2]}`) inputs produce a graceful statusline with exit 0 (no traceback)
- [x] A well-formed payload still extracts context/model/rate-limits correctly
- [x] Add regression tests for each top-level and nested case

Notes:
F2 in SECURITY-ANALYSIS.md — Low/robustness. **Ticket was under-scoped**: ping-pong reproduced nested crashes the top-level guard alone doesn't catch (`5 or {}` → `5`, then `.get` throws). Reference impl: `_dict_get()` + `fixed_extract()` in experiments/security-hardening.

Done: added top-level `if not isinstance(data, dict): data = {}` guard after `json.loads`, plus a `_dict_get(d, key)` type-checked accessor returning `{}` unless the value is a dict. Replaced the `data.get(k) or {}` idiom at the `context_window`, nested `current_usage`, `rate_limits`, and `model` sites. Regression tests in `NonObjectJsonTest` cover all four top-level scalars/array and the three nested wrong-type cases (each exits 0, empty stderr, no traceback) plus a well-formed-payload extraction check.

---

### [CS-001] Sanitize model.display_name to block terminal escape injection
**Priority:** high

Acceptance criteria:
- [x] Sanitize the model label via a **printable allowlist** (drop C0 `\x00-\x1f`, DEL `\x7f`, and C1 `\x80-\x9f`), applied at statusline.py:238 to **both** `model.display_name` **and** the `model.id` fallback (same f-string sink), length-bounded
- [x] Adversarial payloads render as inert text: `\x1b]0;X\x07\x1b[2J\x1b[31mEVIL` (OSC+clear+color), a `\n`-injected second line, `\x9b31m` (C1 8-bit CSI), and `\x1b]52;c;...\x07` (OSC 52 clipboard)
- [x] Legitimate names (e.g. "Opus 4.8 (1M context)") render byte-for-byte unchanged
- [x] Add a regression test covering the OSC, newline, C1, and OSC-52 payloads on both `display_name` and `id`

Notes:
F1 in SECURITY-ANALYSIS.md — Medium. Ping-pong (ADR-0001) confirmed **two** raw sinks, not one: line 238 is `md.get('display_name') or md.get('id') or '?'`. The compiled line-60 ANSI regex matches only SGR colours — it leaves clear/OSC/C1/C0 intact (proven in experiments/security-hardening), so **allowlist, not blocklist**. Reference impl: `fixed_display()` in that experiment. Class = CWE-150 (cf. CVE-2025-55754 Tomcat, CVE-2025-55193 Rails).

Done: added `sanitize_label()` (printable allowlist, 64-char bound, `?` fallback) in statusline.py and applied it to the combined `display_name or id or '?'` sink. Regression tests in `ModelLabelInjectionTest` cover all four payloads on both `display_name` and `id` (asserting the model-label region is free of ESC/BEL/newline/C1 bytes) plus a legit-name-unchanged case.

---

### [CS-005] Bootstrap a stdlib-only regression test harness
**Priority:** high

Acceptance criteria:
- [x] Add `tests/test_statusline.py` (stdlib `unittest`) that drives `statusline.py` **black-box via subprocess** with fixture stdin payloads and a sandboxed `HOME`/cache dir — mirroring how Claude Code invokes it
- [x] Provide shared fixture/helper plumbing so CS-001/002/003 each drop their regression tests in without reinventing setup
- [x] Include a smoke test of the normal rate-limits path and one document of how to run it (README or a make target)

Notes:
Enabling ticket — CS-001/002/003 each require a regression test but the repo currently has **zero tests**. Land this first so the three fixes share one harness. The `experiments/security-hardening` adapters are reference behaviour, not a substitute for black-box tests against the real script. Blocks CS-001, CS-002, CS-003.

Done: `StatuslineTestCase` base (sandboxed HOME + `run_statusline(payload, env_overrides)` helper + cache read helpers) and a `SmokeTest` covering the normal context_window + rate_limits + model path. README gained a "## Tests" section.
