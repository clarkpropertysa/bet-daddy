"""Do receiving and rushing efficiency rates persist? Fitted per position."""
import glob, re, statistics as st
import duckdb

PLAYERS = "data/raw/nflverse/players.parquet"

def recv(path):
    return duckdb.connect().execute(f"""
        with p as (select * from read_parquet('{path}')
                   where season_type='REG' and play_type='pass'
                     and receiver_player_id is not null
                     and coalesce(two_point_attempt,0)=0)
        select p.receiver_player_id pid, pl.position pos, count(*) tgt,
               sum(coalesce(complete_pass,0))*1.0/count(*)                        catch_rate,
               sum(case when complete_pass=1 then yards_gained else 0 end)*1.0
                 / nullif(sum(coalesce(complete_pass,0)),0)                       ypc
        from p left join read_parquet('{PLAYERS}') pl on pl.gsis_id=p.receiver_player_id
        group by 1,2 having count(*) >= 40
    """).fetchall()

def rush(path):
    return duckdb.connect().execute(f"""
        with p as (select * from read_parquet('{path}')
                   where season_type='REG' and rusher_player_id is not null
                     and coalesce(two_point_attempt,0)=0)
        select p.rusher_player_id pid, pl.position pos, count(*) car,
               sum(yards_gained)*1.0/count(*) ypcarry
        from p left join read_parquet('{PLAYERS}') pl on pl.gsis_id=p.rusher_player_id
        group by 1,2 having count(*) >= 40
    """).fetchall()

paths = {int(re.search(r'(\d{4})', p).group(1)): p
         for p in sorted(glob.glob('data/raw/nflverse/pbp_*.parquet'))}
seasons = sorted(paths)

def fit(loader, idx, label, positions, min_n=25):
    by = {y: {r[0]: r for r in loader(paths[y])} for y in seasons}
    groups = {}
    for a, b in zip(seasons, seasons[1:]):
        for pid, row in by[a].items():
            nxt = by[b].get(pid)
            if not nxt or row[idx] is None or nxt[idx] is None:
                continue
            groups.setdefault(row[1] or "?", []).append((float(row[idx]), float(nxt[idx])))
    print(f"\n=== {label} ===")
    for pos in positions:
        g = groups.get(pos, [])
        if len(g) < min_n:
            print(f"  {pos:4} n={len(g):4}  below the {min_n}-pair floor")
            continue
        pool = st.mean(a for _, a in g)
        xs=[x for x,_ in g]; ys=[y for _,y in g]
        mx,my=st.mean(xs),st.mean(ys)
        cov=sum((x-mx)*(y-my) for x,y in g)/len(g)
        r=cov/(st.pstdev(xs)*st.pstdev(ys)) if st.pstdev(xs) and st.pstdev(ys) else 0
        best=min((((k/20),(sum((pool+(x-pool)*(k/20)-y)**2 for x,y in g)/len(g))**0.5)
                  for k in range(0,21)), key=lambda t:t[1])
        raw=(sum((x-y)**2 for x,y in g)/len(g))**0.5
        print(f"  {pos:4} n={len(g):4} pool={pool:7.4f} r={r:+.3f} k={best[0]:.2f} "
              f"RMSE {best[1]:.4f} (raw {raw:.4f})")

fit(recv, 3, "catch rate (receptions per target)", ["WR","TE","RB"])
fit(recv, 4, "yards per catch", ["WR","TE","RB"])
fit(rush, 3, "yards per carry", ["RB","QB","WR"])
