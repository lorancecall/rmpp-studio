#!/bin/sh
# Build the self-contained macOS / Linux programs with PyInstaller (what windows/build.ps1 does for Windows):
#   dist/rmpp-studio/      Linux: the GUI, one folder (dist/rmpp-studio/rmpp-studio)
#   dist/rmpp-studio.app   macOS: the GUI as an app bundle
#   dist/rmpp-ctl/         the command-line tool, one folder (Python + Pillow, no Qt)
# Needs: python3 with PySide6, Pillow and PyInstaller; the tablet binaries in build/ (./build.sh, or downloaded).
# Then unix/package-linux.sh or unix/package-macos.sh makes the release files.
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' rmpp_ctl.py)
echo "rmpp-studio $VERSION ($(uname -s) $(uname -m))"
for f in build/librmpp-remote.so build/rmpp-remote; do
    [ -f "$f" ] || { echo "$f missing: run ./build.sh first"; exit 1; }
done

EXCLUDES="--exclude-module numpy --exclude-module PIL.ImageQt --exclude-module tkinter"
QT_EXCLUDES="--exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtCharts"
EXTRA=
if [ "$(uname -s)" = Darwin ]; then
    EXTRA="--icon $PWD/windows/rmpp-studio.png --osx-bundle-identifier io.github.lorancecall.rmpp-studio"
fi

# shellcheck disable=SC2086
"$PY" -m PyInstaller --noconfirm --clean --windowed --name rmpp-studio $EXTRA \
    --add-data "$PWD/windows/rmpp-studio.png:." \
    --add-data "$PWD/windows/pen-cursor.png:." \
    --add-data "$PWD/tutorials/*.tut:tutorials" \
    --add-data "$PWD/build/librmpp-remote.so:tablet" \
    --add-data "$PWD/build/rmpp-remote:tablet" \
    $EXCLUDES $QT_EXCLUDES \
    --distpath dist --workpath build/pyinstaller --specpath build/pyinstaller \
    rmpp-studio.pyw

# shellcheck disable=SC2086
"$PY" -m PyInstaller --noconfirm --clean --console --name rmpp-ctl \
    $EXCLUDES --exclude-module PySide6 \
    --distpath dist --workpath build/pyinstaller-cli --specpath build/pyinstaller-cli \
    rmpp-ctl.py

if [ "$(uname -s)" = Darwin ]; then
    # the version in Finder's Get Info, then sign again (ad hoc; changing Info.plist breaks PyInstaller's signature)
    PLIST=dist/rmpp-studio.app/Contents/Info.plist
    plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
    plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
    plutil -replace NSHighResolutionCapable -bool true "$PLIST"
    codesign --force --deep --sign - dist/rmpp-studio.app
fi
ls -la dist
