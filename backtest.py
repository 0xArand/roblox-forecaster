#!/usr/bin/env python3
"""Backtest harness for the Roblox Up-and-Coming forecaster (main.py).

Not part of the graded entry: the grader runs only main.py. This script
exists so the tuning in ANALYSIS.md can be re-checked on the practice
history: for each cutoff date D (00:00 UTC), it trains main.py's model on
reads with at < D and scores the forecast on reads with D < at <= D+72h.

Scoring follows RULES.txt exactly. For each test read and each place k,
the probability of the game actually at k is the named row when present,
else the unnamed share (1 - sum of named p at k) split evenly over the
games on that read's chart not named at k. Each place's log probability
is floored at ln(0.0001); a read's score is the sum over its 10 places;
a window's score is the mean over its reads.

Usage (from this directory):
    python3 backtest.py            # current config vs the persistence baseline
    python3 backtest.py rho        # RHO sweep: 0.85 / 0.92 / 0.98 / 1.00
    python3 backtest.py umin       # U_MIN sweep: 0.18 / 0.25 / 0.32 / 0.40
    python3 backtest.py blend      # BLEND sweep: 0.05 / 0.10 / 0.20
Input history defaults to the kit's input directory next to this file
when present, else $MAKEFUN_INPUT_DIR, else ./input.
"""

import importlib.util
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_INPUT = os.path.join(HERE, "..", "roblox-kit",
                         "roblox-up-and-coming-forecast-01-kit", "input")
INPUT_DIR = (KIT_INPUT if os.path.isdir(KIT_INPUT)
             else os.environ.get("MAKEFUN_INPUT_DIR", os.path.join(HERE, "input")))
CUTOFFS = ("2026-11-03", "2026-11-04", "2026-11-05")

spec = importlib.util.spec_from_file_location("roblox_main",
                                             os.path.join(HERE, "main.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

with open(os.path.join(INPUT_DIR, "history.ndjson"), encoding="utf-8") as f:
    READS = [json.loads(line) for line in f if line.strip()]
READS.sort(key=lambda r: r["at"])


def _pt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def score_forecast(forecast, test_reads):
    """Mean per-read log score of a forecast on test reads (RULES.txt)."""
    named = {}
    for row in forecast["probabilities"]:
        named.setdefault(row["place"], {})[row["universe_id"]] = row["p"]
    sums = {k: sum(v.values()) for k, v in named.items()}
    total = 0.0
    for r in test_reads:
        chart = r["up_and_coming"]
        top10 = [g["universe_id"] for g in chart[:10]]
        chart_uids = {g["universe_id"] for g in chart}
        s = 0.0
        for k in range(1, 11):
            uid = top10[k - 1]
            if uid in named.get(k, {}):
                p = named[k][uid]
            else:
                n_un = len(chart_uids) - len(named.get(k, {}))
                p = (1.0 - sums.get(k, 0.0)) / n_un if n_un > 0 else 0.0
            s += math.log(max(p, 0.0001))
        total += s
    return total / len(test_reads) if test_reads else float("nan")


def forecast_for(train):
    """Run main.py's model on the training reads, return its forecast."""
    last = train[-1]
    last_chart = {g["universe_id"]: g["rank"] for g in last["up_and_coming"]}
    t0 = _pt(last["at"])
    vel = m.estimate_velocities(train, t0)
    entry_ranks, new_vel = m.estimate_pools(train)
    exit_hour = m.age_out_hours(train, t0)
    counts, unnamed, rank_sum, rank_n, total = m.simulate(
        last_chart, vel, entry_ranks, new_vel, exit_hour
    )
    return m.build_forecast(last_chart, counts, unnamed, rank_sum, rank_n, total)


def windows():
    """(cutoff datetime, train reads, test reads) for each cutoff date."""
    for d in CUTOFFS:
        c = datetime.fromisoformat(d + "T00:00:00+00:00")
        train = [r for r in READS if _pt(r["at"]) < c]
        test = [r for r in READS
                if c < _pt(r["at"]) <= c + timedelta(hours=72)]
        yield d, train, test


def run_variant(label, overrides=None):
    """Score one parameter variant on all windows; restore afterwards."""
    saved = {k: getattr(m, k) for k in (overrides or {})}
    for k, v in (overrides or {}).items():
        setattr(m, k, v)
    scores = []
    try:
        for _d, train, test in windows():
            scores.append(score_forecast(forecast_for(train), test))
    finally:
        for k, v in saved.items():
            setattr(m, k, v)
    mean = sum(scores) / len(scores)
    print(f"{label}: " + " / ".join(f"{s:.2f}" for s in scores)
          + f"  mean {mean:.2f}", flush=True)
    return mean


def run_baseline():
    """Persistence (house) baseline on the same windows."""
    for d, train, test in windows():
        last_chart = {g["universe_id"]: g["rank"]
                      for g in train[-1]["up_and_coming"]}
        print(f"baseline {d}: "
              f"{score_forecast(m.persistence_forecast(last_chart), test):.2f}",
              flush=True)


if __name__ == "__main__":
    t0 = time.time()
    mode = sys.argv[1] if len(sys.argv) > 1 else "current"
    if mode == "current":
        run_baseline()
        run_variant("current config "
                    f"(RHO={m.RHO} U_MIN={m.U_MIN} BLEND={m.BLEND})")
    elif mode == "rho":
        for rho in (0.85, 0.92, 0.98, 1.00):
            run_variant(f"RHO={rho}", {"RHO": rho})
    elif mode == "umin":
        for u in (0.18, 0.25, 0.32, 0.40):
            run_variant(f"U_MIN={u}", {"U_MIN": u})
    elif mode == "blend":
        for b in (0.05, 0.10, 0.20):
            run_variant(f"BLEND={b}", {"BLEND": b})
    else:
        print(f"unknown mode {mode!r}: current | rho | umin | blend",
              file=sys.stderr)
        sys.exit(2)
    print(f"elapsed {time.time() - t0:.1f}s", flush=True)
