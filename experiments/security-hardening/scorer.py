"""Scoring logic tied to what the statusline actually must guarantee:

- F1: output must contain no ESC/BEL/newline/C1 bytes, and legit names survive.
- F2: extraction must not raise, and valid payloads must still extract.
- F3: a poisoned cache must be overwritable by a legit session (safe = True).
"""

_DANGEROUS_BYTES = set(range(0x00, 0x20)) | {0x7f} | set(range(0x80, 0xa0))


def score_display(rendered, must_not_appear):
    """True if rendered text is inert (no control bytes) and drops banned subs."""
    if any(ord(ch) in _DANGEROUS_BYTES for ch in rendered):
        return False, "contains control byte"
    for sub in must_not_appear:
        if sub in rendered:
            return False, f"leaked {sub!r}"
    return True, "inert"


def score_display_legit(rendered, original):
    """Legit names must pass through unchanged (allowlist keeps printables)."""
    ok = rendered == original
    return ok, "unchanged" if ok else f"altered -> {rendered!r}"


def score_extract(fn, value):
    """True if extraction does not raise on hostile input."""
    try:
        fn(value)
        return True, "no crash"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def score_poison_recoverable(can_overwrite):
    """True (safe) when a legit session CAN overwrite the poisoned cache."""
    return bool(can_overwrite), "recoverable" if can_overwrite else "STUCK (un-clearable)"
