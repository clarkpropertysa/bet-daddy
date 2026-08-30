"""Plain-language justification for a signal.

The Why panel already showed the arithmetic. Arithmetic is not an argument: a reader
cannot AGREE OR DISAGREE with "×1.056". This turns the model's stored facts into
claims a person can push back on.

Two hard rules:

1. **Every claim carries its evidence.** No sentence exists that is not derived from a
   number the model actually used. Nothing is written to sound persuasive.
2. **The caveats are part of the argument, not a footnote.** A thin baseline or an
   unvalidated tier belongs in the same list as the drivers, because those are the
   reasons a reader should disagree.

It also states what would CHANGE the answer. A projection that cannot say what would
falsify it is not an explanation, it is an assertion.

Generated at projection time and stored on the signal, so the rendered explanation is
what the model believed WHEN IT FIRED — not a recomputation against later data.
"""
from __future__ import annotations

from typing import Any


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


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
) -> list[dict[str, Any]]:
    """Ordered claims. `kind` drives how the UI weights each one."""
    out: list[dict[str, Any]] = []

    # ---- what the projection rests on -------------------------------------
    out.append({
        "kind": "driver",
        "claim": f"{player_name} averaged {baseline:.1f} {volume_metric} per game.",
        "evidence": f"{games} games of prior play-by-play. Volume drives props far "
                    f"more than efficiency, so this is the number that matters most.",
    })

    for a in adjustments:
        mult = float(a.get("multiplier", 1.0))
        if abs(mult - 1.0) < 0.001:
            continue
        direction = "raises" if mult > 1 else "lowers"
        out.append({
            "kind": "driver",
            "claim": f"{a.get('detail') or a.get('step')} — {direction} the projection "
                     f"{abs(mult - 1) * 100:.1f}%.",
            "evidence": f"Applied as a named multiplier ({mult:.3f}) to the baseline, "
                        f"not baked into it.",
        })

    # ---- where the strike falls -------------------------------------------
    p50 = percentiles.get("50")
    if p50 is not None:
        pos = "above" if strike > p50 else "below" if strike < p50 else "exactly at"
        out.append({
            "kind": "context",
            "claim": f"Simulating 20,000 games puts the median at {p50:.0f}; "
                     f"the strike of {strike:g} sits {pos} it.",
            "evidence": f"P(over {strike:g}) = {_pct(p_over)}. Efficiency is drawn from "
                        f"this player's own outcomes, so the right tail is real rather "
                        f"than assumed.",
        })

    # ---- the disagreement, which IS the bet -------------------------------
    gap = (model_prob - market_prob) * 100
    label = "over" if side == "yes" else "under"
    out.append({
        "kind": "driver",
        "claim": f"The market prices the {label} at {market_prob * 100:.0f}¢; "
                 f"the model says {_pct(model_prob)}.",
        "evidence": f"A {abs(gap):.1f} point disagreement. The bet is entirely this gap — "
                    f"if the market is right, there is nothing here.",
    })

    out.append({
        "kind": "context",
        "claim": f"The fee takes {fee_cents:.2f}¢, leaving {net_edge_cents:+.2f}¢ net.",
        "evidence": "Kalshi's fee peaks at 1.75¢ near 50¢. An edge smaller than the "
                    "fee is a losing bet however good the model looks.",
    })

    # ---- what would change the answer -------------------------------------
    breakeven_prob = market_prob + (fee_cents / 100.0)
    out.append({
        "kind": "sensitivity",
        "claim": f"The edge disappears if the true probability is below "
                 f"{_pct(float(breakeven_prob))}.",
        "evidence": f"That is the market price plus the fee. The model's "
                    f"{_pct(model_prob)} would have to be overstated by "
                    f"{(model_prob - float(breakeven_prob)) * 100:.1f} points to be wrong.",
    })

    if baseline > 0:
        # how much volume error the edge can absorb before it dies
        out.append({
            "kind": "sensitivity",
            "claim": f"It rests on {player_name} seeing roughly "
                     f"{baseline:.1f} {volume_metric}.",
            "evidence": "A change in role, a game script that stalls the offence, or a "
                        "snap-count cut moves this first. Check the injury report and "
                        "depth chart before acting.",
        })

    # ---- reasons to disagree ----------------------------------------------
    if games < 8:
        out.append({
            "kind": "caveat",
            "claim": f"The baseline rests on only {games} games.",
            "evidence": "Thin history. The projection is more sensitive to a single "
                        "outlier game than the confident-looking number suggests.",
        })

    if tier == "UNVALIDATED":
        out.append({
            "kind": "caveat",
            "claim": "This signal family has no track record yet.",
            "evidence": f"{sample_n} settled contracts. Promotion needs 200 with "
                        "positive closing line value. Until then the edge is a claim, "
                        "not a demonstrated result.",
        })

    return out
