#!/bin/zsh
# Builds macos/dist/Wispr Local.app; --install also copies it to /Applications.
# The bundle points at this repo's .venv and source for the engine, so keep the repo in place.
set -e
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
APP="dist/Wispr Local.app"
if ! swift build -c release 2>&1 | grep -v "^\["; then :; fi
[ "${pipestatus[1]}" -eq 0 ] || { echo "build failed"; exit 1; }
BIN=".build/release/WisprLocal"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/WisprLocal"
sed -e "s|__PYTHON__|$ROOT/.venv/bin/python|" -e "s|__BACKEND__|$ROOT|" Info.plist > "$APP/Contents/Info.plist"
[ -f AppIcon.icns ] && cp AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
# Sign with an Apple Development identity when one exists: its designated requirement
# (team id + bundle id) is stable, so Accessibility/Microphone grants survive rebuilds.
# Ad-hoc signatures change every build and macOS then treats the app as new.
IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null | grep -o '"Apple Development[^"]*"' | head -1 | tr -d '"')
if [ -n "$IDENTITY" ]; then
  codesign --force --deep --sign "$IDENTITY" "$APP" && echo "signed: $IDENTITY"
else
  codesign --force --deep --sign - "$APP" && echo "signed: ad-hoc (permissions reset on each rebuild)"
fi
echo "built: $(pwd)/$APP"

# --install copies the bundle into /Applications (or ~/Applications if that is not writable).
if [[ "$1" == "--install" ]]; then
  DEST="/Applications"; [ -w "$DEST" ] || DEST="$HOME/Applications"
  mkdir -p "$DEST"
  osascript -e 'tell application "Wispr Local" to quit' 2>/dev/null || true
  rm -rf "$DEST/Wispr Local.app"
  cp -R "$APP" "$DEST/"
  echo "installed: $DEST/Wispr Local.app"
fi
