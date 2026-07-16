# Tickets — claude-statusline
<!-- prefix: CS -->

## In Progress

## Refined

## Ready

### [CS-001] Sanitize model.display_name to block terminal escape injection
**Priority:** high

Acceptance criteria:
- [ ] Sanitize the model label via a **printable allowlist** (drop C0 `\x00-\x1f`, DEL `\x7f`, and C1 `\x80-\x9f`), applied at statusline.py:238 to **both** `model.display_name` **and** the `model.id` fallback (same f-string sink), length-bounded
- [ ] Adversarial payloads render as inert text: `\x1b]0;X\x07\x1b[2J\x1b[31mEVIL` (OSC+clear+color), a `\n`-injected second line, `\x9b31m` (C1 8-bit CSI), and `\x1b]52;c;...\x07` (OSC 52 clipboard)
- [ ] Legitimate names (e.g. "Opus 4.8 (1M context)") render byte-for-byte unchanged
- [ ] Add a regression test covering the OSC, newline, C1, and OSC-52 payloads on both `display_name` and `id`

Notes:
F1 in SECURITY-ANALYSIS.md — Medium. Ping-pong (ADR-0001) confirmed **two** raw sinks, not one: line 238 is `md.get('display_name') or md.get('id') or '?'`. The compiled line-60 ANSI regex matches only SGR colours — it leaves clear/OSC/C1/C0 intact (proven in experiments/security-hardening), so **allowlist, not blocklist**. Reference impl: `fixed_display()` in that experiment. Class = CWE-150 (cf. CVE-2025-55754 Tomcat, CVE-2025-55193 Rails).

---

### [CS-002] Guard against valid-but-non-object JSON to prevent crash
**Priority:** high

Acceptance criteria:
- [ ] Add top-level `if not isinstance(data, dict): data = {}` after json parsing (statusline.py:66)
- [ ] **Also guard nested access**: the `data.get(k) or {}` idiom still crashes when a key holds a wrong non-falsy type. Use a type-checked accessor (only return the value if it is a dict) at the `context_window`, `model`, `rate_limits`, and nested `current_usage` sites
- [ ] Both top-level (`null`, `[1,2,3]`, `"hi"`, `42`) **and nested** (`{"model":"hi"}`, `{"context_window":5}`, `{"rate_limits":[1,2]}`) inputs produce a graceful statusline with exit 0 (no traceback)
- [ ] A well-formed payload still extracts context/model/rate-limits correctly
- [ ] Add regression tests for each top-level and nested case

Notes:
F2 in SECURITY-ANALYSIS.md — Low/robustness. **Ticket was under-scoped**: ping-pong reproduced nested crashes the top-level guard alone doesn't catch (`5 or {}` → `5`, then `.get` throws). Reference impl: `_dict_get()` + `fixed_extract()` in experiments/security-hardening.

---

### [CS-003] Validate shared-cache values to stop persistent poisoning
**Priority:** medium

Acceptance criteria:
- [ ] Sanitize rate_limits with a single helper applied on **both** cache read and pre-publish: drop non-finite values (`math.isfinite`), clamp `used_percentage` to [0,100], and **bound `resets_at` to a plausible window** (`now <= resets_at <= now + ~30d`), dropping the field otherwise
- [ ] Bounding `resets_at` is required, not optional: the freshness key compares `resets_at` first, so clamping the percentage alone leaves the poison winning (verified). Sanitizing `resets_at` is what actually restores overwritability
- [ ] Poisoned caches — `used_percentage: 1e308`, `Infinity`, `NaN`, and a far-future `resets_at` — can each be overwritten by a legitimate session and produce no permanent red ⚠️
- [ ] Add regression tests for the poison-then-recover scenario across all four poison shapes

Notes:
F3 in SECURITY-ANALYSIS.md — Low/Medium local availability. Monotone key `(resets_at, used_percentage)`; max-valued poison is never overwritten (`mine > theirs` never true). Ping-pong found **percentage-clamp alone is insufficient** and that `json.loads` accepts `NaN`/`Infinity` (extra poison paths, killed by `isfinite`). Reference impl: `sanitize_rl()` + `fixed_can_overwrite()` in experiments/security-hardening. Re-run the 2-session sync simulation after the change (STANDARDS.md).

---

### [CS-004] Add README "Security" section documenting trust boundaries
**Priority:** medium

Acceptance criteria:
- [ ] Document trust boundaries: untrusted stdin JSON, local-only shared cache, PATH-resolved `ccusage`
- [ ] Note the `curl | bash` install risk and unverified download; publish a SHA-256 and point security-conscious users to clone+install
- [ ] Cross-reference the F1–F3 fixes shipped in this release
- [ ] Bump `__version__` to 1.1.1 and add a CHANGELOG entry

Notes:
Ships alongside CS-001..CS-003 as the v1.1.1 hardening release. Cross-reference ADR-0001 (docs/decisions) and cite CWE-150 precedent (CVE-2025-55754, CVE-2025-55193) as why F1 matters. Run /code-review and re-run the 2-session sync simulation before the PR.

---

### [CS-005] Bootstrap a stdlib-only regression test harness
**Priority:** high

Acceptance criteria:
- [ ] Add `tests/test_statusline.py` (stdlib `unittest`) that drives `statusline.py` **black-box via subprocess** with fixture stdin payloads and a sandboxed `HOME`/cache dir — mirroring how Claude Code invokes it
- [ ] Provide shared fixture/helper plumbing so CS-001/002/003 each drop their regression tests in without reinventing setup
- [ ] Include a smoke test of the normal rate-limits path and one document of how to run it (README or a make target)

Notes:
Enabling ticket — CS-001/002/003 each require a regression test but the repo currently has **zero tests**. Land this first so the three fixes share one harness. The `experiments/security-hardening` adapters are reference behaviour, not a substitute for black-box tests against the real script. Blocks CS-001, CS-002, CS-003.

---

## Blocked

## Done
