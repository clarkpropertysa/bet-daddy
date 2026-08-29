export function PageHeader({
  title,
  sub,
  right,
}: {
  title: string;
  sub?: string;
  right?: React.ReactNode;
}) {
  return (
    // Stacks below lg: the status element on the right is a fixed-width block, and
    // side-by-side it squeezes the prose column to a few characters per line.
    <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between lg:gap-6">
      <div className="min-w-0">
        <h1 className="text-[17px] font-semibold tracking-tight text-ink">{title}</h1>
        {sub && (
          <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-ink-3">{sub}</p>
        )}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}
