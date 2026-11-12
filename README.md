# Roblox Up-and-Coming Top-10 Forecaster — make.fun bounty entry

Entry program for the make.fun bounty
**"Predict Roblox's Up-and-Coming top 10"**
(https://make.fun/bounty/roblox-up-and-coming-forecast-01).
$500 USDC total, 20 paid places; a prize needs a log score strictly above the
best house entry's.

## How to run

```bash
MAKEFUN_INPUT_DIR=/input MAKEFUN_OUTPUT_DIR=/output python3 main.py
```

- `main.py` is the whole entry: **Python 3.13, standard library only, no
  network, deterministic** (fixed seed; two runs on the same input write
  byte-identical output).
- Reads `$MAKEFUN_INPUT_DIR` (default `/input`): `history.ndjson` (one JSON
  object per line, one per read of the Up-and-Coming chart, oldest first) and
  `task.json` (`history_until`, `window`, `places`).
- Writes `$MAKEFUN_OUTPUT_DIR/forecast.json` (default `/output`): exactly the
  keys `probabilities` (rows `{universe_id, place, p}`) and `top10` (10 distinct
  universe ids, in order). File is ~6 KB, far under the 1,048,576-byte limit.
- Runtime ~40–70 s, 1 CPU, well under the 300 s / 1024 MB limits.
- The scored window is **read from `task.json`, never hardcoded**.

## What the model does

A Monte Carlo joint latent-score simulation of the chart, calibrated on the
chart's own history (see `VALIDATION.md` for the numbers):

- Each game has a latent score (higher = better rank); rank = order of scores.
- Per hour a game's score moves by **drift + noise**:
  - drift = momentum + growth drift − pushdown. Momentum is the last
    interval's rank velocity, carried over weakly (coefficient 0.154) and
    fading fast (~8 h half-life). Growth drift is the demeaned log playing
    growth over the last 12 h (coefficient 5.0), fading with a ~12 h
    half-life. Pushdown (0.25/h) is the steady pressure from new entrants.
  - noise is **rank-dependent Gaussian**: top ranks barely move, bottom ranks
    churn (hourly std 0.25 / 0.7 / 1.5 / 3.2 / 3.6 for ranks 1–3 / 4–10 /
    11–25 / 26–50 / 51+). Occasional jumps (1% chance, 2.5× scale).
  - games age out at 28 days from their publish date (`details.created`).
- **New games ("phantoms")** enter at the bottom at ~0.85/hour; 8% are "hot"
  and climb fast (2.5 score units/hour) — this is how brand-new games rocket
  to #1 in this chart, and it is why the forecast must insure against them.
- The forecast is the **per-place marginal probability** of each game,
  averaged over the scored window. Games are named in decreasing marginal
  order, leaving **at least 0.30 of each place unnamed** — the unnamed share is
  spread over every game on the read's chart that is not named there, which is
  the only coverage for a game the program has never seen.

The scoring rule is proper for the per-place marginals, so the joint
structure of the simulation earns nothing directly — the simulation exists to
get the marginals (and the displacement of incumbents by new games) right.

## Files

| Path | What it is |
|---|---|
| `main.py` | The entry program (self-contained). |
| `README.md` | This file. |
| `VALIDATION.md` | Validation results (practice score, backtests, baseline comparison, determinism, runtime). |
| `work/` | Research scripts: scorer (`score.py`), model + tuning (`model.py`, `tune.py`, `sweep*.py`), calibration (`calib.py`), EDA (`explore*.py`), backtest (`backtest.py`, `baseline_bt.py`), and the practice/final-like validation outputs. |
| `data/data_practice_answer.json` | The 10 practice answer reads (Nov 7–10) used for scoring. |
| `roblox-up-and-coming-forecast-01-kit/` | The bounty kit (RULES.txt, competition.yaml, dev dataset, harness, starter baseline). |
| `archive-repo/` | Clone of the MIT-licensed archive github.com/Kenny-Dhub/roblox-snapshots (practice answers extracted from its git history). |
| `skill.md`, `comp.json`, `kit.tar.gz` | Bounty skill doc, competition metadata, kit archive. |

## Validation (headline)

- **Practice log score: −32.06** (typical p 0.041, top-10 hits 6.4/10,
  agreement 54.6). House persistence baseline on the same window: **−43.51**.
  Oracle ceiling (true time-averaged marginals, uses the answers): −13.18.
- Backtest on three earlier 72 h windows (train/test splits of the same
  timeline): −35.99 / −43.75 / −32.08, mean **−37.27**, vs the house baseline's
  −42.85 / −56.90 / −43.51, mean −47.75.
- Determinism: two runs on the practice input produce byte-identical
  `forecast.json`. Scorer cross-checked: it reproduces the house baseline's
  published practice score of exactly −43.512039, and the rules were verified
  against the kit's canonical scorer (`harness-src/grader/forecast/ranked.ts`).

Full numbers in `VALIDATION.md`.

## Notes for submission (not done here)

- This build is **build-and-validate only**: nothing has been pushed to
  GitHub and nothing has been submitted to make.fun.
- The entry repo must be a **public GitHub repo owned by the user's GitHub
  account, created after the competition opened**, with `main.py` at the root
  and an OSI-approved license, plus the AI coding-agent transcripts uploaded
  with each submission.
- Per the user's instruction (2026-11-12), do **not** use the Block Relics
  GitHub identity (`shuvoalrabit-rgb` / `blockrelicnft` org) for make.fun repos
  — the user wants their other profile `shuvoalrabit` (linking it first is a
  separate step; the account currently connected here is ALRABIT-TRADE, the
  Block Relics identity).
- Deadline: **2026-11-13 06:00 UTC** (12:00 Dhaka). Max 5 submissions/day,
  20 total; the last submission before the deadline is the final entry.
