"""Fit the quarterback rate priors in `features/rates.py`.

Every rate the passing model consumes is weakly persistent, and all four were being
carried forward at full strength. Cam Ward's rookie 2.52% touchdown rate produced a
0.9-touchdown projection and a 98%-confident under; Matthew Stafford's 7.7% produced
2.8 a game. Neither is a read on this season -- both are last season repeated.

Run:  uv run python scripts/fit_qb_rates.py
"""

import glob, re, statistics as st
import duckdb

MIN_ATT = 200

def rates(path):
    return duckdb.connect().execute(f"""
        with p as (select * from read_parquet('{path}')
                   where season_type='REG' and passer_player_id is not null
                     and coalesce(two_point_attempt,0)=0)
        select passer_player_id pid, count(*) att,
               sum(coalesce(pass_touchdown,0))*1.0/count(*)                     td_rate,
               sum(coalesce(complete_pass,0))*1.0/count(*)                      comp_rate,
               sum(case when complete_pass=1 then yards_gained else 0 end)*1.0
                 / nullif(sum(coalesce(complete_pass,0)),0)                     ypc,
               count(distinct game_id)                                          g
        from p group by 1 having count(*) >= {MIN_ATT}
    """).fetchall()

paths = {int(re.search(r'(\d{4})', p).group(1)): p
         for p in sorted(glob.glob('data/raw/nflverse/pbp_*.parquet'))}
seasons = sorted(paths)
by = {y: {r[0]: r for r in rates(paths[y])} for y in seasons}

METRICS = [("pass TD rate", 2), ("completion rate", 3), ("yards per completion", 4),
           ("attempts per game", None)]

for label, idx in METRICS:
    obs = []
    for a, b in zip(seasons, seasons[1:]):
        for pid, row in by[a].items():
            nxt = by[b].get(pid)
            if not nxt:
                continue
            if idx is None:
                obs.append((row[1] / row[5], nxt[1] / nxt[5]))
            else:
                obs.append((float(row[idx]), float(nxt[idx])))
    pool = st.mean(a for _, a in obs)
    xs = [p for p, _ in obs]; ys = [a for _, a in obs]
    mx, my = st.mean(xs), st.mean(ys)
    cov = sum((x-mx)*(y-my) for x, y in obs)/len(obs)
    r = cov/(st.pstdev(xs)*st.pstdev(ys))
    best = min((((k/20), (sum((pool+(p-pool)*(k/20)-a)**2 for p, a in obs)/len(obs))**0.5)
                for k in range(0, 21)), key=lambda x: x[1])
    raw = (sum((p-a)**2 for p, a in obs)/len(obs))**0.5
    print(f"{label:22} n={len(obs):3}  pool={pool:8.4f}  r={r:+.3f}  "
          f"best k={best[0]:.2f}  RMSE {best[1]:.5f} (unshrunk {raw:.5f})")
