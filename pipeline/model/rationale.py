"""Plain-language justification for a signal.

The Why panel showed arithmetic. Arithmetic is not an argument: nobody can agree or
disagree with "×1.056". This turns the model's stored facts into claims a person can
push back on individually.

Three rules keep it honest:

1. **Every claim carries its number and its sample size.** A three-game trend and a
   sixteen-game trend are different claims and must not read the same.
2. **Caveats sit in the same list as drivers**, not in a footnote. A thin baseline is
   part of the argument, not a disclaimer attached to it.
3. **Hit rate is context, never the reason.** Section 2 is emphatic that a backward-
   looking clearance rate is worthless on its own because the line has already
   absorbed it. It appears here beside the model's probability, explicitly framed as
   what the market already knows.

Generated at projection time and stored, so the rendered argument is what the model
believed WHEN IT FIRED, not a recomputation against later data.
"""
from __future__ import annotations

from typing import Any


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _ord(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th') }".replace(" ", "")


def build_rationale(
    *,
    player_name: str,
    market_label: str,
    strike: float,
    side: str,
    volume_metric: str,
    baseline: float,
    games: int,
    adjustments: list[dict],
    percentiles: dict[str, float],
    mean_outcome: float,
    p_over: float,
    model_prob: float,
    market_prob: float,
    fee_cents: float,
    net_edge_cents: float,
    sample_n: int,
    tier: str,
    opponent: str | None = None,
    position: str | None = None,
    ctx: Any = None,
    promoted_for: str | None = None,
    match_method: str | None = None,
    game_label: str | None = None,
    is_preseason: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    # A line is meaningless without its game. 50 passing yards is absurd in week 3
    # and routine in a preseason game where a starter plays one series.
    if is_preseason:
        out.append({
            "kind": "caveat",
            "claim": f"This is a preseason game{f' ({game_label})' if game_label else ''}.",
            "evidence": "Starters play a series or two, which is why the line is so "
                        "low. Season usage does not predict preseason snaps, so this "
                        "projection is not trustworthy.",
        })

    if match_method == "FALLBACK":
        out.append({
            "kind": "caveat",
            "claim": "Player identity was matched without the jersey number.",
            "evidence": "The market's key did not match a roster jersey, so the match "
                        "rests on team, surname and first initial. A shared surname on "
                        "one roster would resolve to the wrong player.",
        })

    # Leads the list when it applies: a promoted backup's baseline describes his
    # role BEFORE the promotion, which is the single most important caveat on the
    # whole projection.
    if promoted_for:
        out.append({
            "kind": "caveat",
            "claim": f"{player_name} is starting only because {promoted_for} is out.",
            "evidence": "His usage history was compiled in a smaller role, so the "
                        "baseline understates the opportunity he is about to see — "
                        "and the market may have repriced this faster than the model.",
        })
    over = side == "yes"
    label = "over" if over else "under"

    # ---------- opportunity, with its trend -----------------------------------
    if ctx and ctx.recent_mean is not None and ctx.season_mean:
        direction = "up" if (ctx.trend_pct or 0) > 0.05 else \
                    "down" if (ctx.trend_pct or 0) < -0.05 else "flat"
        out.append({
            "kind": "driver",
            "claim": f"{player_name} is averaging {ctx.season_mean:.1f} {volume_metric} "
                     f"per game, and {ctx.recent_mean:.1f} over his last "
                     f"{ctx.recent_games} — trending {direction}.",
            "evidence": (
                f"{ctx.games_played} games of play-by-play. "
                + (f"The recent stretch is {abs(ctx.trend_pct):.0%} "
                   f"{'above' if ctx.trend_pct > 0 else 'below'} his season rate, "
                   f"on {ctx.recent_games} games — a small sample that moves fast."
                   if direction != "flat" and ctx.trend_pct is not None
                   else "Recent usage matches his season rate.")
            ),
        })
    else:
        out.append({
            "kind": "driver",
            "claim": f"{player_name} averaged {baseline:.1f} {volume_metric} per game.",
            "evidence": f"{games} games of prior play-by-play. Volume drives props far "
                        f"more than efficiency.",
        })

    # ---------- how much of the offense he commands ---------------------------
    if ctx and ctx.target_share is not None:
        out.append({
            "kind": "driver",
            "claim": f"He commands {ctx.target_share:.0%} of his team's targets — "
                     f"{_ord(ctx.share_rank_on_team)} of {ctx.teammates_counted} "
                     f"receivers.",
            "evidence": "Share is more stable than raw counts: it survives a game "
                        "script that changes how often the offense throws at all.",
        })

    # ---------- the specific defensive weakness -------------------------------
    if ctx and ctx.def_metric is not None and opponent:
        rank_txt = (f", {_ord(ctx.def_rank)} of 32" if ctx.def_rank else "")
        soft = ctx.def_rank and ctx.def_rank >= 22
        tough = ctx.def_rank and ctx.def_rank <= 10
        verdict = ("a matchup to attack" if soft else
                   "a difficult matchup" if tough else "a middling matchup")
        out.append({
            "kind": "driver",
            "claim": f"{opponent} allows {ctx.def_metric:+.3f} EPA per play against "
                     f"{ctx.def_split}{rank_txt} — {verdict}.",
            "evidence": "Graded from what the defense actually gave up, split by the "
                        "kind of play this prop depends on. Inferred from play-by-play, "
                        "not charted coverage.",
        })

    for a in adjustments:
        mult = float(a.get("multiplier", 1.0))
        if abs(mult - 1.0) < 0.001:
            continue
        out.append({
            "kind": "driver",
            "claim": f"{a.get('detail') or a.get('step')} — "
                     f"{'raises' if mult > 1 else 'lowers'} the projection "
                     f"{abs(mult - 1) * 100:.1f}%.",
            "evidence": f"A named multiplier ({mult:.3f}) applied to the baseline, "
                        f"not folded into it.",
        })

    # ---------- where the line sits -------------------------------------------
    p50 = percentiles.get("50")
    if p50 is not None:
        pos_txt = "above" if strike > p50 else "below" if strike < p50 else "at"
        out.append({
            "kind": "context",
            "claim": f"20,000 simulated games put his median at {p50:.0f}. "
                     f"The line of {strike:g} sits {pos_txt} it.",
            "evidence": f"P({label} {strike:g}) = {_pct(model_prob)}. Efficiency is "
                        f"drawn from this player's own outcomes, so the right tail is "
                        f"his, not an assumed shape.",
        })

    # ---------- what the market already knows ---------------------------------
    if ctx and ctx.clearance_n:
        rate = ctx.clearance_hits / ctx.clearance_n
        out.append({
            "kind": "context",
            "claim": f"He has cleared {strike:g} in {ctx.clearance_hits} of "
                     f"{ctx.clearance_n} games ({_pct(rate)}).",
            "evidence": "Context, not the reason. A backward-looking hit rate is "
                        "already in the price — if it were the edge, everyone holding "
                        "a box score would have it.",
        })

    # ---------- the disagreement ----------------------------------------------
    gap = (model_prob - market_prob) * 100
    out.append({
        "kind": "driver",
        "claim": f"The market prices the {label} at {market_prob * 100:.0f}¢; the "
                 f"model says {_pct(model_prob)}.",
        "evidence": f"A {abs(gap):.1f} point disagreement, and the entire bet. If the "
                    f"market is right, there is nothing here.",
    })

    out.append({
        "kind": "context",
        "claim": f"The fee takes {fee_cents:.2f}¢, leaving {net_edge_cents:+.2f}¢ net.",
        "evidence": "The fee peaks near mid-price. An edge smaller than the fee is a "
                    "losing bet however good the model looks.",
    })

    # ---------- what would change it ------------------------------------------
    breakeven = market_prob + (fee_cents / 100.0)
    out.append({
        "kind": "sensitivity",
        "claim": f"The edge dies if the true probability is under {_pct(float(breakeven))}.",
        "evidence": f"Market price plus fee. The model's {_pct(model_prob)} would have "
                    f"to be overstated by {(model_prob - float(breakeven)) * 100:.1f} "
                    f"points to be wrong.",
    })

    if ctx and ctx.season_mean:
        # how far volume can fall before the projection stops supporting the line
        out.append({
            "kind": "sensitivity",
            "claim": f"It assumes roughly {baseline:.1f} {volume_metric}. A snap-count "
                     f"cut or a stalled game script moves that first.",
            "evidence": "Check the depth chart and injury report before acting — usage "
                        "is the input this projection is most sensitive to.",
        })

    # ---------- reasons to disagree -------------------------------------------
    if ctx and ctx.recent_games and ctx.recent_games < 3:
        out.append({
            "kind": "caveat",
            "claim": f"The recent-form read rests on {ctx.recent_games} game(s).",
            "evidence": "Too few to separate a trend from a good afternoon.",
        })
    if games < 8:
        out.append({
            "kind": "caveat",
            "claim": f"The baseline rests on only {games} games.",
            "evidence": "Thin history. One outlier game moves this more than the "
                        "confident-looking number suggests.",
        })
    if ctx and ctx.def_rank is None and opponent:
        out.append({
            "kind": "caveat",
            "claim": f"No reliable defensive grade for {opponent} in this split.",
            "evidence": "Too few plays to rank. The matchup adjustment is doing "
                        "nothing here.",
        })
    if tier == "UNVALIDATED":
        out.append({
            "kind": "caveat",
            "claim": "This signal family has no track record yet.",
            "evidence": f"{sample_n} settled contracts. Promotion needs 200 with "
                        f"positive closing line value. Until then the edge is a claim, "
                        f"not a demonstrated result.",
        })

    return out
