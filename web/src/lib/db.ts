import { PrismaClient } from "@prisma/client";

/**
 * The Neon Vercel integration does not publish `DATABASE_URL`. It publishes its own
 * prefixed set — `bet_daddy_archive_DATABASE_URL` (pooled, for queries) and
 * `..._DATABASE_URL_UNPOOLED` (direct, for migrations) — and Prisma's schema can only
 * name ONE variable per field, with no fallback. So production came up with a valid
 * build, a reachable app, and every request failing on
 * "Environment variable not found: DATABASE_URL".
 *
 * Bridged here rather than by copying the connection string into a second Vercel
 * variable: a duplicated secret is one the integration cannot rotate, and it would go
 * stale silently the first time Neon cycles the password. The integration stays the
 * single source of truth; this only gives its value the name Prisma expects.
 *
 * Must run before PrismaClient is constructed — the client reads the environment at
 * construction, not per query.
 */
function bridgeNeonEnv() {
  const pairs: [string, string][] = [
    ["DATABASE_URL", "bet_daddy_archive_DATABASE_URL"],
    ["DIRECT_URL", "bet_daddy_archive_DATABASE_URL_UNPOOLED"],
  ];
  for (const [want, from] of pairs) {
    // A local .env still wins: developers point at their own branch, and an empty
    // assignment is treated as absent for the same reason it is in the Python config.
    if (!process.env[want] && process.env[from]) process.env[want] = process.env[from];
  }
}

bridgeNeonEnv();

// Next dev reloads modules on every edit; without the global cache that opens a new
// pool per reload and exhausts Neon's connection limit within a few saves.
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({ log: process.env.NODE_ENV === "development" ? ["warn", "error"] : ["error"] });

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;
