"""Can this player's volume be priced while a teammate's availability is unresolved?

A running back's carries are not his own property. When the other back in the room may
not play, the projection is a conditional -- one number if he plays, a materially
different one if he does not -- and the simulator produces a single mean. Neither branch
is wrong; the average of them is, because the market prices the branch that happens.

THE CASE THIS EXISTS FOR. TreVeyon Henderson did not practise on the Wednesday before
Week 1 2026 (ankle). Measured on 2025, a player listed with no game designation who did
not practise sits **34.3%** of the time. He and Rhamondre Stevenson split New England's
backfield almost evenly the previous season:

    Stevenson  14 games   9.4 carries/game   43.2 rushing yards/game
    Henderson  17 games  10.6 carries/game   53.6 rushing yards/game

The model projected Stevenson at 39.4 rushing yards -- his committee rate -- and took
UNDER 49.5 at +25.8c as its largest edge on him. If Henderson sits, Stevenson inherits a
ten-carry role and that pick is on the wrong side.

WHY NOTHING CAUGHT IT. Two independent mechanisms should have, and both were inert:

  * `starters.injured_out` selects `report_status in ('Out','Doubtful')`. A Wednesday
    practice report carries NO game designation -- every `report_status` in the Week 1
    file is null -- so `absent_teammates` received an empty set.
  * Even given the absence, `splits.build_with_without` needs prior-season games where
    Henderson sat and Stevenson played. Henderson played all seventeen. The sample is
    empty, so the with/without adjustment is suppressed by its own significance gate.

And `p_inactive` does not help: it lowers a player for HIS OWN injury and never moves a
teammate's share.

So the honest answer is that this volume cannot be priced, and the honest output is a
refusal naming the reason rather than a confident number for a role that may not exist.
"""
from __future__ import annotations

import duckdb

#: Absence probability at which a teammate's availability stops being noise. The
#: measured cells either side of it: "(none)/full participation" is 0.119 and ordinary,
#: "(none)/did not participate" is 0.343 and is not.
TEAMMATE_RISK = 0.25

#: How large a teammate has to be to matter, as a fraction of this player's own prior
#: snap share. A fifth-string back missing practice changes nothing.
MATERIAL_SHARE = 0.50


def build_rooms(depth_path: str) -> dict[tuple[str, str], list[str]]:
    """(team, position) -> every gsis_id listed there, starters and backups alike.

    `starters.resolve_starters` keeps only the top of each slot, which is precisely the
    wrong shape here: the question is who ELSE is in the room.
    """
    try:
        rows = duckdb.connect().execute(f"""
            select distinct team, pos_abb, gsis_id
            from read_parquet('{depth_path}')
            where gsis_id is not null and team is not null and pos_abb is not null
        """).fetchall()
    except Exception:
        return {}
    out: dict[tuple[str, str], list[str]] = {}
    for team, pos, gsis in rows:
        out.setdefault((team, pos), []).append(gsis)
    return out


def unpriced_teammate(
    gsis_id: str,
    team: str | None,
    position: str | None,
    rooms: dict[tuple[str, str], list[str]],
    p_inactive_of,
    prior_snap: dict[str, float],
    names: dict[str, str] | None = None,
) -> tuple[str, float] | None:
    """The riskiest material teammate whose absence we cannot price, if any.

    `p_inactive_of` is a callable taking a gsis_id and returning that player's absence
    probability this week. Returns (name, probability) or None.

    Returns None whenever the inputs are missing rather than guessing: no depth chart,
    no snap history, or an unmapped room means this check has nothing to say, and a
    check that fires on silence would empty the board.
    """
    if not team or not position:
        return None
    mates = rooms.get((team, position.upper()))
    if not mates:
        return None

    own = prior_snap.get(gsis_id)
    if own is None:
        return None
    floor = own * MATERIAL_SHARE

    worst: tuple[str, float] | None = None
    for mate in mates:
        if mate == gsis_id:
            continue
        share = prior_snap.get(mate)
        if share is None or share < floor:
            continue
        p = p_inactive_of(mate)
        if p is None or p < TEAMMATE_RISK:
            continue
        if worst is None or p > worst[1]:
            worst = ((names or {}).get(mate, mate), p)
    return worst


def describe(player_position: str, mate_name: str, p: float) -> str:
    return (
        f"{mate_name} in the same {player_position} room is {p:.0%} likely not to play, "
        f"and no with/without history exists to price the share that would move"
    )
