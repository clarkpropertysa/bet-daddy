/**
 * Section 0 rule 3: when data is unavailable the correct behaviour is an explicit
 * empty state naming which source failed -- never a placeholder number.
 */
export function Empty({ title, source, hint }: { title: string; source: string; hint?: string }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-8 text-center">
      <p className="text-sm font-medium text-zinc-300">{title}</p>
      <p className="mt-1 text-xs text-zinc-500">
        Source: <span className="font-mono">{source}</span>
      </p>
      {hint && <p className="mt-3 text-xs text-zinc-600">{hint}</p>}
    </div>
  );
}
