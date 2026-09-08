"""Score a candidate's weekly figure against a scenario's ground truth.

Pass rules:
  exact      - |got - truth| <= 1e-6  (default)
  bounded    - got is finite and truth <= got <= truth + bound  (poison scenarios:
               we accept an over-count as long as its blast radius is capped)
  resolution - |got - truth| <= bound  (the window edge is resolved to one
               bucket, so one bucket's worth of spend may fall either side)
"""
import math


def score(truth, got, tol=None):
    if not isinstance(got, (int, float)) or not math.isfinite(got):
        return False, f"non-finite result {got!r}"
    err = got - truth
    if tol and tol[0] == "bounded":
        ok = 0.0 <= err <= tol[1] + 1e-6
        return ok, f"got ${got:,.2f} (truth ${truth:,.2f}, over by ${err:,.2f}; bound ${tol[1]:,.0f})"
    if tol and tol[0] == "resolution":
        ok = abs(err) <= tol[1] + 1e-6
        return ok, f"got ${got:,.2f} (truth ${truth:,.2f}, off by ${err:+,.2f}; resolution ${tol[1]:,.0f})"
    ok = abs(err) <= 1e-6
    return ok, f"got ${got:,.2f} (truth ${truth:,.2f})"
