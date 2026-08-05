#!/usr/bin/env bash
set -euo pipefail

REPO="June6699/dart_simple_live"
MAX_VERSIONS="${MAX_VERSIONS:-5}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh api "repos/${REPO}/releases?per_page=100" > "$tmp"
else
  curl -fsSL "https://api.github.com/repos/${REPO}/releases?per_page=100" > "$tmp"
fi

jq -n \
  --slurpfile src source.json \
  --slurpfile rels "$tmp" \
  --argjson max "$MAX_VERSIONS" \
  '$src[0] | .apps[0].versions = (
    $rels[0]
    | map(select(.draft == false and .prerelease == false))
    | map(select(.assets | any(.name == "ios_no_sign.ipa")))
    | .[0:$max]
    | map({
        version: (.tag_name | ltrimstr("v")),
        date: (.published_at[0:10]),
        localizedDescription: (.body // ""),
        downloadURL: ((.assets[] | select(.name == "ios_no_sign.ipa")) | .browser_download_url),
        size: ((.assets[] | select(.name == "ios_no_sign.ipa")) | .size),
        minOSVersion: "13.0",
        buildVersion: (([.assets[]?.name | capture("\\+(?<build>[0-9]+)")? | .build] | first) // "1")
      })
  )' > apps.json.new

python3 -m json.tool apps.json.new > /dev/null
mv apps.json.new apps.json
echo "apps.json updated with $(jq '.apps[0].versions | length' apps.json) versions, latest: $(jq -r '.apps[0].versions[0].version // "none"' apps.json)"
