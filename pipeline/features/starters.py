"""Who is actually starting — the single source of truth.

This logic previously existed twice: `ingest/depth.py` computed it (with injury
promotion) for the Players page, and `model/project.py` reimplemented it (without
promotion) to filter projections. They disagreed exactly where it mattered most:
when a starter is ruled out, the backup who is now starting was refused by the
projection job as a backup.

Section 5.2 calls injury-driven usage redistribution the most exploitable signal in
props. Refusing to project it is the worst possible failure mode, so the promotion
rule lives here and both callers use it.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb

# Depth ranks whose usage is priceable, per position.
STARTER_DEPTH = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}

# Designations that free the snaps below them.
OUT_STATUSES = ("Out", "Doubtful")


@dataclass(frozen=True)
class Starter:
    gsis_id: str
    team: str
    position: str
    depth_rank: int
    promoted_for: str | None   # set when someone ahead of him is out


def latest_depth(depth_path: str) -> list[tuple]:
    """(team, gsis_id, name, position, rank) from the LATEST snapshot only.

    The 2026 file holds ~160 dated snapshots back to March; taking them all returns
    a player at every rank he has ever held.
    """
    return duckdb.connect().execute(f"""
        with latest as (select max(dt) m from read_parquet('{depth_path}')),
        ranked as (
            select d.team, d.gsis_id, d.player_name, d.pos_abb, d.pos_rank,
                   row_number() over (
                       partition by d.team, d.gsis_id, d.pos_abb order by d.pos_rank
                   ) rn
            from read_parquet('{depth_path}') d, latest
            where d.dt = latest.m and d.gsis_id is not null
              and d.pos_abb in ('QB','RB','WR','TE')
        )
        select team, gsis_id, player_name, pos_abb, pos_rank
        from ranked where rn = 1
    """).fetchall()


def injured_out(injuries_path: str | None) -> set[str]:
    if not injuries_path:
        return set()
    try:
        return {
            r[0] for r in duckdb.connect().execute(
                f"""select distinct gsis_id from read_parquet('{injuries_path}')
                    where report_status in {OUT_STATUSES} and gsis_id is not null"""
            ).fetchall()
        }
    except Exception:
        return set()


def resolve_starters(
    depth_path: str, injuries_path: str | None = None
) -> dict[str, Starter]:
    """gsis_id -> Starter, with backups promoted into vacated slots."""
    rows = latest_depth(depth_path)
    out_ids = injured_out(injuries_path)

    by_slot: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
    for team, gsis, name, pos, rank in rows:
        by_slot.setdefault((team, pos), []).append((int(rank), gsis, name))

    starters: dict[str, Starter] = {}
    for (team, pos), players in by_slot.items():
        players.sort()
        depth = STARTER_DEPTH.get(pos, 1)
        normal = players[:depth]
        normal_ids = {p[1] for p in normal}
        available = [p for p in players if p[1] not in out_ids]

        for rank, gsis, _name in available[:depth]:
            promoted_for = None
            if gsis not in normal_ids:
                missing = [p for p in normal if p[1] in out_ids]
                promoted_for = missing[0][2] if missing else "an absent starter"
            starters[gsis] = Starter(gsis, team, pos, rank, promoted_for)

    return starters
