#!/bin/sh
# Install a Linux release file in a fresh distribution container and start the programs (CI, as root):
#   unix/smoke-test.sh deb|rpm-dnf|rpm-zypper|tar|appimage <release dir>
# The GUI runs on a virtual X display (Xvfb) for a few seconds; it passes when it is still running then and Qt
# reported no missing library or platform plugin. A screenshot goes to <release dir>/../smoke-<distro>.png.
set -e
KIND=$1
REL=$(cd "$2" && pwd)
. /etc/os-release
NAME=$ID-${VERSION_ID:-rolling}
echo "== $NAME ($KIND)"

case "$KIND" in
deb)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq "$REL"/rmpp-studio_*_amd64.deb xvfb >/dev/null
    apt-get install -y -qq x11-apps imagemagick >/dev/null || true
    STUDIO=rmpp-studio CTL=rmpp-ctl ;;
rpm-dnf)
    dnf install -y -q "$REL"/rmpp-studio-*.x86_64.rpm xorg-x11-server-Xvfb
    dnf install -y -q xwd ImageMagick || true
    STUDIO=rmpp-studio CTL=rmpp-ctl ;;
rpm-zypper)
    zypper -n --no-gpg-checks install -y --allow-unsigned-rpm "$REL"/rmpp-studio-*.x86_64.rpm xorg-x11-server-Xvfb
    zypper -n install -y xwd ImageMagick || true
    STUDIO=rmpp-studio CTL=rmpp-ctl ;;
tar|appimage)
    # a desktop's usual libraries (what the deb / rpm declare as dependencies)
    if command -v pacman >/dev/null; then
        pacman -Syu --noconfirm --needed mesa libglvnd fontconfig freetype2 ttf-dejavu libxkbcommon-x11 dbus \
            openssh xorg-server-xvfb xorg-xwd imagemagick tar gzip >/dev/null
    elif command -v apt-get >/dev/null; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq libgl1 libegl1 libfontconfig1 fonts-dejavu-core libxkbcommon-x11-0 libdbus-1-3 \
            openssh-client xvfb x11-apps imagemagick >/dev/null
    fi
    mkdir -p /tmp/rs && cd /tmp/rs
    if [ "$KIND" = tar ]; then
        tar -xzf "$REL"/rmpp-studio-*-linux-x86_64.tar.gz
        D=$(echo /tmp/rs/rmpp-studio-*)
        STUDIO=$D/rmpp-studio CTL=$D/rmpp-ctl
    else
        cp "$REL"/rmpp-studio-*-x86_64.AppImage ./rmpp-studio.AppImage && chmod +x rmpp-studio.AppImage
        export APPIMAGE_EXTRACT_AND_RUN=1   # containers have no FUSE
        STUDIO=/tmp/rs/rmpp-studio.AppImage CTL=
    fi ;;
*) echo "unknown kind $KIND"; exit 2 ;;
esac

if [ -n "$CTL" ]; then
    "$CTL" -h | head -3
fi

Xvfb :99 -screen 0 1600x1000x24 >/dev/null 2>&1 &
XVFB=$!
sleep 2
export DISPLAY=:99 QT_QPA_PLATFORM=xcb QT_DEBUG_PLUGINS=0 HOME=/tmp/home
mkdir -p "$HOME"
"$STUDIO" > /tmp/studio.log 2>&1 &
PID=$!
sleep 12
ALIVE=0
kill -0 $PID 2>/dev/null && ALIVE=1
xwd -root -display :99 2>/dev/null | convert xwd:- "$REL/../smoke-$NAME-$KIND.png" 2>/dev/null || true
kill $PID 2>/dev/null || true
kill $XVFB 2>/dev/null || true
cat /tmp/studio.log
if [ $ALIVE != 1 ] || grep -q -i -E "could not (load|find)|cannot open shared object|no Qt platform plugin" /tmp/studio.log; then
    echo "FAIL $NAME ($KIND)"
    exit 1
fi
echo "PASS $NAME ($KIND)"
