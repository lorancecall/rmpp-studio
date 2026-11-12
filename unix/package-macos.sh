#!/bin/sh
# Release files for macOS from dist/ (after unix/build.sh), in dist/release/:
#   rmpp-studio-<v>-macos-<arch>.dmg      the app (drag it to Applications)
#   rmpp-ctl-<v>-macos-<arch>.tar.gz      the command-line tool, one folder
# Not notarized: the first start needs right click > Open (or: xattr -dr com.apple.quarantine <path>).
set -e
cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' rmpp_ctl.py)
case "$(uname -m)" in arm64) ARCH=arm64 ;; *) ARCH=x86_64 ;; esac
OUT=dist/release
STAGE=build/macos-stage
rm -rf "$STAGE" "$OUT"
mkdir -p "$OUT" "$STAGE/dmg"

cp -R dist/rmpp-studio.app "$STAGE/dmg/"
ln -s /Applications "$STAGE/dmg/Applications"
hdiutil create -volname "rmpp-studio $VERSION" -srcfolder "$STAGE/dmg" -fs HFS+ -format UDZO -ov \
    "$OUT/rmpp-studio-$VERSION-macos-$ARCH.dmg"

T=rmpp-ctl-$VERSION-macos-$ARCH
mkdir -p "$STAGE/$T"
cp -R dist/rmpp-ctl/ "$STAGE/$T/"
cp LICENSE "$STAGE/$T/"
tar -C "$STAGE" -czf "$OUT/$T.tar.gz" "$T"

ls -la "$OUT"
