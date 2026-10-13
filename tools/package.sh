#!/usr/bin/env bash
# Makes the release zip that users install: one folder with everything Decky needs, no build step.
set -euo pipefail
cd "$(dirname "$0")/.."
VER=$(node -p "require('./package.json').version")
OUT="release"; DIR="$OUT/Finally_Screenshot_Sound"
rm -rf "$OUT"; mkdir -p "$DIR/dist"
cp plugin.json package.json main.py LICENSE README.md "$DIR/"
cp -r assets "$DIR/assets"
cp dist/index.js "$DIR/dist/"
( cd "$OUT" && zip -qr "Finally-Screenshot-Sound-v$VER.zip" Finally_Screenshot_Sound )
echo "$OUT/Finally-Screenshot-Sound-v$VER.zip"
