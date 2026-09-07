#!/bin/zsh
# Builds macos/dist/Wispr Local.app. The bundle points at this repo's .venv for the engine.
set -e
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
APP="dist/Wispr Local.app"
swift build -c release 2>&1 | grep -v "^\[" || true
BIN=".build/release/WisprLocal"
[ -x "$BIN" ] || { echo "build failed"; exit 1; }
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/WisprLocal"
sed -e "s|__PYTHON__|$ROOT/.venv/bin/python|" -e "s|__BACKEND__|$ROOT|" Info.plist > "$APP/Contents/Info.plist"
[ -f AppIcon.icns ] && cp AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
codesign --force --deep --sign - "$APP" 2>/dev/null || true
echo "built: $(pwd)/$APP"
