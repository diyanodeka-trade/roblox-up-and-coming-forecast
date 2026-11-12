#!/usr/bin/env python3
"""Roblox Up-and-Coming top-10 forecaster (make.fun bounty).

Monte Carlo joint latent-score simulator, calibrated on the chart's own history.

Model
-----
Each game has a latent score x (higher = better rank); rank = order of x.
Per hour, in score units (positive = climbing):
    drift = momentum + growth_drift - pushdown
    noise = rank-dependent Gaussian (top ranks move far less than bottom ranks)
    occasional jump; new games enter as phantoms at the bottom, a few "hot"
    and rocketing up (that is how brand-new games reach #1 in this chart).

Calibration (OLS of rank change per hour on the history, R2 ~ 0.08):
    dRank/dt ~ +0.118 (drift down) - 0.154 * last-interval velocity
             - 10.3 * (24h-ish log playing growth, demeaned)
    residual noise std by rank: 1-3: 0.18, 4-10: 0.41, 11-25: 0.74,
    26-50: 1.26, 51+: 1.41 ranks/hour.  The drifts fade (growth ~12h half-life,
    momentum ~8h); the growth coefficient is shrunk to 5.0 for long horizons.

Forecast: per-place marginals averaged over the scored window, named in
decreasing order with at least 0.30 of each place left unnamed (insurance
against brand-new games, which take ~1-18% of top-10 slots in backtests).

Deterministic: all randomness from a fixed-seed random.Random.  Standard
library only, no network.  Reads $MAKEFUN_INPUT_DIR (default /input):
history.ndjson + task.json.  Writes $MAKEFUN_OUTPUT_DIR/forecast.json
(default /output).  The scored window is read from task.json, never hardcoded.
"""

import json
import math
import os
import random
import sys
from datetime import datetime

# ---------------------------------------------------------------- parameters
PARAMS = {
    "sigma": (0.25, 0.7, 1.5, 3.2, 3.6),   # hourly latent noise std by rank bucket
    "vel_coef": 0.154,                       # momentum carry-over per hour
    "growth_coef": 5.0,                      # demeaned log playing growth -> score/hour
    "pushdown": 0.25,                        # new entrants push incumbents down
    "mom_halflife": 8.0,                     # hours
    "growth_halflife": 12.0,                 # hours
    "jump_p": 0.01,
    "jump_scale": 2.5,
    "phantom_rate": 0.85,                    # new games entering per hour
    "hot_p": 0.08,                           # share of new games that rocket
    "hot_drift": 2.5,                        # score/hour for a hot new game
    "hot_halflife": 36.0,                    # hours
    "growth_window_h": 12.0,                 # log-linear playing fit window
    "u_min": 0.30,                           # min unnamed mass left at each place
}
N_SIMS = 1500
SEED = 20261112
MAX_POOL = 200
CHART_SIZE = 97          # games on a typical Up-and-Coming read (unnamed denominator)
MAX_ROWS_PER_PLACE = 100


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_history(input_dir):
    recs = []
    with open(os.path.join(input_dir, "history.ndjson")) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
    recs.sort(key=lambda r: r.get("at", ""))
    with open(os.path.join(input_dir, "task.json")) as f:
        task = json.load(f)
    return recs, task


