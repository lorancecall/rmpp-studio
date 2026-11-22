# How rmpp-studio works

| Part | Where | What |
|---|---|---|
| `tablet/rmpp-remote.c` | `/usr/lib/rmpp/rmpp-remote/rmpp-remote` | Writes `input_event`s straight into the digitizer nodes (`/dev/input/event2` "Elan marker input" = pen, `/dev/input/event3` "Elan touch input" = touch, multitouch protocol B). Writing to an evdev node injects the events into that device, so xochitl reads them like hardware input (no uinput device, nothing hot-plugged). Also the client for the add-on socket. |
| `addon/remote.cpp` | `/usr/lib/rmpp/rmpp-remote/librmpp-remote.so`, linked as `/usr/lib/rmpp/preload.d/40-rmpp-remote.so` | LD_PRELOAD add-on in xochitl. Listens on the abstract unix socket `@rmpp-remote`. `QQuickWindow::grabWindow()` for screenshots/frames (own 8-bit grayscale PNG encoder: xochitl's Qt ships no PNG writer plugin), item tree / search / hit test, `QInputMethodEvent` / `QKeyEvent` to the focused item, a log of the pointer events Qt received. |
| `rmpp_ctl.py`, `rmpp-ctl.py` | PC (Python 3 + Pillow; ffmpeg for MP4) | Library + CLI and tutorial runner. One `ssh` call per command (~0.3 s). |
| `rmpp-studio.pyw`, `studio/` | PC (PySide6) | GUI on top of `rmpp_ctl`. |

Why these choices (measured on OS 3.29):
- **Screen**: there is no `/dev/fb*`; `/dev/dri/card0` drives the e-paper panel with a 405x1084 "mode" (packed
  waveform data, not pixels), so reading DRM/framebuffer memory does not give an image. Grabbing the QQuickWindow
  gives the real 1620x2160 picture (about 200 ms per grab), exactly what xochitl renders (toolbar flipped when the UI
  is flipped, selection menus, dialogs). Frames are only written when the screen changed, so long recordings stay small.
- **Input**: writing to the existing evdev nodes is simpler than uinput (xochitl keeps the nodes open and would have
  to discover a new device) and goes through xochitl's normal pen path (ink, lasso, palm rejection). Text goes
  through the add-on because the tablet has no keyboard device unless a Type Folio is attached.
- **Coordinates**: the default screen-to-device maps (pen 11180x15340, touch 2064x2832 over 1620x2160) were checked
  with `pointers` (injected (200,1900) arrived at (200,1899)). If a future OS changes this, write
  `/home/root/.config/rmpp-remote/cal` with two lines `pen ax bx cx ay by cy` and `touch ...`
  (device = a·x + b·y + c).

Screen capture details and the history of the window grab: [capture.md](capture.md).
