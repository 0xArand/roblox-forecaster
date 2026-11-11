#!/usr/bin/env python3
"""Roblox Up-and-Coming top-10 forecaster for make.fun
roblox-up-and-coming-forecast-01 (program/v1).

Reads hourly snapshots of the chart from $MAKEFUN_INPUT_DIR/history.ndjson
(default /input) and writes one forecast to
$MAKEFUN_OUTPUT_DIR/forecast.json (default /output): for each of the top 10
places, a probability for each game named being at that place, plus the
best-guess top 10 in order. The forecast is scored against every hourly
read of the 72 hours after the history ends, so it is the average over
that window of the hourly place distribution, not a single guessed order.

Model (see ANALYSIS.md for the data behind it):
  * Playing counts do not drive rank (corr ~ 0), so rank dynamics are
    modelled directly.
  * Each game carries a latent rank-score and a rank velocity. Velocity
    persists (corr ~ 0.25 across read gaps), so it is an AR(1) state
    seeded from a recency-weighted fit of the game's recent ranks.
  * Per-hour: velocity drifts slowly down-chart, is perturbed, the score
    moves, games drop off the chart at a rank-dependent rate and are
    replaced by new games drawn from the empirical entry-rank and
    first-day-velocity pools; games whose `details.created` ages past
    28 days leave the chart (the chart only lists games published in
    the last 28 days).
  * Monte Carlo (fixed seed) over 72 hourly steps; the tallied
    frequencies are the forecast, blended with a diffuse prior (weight
    0.10) and with an unnamed share per place of at least 0.25 that
    covers games not yet on the chart. The unnamed share is the single
    biggest calibration lever: the chart turns over so fast that
    overconfident named probabilities are punished far more than the
    dilution costs. Parameters were re-tuned in a fresh session on three
    72 h backtests (cutoffs 2026-11-03/04/05, 10/11/11 reads, scoring
    exactly per RULES.txt): this configuration (rho 0.98) scores -39.61
    mean against the house baseline's -51.78 on the same windows; rho
    0.92 scored -39.95, rho 0.85 -40.13, rho 1.00 -39.73, U_MIN 0.32
    -39.91, BLEND 0.05/0.20 -39.96/-40.03. A drift mean-reversion variant
    (velocity mean-reverting to DRIFT instead of DRIFT/(1-RHO)) scored
    -40.08 and was rejected.

Standard library only, no network, no wall clock, fixed seed: two runs
on the same input produce byte-identical output.
"""

import json
import math
import os
import random
from datetime import datetime, timedelta, timezone

SEED = 20261113
HOURS = 72
N_PATHS = 1500
RHO = 0.98            # velocity AR(1) coefficient per hour
SIGMA_V = 0.30        # velocity innovation sd (ranks/hour)
DRIFT = 0.08          # slow slide down the chart (ranks/hour)
BLEND = 0.10          # weight of the diffuse prior
U_MIN = 0.25          # minimum unnamed share per place
P_CAP = 0.80          # maximum probability on one game at one place
NAME_MIN_Q = 0.002    # only name a game at a place above this blended mass

# Per-hour rank volatility (sd of the direct score noise) by rank bucket,
# and per-hour dropout (leaves the chart) by rank bucket. Measured from
# the archive's consecutive reads (E[dRank^2] per read / mean gap).
SIGMA_X = ((1, 0.35), (11, 0.80), (31, 1.20), (61, 1.50))
DROPOUT = ((1, 0.0010), (11, 0.0022), (31, 0.0024), (61, 0.0184))


def _bucket(table, rank):
    v = table[0][1]
    for lo, val in table:
        if rank >= lo:
            v = val
    return v


