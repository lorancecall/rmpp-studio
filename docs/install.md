# Installing rmpp-studio

The usual way: the app from the [latest release](https://github.com/lorancecall/rmpp-studio/releases/latest), and the
Paper Pro part rmpp-remote from **rmpp setup** ([rmpp-packages](https://github.com/lorancecall/rmpp-packages#install)),
as the desktop app or the script: tick **Remote control for rmpp-studio**. This page covers the rest. Steps that are
the same for every rmpp add-on live in rmpp-packages and are linked here, not repeated.

## Packages

| Part | How it is installed | Installs with it |
|---|---|---|
| `rmpp-remote` (Paper Pro) | rmpp setup, or `vellum add rmpp-remote` | `rmpp-preload` |
| rmpp-studio, rmpp-ctl (computer) | the release files below | - |

All packages and what needs what: [packages.md](https://github.com/lorancecall/rmpp-packages/blob/main/docs/packages.md).

## Without rmpp setup

- **Vellum:** [manual-install.md](https://github.com/lorancecall/rmpp-packages/blob/main/docs/manual-install.md)
  (Vellum and the rmpp package repository), then on the Paper Pro `vellum add rmpp-remote`.
- **From the app:** Tablet > Install / update rmpp-remote does the same (`vellum add`, or `vellum upgrade` when it is
  installed) when Vellum and the rmpp package repository are on the Paper Pro. Without them it copies the files
  bundled with the app instead, which Vellum does not track (Restore does not bring them back). It refuses after 3
  xochitl restarts in 10 minutes and needs `rmpp-preload` 0.2.0 or newer.
- **By hand:** `./deploy.sh rmpp` from a checkout ([below](#build-and-install-by-hand)), for development; Vellum does
  not track it either.

Every way puts the add-on in `/usr/lib/rmpp/rmpp-remote` with the link `/usr/lib/rmpp/preload.d/40-rmpp-remote.so`
and moves an older `/usr/lib/rmpp-remote` (rmpp-studio 0.3.x) out of the way.

## Uninstall

- **Just rmpp-remote:** untick it in rmpp setup and press **Remove unticked installed**, or `vellum del rmpp-remote`
  on the Paper Pro, or Tablet > Remove rmpp-remote in the app. A copy the app or `./deploy.sh` made without Vellum:
  Tablet > Remove in the app, or `./deploy.sh rmpp --remove`.
- **What stays:** the optional calibration file `/home/root/.config/rmpp-remote/cal`, if you made one.
- **The app:** uninstall it like any app (Windows: Settings > Apps; Linux: your package manager; macOS: move it to
  the Trash). Recordings stay in `Documents\rmpp-studio`.
- **Everything rmpp, and before a factory reset:** [uninstall.md](https://github.com/lorancecall/rmpp-packages/blob/main/docs/uninstall.md).

## Next to other mods

rmpp-remote runs next to xovi and other Vellum packages: [how-it-works.md](https://github.com/lorancecall/rmpp-packages/blob/main/docs/how-it-works.md#next-to-other-mods).
It injects input as a real pen and finger, so do not run two remote-control tools at once.

## The app and rmpp-ctl

- **Windows**: `rmpp-studio-setup-<version>.exe` from the release (per-user, no admin rights). It installs the app and
  the `rmpp-ctl` command (a self-contained program in `…\rmpp-studio\cli`, no Python needed) and, with the
  default option "Add the rmpp-ctl command to PATH", adds that folder to your user PATH; uninstalling removes it.
- **Linux** (x86_64; Ubuntu 22.04+, Debian 12+, Linux Mint 21+, Fedora, RHEL / Rocky / Alma 9+, openSUSE, Arch, ...;
  glibc 2.34 or newer), from the release:
  - `.deb` (Ubuntu, Debian, Mint, Pop!_OS): `sudo apt install ./rmpp-studio_<version>_amd64.deb`
  - `.rpm` (Fedora, RHEL / Rocky / Alma, openSUSE): `sudo dnf install ./rmpp-studio-<version>-1.x86_64.rpm`
    (openSUSE: `sudo zypper install --allow-unsigned-rpm ./rmpp-studio-...rpm`)
  - `.AppImage` (any distribution, the GUI only): `chmod +x`, then run it
  - `.tar.gz` (any distribution, GUI + `rmpp-ctl`): unpack, run `./rmpp-studio` or `./rmpp-ctl`

  The packages install to `/opt/rmpp-studio` with `rmpp-studio` and `rmpp-ctl` in `/usr/bin` and a menu entry.
- **macOS** (14 Sonoma or newer; Apple Silicon `arm64` or Intel `x86_64`): `rmpp-studio-<version>-macos-<arch>.dmg`,
  drag the app to Applications. It is not notarized: the first start needs right click > Open (or
  `xattr -dr com.apple.quarantine /Applications/rmpp-studio.app`). The command-line tool is
  `rmpp-ctl-<version>-macos-<arch>.tar.gz`.
- **macOS / Linux from source**: from this checkout, `./install.sh` (python3 ≥ 3.9). It makes its own venv in
  `~/.local/share/rmpp-studio` (PySide6 + Pillow, nothing installed into your system Python), puts `rmpp-studio` and
  `rmpp-ctl` in its `bin/`, and adds that folder to PATH in your shell startup files (`~/.profile`, `~/.bashrc`,
  `~/.zshrc`, fish), marked with a comment. `./install.sh --cli-only` skips Qt; `./install.sh --uninstall` removes
  the venv, the commands and the PATH lines. On Linux it also adds a menu entry.
- **From the checkout** (any OS): `pip install PySide6 pillow`, then

```sh
rmpp-studio.cmd              # Windows; elsewhere: python3 rmpp-studio.pyw
```

On first start a **connection dialog** asks how to reach the Paper Pro (later: **Connection...** or Tablet > Connection): pick a profile from `~/.ssh/config` (ones that look like a Paper Pro first), or enter host / port / user / key directly (**USB cable** fills in 10.11.99.1). **Set up key login** creates a key (`~/.ssh/id_ed25519_rmpp_studio`) and appends it to the Paper Pro's `authorized_keys`; the root password is typed into ssh's own console window, never into rmpp-studio. **Test connection** checks SSH, rmpp-preload and the add-on.

The installed app needs only Windows' own OpenSSH client (`ssh` with a key for the Paper Pro in `~/.ssh`) and, for MP4,
ffmpeg (`winget install Gyan.FFmpeg`). **Tablet > Install / update rmpp-remote on the tablet** copies the bundled
Paper Pro add-on and tool and restarts xochitl (it refuses after 3 restarts in 10 minutes). User files go to
`Documents\rmpp-studio` (`recordings`, `out`, `tutorials`, with the example tutorial copied there on first start).

Build the installer (Python with Pillow + PySide6 + PyInstaller, Inno Setup 6, Paper Pro binaries from `./build.sh`):

```sh
powershell -ExecutionPolicy Bypass -File windows/build.ps1   # -> dist/rmpp-studio-setup-<version>.exe
```

The icon is drawn by `windows/make_icon.py`. The Linux and macOS release files are built by GitHub Actions
(`.github/workflows/build.yml`: `unix/build.sh`, then `unix/package-linux.sh` / `unix/package-macos.sh`, then
`unix/smoke-test.sh` in Ubuntu, Debian, Fedora, Rocky, openSUSE and Arch containers); it takes the Paper Pro binaries
from the draft release and uploads its files there.

## Build and install by hand

```sh
./build.sh                 # cross-build with ../sdk (Arm GNU aarch64 + Qt 6.10 headers + device Qt libs)
./deploy.sh rmpp           # copy to the Paper Pro, link into /usr/lib/rmpp/preload.d, restart xochitl
./deploy.sh rmpp --remove  # take it out again
```

`deploy.sh` restarts xochitl (after `systemctl reset-failed`; xochitl reboots the Paper Pro after more than 4
restarts in 10 minutes). A restart locks the Paper Pro when a passcode is set: unlock it by hand.
