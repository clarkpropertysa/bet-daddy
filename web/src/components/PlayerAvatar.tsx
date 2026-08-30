"use client";

import { useState } from "react";
import { initials, sizedHeadshot } from "@/lib/headshot";

/**
 * Player headshot with an initials fallback.
 *
 * ~2.4% of rostered players have no headshot, and the CDN occasionally 404s an id
 * that the roster still carries. Both cases fall back rather than rendering a broken
 * image -- a missing photo must never look like a data error.
 */
export function PlayerAvatar({
  name,
  url,
  size = 28,
}: {
  name: string;
  url?: string | null;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const src = failed ? null : sizedHeadshot(url, size);

  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full border border-line-2 bg-steel-100 align-middle"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {src ? (
        // Plain <img>: these are already CDN-resized to exact dimensions, so the
        // Next image optimiser would add a second hop for no benefit.
        <img
          src={src}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
        />
      ) : (
        <span
          className="display text-steel-700"
          style={{ fontSize: Math.max(9, size * 0.36) }}
        >
          {initials(name)}
        </span>
      )}
    </span>
  );
}
