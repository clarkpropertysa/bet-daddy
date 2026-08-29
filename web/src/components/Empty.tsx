/**
 * Section 0 rule 3: an unavailable source produces an explicit empty state naming
 * which system had no data -- never a placeholder number. `source` is required, so
 * a blank surface cannot ship without saying what is missing.
 */
export function Empty({
  title,
  source,
  hint,
}: {
  title: string;
  source: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center rounded-lg border border-dashed border-line-strong bg-surface-1 px-6 py-14 text-center">
      <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-full border border-line bg-surface-2 text-ink-3">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M2 8h12M8 2v12" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" opacity="0.5" />
        </svg>
      </div>
      <p className="text-[13px] font-medium text-ink">{title}</p>
      <p className="mt-1 text-[11px] text-ink-3">
        source <span className="font-mono text-ink-2">{source}</span>
      </p>
      {hint && (
        <p className="mt-3 max-w-md text-[11px] leading-relaxed text-ink-3">{hint}</p>
      )}
    </div>
  );
}
