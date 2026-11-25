# rmpp-studio

![rmpp-studio: live Paper Pro view, preview of the result with captions, clip timeline](docs/rmpp-studio.png)

*rmpp-studio with a recording open: LIVE view of the Paper Pro (click to tap or draw), PREVIEW of the edited result with
its caption, the clip timeline below, and the caption list on the right.*

Record, edit and export tutorials for the reMarkable Paper Pro, and drive the Paper Pro from a PC over SSH (by hand, by
script, or by an AI agent). Editing and exporting recordings works without a Paper Pro; everything that looks at or
touches the Paper Pro needs rmpp-remote on it.

Made for and tested on the reMarkable Paper Pro with OS 3.29.1. Other reMarkable models are not supported.
Updates for newer OS versions may take some time to follow.

> The Paper Pro part, rmpp-remote, is one of the **rmpp add-ons**, built on
> [rmpp-packages](https://github.com/lorancecall/rmpp-packages): it is installed by rmpp setup and loaded into
> xochitl at every boot by rmpp-preload (no xovi). How that differs from xovi:
> [how it works](https://github.com/lorancecall/rmpp-packages/blob/main/docs/how-it-works.md).

| Part | Runs on | What |
|---|---|---|
| **rmpp-studio** | PC (Windows, macOS, Linux) | A small video editor for Paper Pro tutorials: LIVE monitor you can click on, PREVIEW of the result, clip timeline, captions, export to MP4 / WebM / MOV / GIF / WebP / APNG. |
| **rmpp-ctl** | PC, command line | The same functions as commands and tutorial scripts (`.tut`): tap, draw, type, find UI items, screenshots, recording, rendering. |
| **rmpp-remote** | the Paper Pro | What does the work: an add-on inside xochitl (screen capture from the e-paper framebuffer, recording, UI lookup, text input, active pen) and a small tool (pen / touch input, real pen and finger positions). Installed with rmpp setup, or from rmpp-studio (Tablet > Install). |

## Install

Start at **[rmpp-packages](https://github.com/lorancecall/rmpp-packages#install)**: it explains developer mode and
has **rmpp setup**, the installer for all rmpp add-ons, including rmpp-studio's Paper Pro part.

- In rmpp setup (the desktop app or the script), tick **Remote control for rmpp-studio** (rmpp-remote; not selected
  by default). It installs `rmpp-preload` first ([all packages and dependencies](https://github.com/lorancecall/rmpp-packages/blob/main/docs/packages.md)).
- The app on your computer, from the [latest release](https://github.com/lorancecall/rmpp-studio/releases/latest):
  Windows `rmpp-studio-setup-<version>.exe`; Linux `.deb`, `.rpm`, `.AppImage` or `.tar.gz`; macOS `.dmg` (not
  notarized: right click > Open the first time). Its connection dialog finds the Paper Pro (**USB cable** = 10.11.99.1).
- After a reMarkable OS update: **Restore** in rmpp setup.
- Without rmpp setup, removing it, next to other mods, `rmpp-ctl`, from source, building:
  [docs/install.md](docs/install.md).

## Use

- **The app** ([details](docs/gui.md)): LIVE view of the Paper Pro you can click on (tap, draw, type), PREVIEW of the
  edited result, clip timeline, captions, export to MP4 / WebM / MOV / GIF / WebP / APNG.
- **`rmpp-ctl`** ([details](docs/cli.md)): the same as commands and tutorial scripts:

  ```sh
  rmpp-ctl shot screen.png
  rmpp-ctl tap '#undoButton'
  rmpp-ctl run tutorials/lasso-move.tut -o out/lasso-move.gif
  ```

- **Tutorials:** [tutorials/README.md](tutorials/README.md) and the example
  [tutorials/lasso-move.tut](tutorials/lasso-move.tut) ([gif](examples/lasso-move.gif)).

## How it works

rmpp-remote is an add-on inside xochitl (screen capture from the e-paper framebuffer, UI lookup, text input) plus a
small tool that writes pen and touch events into the digitizer devices, so xochitl reads them like real input. The
PC side talks to it over SSH, one call per command. Details and measurements: [docs/how-it-works.md](docs/how-it-works.md);
screen capture: [docs/capture.md](docs/capture.md).

## Build

Building the Paper Pro part, the app and the installers, and the development install:
[docs/install.md](docs/install.md#rmpp-remote-by-hand-development).

## Safety notes

- Injected input is real input: a wrong coordinate taps whatever is there. Run scripts in a notebook made for
  testing, start tutorials with `setup expect ...` so they stop on the wrong screen, and do not touch the Paper Pro
  while a script runs (real and injected touches mix).
- Recordings and screenshots show whatever is on screen (file names in the library, account e-mail in Settings).
  Check them before sharing.
- The pointer log (`pointers`) is cleared and paused while the passcode screen has focus.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
