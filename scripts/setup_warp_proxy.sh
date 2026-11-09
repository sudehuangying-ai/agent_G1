#!/usr/bin/env bash
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" || "${RUNNER_OS:-}" != "Linux" ]]; then
  echo 'WARP setup is intended for disposable Linux GitHub Actions runners.' >&2
  exit 1
fi

cd "${GITHUB_WORKSPACE:?}"
: "${TMPDIR:?}" "${GNUPGHOME:?}"
mkdir -p "$TMPDIR" "$GNUPGHOME"
chmod 700 "$GNUPGHOME"

curl --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 15 --max-time 60 -fsSL \
  https://pkg.cloudflareclient.com/pubkey.gpg -o "$TMPDIR/cloudflare-key.gpg"
gpg --batch --yes --dearmor --output "$TMPDIR/cloudflare-warp.gpg" "$TMPDIR/cloudflare-key.gpg"
sudo install -m 644 "$TMPDIR/cloudflare-warp.gpg" /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
printf 'deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ %s main\n' \
  "$(lsb_release -cs)" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list >/dev/null
sudo apt-get update -qq -o Acquire::Retries=3
sudo apt-get install -y --no-install-recommends -o Acquire::Retries=3 cloudflare-warp
sudo systemctl start warp-svc

ready=false
for attempt in {1..15}; do
  if warp-cli --accept-tos status >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 2
done
if [[ "$ready" != "true" ]]; then
  echo 'WARP service did not become ready; refusing direct access.' >&2
  exit 1
fi

warp-cli --accept-tos registration new
warp-cli --accept-tos mode proxy
warp-cli --accept-tos connect
uv run --frozen --no-dev python -B -m scripts.verify_warp_proxy
