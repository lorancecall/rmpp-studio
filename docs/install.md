# Installing rmpp-studio

The usual way: the app from the [latest release](https://github.com/lorancecall/rmpp-studio/releases/latest), and the
tablet part rmpp-remote from **rmpp setup** ([rmpp-packages](https://github.com/lorancecall/rmpp-packages#install)),
which also sets up developer-mode SSH. This page has the details and the other ways.

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

On first start a **connection dialog** asks how to reach the tablet (later: **Connection...** or Tablet > Connection): pick a profile from `~/.ssh/config` (tablet-looking ones first), or enter host / port / user / key directly (**USB cable** fills in 10.11.99.1). **Set up key login** creates a key (`~/.ssh/id_ed25519_rmpp_studio`) and appends it to the tablet's `authorized_keys`; the root password is typed into ssh's own console window, never into rmpp-studio. **Test connection** checks SSH, rmpp-preload and the add-on.

The installed app needs only Windows' own OpenSSH client (`ssh` with a key for the tablet in `~/.ssh`) and, for MP4,
ffmpeg (`winget install Gyan.FFmpeg`). **Tablet > Install / update rmpp-remote on the tablet** copies the bundled
tablet add-on and tool and restarts xochitl (it refuses after 3 restarts in 10 minutes). User files go to
`Documents\rmpp-studio` (`recordings`, `out`, `tutorials`, with the example tutorial copied there on first start).

Build the installer (Python with Pillow + PySide6 + PyInstaller, Inno Setup 6, tablet binaries from `./build.sh`):

```sh
powershell -ExecutionPolicy Bypass -File windows/build.ps1   # -> dist/rmpp-studio-setup-<version>.exe
```

The icon is drawn by `windows/make_icon.py`. The Linux and macOS release files are built by GitHub Actions
(`.github/workflows/build.yml`: `unix/build.sh`, then `unix/package-linux.sh` / `unix/package-macos.sh`, then
`unix/smoke-test.sh` in Ubuntu, Debian, Fedora, Rocky, openSUSE and Arch containers); it takes the tablet binaries
from the draft release and uploads its files there.

## rmpp-remote on the tablet

- **rmpp setup**: tick rmpp-remote (not selected by default). Run it again to update.
- **From the app**: Tablet > Install / update rmpp-remote copies the tablet files bundled with the app and restarts
  xochitl (it refuses after 3 restarts in 10 minutes).
- Both put the add-on in `/usr/lib/rmpp/rmpp-remote` with the link `/usr/lib/rmpp/preload.d/40-rmpp-remote.so`
  (needs rmpp-preload 0.2.0 or newer, which rmpp setup installs) and move an older `/usr/lib/rmpp-remote`
  (rmpp-studio 0.3.x) out of the way.
- Removal: `./deploy.sh rmpp --remove` (below), or **Remove everything** in rmpp setup.

## rmpp-remote by hand (development)

```sh
./build.sh                 # cross-build with ../sdk (Arm GNU aarch64 + Qt 6.10 headers + device Qt libs)
./deploy.sh rmpp           # copy to the tablet, link into /usr/lib/rmpp/preload.d, restart xochitl
./deploy.sh rmpp --remove  # take it out again
```

`deploy.sh` restarts xochitl (after `systemctl reset-failed`; xochitl reboots the tablet after more than 4
restarts in 10 minutes). A restart locks the tablet when a passcode is set: unlock it by hand.
