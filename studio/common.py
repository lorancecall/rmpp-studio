"""Shared helpers: paths, settings, background jobs, image conversion, theme."""
import contextlib
import io
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPalette

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import rmpp_ctl as ctl  # noqa: E402

FROZEN = getattr(sys, "frozen", False)
RES = getattr(sys, "_MEIPASS", HERE)
if FROZEN:
    DATA = os.path.join(os.path.expanduser("~"), "Documents", "rmpp-studio")
    ICON = os.path.join(RES, "rmpp-studio.png")
    PEN_CURSOR = os.path.join(RES, "pen-cursor.png")
    TABLET_BIN = os.path.join(RES, "tablet")
else:
    DATA = HERE
    ICON = os.path.join(HERE, "windows", "rmpp-studio.png")
    PEN_CURSOR = os.path.join(HERE, "windows", "pen-cursor.png")
    TABLET_BIN = os.path.join(HERE, "build")
# install.sh (macOS / Linux) sets this so recordings live in ~/Documents/rmpp-studio, not next to the program
DATA = os.environ.get("RMPP_STUDIO_DATA") or DATA

if platform.system() == "Windows":
    CONFIG = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "rmpp-studio", "studio.json")
elif platform.system() == "Darwin":
    CONFIG = os.path.expanduser("~/Library/Application Support/rmpp-studio/studio.json")
else:
    CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "rmpp-studio",
                          "studio.json")

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def load_settings():
    legacy = os.path.join(os.path.dirname(os.path.dirname(CONFIG)), "rmpp-tester", "studio.json")
    if not os.path.exists(CONFIG) and os.path.exists(legacy):   # settings from before the rename
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        shutil.copy(legacy, CONFIG)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)


def fmt_ms(ms):
    ms = max(0, int(ms))
    return f"{ms // 60000}:{ms // 1000 % 60:02d}.{ms % 1000 // 100}"


def parse_ms(s):
    s = s.strip()
    if ":" in s:
        m, sec = s.split(":", 1)
        return int((int(m) * 60 + float(sec)) * 1000)
    return int(float(s) * 1000)


def smooth_scaled(img, w, h):
    """Shrink a QImage without aliasing: halve with averaging until close, then scale to the exact size (QPainter
    or a single big scaling step skips pixels, so thin e-paper lines break up)."""
    while img.width() >= 2 * w and img.height() >= 2 * h:
        img = img.scaled(img.width() // 2, img.height() // 2, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def pil_to_qimage(im):
    """PIL RGB image -> QImage (copied, so the PIL buffer can go away)"""
    im = im.convert("RGB")
    data = im.tobytes()
    q = QImage(data, im.width, im.height, im.width * 3, QImage.Format.Format_RGB888)
    return q.copy()


class LogWriter(io.TextIOBase):
    def __init__(self, emit):
        self.emit = emit

    def write(self, s):
        if s.strip():
            self.emit(s.rstrip("\n"))
        return len(s)


class Jobs(QObject):
    """Runs tablet commands one at a time on a background thread; results come back as signals."""
    started = Signal(str)
    finished = Signal(object, object, str)   # callback, result, label
    failed = Signal(str, str)                # label, message
    log = Signal(str)

    def __init__(self):
        super().__init__()
        self.q = queue.Queue()
        self.busy = False
        self.finished.connect(lambda cb, r, label: cb(r) if cb else None)
        threading.Thread(target=self._loop, daemon=True).start()

    def run(self, label, fn, done=None):
        self.q.put((label, fn, done))

    def _loop(self):
        while True:
            label, fn, done = self.q.get()
            self.busy = True
            self.started.emit(label)
            try:
                with contextlib.redirect_stdout(LogWriter(self.log.emit)):
                    r = fn()
                self.finished.emit(done, r, label)
            except BaseException as e:   # rmpp_ctl reports errors as SystemExit(message)
                self.failed.emit(label, str(e) or e.__class__.__name__)
            finally:
                self.busy = self.q.qsize() > 0


def apply_theme(app):
    """A calm dark theme (Fusion) that keeps e-paper screenshots readable."""
    app.setStyle("Fusion")
    p = QPalette()
    base, alt, text, mid = QColor(32, 33, 36), QColor(42, 44, 48), QColor(230, 230, 230), QColor(58, 60, 66)
    p.setColor(QPalette.ColorRole.Window, alt)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, alt)
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, mid)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.Highlight, QColor(222, 52, 52))
    p.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(140, 140, 140))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(120, 120, 120))
    app.setPalette(p)
    app.setStyleSheet("""
        QToolBar { spacing: 6px; padding: 4px; border: none; }
        QToolButton { padding: 4px 8px; border-radius: 4px; }
        QToolButton:hover { background: #4a4d55; }
        QToolButton:checked { background: #5a3030; }
        QDockWidget::title { padding: 6px; background: #2a2c30; }
        QListWidget, QPlainTextEdit, QTreeWidget { border: 1px solid #3a3c42; }
        QPushButton { padding: 4px 10px; }
    """)


def open_path(path):
    """Open a folder or file with the system's file manager / viewer."""
    if platform.system() == "Windows":
        os.startfile(path)   # noqa: S606
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
