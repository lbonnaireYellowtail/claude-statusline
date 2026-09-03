"""Synthetic statusline tick streams that stress the dimensions on which the
ledger policies differ. Each scenario is a list of (now, session_id,
total_cost_usd) ticks exactly as a statusline process would observe them, plus
the ground truth: dollars actually spent in the 7 days before `end`.

T0 is hour-aligned so bucket arithmetic is easy to reason about by hand.
"""
import math

HOUR = 3600
T0 = 1_800_000_000  # == 500000 * 3600


def ramp(sid, start, hours, rate, step, base=0.0):
    """Ticks every `step` s for `hours` h; cumulative total grows `rate` $/h from `base`."""
    out, t = [], start
    while t <= start + hours * HOUR:
        out.append((t, sid, base + rate * (t - start) / HOUR))
        t += step
    return out


def flat(sid, start, hours, total, step):
    return [(t, sid, total) for t in range(start, start + hours * HOUR + 1, step)]


def scenarios():
    S = []

    ev = ramp("A", T0, 240, 1.0, 600)
    # Hourly buckets resolve the window edge to one bucket, so up to one hour of
    # spend ($1 here) may fall just outside: that is the documented resolution.
    S.append(dict(name="steady-10d", desc="one session, $1/h for 10 days, tick every 10 min",
                  events=ev, end=ev[-1][0], truth=168.0, tol=("resolution", 1.0)))

    ev = ramp("A", T0, 1, 50.0, 600) + flat("A", T0 + HOUR + 600, 239, 50.0, 600)
    S.append(dict(name="long-idle", desc="$50 in the first hour, then the session idles 10 days",
                  events=ev, end=ev[-1][0], truth=0.0))

    a, b = ramp("A", T0, 72, 0.5, 300), ramp("B", T0 + 150, 72, 0.5, 300)
    ev = sorted(a + b)
    S.append(dict(name="two-concurrent", desc="two sessions interleaved, $0.5/h each, 3 days",
                  events=ev, end=ev[-1][0], truth=72.0))

    ev = ramp("A", T0, 2, 5.0, 300) + ramp("B", T0 + 2 * HOUR + 300, 2, 2.5, 300)
    S.append(dict(name="clear", desc="/clear: A reaches $10, new session B spends $5 from $0",
                  events=ev, end=ev[-1][0], truth=15.0))

    ev = ramp("S", T0, 2, 5.0, 300) + ramp("S", T0 + 3 * HOUR, 2, 2.0, 300)
    S.append(dict(name="resume-reset", desc="same session_id; total resets to $0 on resume, climbs $4",
                  events=ev, end=ev[-1][0], truth=14.0))

    ev = ramp("S", T0, 2, 5.0, 300) + ramp("S", T0 + 3 * HOUR, 2, 2.0, 300, base=10.0)
    S.append(dict(name="resume-continue", desc="same session_id; total continues $10 -> $14 after a gap",
                  events=ev, end=ev[-1][0], truth=14.0))

    ev = [(T0 + 2 * i, "A", 3.0) for i in range(1000)]
    S.append(dict(name="duplicate-ticks", desc="the same $3 total repeated 1000 times (refreshInterval)",
                  events=ev, end=ev[-1][0], truth=3.0))

    pre = ramp("A", T0, 2, 5.0, 300)
    post = ramp("A", T0 + 2 * HOUR + 300, 1, 2.0, 300, base=10.0)
    S.append(dict(name="poison-huge", desc="one tick claims total=$1e12, then honest ticks resume",
                  events=pre + [(T0 + 2 * HOUR + 150, "A", 1e12)] + post, end=post[-1][0],
                  truth=12.0, tol=("bounded", 100.0)))

    S.append(dict(name="poison-plausible", desc="one tick claims a plausible $60, then honest ticks resume",
                  events=pre + [(T0 + 2 * HOUR + 150, "A", 60.0)] + post, end=post[-1][0],
                  truth=12.0, tol=("bounded", 100.0)))

    junk = [math.nan, math.inf, -math.inf, -5.0, "12", None, [1], {"x": 1}, True]
    ev = []
    for i, (t, sid, tot) in enumerate(ramp("A", T0, 2, 5.0, 300)):
        ev.append((t, sid, tot))
        if i < len(junk):
            ev.append((t + 1, sid, junk[i]))
    S.append(dict(name="poison-nonnumeric", desc="NaN/Inf/negative/string/null/list/bool ticks interleaved",
                  events=ev, end=ev[-1][0], truth=10.0))

    ev = [(T0, "A", 10.0)] + flat("A", T0 + 600, 168, 10.0, 600) + [(T0 + 169 * HOUR, "A", 15.0)]
    S.append(dict(name="window-boundary", desc="$10 spent 169 h ago, $5 spent now",
                  events=ev, end=ev[-1][0], truth=5.0))

    ev = [(T0, "S", 10.0)] + ramp("S", T0 + 240 * HOUR, 1, 2.0, 300, base=10.0)
    S.append(dict(name="resume-after-prune", desc="session idle 10 days (past the 7d window), then resumes $10 -> $12",
                  events=ev, end=ev[-1][0], truth=2.0))

    ev = ramp("A", T0, 1, 1.0, 300, base=7.0)
    S.append(dict(name="install-mid-session", desc="first ever tick already shows $7; $1 more this hour",
                  events=ev, end=ev[-1][0], truth=8.0))

    return S
