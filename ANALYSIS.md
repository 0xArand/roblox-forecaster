# Roblox Up-and-Coming forecast: data analysis

History: 34 reads, 2026-10-30 07:36Z to 2026-11-07 20:53Z, all from the
kenny-dhub public archive (4-11 h apart, median 6.2 h). 207 distinct games
ever on the chart; ~92-99 games per read. No `details` in any dev read
(archive has no votes/genres/details); the final history (house recorder,
hourly) will have them.

## What drives the chart

- **Playing counts do NOT drive rank.** corr(dlog(playing), dRank) = -0.018.
  Rank 8 had 108k playing while rank 2 had 18k. The sort is Roblox's
  internal "user growth", not visible in playing level or its change.
  => Model rank dynamics directly; ignore playing.
- **Rank velocity is persistent.** corr(v over one read gap, v over the
  next) = 0.223 overall, 0.274 for top-30 games. A climbing game keeps
  climbing; a sliding game keeps sliding. => AR(1) velocity state.
- **Lifecycle shape.** #1 games show it clearly: fast climb from rank
  50-90 to #1 in ~10 reads, plateau at the top ~7-10 reads, then a slow
  slide down over ~20+ reads. 7 distinct #1 games in 8 days; 39 distinct
  games ever in the top 10.
- **Top-10 dwell:** median 4 reads (~25 h), long tail to 27 reads.
- **Top-10 churn per read pair:** overlap ~8.7/10; ~1.3 new games per read.
  Over a 72 h window only 53-78% of top-10 slots are held by games that
  were top-10 at the window start; 19-27% come from ranks 11-30, 5-12%
  from 61+, 2-14% from games not on the chart at all.
- **Per-hour rank volatility (E[dRank^2] per read / mean dt):**
  ranks 1-10 sd ~0.95/h, 11-30 ~2.17/h, 31-60 ~3.32/h, 61+ ~3.92/h.
  Mean drift +0.09 to +0.15 ranks/h for ranks 1-60 (slow slide down);
  61+ survivors climb (-0.11/h, a selection effect: the worst drop out).
- **Dropout (leaves chart) per hour:** 1-10: 0.10%, 11-30: 0.22%,
  31-60: 0.24%, 61+: 1.84%. Tail turns over fast; bulk refresh events
  (15-20 tail games replaced at once) happen ~3x in 8 days, leavers
  almost never return.
- **New games enter at the bottom** (median entry rank 87; 1 of 115
  entered top 10 directly) but climb fast: 39 of 207 games reached the
  top 10, median 39.5 h after first sight, 16 within 24 h.

## Model

Monte Carlo over the chart's latent rank-scores, 72 hourly steps, fixed
seed: per-game AR(1) velocity (rho ~0.85) + rank-dependent noise +
drift + bucket dropout + new-game entry (empirical entry-rank and
first-day velocity pools) + 28-day age-out from `details.created` when
present. Tally P(game at place k) averaged over all 72 hours (the score
is the mean over the window's hourly reads). Blend with a diffuse prior,
leave an unnamed share per place (covers brand-new games), name a game
at a place only when its modelled p beats the unnamed per-game value.

## Backtest results (own harness, cutoffs Nov 3 / Nov 4 / Nov 5, 10 reads each)

House baseline (persistence): -52.71 / -50.27 / -56.91, mean -53.30.
(Practice-window baseline reported by the house: -43.512039.)

| variant | cutoff Nov 3 | cutoff Nov 4 | cutoff Nov 5 | mean |
|---|---|---|---|---|
| v1 Monte Carlo (rho .85, sigV .30, blend .20, U>=.05) | -37.63 | -38.69 | -45.98 | -40.77 |
| RHO 0.92 | -37.64 | -38.20 | -45.39 | -40.41 |
| U_MIN 0.12 | -36.68 | -37.65 | -43.42 | -39.25 |
| U_MIN 0.18 + RHO 0.92 + BLEND 0.10 | -36.49 | -36.85 | -41.88 | -38.41 |
| **FINAL: U_MIN 0.25 + RHO 0.92 + BLEND 0.10** | **-36.63** | **-36.95** | **-41.35** | **-38.31** |
| variant B: empirical recency-weighted place frequencies (no simulation) | -45.66 | -46.99 | -56.08 | -49.57 |

Final beats the house baseline by +14.99 on the same windows (baseline
mean -53.30; practice-window baseline reported by the house: -43.512039).
N_PATHS 3000 scores the same as 1500 (-38.307 vs -38.310), so 1500 stays.
Full-history run: ~20 s, 19,228-byte forecast, two runs byte-identical.
Edge cases verified: 1-read history falls back to the persistence
forecast, 2-read history runs the simulation; both emit valid output.
