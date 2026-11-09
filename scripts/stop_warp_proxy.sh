#!/usr/bin/env bash
set -euo pipefail

if command -v warp-cli >/dev/null 2>&1; then
  warp-cli --accept-tos disconnect || true
  warp-cli --accept-tos registration delete || true
  sudo systemctl stop warp-svc || true
fi
