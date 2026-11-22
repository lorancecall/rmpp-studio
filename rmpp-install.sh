#!/bin/sh
# Install rmpp-remote (rmpp-studio's tablet part) from the files next to this script: the rmpp installer
# (rmpp setup, https://github.com/lorancecall/rmpp-packages) downloads the release assets on the computer, copies
# them into one folder on the tablet and runs this script there as root.
# The same layout as rmpp-studio's Tablet > Install (rmpp_ctl.INSTALL_SCRIPT): /usr/lib/rmpp/rmpp-remote, linked as
# /usr/lib/rmpp/preload.d/40-rmpp-remote.so; needs rmpp-preload 0.2.0+ (the installer installs it first).
set -e
cd "$(dirname "$0")"
P=/usr/lib/rmpp
D=$P/rmpp-remote
[ -x "$P/launch" ] || { echo "rmpp-preload 0.2.0 or newer is needed (/usr/lib/rmpp/launch missing)"; exit 3; }
# Plain remount: Vellum's mount-rw would drop the /etc/dropbear bind mount (SSH host key).
mount -o remount,rw /
# rmpp-studio 0.3.x (and its old name rmpp-tester) installed to /usr/lib: set aside, deleted after the restart
for o in /usr/lib/rmpp-remote /usr/lib/rmpp-tester; do
	[ ! -e "$o" ] || { mkdir -p "$P/.trash" && mv "$o" "$P/.trash/$(echo "${o#/}" | tr / _).$$"; }
done
rm -f /usr/lib/rmpp-preload.d/40-rmpp-remote.so /usr/lib/rmpp-preload.d/40-rmpp-tester.so
rmdir /usr/lib/rmpp-preload.d 2>/dev/null || true
mkdir -p "$D" "$P/preload.d"
# a library or program that is in use is renamed to *.old, never deleted ($P/restart deletes it after the restart)
for f in librmpp-remote.so rmpp-remote; do
	cp "$f" "$D/$f.new" && chmod 755 "$D/$f.new" &&
		{ [ ! -e "$D/$f" ] || mv -f "$D/$f" "$D/$f.old"; } &&
		mv -f "$D/$f.new" "$D/$f"
done
ln -sfn ../rmpp-remote/librmpp-remote.so "$P/preload.d/40-rmpp-remote.so"
# running rmpp-remote programs (rmpp-studio's pointer stream) still run the old binary: while they hold the deleted
# *.old file, / cannot go back to read-only after the restart. rmpp-studio reconnects by itself.
R=$(pidof rmpp-remote) || true
[ -z "$R" ] || kill $R 2>/dev/null || true
sync
mount -o remount,ro / || echo "note: / stays read-write until xochitl restarts"
# never `systemctl stop xochitl` (it powers the tablet off). Share one xochitl restart with the Vellum packages
# installed just before: (re)arm their timer, which runs $P/restart (reset-failed, restart, clean up).
systemctl stop rmpp-restart-xochitl.timer 2>/dev/null || true
systemd-run --quiet --unit=rmpp-restart-xochitl --on-active=15 --timer-property=AccuracySec=1s \
	/bin/sh -c '[ -x /usr/lib/rmpp/restart ] && exec /usr/lib/rmpp/restart; systemctl reset-failed xochitl; systemctl restart xochitl' || \
	{ systemctl reset-failed xochitl 2>/dev/null || true; systemctl restart xochitl; }
echo "xochitl restarts in about 15 seconds"
echo "rmpp-remote installed"