def extract_features(recs, t0):
    """Per-game features at the close: last rank, last-interval velocity,
    log playing growth over the last growth_window_h (demeaned), age."""
    traj = {}
    details_created = {}
    for r in recs:
        t = parse_ts(r["at"])
        for g in r.get("up_and_coming") or []:
            uid = g["universe_id"]
            traj.setdefault(uid, []).append(
                (t, g["rank"], g.get("playing"), g.get("name")))
        det = r.get("details")
        if det:
            for uid_s, d in det.items():
                try:
                    uid = int(uid_s)
                except (TypeError, ValueError):
                    continue
                if d and d.get("created"):
                    details_created.setdefault(uid, d["created"])
    feats = {}
    all_growth = []
    for uid, lst in traj.items():
        lst.sort(key=lambda x: x[0])
        last_t, last_rank, last_playing, last_name = lst[-1]
        # velocity: last interval only, shrunk and capped
        vel = 0.0
        if len(lst) >= 2:
            (t1, r1, _, _), (t2, r2, _, _) = lst[-2], lst[-1]
            dt = (t2 - t1).total_seconds() / 3600.0
            if dt > 0:
                vel = -(r2 - r1) / dt
        vel = max(-1.5, min(1.5, vel)) * 0.7
        # growth: log-linear fit of playing over the last window
        growth = 0.0
        gw = PARAMS["growth_window_h"]
        pl_pts = [(t, pl) for (t, rk, pl, nm) in lst
                  if pl and pl > 0 and (t0 - t).total_seconds() <= gw * 3600]
        if len(pl_pts) >= 3:
            ts = [(t - pl_pts[0][0]).total_seconds() / 3600.0 for (t, pl) in pl_pts]
            ls = [math.log(pl) for (t, pl) in pl_pts]
            n = len(ts)
            mt = sum(ts) / n
            ml = sum(ls) / n
            den = sum((x - mt) ** 2 for x in ts)
            if den > 0:
                growth = sum((x - mt) * (y - ml) for x, y in zip(ts, ls)) / den
                growth *= len(pl_pts) / (len(pl_pts) + 2.0)
        growth = max(-0.1, min(0.1, growth))
        all_growth.append(growth)
        age_days = None
        if uid in details_created:
            try:
                age_days = (t0 - parse_ts(details_created[uid])).total_seconds() / 86400.0
            except Exception:
                age_days = None
        feats[uid] = {"last_rank": last_rank, "last_t": last_t,
                      "playing": last_playing, "vel": vel, "growth": growth,
                      "age_days": age_days, "name": last_name, "n_obs": len(lst)}
    all_growth.sort()
    med_growth = all_growth[len(all_growth) // 2] if all_growth else 0.0
    for f in feats.values():
        f["growth_dm"] = f["growth"] - med_growth
    return feats


def build_pool(recs, feats, t0):
    """Games on the close chart first, then recently-seen off-chart games."""
    close = recs[-1].get("up_and_coming") or []
    close_uids = [g["universe_id"] for g in sorted(close, key=lambda g: g["rank"])]
    close_set = set(close_uids)
    pool = []
    for uid in close_uids:
        f = feats.get(uid, {})
        pool.append({"uid": uid, "rank": f.get("last_rank"), "vel": f.get("vel", 0.0),
                     "growth_dm": f.get("growth_dm", 0.0), "age": f.get("age_days"),
                     "last_t": f.get("last_t"), "on_chart": True})
    off = []
    for uid, f in feats.items():
        if uid in close_set:
            continue
        dt_days = (t0 - f["last_t"]).total_seconds() / 86400.0
        if dt_days <= 7:
            off.append((dt_days, f["last_rank"], uid))
    off.sort(key=lambda x: (x[0], x[1]))
    for dt_days, last_rank, uid in off[: max(0, MAX_POOL - len(pool))]:
        f = feats[uid]
        pool.append({"uid": uid, "rank": None, "vel": f.get("vel", 0.0),
                     "growth_dm": f.get("growth_dm", 0.0), "age": f.get("age_days"),
                     "last_t": f.get("last_t"), "on_chart": False,
                     "days_off": dt_days, "last_rank": last_rank})
    return pool


def sigma_for_rank(rank, sig):
    if rank <= 3:
        return sig[0]
    if rank <= 10:
        return sig[1]
    if rank <= 25:
        return sig[2]
    if rank <= 50:
        return sig[3]
    return sig[4]


def simulate(recs, task, n_sims, seed, start_hour, n_record_hours):
    """Monte Carlo over the scored window.  Returns per-place marginals
    (list of dict uid -> probability) and phantom (new-game) mass per place."""
    t0 = parse_ts(recs[-1]["at"])
    feats = extract_features(recs, t0)
    pool = build_pool(recs, feats, t0)
    rng = random.Random(seed)
    places = task.get("places", 10)
    P = PARAMS
    sig = P["sigma"]
    mom_decay = 0.5 ** (1.0 / P["mom_halflife"])
    growth_decay = 0.5 ** (1.0 / P["growth_halflife"])
    hot_decay = 0.5 ** (1.0 / P["hot_halflife"])
    total_hours = start_hour + n_record_hours - 1
    counts = [dict() for _ in range(places)]
    phantom_counts = [0] * places
    n0 = len(pool)
    total_samples = n_sims * n_record_hours
    for _ in range(n_sims):
        x = []
        mom = []
        gd = []
        age = []
        is_phantom = []
        for p in pool:
            if p["on_chart"]:
                x.append(-float(p["rank"]))
            else:
                x.append(-(110.0 + 10.0 * p.get("days_off", 1.0)
                           + 0.1 * (p.get("last_rank") or 50)))
            mom.append(P["vel_coef"] * p["vel"])
            gd.append(P["growth_coef"] * p["growth_dm"])
            age.append(p["age"])
            is_phantom.append(False)
        for h in range(1, total_hours + 1):
            # new games enter as phantoms at the bottom
            n_new = 0
            acc = P["phantom_rate"]
            while acc >= 1.0:
                n_new += 1
                acc -= 1.0
            if rng.random() < acc:
                n_new += 1
            for _ in range(n_new):
                hot = rng.random() < P["hot_p"]
                r = rng.random()
                if r < 0.85:
                    er = 51.0 + rng.random() * 49.0
                elif r < 0.97:
                    er = 26.0 + rng.random() * 25.0
                else:
                    er = 6.0 + rng.random() * 20.0
                x.append(-er)
                mom.append(P["hot_drift"] if hot else 0.0)
                gd.append(0.0)
                age.append(None)
                is_phantom.append(True)
            n = len(x)
            order = sorted(range(n), key=lambda i: x[i], reverse=True)
            rank_of = [0] * n
            for pos, idx in enumerate(order):
                rank_of[idx] = pos + 1
            for i in range(n):
                if age[i] is not None and age[i] + h / 24.0 >= 28.0:
                    x[i] = -1e9
                    continue
                s = sigma_for_rank(rank_of[i], sig)
                e = rng.gauss(0.0, s)
                if rng.random() < P["jump_p"]:
                    e = rng.gauss(0.0, s * P["jump_scale"])
                if is_phantom[i]:
                    x[i] += mom[i] + gd[i] - P["pushdown"] + e
                    mom[i] *= hot_decay
                else:
                    x[i] += mom[i] + gd[i] - P["pushdown"] + e
                    mom[i] *= mom_decay
                    gd[i] *= growth_decay
            if h < start_hour:
                continue
            order = sorted(range(n), key=lambda i: x[i], reverse=True)
            for k in range(places):
                idx = order[k]
                if is_phantom[idx]:
                    phantom_counts[k] += 1
                elif idx < n0:
                    uid = pool[idx]["uid"]
                    d = counts[k]
                    d[uid] = d.get(uid, 0) + 1
    marginals = [{uid: c / total_samples for uid, c in counts[k].items()}
                 for k in range(places)]
    phantom_p = [c / total_samples for c in phantom_counts]
    return marginals, phantom_p, pool


def build_forecast(marginals, phantom_p, pool, task):
    places = task.get("places", 10)
    u_min = PARAMS["u_min"]
    probabilities = []
    for k in range(places):
        marg = marginals[k]
        items = sorted(marg.items(), key=lambda kv: -kv[1])
        named = []
        s = 0.0
        for uid, p in items:
            if len(named) >= MAX_ROWS_PER_PLACE:
                break
            n_named = len(named)
            unnamed = (1.0 - s) / max(CHART_SIZE - n_named, 1)
            if p > unnamed and p > 0.001 and (1.0 - s - p) >= u_min - 1e-12:
                named.append((uid, p))
                s += p
            else:
                break
        for uid, p in named:
            probabilities.append({"universe_id": int(uid), "place": k + 1,
                                  "p": round(p, 6)})
    # top10 by greedy max assignment on the marginals
    cand = {}
    for k in range(places):
        for uid, p in marginals[k].items():
            cand.setdefault(uid, [0.0] * places)
            cand[uid][k] = p
    used = set()
    top10 = []
    for k in range(places):
        best, bestp = None, -1.0
        for uid, arr in cand.items():
            if uid in used:
                continue
            if arr[k] > bestp:
                bestp, best = arr[k], uid
        if best is not None:
            top10.append(int(best))
            used.add(best)
    if len(top10) < places:
        for uid, arr in sorted(cand.items(), key=lambda kv: -max(kv[1])):
            if uid not in used:
                top10.append(int(uid))
                used.add(uid)
            if len(top10) >= places:
                break
    return {"probabilities": probabilities, "top10": top10[:places]}


def window_hours(recs, task):
    """(start_hour, n_record_hours) from task.json's window; defaults 1, 72."""
    try:
        w = task["window"]
        t_from = parse_ts(w["from"])
        t_until = parse_ts(w["until"])
        t_last = parse_ts(recs[-1]["at"])
        start_hour = max(1, int(round((t_from - t_last).total_seconds() / 3600.0)))
        n_hours = int(round((t_until - t_from).total_seconds() / 3600.0))
        if n_hours <= 0:
            n_hours = 72
        return start_hour, n_hours
    except Exception:
        return 1, 72


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    recs, task = load_history(input_dir)
    if not recs:
        # degenerate fallback: empty forecast is still a valid forecast
        fc = {"probabilities": [], "top10": []}
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "forecast.json"), "w") as f:
            f.write(json.dumps(fc) + "\n")
        return 0
    start_hour, n_hours = window_hours(recs, task)
    marginals, phantom_p, pool = simulate(recs, task, N_SIMS, SEED,
                                          start_hour, n_hours)
    fc = build_forecast(marginals, phantom_p, pool, task)
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "forecast.json")
    with open(out_path, "w") as f:
        f.write(json.dumps(fc) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
