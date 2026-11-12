#!/bin/sh
# Release files for Linux from dist/ (after unix/build.sh), in dist/release/:
#   rmpp-studio_<v>_amd64.deb             Ubuntu, Debian, Linux Mint, Pop!_OS, ...
#   rmpp-studio-<v>-1.x86_64.rpm          Fedora, RHEL / Rocky / Alma, openSUSE
#   rmpp-studio-<v>-x86_64.AppImage       any distribution (GUI only)
#   rmpp-studio-<v>-linux-x86_64.tar.gz   any distribution (GUI + rmpp-ctl, unpack and run)
# Needs: nfpm (deb / rpm), appimagetool (AppImage), python3 with Pillow (icon sizes).
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' rmpp_ctl.py)
export VERSION
ARCH=$(uname -m)
OUT=dist/release
STAGE=build/linux-stage
rm -rf "$STAGE" "$OUT"
mkdir -p "$OUT" "$STAGE/icons"

for s in 48 128 256 512; do
    "$PY" -c "import sys; from PIL import Image; Image.open('windows/rmpp-studio.png').resize((int(sys.argv[1]),) * 2, Image.LANCZOS).save(sys.argv[2])" \
        "$s" "$STAGE/icons/$s.png"
done

# deb + rpm: /opt/rmpp-studio/{app,cli}, commands in /usr/bin, menu entry and icons (unix/nfpm.yaml)
nfpm package --config unix/nfpm.yaml --packager deb --target "$OUT/"
nfpm package --config unix/nfpm.yaml --packager rpm --target "$OUT/"

# AppImage (the GUI)
APPDIR=$STAGE/AppDir
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -R dist/rmpp-studio "$APPDIR/usr/lib/rmpp-studio"
cp unix/rmpp-studio.desktop "$APPDIR/rmpp-studio.desktop"
cp "$STAGE/icons/256.png" "$APPDIR/rmpp-studio.png"
cp "$STAGE/icons/256.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/rmpp-studio.png"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
exec "$HERE/usr/lib/rmpp-studio/rmpp-studio" "$@"
EOF
chmod 755 "$APPDIR/AppRun"
ARCH=$ARCH appimagetool --no-appstream "$APPDIR" "$OUT/rmpp-studio-$VERSION-$ARCH.AppImage"

# tar.gz: unpack anywhere, run ./rmpp-studio or ./rmpp-ctl
T=rmpp-studio-$VERSION-linux-$ARCH
mkdir -p "$STAGE/$T"
cp -R dist/rmpp-studio "$STAGE/$T/app"
cp -R dist/rmpp-ctl "$STAGE/$T/cli"
ln -s app/rmpp-studio "$STAGE/$T/rmpp-studio"
ln -s cli/rmpp-ctl "$STAGE/$T/rmpp-ctl"
cp unix/rmpp-studio.desktop "$STAGE/$T/"
cp "$STAGE/icons/256.png" "$STAGE/$T/rmpp-studio.png"
cp LICENSE "$STAGE/$T/"
tar -C "$STAGE" -czf "$OUT/$T.tar.gz" --owner=0 --group=0 "$T"

ls -la "$OUT"
