#!/usr/bin/env bash
# Next dev server launcher.
#
# Two environment quirks handled here:
#
# 1. Turbopack (the Next 16 dev default) panics in this environment when it spawns
#    its pooled node worker for the PostCSS/Tailwind loader:
#      "spawning node pooled process - No such file or directory (os error 2)"
#    Putting node on PATH does not fix it, so dev runs on webpack. The production
#    build is unaffected and still uses the default pipeline.
#
# 2. node must be on PATH regardless -- child processes are looked up by name, so
#    an absolute path to the node binary is not sufficient on its own.
set -euo pipefail
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
NODE_BIN="$(dirname "$(ls -d "$NVM_DIR"/versions/node/*/bin/node | tail -1)")"
export PATH="$NODE_BIN:$PATH"
cd "$(dirname "$0")/../web"
exec node node_modules/next/dist/bin/next dev --webpack -p "${PORT:-3000}"
