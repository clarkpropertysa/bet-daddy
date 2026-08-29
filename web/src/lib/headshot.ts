/**
 * NFL headshot URLs are Cloudinary-backed. The stored originals are ~4MB PNGs --
 * fifty of them on a board is ~200MB of transfer.
 *
 * Injecting a sizing transform into the delivery segment takes the same image to
 * ~4KB, a thousandfold reduction, and `g_face` keeps the crop on the player rather
 * than centring on the jersey.
 *
 *   .../image/upload/f_auto,q_auto/league/<id>
 *   .../image/upload/f_auto,q_auto,c_fill,g_face,h_96,w_96/league/<id>
 */
const UPLOAD = "/image/upload/";

export function sizedHeadshot(url: string | null | undefined, px = 48): string | null {
  if (!url) return null;
  const i = url.indexOf(UPLOAD);
  if (i === -1) return url; // unknown shape: pass through rather than mangle it
  const head = url.slice(0, i + UPLOAD.length);
  const rest = url.slice(i + UPLOAD.length);
  // Drop the existing transform segment if there is one, keep the asset path.
  const slash = rest.indexOf("/");
  const assetPath = slash === -1 ? rest : rest.slice(slash + 1);
  // 2x for retina; the file is small enough that it costs nothing.
  const d = px * 2;
  return `${head}f_auto,q_auto,c_fill,g_face,h_${d},w_${d}/${assetPath}`;
}

export function initials(name: string): string {
  const parts = name.replace(/[^A-Za-z .'-]/g, "").split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