def _parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_history(input_dir):
    with open(os.path.join(input_dir, "task.json"), "r", encoding="utf-8") as f:
        task = json.load(f)
    reads = []
    with open(os.path.join(input_dir, "history.ndjson"), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                reads.append(json.loads(line))
    reads.sort(key=lambda r: r["at"])
    return task, reads


def estimate_velocities(reads, t0):
    """Per-game rank velocity (ranks/hour) from a recency-weighted fit of
    its ranks over the last 72 h, shrunk toward DRIFT when data is thin."""
    window_start = t0 - timedelta(hours=72)
    obs = {}
    for r in reads:
        t = _parse_time(r["at"])
        for g in r["up_and_coming"]:
            u = g["universe_id"]
            if t >= window_start:
                obs.setdefault(u, []).append((t, g["rank"]))
    vel = {}
    for u, points in obs.items():
        if len(points) >= 2:
            span = (points[-1][0] - points[0][0]).total_seconds() / 3600.0
            if span >= 3.0:
                ws, swx, swy, swxx, swxy = 0.0, 0.0, 0.0, 0.0, 0.0
                for t, rank in points:
                    age = (t0 - t).total_seconds() / 3600.0
                    w = math.exp(-age / 24.0)
                    x = (t - t0).total_seconds() / 3600.0
                    ws += w
                    swx += w * x
                    swy += w * rank
                    swxx += w * x * x
                    swxy += w * x * rank
                den = ws * swxx - swx * swx
                if den > 1e-9:
                    b = (ws * swxy - swx * swy) / den
                    shrink = span / (span + 24.0)
                    b = DRIFT + (b - DRIFT) * shrink
                    vel[u] = max(-4.0, min(4.0, b))
                    continue
        vel[u] = DRIFT
    return vel


def estimate_pools(reads):
    """Empirical entry-rank pool and first-day velocity pool for new games."""
    first_time = {}
    first_day_vel = []
    entry_ranks = []
    seen = set()
    for r in reads:
        t = _parse_time(r["at"])
        for g in r["up_and_coming"]:
            u = g["universe_id"]
            if u not in seen:
                seen.add(u)
                first_time[u] = t
                if len(reads) > 1 and r is not reads[0]:
                    entry_ranks.append(g["rank"])
    # first-day velocity: rank change over the first 24 h on the chart
    for u, t_first in first_time.items():
        pts = []
        for r in reads:
            t = _parse_time(r["at"])
            if t < t_first:
                continue
            if (t - t_first).total_seconds() > 24 * 3600:
                break
            for g in r["up_and_coming"]:
                if g["universe_id"] == u:
                    pts.append((t, g["rank"]))
        if len(pts) >= 2:
            dt = (pts[-1][0] - pts[0][0]).total_seconds() / 3600.0
            if dt >= 3.0:
                first_day_vel.append((pts[-1][1] - pts[0][1]) / dt)
    if not entry_ranks:
        entry_ranks = [60 + i for i in range(39)]
    if not first_day_vel:
        first_day_vel = [0.0]
    return entry_ranks, first_day_vel


def age_out_hours(reads, t0):
    """For games with details.created, the hour (0..72) they turn 28 days
    old and leave the chart; None when details are absent."""
    created = {}
    for r in reads:
        det = r.get("details")
        if not det:
            continue
        # details may be a list of game dicts, or a dict keyed by
        # universe id: the practice kit's details is always null, so the
        # final history's exact shape is unverified. Handle both, so a
        # dict-shaped details does not silently disable age-out.
        if isinstance(det, dict):
            entries = []
            for key, item in det.items():
                if not isinstance(item, dict):
                    continue
                uid = item.get("universe_id")
                if uid is None:
                    try:
                        uid = int(key)
                    except (TypeError, ValueError):
                        continue
                entries.append((uid, item.get("created")))
        else:
            entries = [
                (item.get("universe_id"), item.get("created"))
                for item in det
                if isinstance(item, dict)
            ]
        for uid, c in entries:
            if uid is not None and c:
                created[uid] = _parse_time(c)
    out = {}
    for u, c in created.items():
        age_h = (t0 - c).total_seconds() / 3600.0
        left = 28 * 24 - age_h
        if 0.0 <= left < HOURS:
            out[u] = int(math.floor(left))
    return out


def simulate(last_chart, vel, entry_ranks, new_vel, exit_hour):
    """Monte Carlo the chart 72 hourly steps. Returns per-place tallies:
    counts[place][uid], unnamed[place], rank_sum[uid], rank_n[uid]."""
    rng = random.Random(SEED)
    gauss = rng.gauss
    rnd = rng.random
    choice = rng.choice
    n = len(last_chart)
    counts = {k: {} for k in range(1, 11)}
    unnamed = {k: 0 for k in range(1, 11)}
    rank_sum = {}
    rank_n = {}
    for _ in range(N_PATHS):
        uids = list(last_chart)
        s = [float(last_chart[u]) for u in uids]
        v = [vel.get(u, DRIFT) for u in uids]
        ex = [exit_hour.get(u) for u in uids]
        for h in range(HOURS):
            # update velocities and scores using the previous hour's bucket
            order = sorted(range(n), key=lambda i: s[i])
            rank_of = [0] * n
            for pos, i in enumerate(order):
                rank_of[i] = pos + 1
            for i in range(n):
                rk = rank_of[i]
                vi = RHO * v[i] + DRIFT + gauss(0.0, SIGMA_V)
                v[i] = vi
                s[i] += vi + gauss(0.0, _bucket(SIGMA_X, rk))
            # dropouts / age-outs, replaced by new (anonymous) games
            for i in range(n):
                rk = rank_of[i]
                drop = ex[i] is not None and h >= ex[i]
                if not drop and rnd() < _bucket(DROPOUT, rk):
                    drop = True
                if drop:
                    uids[i] = None
                    s[i] = float(choice(entry_ranks)) + gauss(0.0, 2.0)
                    v[i] = choice(new_vel)
                    ex[i] = None
            order = sorted(range(n), key=lambda i: s[i])
            for pos, i in enumerate(order):
                if pos < 10:
                    u = uids[i]
                    if u is None:
                        unnamed[pos + 1] += 1
                    else:
                        d = counts[pos + 1]
                        d[u] = d.get(u, 0) + 1
                u = uids[i]
                if u is not None:
                    rank_sum[u] = rank_sum.get(u, 0.0) + (pos + 1)
                    rank_n[u] = rank_n.get(u, 0) + 1
    total = N_PATHS * HOURS
    return counts, unnamed, rank_sum, rank_n, total


def build_forecast(last_chart, counts, unnamed, rank_sum, rank_n, total):
    places = 10
    # diffuse prior per place: broad kernel around the diagonal, over the
    # top 40 games by their rank at the close of history
    top40 = sorted(last_chart, key=lambda u: last_chart[u])[:40]
    prior = {}
    for k in range(1, places + 1):
        w = {}
        tot = 0.0
        for u in top40:
            d = (last_chart[u] - k) / 5.0
            wi = 1.0 / (1.0 + d * d)
            w[u] = wi
            tot += wi
        prior[k] = {u: wi / tot for u, wi in w.items()}
    probabilities = []
    for k in range(1, places + 1):
        freq = counts[k]
        f_named = sum(freq.values()) / total
        f_un = unnamed[k] / total
        q = {}
        for u, c in freq.items():
            base = c / total
            pr = prior[k].get(u, 0.0)
            q[u] = (1.0 - BLEND) * base + BLEND * pr * f_named
        for u, pr in prior[k].items():
            if u not in q and pr > 0.0:
                q[u] = BLEND * pr * f_named
        named = {u: v for u, v in q.items() if v >= NAME_MIN_Q}
        if not named:
            continue
        u_share = max(f_un, U_MIN)
        # mass not assigned to named games flows to the unnamed share
        rest = sum(v for u, v in q.items() if u not in named)
        u_share = max(u_share, rest)
        if u_share >= 0.98:
            continue
        ssum = sum(named.values())
        scale = (1.0 - u_share) / ssum if ssum > 0 else 0.0
        for u in sorted(named, key=lambda u: (-named[u], u)):
            p = named[u] * scale
            if p > P_CAP:
                p = P_CAP
            p = round(p, 6)
            if p > 0:
                probabilities.append(
                    {"universe_id": u, "place": k, "p": p}
                )
    probabilities.sort(key=lambda r: (r["place"], -r["p"], r["universe_id"]))
    # top 10 by expected rank over the simulation
    exp_rank = {
        u: rank_sum[u] / rank_n[u] for u in rank_sum if rank_n[u] > 0
    }
    top10 = sorted(exp_rank, key=lambda u: (exp_rank[u], u))[:places]
    for u in sorted(last_chart, key=lambda u: last_chart[u]):
        if len(top10) >= places:
            break
        if u not in top10:
            top10.append(u)
    return {"probabilities": probabilities, "top10": top10[:places]}


def persistence_forecast(last_chart):
    """Fallback when history is too thin: the house baseline shape."""
    chart = sorted(last_chart, key=lambda u: last_chart[u])
    probs = []
    for place in range(1, 11):
        if place > len(chart):
            break
        probs.append(
            {"universe_id": chart[place - 1], "place": place, "p": 0.5}
        )
        if place == 1:
            if len(chart) > 1:
                probs.append(
                    {"universe_id": chart[1], "place": place, "p": 0.3}
                )
        else:
            probs.append(
                {"universe_id": chart[place - 2], "place": place, "p": 0.15}
            )
            if place < len(chart):
                probs.append(
                    {"universe_id": chart[place], "place": place, "p": 0.15}
                )
    return {"probabilities": probs, "top10": chart[:10]}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    task, reads = load_history(input_dir)
    places = int(task.get("places", 10))
    out_name = task.get("output", "forecast.json")
    last = reads[-1]
    last_chart = {
        g["universe_id"]: g["rank"] for g in last["up_and_coming"]
    }
    if len(reads) < 2 or len(last_chart) < places:
        forecast = persistence_forecast(last_chart)
    else:
        t0 = _parse_time(last["at"])
        vel = estimate_velocities(reads, t0)
        entry_ranks, new_vel = estimate_pools(reads)
        exit_hour = age_out_hours(reads, t0)
        counts, unnamed, rank_sum, rank_n, total = simulate(
            last_chart, vel, entry_ranks, new_vel, exit_hour
        )
        forecast = build_forecast(
            last_chart, counts, unnamed, rank_sum, rank_n, total
        )
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, out_name), "w", encoding="utf-8") as f:
        f.write(json.dumps(forecast, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
