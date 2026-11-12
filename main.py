import json
import os
import math
import random
from datetime import datetime, timezone, timedelta

def parse_iso(s):
    if not s: return None
    return datetime.fromisoformat(s.replace('Z', '+00:00'))

def solve_log_linear_slope(points):
    n = len(points)
    if n < 3: return 0
    sum_t = 0
    sum_y = 0
    sum_tt = 0
    sum_ty = 0
    for t, p in points:
        y = math.log(p)
        sum_t += t
        sum_y += y
        sum_tt += t * t
        sum_ty += t * y
    denom = (n * sum_tt - sum_t * sum_t)
    if abs(denom) < 1e-12: return 0
    b = (n * sum_ty - sum_t * sum_y) / denom
    return b

def main():
    input_dir = os.environ.get('MAKEFUN_INPUT_DIR', '/input')
    output_dir = os.environ.get('MAKEFUN_OUTPUT_DIR', '/output')
    history_path = os.path.join(input_dir, 'history.ndjson')
    task_path = os.path.join(input_dir, 'task.json')
    
    if not os.path.exists(history_path) or not os.path.exists(task_path):
        write_empty_forecast(output_dir)
        return

    try:
        with open(task_path, 'r') as f:
            task = json.load(f)
        window = task['window']
        win_from = parse_iso(window['from'])
        win_until = parse_iso(window['until'])
    except:
        write_empty_forecast(output_dir)
        return
    
    history = []
    if os.path.exists(history_path):
        with open(history_path, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        history.append(json.loads(line))
                    except:
                        continue
    
    if not history:
        write_empty_forecast(output_dir)
        return

    last_read = history[-1]
    close_time = parse_iso(last_read['at'])
    all_games = {} 
    
    for entry in history:
        t_str = entry.get('at')
        if not t_str: continue
        t = parse_iso(t_str)
        dt_hours = (close_time - t).total_seconds() / 3600.0
        for g in entry.get('up_and_coming') or []:
            uid = g['universe_id']
            if uid not in all_games:
                all_games[uid] = {
                    'playing_history': [],
                    'last_seen_at': t,
                    'last_rank': g['rank'],
                    'created_at': None
                }
            all_games[uid]['playing_history'].append(( -dt_hours, g['playing'] ))
            if t >= all_games[uid]['last_seen_at']:
                all_games[uid]['last_seen_at'] = t
                all_games[uid]['last_rank'] = g['rank']
            
        details = entry.get('details') or {}
        for uid_str, d in details.items():
            try:
                uid = int(uid_str)
                if d and d.get('created') and uid in all_games:
                    if not all_games[uid]['created_at']:
                        all_games[uid]['created_at'] = parse_iso(d['created'])
            except: continue

    close_chart = {g['universe_id']: g['rank'] for g in (last_read.get('up_and_coming') or [])}
    
    if len(history) >= 2:
        prev_read = history[-2]
        prev_time = parse_iso(prev_read['at'])
        dt_vel = (close_time - prev_time).total_seconds() / 3600.0
        if dt_vel <= 0: dt_vel = 1.0
        prev_chart = {g['universe_id']: g['rank'] for g in (prev_read.get('up_and_coming') or [])}
    else:
        dt_vel = 1.0
        prev_chart = {}

    for uid in close_chart:
        rank_curr = close_chart[uid]
        rank_prev = prev_chart.get(uid, 100) 
        vel = (rank_prev - rank_curr) / dt_vel
        vel *= 0.7
        vel = max(-1.5, min(1.5, vel))
        all_games[uid]['velocity'] = vel

    growth_values = []
    for uid, data in all_games.items():
        points = [(t, p) for t, p in data['playing_history'] if t >= -12 and p > 0]
        n = len(points)
        if n >= 3:
            slope = solve_log_linear_slope(points)
            shrunk_slope = slope * (n / (n + 2))
            capped_slope = max(-0.1, min(0.1, shrunk_slope))
            data['growth'] = capped_slope
            growth_values.append(capped_slope)
        else:
            data['growth'] = 0.0

    median_growth = 0
    if growth_values:
        growth_values.sort()
        mid = len(growth_values) // 2
        if len(growth_values) % 2 == 0:
            median_growth = (growth_values[mid-1] + growth_values[mid]) / 2
        else:
            median_growth = growth_values[mid]
            
    for uid, data in all_games.items():
        data['demeaned_growth'] = data['growth'] - median_growth

    pool = [] 
    for uid, rank in close_chart.items():
        data = all_games[uid]
        pool.append({
            'universe_id': uid,
            'score': float(-rank),
            'momentum': 0.154 * data.get('velocity', 0),
            'growth_drift': 5.0 * data.get('demeaned_growth', 0),
            'created_at': data['created_at'],
            'is_phantom': False
        })
        
    off_chart_candidates = []
    for uid, data in all_games.items():
        if uid in close_chart: continue
        days_off = (close_time - data['last_seen_at']).total_seconds() / 86400.0
        if days_off <= 7:
            score = -(110 + 10 * days_off + 0.1 * data['last_rank'])
            off_chart_candidates.append({
                'universe_id': uid,
                'score': score,
                'momentum': 0.0,
                'growth_drift': 5.0 * data.get('demeaned_growth', 0),
                'created_at': data['created_at'],
                'is_phantom': False
            })
            
    off_chart_candidates.sort(key=lambda x: x['score'], reverse=True)
    remaining_slots = 200 - len(pool)
    if remaining_slots > 0:
        pool.extend(off_chart_candidates[:remaining_slots])

    seed = 20261112
    rng = random.Random(seed)
    
    start_hour = round((win_from - close_time).total_seconds() / 3600.0)
    start_hour = max(1, start_hour)
    recorded_hours = round((win_until - win_from).total_seconds() / 3600.0)
    if recorded_hours <= 0: recorded_hours = 72
    
    total_sim_hours = start_hour + recorded_hours
    num_runs = 1500
    marginals = {p: {} for p in range(1, 11)}
    
    fade_mom = 0.5 ** (1/8)
    fade_growth = 0.5 ** (1/12)
    fade_hot = 0.5 ** (1/36)
    initial_pool_state = pool

    for run_idx in range(num_runs):
        current_pool = [dict(p) for p in initial_pool_state]
        for h in range(1, total_sim_hours):
            if rng.random() < 0.85:
                r = rng.random()
                if r < 0.03: entry_rank = rng.uniform(6, 26)
                elif r < 0.15: entry_rank = rng.uniform(26, 51)
                else: entry_rank = rng.uniform(51, 100)
                hot = rng.random() < 0.08
                current_pool.append({
                    'universe_id': -1, 
                    'score': float(-entry_rank),
                    'momentum': 2.5 if hot else 0.0,
                    'growth_drift': 0.0,
                    'created_at': None,
                    'is_phantom': True,
                    'hot': hot
                })
                
            current_pool.sort(key=lambda x: x['score'], reverse=True)
            for i, p in enumerate(current_pool):
                rank = i + 1
                if rank <= 3: std = 0.25
                elif rank <= 10: std = 0.7
                elif rank <= 25: std = 1.5
                elif rank <= 50: std = 3.2
                else: std = 3.6
                if rng.random() < 0.01: std *= 2.5
                noise = rng.gauss(0, std)
                drift = p['momentum'] + p['growth_drift'] - 0.25
                p['score'] += (drift + noise)
                if p['is_phantom'] and p.get('hot'): p['momentum'] *= fade_hot
                else: p['momentum'] *= fade_mom
                p['growth_drift'] *= fade_growth
                if p['created_at']:
                    age_days = (close_time - p['created_at']).total_seconds() / 86400.0 + h / 24.0
                    if age_days >= 28: p['score'] = -1e15
            
            if h >= start_hour:
                current_pool.sort(key=lambda x: x['score'], reverse=True)
                for rank_idx in range(10):
                    if rank_idx < len(current_pool):
                        game = current_pool[rank_idx]
                        if not game['is_phantom']:
                            uid = game['universe_id']
                            place = rank_idx + 1
                            marginals[place][uid] = marginals[place].get(uid, 0) + 1

    total_samples = num_runs * recorded_hours
    prob_rows = []
    for place in range(1, 11):
        games = sorted(marginals[place].items(), key=lambda x: x[1], reverse=True)
        sum_named = 0.0
        rows_named = 0
        for uid, count in games:
            p = count / total_samples
            threshold = (1.0 - sum_named) / (97 - rows_named) if (97 - rows_named) > 0 else 1.0
            if p > threshold and p > 0.001 and (1.0 - sum_named - p) >= 0.30:
                prob_rows.append({"universe_id": uid, "place": place, "p": round(p, 6)})
                sum_named += p
                rows_named += 1
                if rows_named >= 100: break

    top10 = []
    used = set()
    for place in range(1, 11):
        best_uid = None
        best_p = -1
        for uid, count in marginals[place].items():
            if uid not in used:
                if count > best_p:
                    best_p = count
                    best_uid = uid
        if best_uid is not None:
            top10.append(best_uid)
            used.add(best_uid)
            
    if len(top10) < 10:
        remaining = []
        all_uids = set()
        for p in range(1, 11):
            for uid in marginals[p]: all_uids.add(uid)
        for uid in all_uids:
            if uid not in used:
                max_m = max(marginals[p].get(uid, 0) for p in range(1, 11))
                remaining.append((uid, max_m))
        remaining.sort(key=lambda x: x[1], reverse=True)
        for uid, m in remaining:
            if len(top10) >= 10: break
            top10.append(uid); used.add(uid)
            
    if len(top10) < 10:
        for i in range(1, 11):
            if len(top10) >= 10: break
            if i not in used: top10.append(i); used.add(i)

    forecast = {"probabilities": prob_rows, "top10": top10}
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, 'forecast.json'), 'w') as f:
        json.dump(forecast, f)

def write_empty_forecast(output_dir):
    forecast = {"probabilities": [], "top10": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, 'forecast.json'), 'w') as f:
        json.dump(forecast, f)

if __name__ == '__main__':
    main()
