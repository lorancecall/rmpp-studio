#!/bin/sh
# Copy build/ to the tablet and restart xochitl so the add-on loads (the same as rmpp-studio's Tablet > Install).
#   ./deploy.sh [ssh-host]          (default: $RMPP_HOST or "rmpp")
#   ./deploy.sh [ssh-host] --remove (take the add-on out again)
# Needs rmpp-preload 0.2.0+ (/usr/lib/rmpp). Installs to /usr/lib/rmpp/rmpp-remote, linked as
# /usr/lib/rmpp/preload.d/40-rmpp-remote.so; an older /usr/lib/rmpp-remote is moved out of the way. xochitl restarts
# once through /usr/lib/rmpp/restart (reset-failed first; it reboots the tablet after more than 4 restarts in 10 min).
set -e
cd "$(dirname "$0")"
HOST=${1:-${RMPP_HOST:-rmpp}}
PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || PY=python
"$PY" - "$HOST" "${2:-}" <<'PYEOF'
import sys
sys.path.insert(0, ".")
import rmpp_ctl as ctl
tab = ctl.Tablet(sys.argv[1])
if sys.argv[2] == "--remove":
    print(ctl.remove_tablet(tab))
else:
    print(ctl.install_tablet(tab, "build/librmpp-remote.so", "build/rmpp-remote"))
PYEOF
