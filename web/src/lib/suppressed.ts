/**
 * Families withheld from the recommendation surfaces.
 *
 * RUSHING YARDS, suppressed 2026-09-12. Three independent measurements say the model
 * is wrong in the one direction the board was betting -- and five of the ten Top Picks
 * for Week 2 were rushing unders, with positive-edge rushing rows running 255 unders
 * to 132 overs:
 *
 *   1. The projection cuts the highest-volume backs hardest. Board-wide the median
 *      back is projected at 0.94x his own 2025 per-game average, but the workhorses
 *      lose 23-30 yards a game: Cook -29.5, Taylor -28.3, Achane -28.2, Henry -25.2,
 *      Bijan -23.2. Every one of those becomes an under.
 *   2. Replaying 615 running-back games from 2025 says that cut is too deep:
 *      projected 43.4 against an actual 47.9, and for the top tier 66.8 against 70.2,
 *      with the actual landing ABOVE the projection in 51.2% of those games.
 *   3. The simulated distribution is too narrow for rushing -- spread score 1.26 to
 *      1.75 where 1.00 is right, the worst of any market -- so the confidence on
 *      those unders is overstated on top of the mean being low.
 *
 * And the money agrees: rush_yds graded at -8.06c per contract over 64 settled bets,
 * the only family losing money, while its CLV (+0.25c) was positive enough to earn a
 * PROVISIONAL badge. The badge and the P&L disagree, which is reason enough not to
 * put these in front of anyone as picks.
 *
 * This is a blunt instrument and deliberately so: the honest fix is the per-snap
 * volume rebuild scheduled after Week 1 (DECISIONS.md), which addresses why the
 * volume is low rather than hiding the consequence. Withheld until the backtest shows
 * the rebuilt model projecting rushing without the bias -- not until it merely looks
 * better.
 *
 * Nothing is DELETED: /board still lists every rushing strike with its edge, the
 * player pages still show the projection, and the Why panel still explains it. What
 * is withheld is the recommendation.
 */
export const SUPPRESSED_MARKETS: ReadonlySet<string> = new Set(["rush_yds"]);

/** Human-readable, for the note that has to appear wherever rows were withheld. */
export const SUPPRESSED_LABEL = "rushing yards";

export const SUPPRESSED_WHY =
  "Rushing projections run low on high-volume backs — a 2025 replay of 615 games has " +
  "them 4.5 yards a game under, the distribution is the model's least calibrated, and " +
  "the family is down 8.06¢ a contract over 64 settled bets. Held back until the " +
  "per-snap volume rebuild is measured, not merely finished.";

export function isSuppressed(marketType: string | null | undefined): boolean {
  return !!marketType && SUPPRESSED_MARKETS.has(marketType);
}
