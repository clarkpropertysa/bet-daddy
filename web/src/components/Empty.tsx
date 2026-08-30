import { OddsCrown } from "@/components/Logo";

/**
 * Section 0 rule 3: an unavailable source produces an explicit empty state naming
 * which system had no data -- never a placeholder number. `source` is required.
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
    <div className="flex flex-col items-center rounded border border-dashed border-line-2 bg-card px-6 py-16 text-center">
      <div className="mb-4 opacity-25">
        <OddsCrown size={30} />
      </div>
      <p className="display text-[15px] text-ink">{title}</p>
      <p className="eyebrow mt-2">source · {source}</p>
      {hint && (
        <p className="mt-4 max-w-md text-[12px] leading-relaxed text-ink-2">{hint}</p>
      )}
    </div>
  );
}
