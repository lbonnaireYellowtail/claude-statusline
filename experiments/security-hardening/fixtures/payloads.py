"""Adversarial fixtures, one cluster per finding.

Each fixture stresses the specific dimension that separates the vulnerable and
fixed adapters — not general validity. `now` is a fixed reference epoch so the
resets_at bounds are deterministic (the production script uses time.time()).
"""

NOW = 4_100_000_000  # fixed reference "now" for deterministic resets_at bounds

# --- F1 / CS-001: escape-injection display names -----------------------------
# (label, raw field, must_not_appear_substrings)
DISPLAY_FIXTURES = [
    ("osc_title_clear_color", "\x1b]0;PWNED\x07\x1b[2J\x1b[31mEVIL", ["\x1b", "\x07"]),
    ("newline_second_line", "Opus\n\x1b[32mFAKE 5h 0%", ["\n", "\x1b"]),
    ("c1_8bit_csi", "M\x9b31mODEL", ["\x9b"]),
    ("osc52_clipboard", "\x1b]52;c;ZWls\x07x", ["\x1b", "\x07"]),
    ("bare_bell", "Opus\x07 4.8", ["\x07"]),
    # legitimate names must survive untouched
    ("legit_plain", "Opus 4.8", []),
    ("legit_paren", "Opus 4.8 (1M context)", []),
]

# --- F2 / CS-002: non-object / type-confused JSON ----------------------------
# (label, parsed_json_value)  — value is what json.loads returns
EXTRACT_FIXTURES = [
    ("toplevel_null", None),
    ("toplevel_list", [1, 2, 3]),
    ("toplevel_str", "hi"),
    ("toplevel_int", 42),
    ("nested_model_str", {"model": "hi"}),
    ("nested_ctx_int", {"context_window": 5}),
    ("nested_rl_list", {"rate_limits": [1, 2]}),
    # well-formed payload must still extract correctly
    ("valid_full", {
        "context_window": {"total_input_tokens": 60541},
        "model": {"display_name": "Opus 4.8"},
        "rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": NOW + 3600}},
    }),
]

# --- F3 / CS-003: cache poisoning --------------------------------------------
# A legit session's live rate_limits (the "mine" that should win over poison).
LEGIT_MINE = {
    "five_hour": {"used_percentage": 42.0, "resets_at": NOW + 3600},
    "seven_day": {"used_percentage": 18.0, "resets_at": NOW + 5 * 86400},
}

# (label, poisoned_cache_contents)
POISON_FIXTURES = [
    ("max_float", {
        "five_hour": {"used_percentage": 1e308, "resets_at": 9_999_999_999},
        "seven_day": {"used_percentage": 1e308, "resets_at": 9_999_999_999},
    }),
    ("infinity", {
        "five_hour": {"used_percentage": float("inf"), "resets_at": float("inf")},
        "seven_day": {"used_percentage": float("inf"), "resets_at": float("inf")},
    }),
    ("nan", {
        "five_hour": {"used_percentage": float("nan"), "resets_at": float("nan")},
        "seven_day": {"used_percentage": float("nan"), "resets_at": float("nan")},
    }),
    ("far_future_reset", {
        "five_hour": {"used_percentage": 99.0, "resets_at": NOW + 3650 * 86400},
        "seven_day": {"used_percentage": 99.0, "resets_at": NOW + 3650 * 86400},
    }),
    # resets_at 20 days out: within a generous flat bound (~30d) but far beyond
    # either window's real horizon. Only a per-window bound drops it; a flat
    # bound would leave this poison winning the freshness key for weeks.
    ("within_wide_bound_reset", {
        "five_hour": {"used_percentage": 100.0, "resets_at": NOW + 20 * 86400},
        "seven_day": {"used_percentage": 100.0, "resets_at": NOW + 20 * 86400},
    }),
]
