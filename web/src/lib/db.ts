import { PrismaClient } from "@prisma/client";

// Next dev reloads modules on every edit; without the global cache that opens a new
// pool per reload and exhausts Neon's connection limit within a few saves.
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({ log: process.env.NODE_ENV === "development" ? ["warn", "error"] : ["error"] });

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;
