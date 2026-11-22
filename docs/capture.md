# Screen capture: framebuffer copy (default) vs window grab

**Fixed (2026-11-11):** captures now copy xochitl's e-paper framebuffer instead of rendering the scene again
(`ui source fb`, the default). xochitl's `EPFramebuffer` object (the source Screen Share reads from) is not in the
object tree, so the add-on interposes `QMetaObject::activate` (xochitl calls it through the dynamic linker): when
an `EPFramebuffer` emits a signal, the add-on keeps the sender. Inside it is the panel image (a 1620x2160 RGB32
`QImage`, found by comparing the object's words with QImage's vtable); a shot copies its rows. Recording copies a
frame only when `framebufferUpdated(QRect)` fired since the last one. Test with the developer: 60 s at 4 fps with
page turns, quick-settings taps and fast pen scribbles, no freeze (the window grab froze the panel within 10-30 s
under the same conditions). `ui epfb` shows what the hook found. Until the first screen update after a xochitl start
the framebuffer is unknown and a shot falls back to one window grab. `ui source window` brings back the old method.

## History: the window grab froze the e-paper display


Reproduced on 2026-11-11 in a controlled test (one capture process only, the developer using the Paper Pro):

| Phase | Captures | Developer's input | Result |
|---|---|---|---|
| 1 | `ui shot` once per second, 40 s | page turns, menus, fast pen scribbles, finger taps | display kept updating |
| 2 | `rec start ... 4` (about 3.5 grabs/s), 40 s | same; quick finger taps on the quick-settings corner, fast pen scratching | display froze after 10-15 s and stayed frozen after the captures stopped |

While frozen, xochitl kept working: input was handled and `ui shot` showed the new UI state (Qt still renders),
the e-paper threads (framegen, vsync-flip, swt-*, EPFramebufferQueue) all sat idle on futexes, and only a xochitl
restart brought the panel back. So `QQuickWindow::grabWindow()` (a second render of the scene on the GUI thread)
sometimes leaves xochitl's e-paper update pipeline waiting for an update that never comes, more likely the more often
it runs and when it coincides with fast partial updates (pen, animations). The earlier freeze (four minutes at about
one grab per second from two processes) fits this.

Re-test the same day (experiments run inside xochitl with the add-on's dev loader, `ui "load <so> [arg]"`):
the freeze came back after 28 s at 4 fps. While frozen: xochitl's full refresh (`GhostBuster_Gallery3.userRequestedClear()`)
did reach the panel once (it flashed) but normal updates stayed stuck; `QQuickWindow::update()`, `requestUpdate()`,
an expose event and dirtying every item did not help; only a restart did. So the stall is in xochitl's own e-paper
partial-update path, not in Qt's render loop. `QScreen::grabWindow()` (`ui "source screen"`) returns nothing on this
platform plugin, and xochitl's `EPFramebuffer` object is not reachable from the QObject tree.

Until there is a safe capture path: keep **Live** off (default), prefer single shots, keep recordings short and slow
(1-2 fps), and restart xochitl if the panel freezes. Next: capture without re-rendering (`QScreen::grabWindow()` /
the epaper plugin's framebuffer) and repeat the phase 2 test.
