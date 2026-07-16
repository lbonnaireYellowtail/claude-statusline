# Experiment — security hardening (CS-001..CS-003)

Validates each finding in `SECURITY-ANALYSIS.md` by reproducing the vulnerable
behaviour and the proposed fix side by side, then scoring both against
adversarial fixtures.

```
python3 run.py        # regenerates results/report.md; exits non-zero on any fixed-adapter failure
```

| File | Role |
| --- | --- |
| `fixtures/payloads.py` | Adversarial inputs, one cluster per finding |
| `adapters.py` | `vulnerable_*` (current behaviour) vs `fixed_*` (reference for the fix) |
| `scorer.py` | Pass/fail tied to the real guarantee (no injection / no crash / cache recoverable) |
| `run.py` | Runs all candidates × fixtures, writes the report |
| `results/report.md` | Committed output |

The `fixed_*` functions in `adapters.py` are the **reference implementation** the
CS-001..CS-003 fixes in `statusline.py` should match. This harness is not a
substitute for the in-script regression tests STANDARDS.md requires — it proves
the approach; the swarm still adds black-box tests against `statusline.py` itself.
