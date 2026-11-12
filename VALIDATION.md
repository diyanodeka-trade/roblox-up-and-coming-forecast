# Validation results — Roblox Up-and-Coming forecaster (`main.py`)

## Headline

| Metric | Value |
|---|---|
| **Practice log score** | **−32.06** (typical p 0.0405, top-10 hits 6.4/10, agreement 54.6) |
| House persistence baseline, same window | −43.51 (typical p 0.0129, hits 6.4, agreement 53.5) |
| Oracle ceiling (true time-averaged marginals; uses the answers) | −13.18 (typical p 0.268, hits 8.3) |
| Simple spread-persistence forecasts | −38.2 to −41.9 |
| First Monte Carlo model (v1, uniform noise) | −44.46 |
| Page's "best baseline" | −37.2 nats |

The entry beats the house baseline by **+11.5 nats on the practice window**
and must beat the best house entry (baseline or house model) to win any prize.
It does not reach the oracle ceiling — the chart is genuinely noisy
(R² ≈ 0.08 for rank-change prediction) — but it is far ahead of persistence.

## Practice window detail

Practice data: archive's 34 reads 2026-10-30T07:36:30Z to 2026-11-07T20:53:19Z;
window 2026-11-07T23:00:00Z to 2026-11-10T23:00:00Z; 10 answer reads.
Output: `work/practice_out/forecast.json` (5,694 bytes; 97 probability rows,
max 14 per place; place sums 0.57–0.70, so 0.30–0.43 left unnamed at each
place; top10 = [10771743491, 10769671316, 10770575733, 10773425091,
10771928551, 10769941703, 10772217708, 10771421858, 10771881861,
10772879271]).

Per-read log scores (10 reads): −21.91, −32.41, −29.22, −28.69, −28.69,
−32.05, −33.88, −35.33, −37.90, −40.51. Scores decay over the window — the
forecast is most accurate near the close and the chart moves away from it,
as expected.

## Backtest (three earlier 72 h windows of the same timeline)

| Window | Train / test | Model | House baseline |
|---|---|---|---|
| A | reads 1–14 / 15–24 | **−35.99** | −42.85 |
| B (new-game heavy: 18/100 top-10 slots are games unseen in training) | reads 1–24 / 25–34 | **−43.75** | −56.90 |
| C (practice) | reads 1–34 / 35–44 | **−32.08** | −43.51 |
| **Mean** | | **−37.27** | **−47.75** |

The model beats the baseline in all three windows (mean margin +10.5 nats).
Parameters were selected on the mean of these three windows, not on the
practice window alone, to avoid overfitting to one window.

## What the tuning found (and rejected)

- **Calibration (work/calib.py, 3,751 rows):** dRank/dt ~ +0.118 (drift down)
  − 0.154·last velocity − 10.3·(demeaned growth), R² = 0.080. Residual noise
  std by rank: 1–3: 0.18, 4–10: 0.41, 11–25: 0.74, 26–50: 1.26, 51+: 1.41
  ranks/hour. This is why the v1 model (single σ = 2.0 for all games) failed:
  it diffused the stable top games far too much.
- Growth window 12 h beats 36 h (catches playing explosions like Sweep The
  Moon's 18,092 → 45,252 in the last 4.4 h before the close). Growth
  coefficient 5.0 beats 10.3 / 15 / 20 (long-horizon shrinkage).
- Rank-dependent noise (0.25, 0.7, 1.5, 3.2, 3.6) beats uniform and both
  smaller/larger profiles.
- **Unnamed mass is the big lever:** leaving ≥ 0.30 of each place unnamed
  (u_min = 0.30) beats 0.20 / 0.25 / 0.35 / 0.40 and beats raising the phantom
  rate alone. Brand-new games take 1–18% of top-10 slots in the backtests,
  and the log score punishes a near-zero probability on them far more than it
  rewards a slightly larger probability on an incumbent.
- Rejected (hurt the score): mean reversion toward the close rank (0.01–0.04),
  last-interval growth weight (0.3–1.0), velocity coefficient 0 / 0.35
  (indifferent), pushdown 0 (slightly worse than 0.25).

## Scorer cross-check

- `work/score.py` implements the scoring rule exactly as specified in
  RULES.txt (named p, else unnamed share split equally over the chart's games
  not named at that place; floor 0.0001; mean over reads).
- It reproduces the house baseline's published practice score **exactly:
  −43.512039**.
- The rules were also verified against the kit's canonical scorer source
  (`roblox-up-and-coming-forecast-01-kit/harness-src/grader/forecast/ranked.ts`,
  `placeProbability` / `orderLogScore`): same unnamed-share denominator,
  same floor, and the note that the score is proper for the **place marginals**,
  not the joint — which is why the program outputs calibrated per-place
  marginals.

## Format, determinism, runtime

- Output format verified on both the practice input and a larger final-like
  input (44-read history, 72 h window): exactly the keys `probabilities` and
  `top10`; 10 distinct top-10 ids; ≤ 100 rows per place; every place's
  probabilities sum to ≤ 1; all p in [0, 1]; all universe_ids integers; file
  ≤ 1,048,576 bytes (5,694 and 7,002 bytes in the two tests).
- **Determinism:** two runs on the practice input produce byte-identical
  `forecast.json` (fixed seed, no time/network dependence).
- **Runtime:** ~40–66 s on the practice input (1,500 sims), ~43 s on the
  44-read final-like input — well within the 300 s limit. Standard library
  only; no network access; reads the window from `task.json`.
- Final-like run output: `work/final_like_out/forecast.json` (120 rows, place
  sums 0.48–0.70). Note the final history will be larger still (45 archive
  reads + hourly house-recorder reads); runtime scales with the pool size
  (capped at 200 games) and the number of simulation hours, and the 300 s
  budget has ~4× headroom at the tested sizes.

## Known limits

- A game the program has never seen cannot be named; only the unnamed share
  covers it. In the practice window three of the top-10 games were entirely
  absent from the history (Do Not Stop., Bloody Ragdoll Physics, Build a
  Bridge) — the 0.30 unnamed floor is the mitigation.
- Per-read scores decay across the 72 h window; the model cannot foresee
  which specific new game will rocket.
- The backtests are three windows of one 12-day timeline; the final window
  (Nov 13–16) may behave differently, especially if a new-game burst occurs
  (window B shows the model still beats the baseline by a wide margin then).
