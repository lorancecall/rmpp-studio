#!/bin/sh
# rmpp-studio for macOS and Linux: rmpp-studio (GUI) and rmpp-ctl (CLI) in their own Python venv, with both
# commands on PATH. (Windows: use the installer, rmpp-studio-setup-<version>.exe.)
#
#   ./install.sh               install or update (needs python3 >= 3.9 with venv)
#   ./install.sh --cli-only    only rmpp-ctl (no Qt download)
#   ./install.sh --uninstall   remove the venv, the commands and the PATH lines
#
# Everything goes to $RMPP_STUDIO_HOME (default ~/.local/share/rmpp-studio): venv/, app/, bin/. The bin folder is
# added to PATH in your shell startup files (bash, zsh, fish, ~/.profile), marked with a comment so --uninstall can
# take it out again. Recordings and exports go to ~/Documents/rmpp-studio. Video export needs ffmpeg (brew install
# ffmpeg / apt install ffmpeg).
set -e
SRC=$(cd "$(dirname "$0")" && pwd)
PREFIX=${RMPP_STUDIO_HOME:-$HOME/.local/share/rmpp-studio}
BIN=$PREFIX/bin
MARK="# rmpp-studio: added by install.sh"
FISH_CONF=$HOME/.config/fish/conf.d/rmpp-studio.fish
DESKTOP=$HOME/.local/share/applications/rmpp-studio.desktop

say() { printf '%s\n' "$*"; }

rc_files() {
    # the files a new terminal reads: login (.profile, .bash_profile, .zprofile) and interactive (.bashrc, .zshrc)
    for f in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.zprofile"; do
        [ -f "$f" ] && printf '%s\n' "$f"
    done
    case "${SHELL:-}" in   # make sure the user's own shell gets one even if its file does not exist yet
        */zsh) [ -f "$HOME/.zshrc" ] || printf '%s\n' "$HOME/.zshrc" ;;
        */bash) [ -f "$HOME/.bashrc" ] || printf '%s\n' "$HOME/.bashrc" ;;
    esac
    [ -f "$HOME/.profile" ] || printf '%s\n' "$HOME/.profile"
}

remove_path_lines() {
    for f in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.zprofile"; do
        [ -f "$f" ] || continue
        if grep -q "$MARK" "$f"; then
            grep -v "$MARK" "$f" > "$f.rmpp-tmp" && cat "$f.rmpp-tmp" > "$f" && rm -f "$f.rmpp-tmp"
            say "  PATH line removed from $f"
        fi
    done
    rm -f "$FISH_CONF"
}

if [ "${1:-}" = "--uninstall" ]; then
    say "Removing rmpp-studio from $PREFIX"
    remove_path_lines
    rm -f "$DESKTOP"
    rm -rf "$PREFIX"
    say "Done. Open a new terminal (the current one may still have the old PATH)."
    say "Your recordings in ~/Documents/rmpp-studio were kept."
    exit 0
fi

GUI=1
[ "${1:-}" = "--cli-only" ] && GUI=0

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || { say "python3 not found (macOS: install Python from python.org or brew install python; Linux: apt install python3 python3-venv)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { say "python3 >= 3.9 is needed"; exit 1; }

say "Installing rmpp-studio into $PREFIX"
mkdir -p "$PREFIX" "$BIN"
if [ ! -x "$PREFIX/venv/bin/python" ]; then
    "$PY" -m venv "$PREFIX/venv" || { say "could not create a venv (Debian/Ubuntu: apt install python3-venv)"; exit 1; }
fi
VPY=$PREFIX/venv/bin/python
"$VPY" -m pip install --quiet --upgrade pip
if [ $GUI = 1 ]; then
    "$VPY" -m pip install --quiet --upgrade pillow PySide6
else
    "$VPY" -m pip install --quiet --upgrade pillow
fi

# the program files (a copy, so the checkout can move or change)
rm -rf "$PREFIX/app"
mkdir -p "$PREFIX/app/build" "$PREFIX/app/windows"
cp "$SRC/rmpp_ctl.py" "$SRC/rmpp-ctl.py" "$SRC/rmpp-studio.pyw" "$PREFIX/app/"
cp -R "$SRC/studio" "$SRC/tutorials" "$PREFIX/app/"
cp "$SRC/windows/rmpp-studio.png" "$SRC/windows/pen-cursor.png" "$PREFIX/app/windows/"
for f in librmpp-remote.so rmpp-remote; do   # tablet files for Tablet > Install (built with ./build.sh)
    [ -f "$SRC/build/$f" ] && cp "$SRC/build/$f" "$PREFIX/app/build/"
done
rm -rf "$PREFIX/app/studio/__pycache__"

cat > "$BIN/rmpp-ctl" <<EOF
#!/bin/sh
exec "$VPY" "$PREFIX/app/rmpp-ctl.py" "\$@"
EOF
chmod 755 "$BIN/rmpp-ctl"
if [ $GUI = 1 ]; then
    cat > "$BIN/rmpp-studio" <<EOF
#!/bin/sh
RMPP_STUDIO_DATA="\${RMPP_STUDIO_DATA:-\$HOME/Documents/rmpp-studio}" exec "$VPY" "$PREFIX/app/rmpp-studio.pyw" "\$@"
EOF
    chmod 755 "$BIN/rmpp-studio"
    if [ "$(uname)" = "Linux" ]; then   # a launcher entry in the desktop's app menu
        mkdir -p "$(dirname "$DESKTOP")"
        cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=rmpp-studio
Comment=Record, edit and export reMarkable Paper Pro tutorials
Exec=$BIN/rmpp-studio
Icon=$PREFIX/app/windows/rmpp-studio.png
Categories=Utility;
EOF
    fi
else
    rm -f "$BIN/rmpp-studio"
fi

# PATH
LINE="export PATH=\"$BIN:\$PATH\"  $MARK"
for f in $(rc_files); do
    if ! grep -q "$MARK" "$f" 2>/dev/null; then
        # start on a fresh line when the file does not end with one (no blank line left behind on uninstall)
        [ -s "$f" ] && [ -n "$(tail -c 1 "$f")" ] && printf '\n' >> "$f"
        printf '%s\n' "$LINE" >> "$f"
        say "  PATH added in $f"
    fi
done
if command -v fish >/dev/null 2>&1 || [ -d "$HOME/.config/fish" ]; then
    mkdir -p "$(dirname "$FISH_CONF")"
    printf 'fish_add_path -g %s  %s\n' "$BIN" "$MARK" > "$FISH_CONF"
    say "  PATH added for fish ($FISH_CONF)"
fi

say ""
say "Installed: $(ls "$BIN" | tr '\n' ' ')"
say "Open a new terminal (or run: export PATH=\"$BIN:\$PATH\"), then: rmpp-ctl -h$( [ $GUI = 1 ] && echo ' / rmpp-studio')"
command -v ffmpeg >/dev/null 2>&1 || say "Note: ffmpeg not found; GIF / WebP / APNG export works, videos need ffmpeg."
