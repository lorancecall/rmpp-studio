#!/bin/sh
# Copy build/ to the tablet and restart xochitl so the add-on loads.
#   ./deploy.sh [ssh-host]          (default: $RMPP_HOST or "rmpp")
#   ./deploy.sh [ssh-host] --remove (take the add-on out again)
# The root fs is read-only: remount rw, copy to .new + mv, remount ro. `systemctl reset-failed` before each
# restart, because xochitl reboots the tablet after more than 4 restarts in 10 minutes.
set -e
cd "$(dirname "$0")"
HOST=${1:-${RMPP_HOST:-rmpp}}
if [ "$2" = "--remove" ]; then
  ssh "$HOST" 'mount -o remount,rw / && rm -f /usr/lib/rmpp-preload.d/40-rmpp-remote.so && rm -rf /usr/lib/rmpp-remote;
    sync; systemctl reset-failed xochitl; systemctl restart xochitl; sleep 5; mount -o remount,ro /; echo removed'
  exit
fi
ssh "$HOST" mkdir -p /tmp/rmpp-remote-new
scp -q build/librmpp-remote.so build/rmpp-remote "$HOST":/tmp/rmpp-remote-new/
ssh "$HOST" 'set -e
  D=/usr/lib/rmpp-remote
  mount -o remount,rw /
  mkdir -p $D
  for f in librmpp-remote.so rmpp-remote; do cp /tmp/rmpp-remote-new/$f $D/$f.new; chmod 755 $D/$f.new; mv $D/$f.new $D/$f; done
  rm -rf /tmp/rmpp-remote-new
  ln -sf $D/librmpp-remote.so /usr/lib/rmpp-preload.d/40-rmpp-remote.so
  rm -f /usr/lib/rmpp-preload.d/40-rmpp-tester.so; rm -rf /usr/lib/rmpp-tester   # its old name
  sync
  systemctl reset-failed xochitl; systemctl restart xochitl
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do sleep 1; $D/rmpp-remote ui ping >/dev/null 2>&1 && break; done
  P=$(pidof rmpp-remote); [ -n "$P" ] && kill $P; sleep 1   # a pointer stream (watch) keeps the old binary open
  mount -o remount,ro / || echo "warning: / is still read-write"
  $D/rmpp-remote ui info'
