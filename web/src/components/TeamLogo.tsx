export function TeamLogo({
  url, team, size = 20,
}: { url: string | null; team: string; size?: number }) {
  if (!url) {
    return (
      <span
        className="eyebrow inline-flex shrink-0 items-center justify-center"
        style={{ width: size, height: size }}
      >
        {team}
      </span>
    );
  }
  return (
    <img
      src={url}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      className="shrink-0 object-contain"
      style={{ width: size, height: size }}
    />
  );
}
