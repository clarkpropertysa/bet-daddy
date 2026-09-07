import type { InjuryNote } from "@/lib/queries";

/**
 * This week's injury report for the player and his positional room, plus the reason
 * he carries no signal if he does not.
 *
 * Both were invisible before. The report existed only as Parquet read by the pipeline,
 * so the number that makes the model refuse to price someone -- 34.3% for a listed
 * player who did not practise -- could not be shown; and a refused player simply
 * vanished from the board with no explanation anywhere.
 */
export function AvailabilityPanel({
  notes,
  refusal,
}: {
  notes: InjuryNote[];
  refusal: { reason: string; detail: string } | null;
}) {
  const self = notes.find((n) => n.isSelf) ?? null;
  const room = notes.filter((n) => !n.isSelf);
  if (!self && room.length === 0 && !refusal) return null;

  const pct = (p: number | null) =>
    p === null || p === undefined ? null : `${Math.round(p * 100)}%`;

  return (
    <section className="rounded border border-line bg-card">
      <div className="border-b border-line px-4 py-3">
        <h2 className="display text-[14px] text-ink">Availability</h2>
        <p className="eyebrow mt-0.5">this week&apos;s report</p>
      </div>

      {refusal && (
        // The model declined to price him. Saying so where the reader looks for him
        // beats an empty markets list that reads like a data failure.
        <div className="border-b border-line-2 bg-warn/5 px-4 py-3">
          <p className="text-[12.5px] leading-relaxed text-ink">
            <span className="font-medium">Not priced this week.</span> {refusal.detail}.
          </p>
          <p className="mt-1 text-[11px] text-ink-3">
            The model declines rather than publishing a number it cannot stand behind.
            The market still has a price; we simply do not claim to disagree with it.
          </p>
        </div>
      )}

      {self && (
        <div className="border-b border-line-2 px-4 py-3">
          <p className="text-[12.5px] text-ink">
            <span className="font-medium">On the report</span>
            {self.primaryInjury ? ` — ${self.primaryInjury.toLowerCase()}` : ""}
            {self.practiceStatus ? `, ${self.practiceStatus.toLowerCase()}` : ""}
            {self.reportStatus ? ` · listed ${self.reportStatus}` : ""}
          </p>
          {pct(self.pInactive) && (
            <p className="mt-1 text-[11px] text-ink-3">
              Players with that designation took no offensive snap{" "}
              <span className="font-medium text-ink-2">{pct(self.pInactive)}</span> of
              the time last season. That is a measured rate, not a guess, and it is the
              same number the projection uses.
            </p>
          )}
        </div>
      )}

      {room.length > 0 ? (
        <ul className="divide-y divide-line-2">
          {room.map((n) => (
            <li key={n.fullName} className="px-4 py-3">
              <p className="text-[12.5px] text-ink">
                <span className="font-medium">{n.fullName}</span>
                <span className="text-ink-2">
                  {" "}
                  ({n.position}) {n.practiceStatus?.toLowerCase() ?? "listed"}
                  {n.primaryInjury ? ` — ${n.primaryInjury.toLowerCase()}` : ""}
                </span>
              </p>
              {pct(n.pInactive) && (
                <p className="mt-0.5 text-[11px] text-ink-3">
                  {pct(n.pInactive)} likely to take no offensive snap. His carries or
                  targets would have to go somewhere.
                </p>
              )}
            </li>
          ))}
        </ul>
      ) : (
        !self && (
          <p className="px-4 py-5 text-[12px] leading-relaxed text-ink-2">
            Nobody in his positional room is on this week&apos;s report. Note that
            game designations — Out, Doubtful, Questionable — are not filed until
            Friday, so a midweek report shows practice participation only.
          </p>
        )
      )}
    </section>
  );
}
