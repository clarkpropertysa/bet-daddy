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
    <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between lg:gap-6">
      <div className="min-w-0">
        <h1 className="display text-[22px] leading-none text-ink">{title}</h1>
        {sub && (
          <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-ink-2">{sub}</p>
        )}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}
