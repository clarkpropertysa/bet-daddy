"""P(a player takes no offensive snap), from the injury report.

`VolumeProjection.p_inactive` has existed since the simulator was written and has never
been set: it is 0.0 on every production projection. So a prop is priced as though the
player is certain to play, and the distribution has no left tail at all -- while a DNP
is by far the largest single risk on a yardage line.

Meanwhile the starter filter keys on `report_status in ('Out','Doubtful')`, which means
every **Questionable** player is treated as fully available. Measured on 2025 skill
players, that is wrong by about forty points:

    report          practice                       n     P(0 offensive snaps)
    Out             any                          419     100.0%
    Questionable    Did Not Participate           45      48.9%
    Questionable    Limited Participation        232      41.8%
    Questionable    Full Participation            83      41.0%
    (none)          Full Participation           821      11.9%

Two design notes.

**Zero offensive snaps, not "no stat line".** A WR3 can be active and record no
receptions; he is available and the market prices him that way. Using a missing stat
line as the target inflates the base rate to ~28% even for healthy players. Snap counts
are the honest measure, joined pfr->gsis through the same 99.7%-coverage path
`splits.build_availability` already uses.

**Practice status separates weakly WITHIN Questionable** (48.9 vs 41.0), so the signal
is mostly the designation itself. The table is still keyed on both because the
`(none)` rows -- 54% of the injury file, invisible to a `report_status` filter -- do
separate: 34.3% for DNP against 11.9% for full participation.

Rates are MEASURED from a season rather than hardcoded, so they move when the league
does, and fall back to a documented prior when a cell is too thin to trust.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb

from pipeline.features.splits import build_availability

#: Below this many observations a cell is not its own estimate.
MIN_CELL_N = 25

#: Fallbacks when a cell is missing or too thin. Deliberately conservative -- these
#: are the 2022-25 aggregates, and being roughly right beats refusing to model a tail
#: that certainly exists.
PRIOR = {
    "Out": 1.0,
    "Doubtful": 0.85,
    "Questionable": 0.42,
    "(none)": 0.10,
}

#: A player absent from the injury report entirely. Not zero: starters miss games for
#: reasons that never reach a Wednesday practice report.
DEFAULT_HEALTHY = 0.02

SKILL = ("QB", "RB", "WR", "TE")


@dataclass(frozen=True)
class InactivityTable:
    """(report_status, practice_status) -> P(no offensive snap)."""
    rates: dict[tuple[str, str], float]
    counts: dict[tuple[str, str], int]
    season: int

    def probability(
        self, report_status: str | None, practice_status: str | None
    ) -> float:
        """For a player who APPEARS on the injury report.

        `(none)` here means "listed, but carrying no game-status designation" -- 54%
        of the file, and measurably riskier than a player who is not listed at all
        (11.9% against ~2%). Use `for_player` when you do not know whether the player
        is on the report; conflating the two treats every healthy starter as a coin
        flip's worth of injury risk.
        """
        rs = (report_status or "(none)").strip() or "(none)"
        ps = (practice_status or "(none)").strip() or "(none)"
        cell = self.rates.get((rs, ps))
        if cell is not None and self.counts.get((rs, ps), 0) >= MIN_CELL_N:
            return cell
        return PRIOR.get(rs, DEFAULT_HEALTHY)

    def for_player(self, status: tuple[str, str] | None) -> float:
        """P(inactive) given this week's report entry, or None if not listed."""
        if status is None:
            return DEFAULT_HEALTHY
        return self.probability(status[0], status[1])

    @property
    def is_empty(self) -> bool:
        return not self.rates


def build_inactivity_table(
    injuries_path: str, snap_counts_path: str, players_path: str, season: int
) -> InactivityTable:
    """Measure P(0 offensive snaps) per (report_status, practice_status) cell."""
    try:
        avail = build_availability(snap_counts_path, players_path)
    except Exception:
        return InactivityTable({}, {}, season)

    con = duckdb.connect()
    con.register("avail", avail)

    # THE SNAP DATA MUST COVER THE SEASON BEING MEASURED.
    #
    # Without this the failure is silent and catastrophic. The join below is a LEFT
    # join, and a player with no matching snap row counts as inactive -- so pairing a
    # 2026 injury report with a 2025 snap-counts file makes every cell resolve to
    # p_inactive = 1.000, on large samples, with is_empty False. Every player on the
    # injury report is then projected as certain not to play, their whole projection
    # zeroed, while the inertness counter reports the layer as working perfectly.
    #
    # That is exactly the production default: project.py ships --snaps
    # snap_counts_2025.parquet and --season 2026.
    try:
        covered = con.execute(
            "select count(*) from avail where season = ?", [int(season)]
        ).fetchone()[0]
    except Exception:
        covered = 0
    if not covered:
        return InactivityTable({}, {}, season)

    positions = ", ".join(f"'{p}'" for p in SKILL)
    try:
        rows = con.execute(f"""
            with inj as (
                select season, week, gsis_id,
                       coalesce(nullif(trim(report_status), ''), '(none)')   as rs,
                       coalesce(nullif(trim(practice_status), ''), '(none)') as ps
                from read_parquet('{injuries_path}')
                where gsis_id is not null and position in ({positions})
                  and season = {int(season)}
            )
            select i.rs, i.ps, count(*) as n,
                   sum(case when a.player_id is null
                                 or coalesce(a.offense_snaps, 0) = 0
                            then 1 else 0 end) * 1.0 / count(*) as p_inactive
            from inj i
            left join avail a
              on a.season = i.season and a.week = i.week and a.player_id = i.gsis_id
            group by 1, 2
        """).fetchall()
    except Exception:
        return InactivityTable({}, {}, season)

    rates = {(r[0], r[1]): float(r[3]) for r in rows}
    counts = {(r[0], r[1]): int(r[2]) for r in rows}
    return InactivityTable(rates, counts, season)


def status_lookup(injuries_path: str, season: int, week: int) -> dict[str, tuple]:
    """gsis_id -> (report_status, practice_status) for one week.

    Scoped to a week for the same reason `injured_out` is: an injury report is a
    weekly snapshot, and reading it cumulatively marks half the league unavailable by
    December.
    """
    try:
        rows = duckdb.connect().execute(f"""
            select gsis_id,
                   coalesce(nullif(trim(report_status), ''), '(none)'),
                   coalesce(nullif(trim(practice_status), ''), '(none)')
            from read_parquet('{injuries_path}')
            where gsis_id is not null
              and season = {int(season)} and week = {int(week)}
        """).fetchall()
    except Exception:
        return {}
    return {r[0]: (r[1], r[2]) for r in rows}
