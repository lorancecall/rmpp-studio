"""rmpp-studio main window: record the tablet, edit takes on a timeline, export GIF/MP4, run tutorial scripts."""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QAction, QActionGroup, QIcon, QImage, QKeySequence, QPixmap, QTextCursor, QTextFormat
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTabWidget, QTextEdit,
                               QToolButton,
                               QVBoxLayout, QWidget)

from . import common
from .common import (DATA, ICON, NO_WINDOW, TABLET_BIN, Jobs, ctl, fmt_ms, open_path, parse_ms, pil_to_qimage,
                     smooth_scaled)
from .connect import ConnectDialog, label as conn_label
from .ink import InkStyle
from .timeline import Timeline
from .viewer import Viewer

PREVIEW_SCALE = 0.5   # take frames are shown at 810 x 1080
QUICK = [("Pen", "tool #primaryPenMenu"), ("Select", "tool #selectionButton"), ("Eraser", "tool #eraserMenu"),
         ("Undo", "tap #undoButton"), ("Redo", "tap #redoButton"), ("Toolbar", "tap #hide-show-toolbar-button"),
         ("Close doc", "tap #close-documentview-button"), ("Delete sel.", "tap Button icon=trashcan")]


class Bridge(QObject):
    """Signals from helper threads to the GUI thread."""
    shot = Signal(QImage, float)
    pen_style = Signal(str)
    pointer = Signal(str)
    status = Signal(str)
    progress = Signal(int, int)
    thumbs = Signal(str, list)
    script_line = Signal(int)


class Studio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"rmpp-studio {ctl.__version__}")
        if os.path.exists(ICON):
            self.setWindowIcon(QIcon(ICON))
        self.cfg = common.load_settings()
        self.conn = self.cfg.get("conn") or ({"mode": "profile", "alias": self.cfg["host"]} if self.cfg.get("host")
                                             else None)
        self.rec_dir = self.cfg.get("recordings", os.path.join(DATA, "recordings"))
        for sub in ("recordings", "out", "tutorials"):
            os.makedirs(os.path.join(DATA, sub), exist_ok=True)
        os.makedirs(self.rec_dir, exist_ok=True)
        self.copy_examples()
        self.jobs = Jobs()
        self.bridge = Bridge()
        self.shot_lock = threading.Lock()
        self.watch_proc = None
        self.fb_capture = False      # tablet add-on copies the framebuffer (safe for Live)
        self.recording_since = None
        self.stop_event = threading.Event()
        self.script_path = self.cfg.get("script")
        # editor state
        self.take = None
        self.renderer = None
        self.edit = None
        self.play_plan = []
        self.undo_stack, self.redo_stack, self.last_state = [], [], None
        self.play_index = 0

        self.build_actions()
        self.build_ui()
        self.connect_signals()
        self.resize(1400, 900)
        if self.cfg.get("geometry"):
            self.restoreGeometry(bytes.fromhex(self.cfg["geometry"]))
        self.refresh_takes()
        if self.script_path and os.path.exists(self.script_path):
            self.load_script(self.script_path)
        else:
            self.new_script()
        self.live_timer = QTimer(self, interval=1000, timeout=self.live_tick)
        self.live_timer.start()
        self.play_timer = QTimer(self, timeout=self.play_tick)
        self.viewer.placeholder = "Connecting …" if self.conn else "Not connected"
        self.show_tab("Remote")
        if self.conn:
            QTimer.singleShot(200, self.on_connected)
        else:
            QTimer.singleShot(300, lambda: self.edit_connection(first_run=True))

    # ======================================================================= setup
    def copy_examples(self):
        src = os.path.join(common.RES, "tutorials")
        if common.FROZEN and os.path.isdir(src):
            for name in os.listdir(src):
                dst = os.path.join(DATA, "tutorials", name)
                if not os.path.exists(dst):
                    shutil.copy(os.path.join(src, name), dst)

    def build_actions(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.conn_label = QLabel()
        self.conn_label.setStyleSheet("padding: 0 8px; font-weight: bold")
        tb.addWidget(QLabel("  Tablet:"))
        tb.addWidget(self.conn_label)
        self.act_conn = tb.addAction("Connection…", self.edit_connection)
        tb.addSeparator()
        self.act_rec = QAction("● Record", self, checkable=True)
        self.act_rec.setToolTip("Record the tablet screen (frames are copied only when the screen changes)")
        self.act_rec.triggered.connect(self.toggle_record)
        tb.addAction(self.act_rec)
        self.rec_fps = QSpinBox()
        self.rec_fps.setRange(1, 8)
        self.rec_fps.setValue(int(self.cfg.get("rec_fps", 4)))
        self.rec_fps.setSuffix(" fps")
        tb.addWidget(self.rec_fps)
        self.rec_time = QLabel("")
        self.rec_time.setStyleSheet("color:#f66; padding: 0 6px")
        tb.addWidget(self.rec_time)
        tb.addSeparator()
        tb.addAction("📷 Shot", self.save_shot)
        tb.addAction("▶ Run script", lambda: self.run_script(True))
        tb.addAction("⇪ Export", self.export)

        m = self.menuBar().addMenu("&File")
        m.addAction("Open recordings folder", lambda: open_path(self.rec_dir))
        m.addAction("Open output folder", lambda: open_path(os.path.join(DATA, "out")))
        m.addAction("Open tutorials folder", lambda: open_path(os.path.join(DATA, "tutorials")))
        m.addSeparator()
        m.addAction("Import take folder…", self.import_take)
        m.addSeparator()
        m.addAction("Quit", self.close, QKeySequence.StandardKey.Quit)
        m = self.menuBar().addMenu("&Tablet")
        m.addAction("Connection…", self.edit_connection)
        m.addAction("Check connection", self.check)
        m.addSeparator()
        m.addAction("Install / update rmpp-remote on the tablet…", self.install_tablet)
        m.addAction("Remove rmpp-remote from the tablet…", self.remove_tablet)
        m = self.menuBar().addMenu("&Help")
        m.addAction("Keyboard shortcuts", self.show_shortcuts)
        m.addAction("About", self.about)

    def build_ui(self):
        # ---- center: live tablet (left) and the take's result (right), each with its bar; timeline below
        self.viewer = Viewer()                 # live, interactive
        self.preview = Viewer()                # take preview
        self.preview.set_mode(False)
        self.preview.placeholder = "Record something or pick a recording on the left"
        # tablet bar
        tbar = QWidget()
        h = QHBoxLayout(tbar)
        h.setContentsMargins(6, 2, 6, 2)
        self.input_group = QButtonGroup(self)
        for i, (text, mode, tip) in enumerate((("👆 Tap", "tap", "Tap / swipe: click = tap, hold = long press, "
                                                                 "drag = swipe"),
                                               ("✎ Pen", "pen", "Pen: drag = pen stroke"),
                                               ("? Look", "look", "Look: click = list the UI items there"))):
            b = QToolButton(text=text, checkable=True, checked=i == 0, toolTip=tip)
            b.clicked.connect(lambda _=False, m=mode: self.viewer.set_input_mode(m))
            self.input_group.addButton(b)
            h.addWidget(b)
        h.addSpacing(8)
        self.live = QCheckBox("Live", checked=bool(self.cfg.get("live", True)))
        self.live.setToolTip("Refresh the screen every second (needs the framebuffer capture of rmpp-remote ≥ 0.2)")
        h.addWidget(self.live)
        self.pointer_cb = QCheckBox("Pointer", checked=True, toolTip="Show where the real pen and fingers are")
        self.pointer_cb.toggled.connect(self.toggle_pointer)
        h.addWidget(self.pointer_cb)
        rb = QToolButton(text="↻", toolTip="Refresh the screen now")
        rb.clicked.connect(self.refresh_preview)
        h.addWidget(rb)
        h.addStretch(1)
        self.coords = QLabel("")
        self.coords.setStyleSheet("color:#999; font-family: Consolas, monospace")
        self.coords.setFixedWidth(self.coords.fontMetrics().horizontalAdvance("0000, 0000") + 8)   # no relayout
        self.coords.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self.coords)
        # edit bar (transport)
        ebar = QWidget()
        h = QHBoxLayout(ebar)
        h.setContentsMargins(6, 2, 6, 2)
        h.setSpacing(2)
        self.btn_start = QToolButton(text="⏮", toolTip="Start (Home)")
        self.btn_prev = QToolButton(text="◀◀", toolTip="Previous change (←)")
        self.btn_play = QToolButton(text="▶", toolTip="Play / pause the result (Space)")
        self.btn_next = QToolButton(text="▶▶", toolTip="Next change (→)")
        self.btn_end = QToolButton(text="⏭", toolTip="End (End)")
        for b in (self.btn_start, self.btn_prev, self.btn_play, self.btn_next, self.btn_end):
            b.setMinimumWidth(30)
            h.addWidget(b)
        self.btn_play.setStyleSheet("font-size: 14pt")
        self.time_label = QLabel("0:00.0 / 0:00.0")
        self.time_label.setStyleSheet("font-family: Consolas, monospace; padding: 0 6px")
        h.addWidget(self.time_label)
        self.result_label = QLabel("")
        self.result_label.setStyleSheet("color:#999")
        h.addWidget(self.result_label)
        h.addStretch(1)

        def monitor(title, view, bar):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            t = QLabel(title)
            t.setStyleSheet("padding: 4px 8px; color: #bbb; font-weight: bold; background: #26282c")
            v.addWidget(t)
            v.addWidget(view, 1)
            v.addWidget(bar)
            # both monitors always get half of the width, whatever their bars contain
            w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            w.setMinimumWidth(320)
            return w
        for bar in (tbar, ebar):   # same bar height under both monitors -> same picture size
            bar.setFixedHeight(40)
        monitors = QWidget()
        mh = QHBoxLayout(monitors)
        mh.setContentsMargins(0, 0, 0, 0)
        mh.setSpacing(4)
        mh.addWidget(monitor("LIVE  ·  tablet", self.viewer, tbar), 1)
        mh.addWidget(monitor("PREVIEW  ·  result", self.preview, ebar), 1)
        self.timeline = Timeline()
        # clip tools above the timeline
        clipbar = QWidget()
        ch = QHBoxLayout(clipbar)
        ch.setContentsMargins(6, 2, 6, 2)
        ch.setSpacing(2)
        lbl = QLabel("CLIPS")
        lbl.setStyleSheet("color:#bbb; font-weight:bold; padding-right: 8px")
        ch.addWidget(lbl)
        for text, tip, fn in (("✂ Split", "Split the clip at the playhead (S)", self.clip_split),
                              ("[ In", "Clip starts at the playhead (I)", lambda: self.set_trim("in")),
                              ("Out ]", "Clip ends at the playhead (O)", lambda: self.set_trim("out")),
                              ("⧉ Duplicate", "Copy the selected clip right after it (Ctrl+D; Ctrl+C / Ctrl+V)",
                               self.clip_duplicate),
                              ("🗑 Delete", "Remove the selected clip from the result (Delete); the recording keeps it",
                               self.clip_delete),
                              ("|", None, None),
                              ("↶ Undo", "Undo (Ctrl+Z)", self.undo), ("↷ Redo", "Redo (Ctrl+Shift+Z)", self.redo),
                              ("⟲ Reset", "One clip with the whole recording again", lambda: self.set_trim(None))):
            if fn is None:
                sep = QLabel("│")
                sep.setStyleSheet("color:#555; padding: 0 6px")
                ch.addWidget(sep)
                continue
            b = QToolButton(text=text, toolTip=tip)
            b.clicked.connect(fn)
            ch.addWidget(b)
        ch.addStretch(1)
        hint = QLabel("drag a clip to move it · drag its edges to trim · Ctrl+wheel zooms")
        hint.setStyleSheet("color:#888")
        ch.addWidget(hint)
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(0)
        bv.addWidget(clipbar)
        bv.addWidget(self.timeline, 1)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(monitors)
        split.addWidget(bottom)
        split.setStretchFactor(0, 1)
        split.setSizes([680, 190])
        self.setCentralWidget(split)

        # ---- left: takes
        self.takes = QListWidget()
        self.takes.setIconSize(QSize(54, 72))
        self.takes.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.takes.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.takes.setWordWrap(True)
        self.takes.setSpacing(2)
        tw = QWidget()
        v = QVBoxLayout(tw)
        v.setContentsMargins(4, 4, 4, 4)
        v.addWidget(self.takes, 1)
        h = QHBoxLayout()
        for text, fn in (("Rename", self.rename_take), ("Delete", self.delete_take),
                         ("Folder", lambda: open_path(self.take or self.rec_dir))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        v.addLayout(h)
        d = QDockWidget("Recordings", self)
        d.setObjectName("takes")
        d.setWidget(tw)
        d.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, d)

        # ---- right: inspector
        self.inspector = QTabWidget()
        # in workflow order: drive the tablet, automate it, edit captions, export, see what happened
        self.inspector.addTab(self.build_tablet_tab(), "Remote")
        self.inspector.addTab(self.build_script_tab(), "Script")
        self.inspector.addTab(self.build_caption_tab(), "Captions")
        self.inspector.addTab(self.build_export_tab(), "Export")
        self.logbox = QPlainTextEdit(readOnly=True)
        self.logbox.setMaximumBlockCount(2000)
        self.logbox.setStyleSheet("font-family: Consolas, monospace; font-size: 9pt")
        self.inspector.addTab(self.logbox, "Log")
        d = QDockWidget("Tools", self)
        d.setObjectName("inspector")
        d.setWidget(self.inspector)
        d.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        d.setMinimumWidth(380)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, d)
        self.statusBar().showMessage("Ready")

    def build_caption_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        info = QLabel("A caption is shown from its time until the next one. Drag captions on the timeline to move "
                      "them; double click to edit.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa")
        v.addWidget(info)
        self.cap_list = QListWidget()
        v.addWidget(self.cap_list, 1)
        f = QFormLayout()
        self.cap_time = QLineEdit()
        self.cap_time.setPlaceholderText("m:ss.s")
        f.addRow("Time", self.cap_time)
        self.cap_text = QPlainTextEdit()
        self.cap_text.setMaximumHeight(80)
        self.cap_text.setPlaceholderText("Caption text (empty = no caption from here)")
        f.addRow("Text", self.cap_text)
        v.addLayout(f)
        g = QGridLayout()
        for i, (text, fn) in enumerate((("＋ Add at playhead", self.caption_add), ("✓ Apply", self.caption_apply),
                                        ("⇤ Move to playhead", self.caption_move), ("✕ Delete", self.caption_delete),
                                        ("∅ No caption from here", lambda: self.caption_add(clear=True)))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
        v.addLayout(g)
        live = QLabel("While recording: type a caption and press Mark (Ctrl+M) to put it at that moment.")
        live.setWordWrap(True)
        live.setStyleSheet("color:#aaa; margin-top: 10px")
        v.addWidget(live)
        h = QHBoxLayout()
        self.live_cap = QLineEdit()
        self.live_cap.setPlaceholderText("caption while recording")
        self.live_cap.returnPressed.connect(self.mark_caption)
        b = QPushButton("Mark")
        b.clicked.connect(self.mark_caption)
        h.addWidget(self.live_cap)
        h.addWidget(b)
        v.addLayout(h)
        return w

    def build_export_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        self.out_fps = QSpinBox(minimum=2, maximum=30, value=int(self.cfg.get("out_fps", 8)), suffix=" fps")
        self.out_scale = QDoubleSpinBox(minimum=0.2, maximum=1.0, singleStep=0.1, value=self.cfg.get("out_scale", 0.5))
        self.max_still = QDoubleSpinBox(minimum=0, maximum=60, singleStep=0.5, value=0, suffix=" s")
        self.max_still.setToolTip("Shorten still stretches (the screen did not change) to at most this long; 0 = keep")
        self.hold_end = QDoubleSpinBox(minimum=0, maximum=10, singleStep=0.5, value=1.5, suffix=" s")
        f.addRow("Frame rate", self.out_fps)
        f.addRow("Size (× 1620×2160)", self.out_scale)
        f.addRow("Shorten pauses to", self.max_still)
        f.addRow("Hold last frame", self.hold_end)
        for wdg in (self.max_still, self.hold_end):
            wdg.valueChanged.connect(self.export_settings_changed)
        self.out_fps.valueChanged.connect(lambda _: self.update_result_info())
        # format (one per export), codec for videos, quality
        fmt_form = QFormLayout()
        self.out_format = QComboBox()
        has_ffmpeg = bool(ctl.find_ffmpeg())
        for ext, (label, kind, _) in ctl.FORMATS.items():
            usable = kind == "anim" or (has_ffmpeg and ctl.available_codecs(ext))
            self.out_format.addItem(f"{label}  ({ext})" + ("" if usable else "  – needs ffmpeg"), ext)
            if not usable:
                self.out_format.model().item(self.out_format.count() - 1).setEnabled(False)
        i = self.out_format.findData(self.cfg.get("out_format", ".mp4" if has_ffmpeg else ".gif"))
        self.out_format.setCurrentIndex(max(0, i))
        self.out_codec = QComboBox()
        self.out_quality = QComboBox()
        self.out_format.currentIndexChanged.connect(self.format_changed)
        fmt_form.addRow("Format", self.out_format)
        fmt_form.addRow("Codec", self.out_codec)
        fmt_form.addRow("Quality", self.out_quality)
        v.addLayout(fmt_form)
        v.addSpacing(6)
        v.addLayout(f)
        self.format_changed()
        b = QPushButton("⇪ Export…")
        b.setStyleSheet("font-weight: bold; padding: 8px")
        b.clicked.connect(self.export)
        v.addWidget(b)
        self.progress = QProgressBar()
        v.addWidget(self.progress)
        self.out_list = QListWidget()
        self.out_list.itemDoubleClicked.connect(lambda it: open_path(it.data(Qt.ItemDataRole.UserRole)))
        v.addWidget(QLabel("Exported (double click to open):"))
        v.addWidget(self.out_list, 1)
        b = QPushButton("Open output folder")
        b.clicked.connect(lambda: open_path(os.path.join(DATA, "out")))
        v.addWidget(b)
        return w

    def build_tablet_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        self.text_in = QLineEdit()
        self.text_in.setPlaceholderText("Text for the focused field (Enter)")
        self.text_in.returnPressed.connect(self.send_text)
        h.addWidget(self.text_in)
        b = QPushButton("Type")
        b.clicked.connect(self.send_text)
        h.addWidget(b)
        v.addLayout(h)
        h = QHBoxLayout()
        for k in ("enter", "backspace", "escape", "tab", "ctrl+a"):
            b = QPushButton(k)
            b.clicked.connect(lambda _=False, k=k: self.action(f"key {k}"))
            h.addWidget(b)
        v.addLayout(h)
        g = QGridLayout()
        for i, (label, cmd) in enumerate(QUICK):
            b = QPushButton(label)
            b.setToolTip(cmd)
            b.clicked.connect(lambda _=False, c=cmd: self.action(c))
            g.addWidget(b, i // 4, i % 4)
        v.addLayout(g)
        h = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText('UI items: words, #objectName or "exact text"')
        self.query.returnPressed.connect(self.find)
        h.addWidget(self.query)
        for text, fn in (("Find", self.find), ("Named", lambda: self.find(named=True))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        v.addLayout(h)
        self.items = QListWidget()
        self.items.setStyleSheet("font-family: Consolas, monospace; font-size: 9pt")
        self.items.currentTextChanged.connect(self.show_item)
        self.items.itemDoubleClicked.connect(lambda it: self.tap_item(it.text()))
        v.addWidget(self.items, 1)
        self.rec_steps = QCheckBox("Record my actions as script steps")
        self.rec_steps.setToolTip("Taps, strokes, text, keys and shots are appended to the Script tab "
                                  "(as tap #objectName when a named item is there)")
        v.addWidget(self.rec_steps)
        return w

    def build_script_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGridLayout()
        btns = [("New", self.new_script), ("Open…", self.open_script), ("Save", self.save_script),
                ("Save as…", lambda: self.save_script(ask=True)), ("+ caption", self.insert_caption),
                ("+ wait", lambda: self.insert_step("wait 1000")), ("+ expect screen", self.insert_expect),
                ("+ shot", lambda: self.insert_step("shot step.png")),
                ("▶ Run + record", lambda: self.run_script(True)), ("▶ Try", lambda: self.run_script(False)),
                ("■ Stop", self.stop_event.set)]
        for i, (text, fn) in enumerate(btns):
            b = QPushButton(text)
            b.clicked.connect(fn)
            g.addWidget(b, i // 4, i % 4)
        v.addLayout(g)
        self.script_name = QLabel("")
        self.script_name.setStyleSheet("color:#aaa")
        v.addWidget(self.script_name)
        self.script = QPlainTextEdit()
        self.script.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt")
        self.script.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        v.addWidget(self.script, 1)
        return w

    def connect_signals(self):
        j = self.jobs
        j.started.connect(lambda label: self.statusBar().showMessage(label + " …"))
        j.finished.connect(lambda cb, r, label: self.statusBar().showMessage(label + ": ok", 4000))
        j.failed.connect(self.on_job_failed)
        j.log.connect(self.log)
        b = self.bridge
        b.shot.connect(self.on_shot)
        b.pen_style.connect(self.on_pen_style)
        self.viewer.penEntered.connect(self.query_pen)
        b.pointer.connect(self.on_pointer)
        b.status.connect(lambda s: self.statusBar().showMessage(s, 5000))
        b.progress.connect(lambda i, n: (self.progress.setMaximum(n), self.progress.setValue(i)))
        b.thumbs.connect(self.on_thumbs)
        b.script_line.connect(self.mark_script_line)
        self.viewer.action.connect(self.action)
        self.viewer.look.connect(self.look)
        self.viewer.hover.connect(lambda x, y: self.coords.setText(f"{x}, {y}"))
        t = self.timeline
        t.seek.connect(self.seek)
        t.captionSelected.connect(self.select_caption)
        t.captionsChanged.connect(self.captions_changed)
        t.captionEdit.connect(self.edit_caption_dialog)
        t.clipsChanged.connect(self.commit)
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_start.clicked.connect(lambda: self.seek(0, update_timeline=True))
        self.btn_end.clicked.connect(lambda: self.seek(self.timeline.length, True))
        self.btn_prev.clicked.connect(lambda: self.step_change(-1))
        self.btn_next.clicked.connect(lambda: self.step_change(1))
        self.takes.currentItemChanged.connect(lambda it, _: it and self.open_take(it.data(Qt.ItemDataRole.UserRole)))
        self.cap_list.currentRowChanged.connect(self.cap_list_selected)
        for key, fn in (("Space", self.toggle_play), ("Left", lambda: self.step_change(-1)),
                        ("Right", lambda: self.step_change(1)), ("Home", lambda: self.seek(0, True)),
                        ("Ctrl+M", self.mark_caption), ("Ctrl+R", lambda: self.act_rec.trigger()),
                        ("I", lambda: self.set_trim("in")), ("O", lambda: self.set_trim("out")),
                        ("S", self.clip_split), ("Delete", self.clip_delete), ("Ctrl+D", self.clip_duplicate),
                        ("Ctrl+C", self.clip_copy), ("Ctrl+V", self.clip_paste), ("Ctrl+Z", self.undo),
                        ("Ctrl+Shift+Z", self.redo), ("Ctrl+Y", self.redo), ("End", lambda: self.seek(
                            self.timeline.length, True))):
            a = QAction(self, shortcut=QKeySequence(key), shortcutContext=Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(lambda _=False, fn=fn: self.shortcut(fn))
            self.addAction(a)

    def shortcut(self, fn):
        if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QTextEdit)):
            return   # typing
        fn()

    # ======================================================================= helpers
    def show_tab(self, name):
        for i in range(self.inspector.count()):
            if self.inspector.tabText(i) == name:
                self.inspector.setCurrentIndex(i)
                return

    def log(self, s):
        self.logbox.appendPlainText(s)

    def on_job_failed(self, label, msg):
        self.statusBar().showMessage(f"{label}: {msg}", 10000)
        self.log(f"ERROR {label}: {msg}")
        if label in ("start recording", "stop recording"):
            self.set_recording(False)

    def tablet(self):
        return ctl.Tablet.from_conn(self.conn)


    # ======================================================================= connection
    def edit_connection(self, first_run=False):
        d = ConnectDialog(self, self.conn, first_run=first_run)
        if d.exec() and d.result_conn:
            self.conn = d.result_conn
            self.save_settings()
            self.on_connected()

    def on_connected(self):
        self.conn_label.setText(conn_label(self.conn))
        p = self.watch_proc
        if p and p.poll() is None:
            p.kill()
        self.toggle_pointer(self.pointer_cb.isChecked())

        def go():
            ok, msg = self.tablet().probe()
            info = self.tablet().ui("info", check=False) if ok else ""
            return ok, msg, "source fb" in info
        self.jobs.run("check connection", go, self.connected_result)

    def connected_result(self, r):
        ok, msg, fb = r
        self.fb_capture = fb
        self.log(msg)
        self.statusBar().showMessage(msg, 8000)
        if ok and not fb:
            self.log("Live preview is off: the tablet's rmpp-remote is older than the framebuffer capture "
                     "(Tablet ▸ Install / update).")
        self.refresh_preview()

    def check(self):
        self.on_connected()

    def install_tablet(self):
        so, tool = os.path.join(TABLET_BIN, "librmpp-remote.so"), os.path.join(TABLET_BIN, "rmpp-remote")
        if not (os.path.exists(so) and os.path.exists(tool)):
            QMessageBox.critical(self, "Install", f"tablet files not found in {TABLET_BIN}")
            return
        if QMessageBox.question(self, "Install on the tablet", (
                f"Install rmpp-remote {ctl.__version__} on {conn_label(self.conn)}?\n\nCopies the add-on to "
                "/usr/lib/rmpp-remote, links it into rmpp-preload.d and restarts xochitl (the tablet may ask for "
                "its passcode afterwards).")) != QMessageBox.StandardButton.Yes:
            return
        tab = self.tablet()
        self.jobs.run("install on tablet", lambda: ctl.install_tablet(tab, so, tool, log=print),
                      lambda r: (self.log(r), self.on_connected()))

    def remove_tablet(self):
        if QMessageBox.question(self, "Remove", "Remove rmpp-remote from the tablet and restart xochitl?") == \
                QMessageBox.StandardButton.Yes:
            tab = self.tablet()
            self.jobs.run("remove from tablet", lambda: ctl.remove_tablet(tab), self.log)

    # ======================================================================= live screen + pointer
    def live_tick(self):
        if self.conn and self.live.isChecked() and self.fb_capture \
                and not self.shot_lock.locked():
            self.refresh_preview()
        if self.recording_since:
            self.rec_time.setText(fmt_ms((time.time() - self.recording_since) * 1000)[:-2])

    def refresh_preview(self):
        if not self.conn:
            return
        tab = self.tablet()

        def grab():
            if not self.shot_lock.acquire(blocking=False):
                return
            try:
                path = os.path.join(tempfile.gettempdir(), "rmpp-studio-live.png")
                taken_at = time.time()
                tab.shot(path)
                img = QImage(path)
                if not img.isNull():
                    self.bridge.shot.emit(img, taken_at)
            except BaseException as e:
                self.bridge.status.emit(f"screen: {e}")
            finally:
                self.shot_lock.release()
        threading.Thread(target=grab, daemon=True).start()

    def on_shot(self, img, taken_at):
        self.viewer.set_image(img, taken_at)

    # ---- which pen is active, so strokes written on the tablet show up in its style right away
    def query_pen(self):
        now = time.time()
        if now - getattr(self, "pen_queried", 0) < 1.5 or not self.conn:
            return
        self.pen_queried = now
        tab = self.tablet()

        def go():
            try:
                self.bridge.pen_style.emit(tab.ui("pen", check=False))
            except BaseException:
                pass
        threading.Thread(target=go, daemon=True).start()

    def on_pen_style(self, reply):
        if not reply.startswith("ok"):
            return   # older add-on without 'pen': keep the plain trace
        kv = dict(part.split("=", 1) for part in reply.split()[1:] if "=" in part)
        self.viewer.ink_menu = kv.get("menu", "")
        self.viewer.ink_style = InkStyle.parse(reply)

    def on_pointer(self, line):
        had = len(self.viewer.stroke)
        self.viewer.pointer_line(line)
        if had and not self.viewer.stroke and self.live.isChecked():   # a stroke just ended
            QTimer.singleShot(700, self.refresh_preview)

    def toggle_pointer(self, on):
        if on and self.conn:
            if not (self.watch_proc and self.watch_proc.poll() is None):
                threading.Thread(target=self.watch_loop, daemon=True).start()
        else:
            p, self.watch_proc = self.watch_proc, None
            if p and p.poll() is None:
                p.kill()

    def watch_loop(self):
        while self.pointer_cb.isChecked() and self.conn:
            try:
                p = subprocess.Popen(["ssh"] + self.tablet().ssh_args() + [f"{ctl.TOOL} watch"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW)
            except OSError:
                return
            self.watch_proc = p
            for raw in p.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if line and line != "watch ok":
                    self.bridge.pointer.emit(line)
            if self.watch_proc is not p:
                return
            self.watch_proc = None
            time.sleep(3)   # lost (tablet asleep?): try again

    # ======================================================================= tablet actions
    def action(self, cmd, point=None):
        if not self.conn:
            return
        tab = self.tablet()
        record = self.rec_steps.isChecked()

        def go():
            step = self.step_for_point(tab, cmd, *point) if (point and record) else cmd
            ctl.do(tab, ctl.shlex.split(cmd), {})
            return step

        def done(step):
            if record and not cmd.startswith(("info", "find", "hit")):
                self.insert_step(step)
            QTimer.singleShot(600, self.refresh_preview)
        self.jobs.run(cmd.split()[0], go, done)

    @staticmethod
    def step_for_point(tab, cmd, x, y):
        out = tab.ui(f"hit {x} {y}", check=False)
        for line in out.splitlines():
            m = re.search(r" #(\S+)", line)
            size = re.match(r"\s*-?\d+,-?\d+ (\d+)x(\d+)", line)
            if m and size and int(size.group(1)) < 800 and int(size.group(2)) < 800:
                if not tab.ui(f"center #{m.group(1)}", check=False).startswith("error"):
                    return f"{cmd.split()[0]} #{m.group(1)}"
        return cmd

    def send_text(self):
        t = self.text_in.text()
        if t:
            self.action("text " + t)
            self.text_in.clear()

    def look(self, x, y):
        self.show_tab("Remote")
        self.jobs.run("look", lambda: self.tablet().ui(f"hit {x} {y}", check=False), self.fill_items)

    def find(self, named=False):
        q = self.query.text().strip()

        def go():
            out = self.tablet().ui("tree" if named or not q else f"find {q}", check=False)
            lines = [ln.strip() for ln in out.splitlines()]
            if named:
                lines = [ln for ln in lines if " #" in ln and not re.match(r"\S+ (0x\d+|\d+x0) ", ln)]
            return "\n".join(lines)
        self.jobs.run("find", go, self.fill_items)

    def fill_items(self, text):
        self.items.clear()
        self.items.addItems([ln for ln in text.splitlines() if ln.strip()])

    def show_item(self, line):
        m = re.match(r"\s*(-?\d+),(-?\d+) (\d+)x(\d+)", line or "")
        self.viewer.box = tuple(map(int, m.groups())) if m else None
        self.viewer.update()

    def tap_item(self, line):
        m = re.search(r" #(\S+)", line)
        if m:
            self.action(f"tap #{m.group(1)}")
            return
        m = re.match(r"\s*(-?\d+),(-?\d+) (\d+)x(\d+)", line)
        if m:
            x, y, w, h = map(int, m.groups())
            self.action(f"tap {x + w // 2} {y + h // 2}")

    def save_shot(self):
        if not self.conn:
            return
        default = os.path.join(DATA, "out", datetime.datetime.now().strftime("shot-%Y%m%d-%H%M%S.png"))
        path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", default, "PNG (*.png)")
        if not path:
            return
        record = self.rec_steps.isChecked()
        self.jobs.run("screenshot", lambda: self.tablet().shot(path),
                      lambda r: (self.log(f"saved {r}"), record and self.insert_step(f"shot {os.path.basename(path)}")))

    # ======================================================================= recording
    def set_recording(self, on):
        self.recording_since = time.time() if on else None
        self.act_rec.setChecked(on)
        self.act_rec.setText("■ Stop" if on else "● Record")
        self.rec_time.setText("" if not on else "0:00")

    def toggle_record(self):
        if not self.conn:
            self.act_rec.setChecked(False)
            return
        if self.recording_since is None:
            fps = self.rec_fps.value()
            self.set_recording(True)

            def go():
                tab = self.tablet()
                tab.ssh(f"rm -rf {ctl.REC_DIR}")
                return tab.ui(f"rec start {ctl.REC_DIR} {fps}")
            self.jobs.run("start recording", go, self.log)
        else:
            name, ok = QInputDialog.getText(self, "Save take", "Name of this take:", text="take")
            folder = self.new_take_folder(name if ok else "take")

            def go():
                tab = self.tablet()
                r = tab.ui("rec stop")
                tab.pull_recording(folder)
                return r

            def done(r):
                self.log(r)
                self.refresh_takes(select=folder)
                self.show_tab("Captions")
            self.set_recording(False)
            self.jobs.run("stop recording", go, done)

    def mark_caption(self):
        text = self.live_cap.text().strip()
        if self.recording_since is None:
            self.statusBar().showMessage("Not recording: add captions on the timeline instead", 5000)
            return
        self.jobs.run("caption", lambda: self.tablet().ui("rec mark " + text), lambda r: self.log(f"caption: {text}"))
        self.live_cap.clear()

    def new_take_folder(self, name):
        name = re.sub(r"[^\w.-]+", "-", (name or "take").strip()) or "take"
        return os.path.join(self.rec_dir, datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + name)

    # ======================================================================= takes
    def refresh_takes(self, select=None):
        self.takes.blockSignals(True)
        self.takes.clear()
        names = sorted((d for d in os.listdir(self.rec_dir)
                        if os.path.exists(os.path.join(self.rec_dir, d, "frames.txt"))), reverse=True)
        for d in names:
            folder = os.path.join(self.rec_dir, d)
            try:
                samples, _ = ctl.load_timeline(folder)
                dur = fmt_ms(samples[-1][0])[:-2] if samples else "?"
                icon = QIcon(QPixmap.fromImage(smooth_scaled(QImage(os.path.join(folder, samples[-1][1])), 108, 144)))
            except Exception:
                dur, icon = "?", QIcon()
            label = re.sub(r"^\d{8}-\d{6}-", "", d)
            stamp = re.match(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})", d)
            when = f"{stamp.group(2)}/{stamp.group(3)} {stamp.group(4)}:{stamp.group(5)}" if stamp else ""
            it = QListWidgetItem(icon, f"{label}\n{dur}  ·  {when}")
            it.setData(Qt.ItemDataRole.UserRole, folder)
            self.takes.addItem(it)
            if select and os.path.normcase(folder) == os.path.normcase(select):
                self.takes.setCurrentItem(it)
        self.takes.blockSignals(False)
        if select:
            self.open_take(select)

    def import_take(self):
        d = QFileDialog.getExistingDirectory(self, "Take folder (with frames.txt)", self.rec_dir)
        if d:
            self.open_take(d)

    def rename_take(self):
        if not self.take:
            return
        old = os.path.basename(self.take)
        prefix = re.match(r"^\d{8}-\d{6}-", old)
        name, ok = QInputDialog.getText(self, "Rename take", "Name:", text=old[len(prefix.group(0)):] if prefix else old)
        if ok and name.strip():
            new = os.path.join(os.path.dirname(self.take),
                               (prefix.group(0) if prefix else "") + re.sub(r"[^\w.-]+", "-", name.strip()))
            os.rename(self.take, new)
            self.refresh_takes(select=new)

    def delete_take(self):
        if not self.take:
            return
        if QMessageBox.question(self, "Delete take", f"Delete {os.path.basename(self.take)} and its frames?") == \
                QMessageBox.StandardButton.Yes:
            shutil.rmtree(self.take, ignore_errors=True)
            self.take = self.renderer = self.edit = None
            self.timeline.clear()
            self.cap_list.clear()
            self.refresh_takes()
            self.preview.set_image(None)

    def open_take(self, folder):
        self.stop_play()
        try:
            self.renderer = ctl.Renderer(folder, scale=PREVIEW_SCALE)
        except BaseException as e:
            QMessageBox.critical(self, "Open take", str(e))
            return
        self.take = folder
        self.edit = self.renderer.edit
        self.max_still.blockSignals(True)
        self.hold_end.blockSignals(True)
        self.max_still.setValue(float(self.edit.get("max_still") or 0))
        self.hold_end.setValue(float(self.edit.get("hold_end", 1.5)))
        self.max_still.blockSignals(False)
        self.hold_end.blockSignals(False)
        if not self.edit.get("segments"):   # older edits: in/out -> one clip
            self.edit["segments"] = self.renderer.segments()
            self.edit.pop("in", None)
            self.edit.pop("out", None)
        self.undo_stack, self.redo_stack = [], []
        self.last_state = self.snapshot()
        self.timeline.set_take(self.renderer.length, [], self.edit["captions"], self.edit["segments"])
        self.fill_captions()
        self.update_result_info()
        self.show_frame()
        samples = list(self.renderer.samples)

        def thumbs():   # small images where the picture changes, made in the background
            out, last = [], None
            for ms, name in samples:
                if name == last:
                    continue
                last = name
                im = QImage(os.path.join(folder, name))
                if not im.isNull():
                    out.append((ms, smooth_scaled(im, 60, 80)))
            self.bridge.thumbs.emit(folder, out)
        threading.Thread(target=thumbs, daemon=True).start()

    def on_thumbs(self, folder, thumbs):
        if folder == self.take:
            self.timeline.thumbs = thumbs
            self.timeline.update()

    # ======================================================================= editor
    def save_edit(self):
        if self.take and self.edit is not None:
            ctl.save_edit(self.take, self.edit)

    def src_at(self, seq):
        return self.timeline.seq_to_src(seq)[0]

    def show_frame(self):
        if not self.renderer or not self.timeline.segments:
            self.preview.set_image(None)
            return
        t = self.timeline.playhead
        self.preview.dim = False
        self.preview.set_image(pil_to_qimage(self.renderer.frame(self.src_at(t))))
        self.time_label.setText(f"{fmt_ms(t)} / {fmt_ms(self.timeline.length)}")

    def seek(self, ms, update_timeline=False):
        if update_timeline:
            self.timeline.set_playhead(ms)
        if not self.play_timer.isActive():
            self.show_frame()

    def step_change(self, d):
        """previous / next place where the picture or the caption changes, or a clip starts"""
        if not self.renderer:
            return
        t = self.timeline.playhead
        changes = self.renderer.change_times()
        points = set()
        for (a, b), o in zip(self.timeline.segments, self.timeline.offsets()):
            points.add(o)
            points.update(o + c - a for c in changes if a < c < b)
        points.add(self.timeline.length)
        pts = sorted(points)
        nxt = next((x for x in pts if x > t), self.timeline.length) if d > 0 else \
            next((x for x in reversed(pts) if x < t), 0)
        self.seek(nxt, True)

    # ---- clips: split / trim / duplicate / delete / move (timeline) with undo
    def snapshot(self):
        return json.dumps({"segments": self.edit.get("segments"), "captions": self.edit.get("captions")})

    def restore(self, state):
        d = json.loads(state)
        self.edit["segments"][:] = d["segments"]   # in place: the timeline shares these lists
        self.edit["captions"][:] = d["captions"]
        self.last_state = state
        self.after_edit()

    def commit(self, what=""):
        """record an edit (already applied to self.edit) for undo, save, refresh"""
        if not self.edit:
            return
        state = self.snapshot()
        if state != self.last_state:
            self.undo_stack.append(self.last_state)
            self.undo_stack = self.undo_stack[-100:]
            self.redo_stack.clear()
            self.last_state = state
            if what:
                self.statusBar().showMessage(what, 3000)
        self.after_edit()

    def after_edit(self):
        self.timeline.set_playhead(min(self.timeline.playhead, self.timeline.length))
        self.fill_captions(self.timeline.selected if self.timeline.selected >= 0 else None)
        self.save_edit()
        self.update_result_info()
        self.show_frame()

    def undo(self):
        if self.edit and self.undo_stack:
            self.redo_stack.append(self.last_state)
            self.restore(self.undo_stack.pop())

    def redo(self):
        if self.edit and self.redo_stack:
            self.undo_stack.append(self.last_state)
            self.restore(self.redo_stack.pop())

    def current_clip(self):
        segs = self.timeline.segments
        if 0 <= self.timeline.clip < len(segs):
            return self.timeline.clip
        return self.timeline.clip_at(self.timeline.playhead) if segs else -1

    def clip_split(self):
        if not self.renderer:
            return
        src, i = self.timeline.seq_to_src(self.timeline.playhead)
        a, b = self.edit["segments"][i]
        if not (a + 100 <= src <= b - 100):
            self.statusBar().showMessage("Move the playhead inside a clip to split it", 4000)
            return
        self.edit["segments"][i:i + 1] = [[a, src], [src, b]]
        self.timeline.clip = i + 1
        self.commit("split")

    def set_trim(self, which):
        if not self.renderer:
            return
        if which is None:
            self.edit["segments"][:] = [[0, self.renderer.length]]
            self.timeline.clip = -1
            self.commit("reset to the whole recording")
            return
        src, i = self.timeline.seq_to_src(self.timeline.playhead)
        a, b = self.edit["segments"][i]
        if which == "in" and src < b - 100:
            self.edit["segments"][i][0] = src
        elif which == "out" and src > a + 100:
            self.edit["segments"][i][1] = src
        else:
            return
        self.timeline.clip = i
        self.commit("clip start" if which == "in" else "clip end")

    def clip_copy(self):
        i = self.current_clip()
        if i >= 0:
            self.clipboard = list(self.edit["segments"][i])
            self.statusBar().showMessage(f"copied clip {i + 1}", 3000)

    def clip_paste(self):
        seg = getattr(self, "clipboard", None)
        if not seg or not self.renderer:
            return
        i = self.current_clip()
        self.edit["segments"].insert(i + 1, list(seg))
        self.timeline.clip = i + 1
        self.commit("paste clip")

    def clip_duplicate(self):
        i = self.current_clip()
        if i >= 0:
            self.edit["segments"].insert(i + 1, list(self.edit["segments"][i]))
            self.timeline.clip = i + 1
            self.commit("duplicate clip")

    def clip_delete(self):
        i = self.current_clip()
        if i < 0:
            return
        if len(self.edit["segments"]) == 1:
            self.statusBar().showMessage("The last clip cannot be deleted (use In / Out, or Reset)", 4000)
            return
        del self.edit["segments"][i]
        self.timeline.clip = min(i, len(self.edit["segments"]) - 1)
        self.commit("delete clip")

    def export_settings_changed(self):
        if self.edit is not None:
            self.edit["max_still"] = self.max_still.value()
            self.edit["hold_end"] = self.hold_end.value()
            self.save_edit()
            self.update_result_info()

    def update_result_info(self):
        if not self.renderer:
            self.result_label.setText("")
            return
        n = len(self.renderer.times(self.out_fps.value()))
        self.result_label.setText(f"→ {fmt_ms(n * 1000 / self.out_fps.value())[:-2]}")
        self.result_label.setToolTip("Length of the exported result (clips, shortened pauses, hold end)")

    # ---- playback of the result (clips, shortened pauses, captions)
    def toggle_play(self):
        if not self.renderer:
            return
        if self.play_timer.isActive():
            self.stop_play()
            return
        fps = self.out_fps.value()
        self.play_plan = self.renderer.frames_plan(fps)
        t = self.timeline.playhead
        self.play_index = next((i for i, (seq, _) in enumerate(self.play_plan) if seq >= t), 0)
        if self.play_index >= len(self.play_plan) - 1:
            self.play_index = 0
        self.btn_play.setText("⏸")
        self.play_timer.start(int(1000 / fps))

    def stop_play(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
        self.btn_play.setText("▶")

    def play_tick(self):
        if self.play_index >= len(self.play_plan):
            self.stop_play()
            return
        seq, src = self.play_plan[self.play_index]
        self.play_index += 1
        self.timeline.set_playhead(seq)
        self.preview.dim = False
        self.preview.set_image(pil_to_qimage(self.renderer.frame(src)))
        self.time_label.setText(f"{fmt_ms(seq)} / {fmt_ms(self.timeline.length)}")

    # ---- captions (stored in recording time; shown at their place in the edited sequence)
    def seq_of_src(self, src):
        for (a, b), o in zip(self.timeline.segments, self.timeline.offsets()):
            if a <= src < b:
                return o + src - a
        return None

    def fill_captions(self, select=None):
        caps = self.edit["captions"] if self.edit else []
        caps.sort(key=lambda c: c[0])
        self.cap_list.blockSignals(True)
        self.cap_list.clear()
        for ms, text in caps:
            seq = self.seq_of_src(ms)
            when = fmt_ms(seq) if seq is not None else "  (cut)"
            self.cap_list.addItem(f"{when}   {text or '(no caption)'}")
        if select is not None and 0 <= select < len(caps):
            self.cap_list.setCurrentRow(select)
        self.cap_list.blockSignals(False)
        self.timeline.selected = select if select is not None else -1
        self.timeline.update()
        if self.renderer:
            self.renderer.cache.clear()

    def cap_list_selected(self, row):
        if self.edit and 0 <= row < len(self.edit["captions"]):
            self.select_caption(row)
            seq = self.seq_of_src(self.edit["captions"][row][0])
            if seq is not None:
                self.seek(seq, True)

    def select_caption(self, i):
        if not self.edit or not (0 <= i < len(self.edit["captions"])):
            return
        ms, text = self.edit["captions"][i]
        seq = self.seq_of_src(ms)
        self.cap_time.setText(fmt_ms(seq) if seq is not None else "")
        self.cap_text.setPlainText(text)
        self.timeline.selected = i
        self.cap_list.blockSignals(True)
        self.cap_list.setCurrentRow(i)
        self.cap_list.blockSignals(False)
        self.show_tab("Captions")
        self.timeline.update()

    def caption_changed_common(self, select=None):
        self.commit()
        self.fill_captions(select)

    def captions_changed(self):   # dragged on the timeline
        i = self.timeline.selected
        moved = self.edit["captions"][i] if 0 <= i < len(self.edit["captions"]) else None
        self.edit["captions"].sort(key=lambda c: c[0])
        self.caption_changed_common(self.edit["captions"].index(moved) if moved else None)
        if moved:
            seq = self.seq_of_src(moved[0])
            self.cap_time.setText(fmt_ms(seq) if seq is not None else "")

    def caption_add(self, clear=False):
        if not self.edit:
            return
        text = "" if clear else (self.cap_text.toPlainText().strip() or "New caption")
        cap = [self.src_at(self.timeline.playhead), text]
        self.edit["captions"].append(cap)
        self.edit["captions"].sort(key=lambda c: c[0])
        self.caption_changed_common(self.edit["captions"].index(cap))
        self.select_caption(self.edit["captions"].index(cap))
        if not clear:
            self.cap_text.setFocus()
            self.cap_text.selectAll()

    def caption_apply(self):
        i = self.timeline.selected
        if not self.edit or not (0 <= i < len(self.edit["captions"])):
            return self.caption_add()
        cap = self.edit["captions"][i]
        if self.cap_time.text().strip():
            try:
                cap[0] = self.src_at(parse_ms(self.cap_time.text()))
            except ValueError:
                QMessageBox.warning(self, "Caption", "Time: seconds or m:ss.s (position in the result)")
                return
        cap[1] = self.cap_text.toPlainText().strip()
        self.edit["captions"].sort(key=lambda c: c[0])
        self.caption_changed_common(self.edit["captions"].index(cap))

    def caption_move(self):
        i = self.timeline.selected
        if self.edit and 0 <= i < len(self.edit["captions"]):
            cap = self.edit["captions"][i]
            cap[0] = self.src_at(self.timeline.playhead)
            self.edit["captions"].sort(key=lambda c: c[0])
            self.caption_changed_common(self.edit["captions"].index(cap))
            self.cap_time.setText(fmt_ms(self.timeline.playhead))

    def caption_delete(self):
        i = self.timeline.selected
        if self.edit and 0 <= i < len(self.edit["captions"]):
            del self.edit["captions"][i]
            self.timeline.selected = -1
            self.caption_changed_common()
            self.cap_text.clear()
            self.cap_time.clear()

    def edit_caption_dialog(self, i):
        text, ok = QInputDialog.getMultiLineText(self, "Caption", "Text:", self.edit["captions"][i][1])
        if ok:
            self.edit["captions"][i][1] = text.strip()
            self.caption_changed_common(i)
            self.select_caption(i)

    # ---- export
    def format_changed(self):
        ext = self.out_format.currentData()
        label, kind, codecs = ctl.FORMATS[ext]
        self.out_codec.clear()
        if kind == "video":
            for c in codecs:
                ok = c in ctl.available_codecs(ext)
                self.out_codec.addItem(ctl.CODECS[c][0] + ("" if ok else "  – not in this ffmpeg"), c)
                if not ok:
                    self.out_codec.model().item(self.out_codec.count() - 1).setEnabled(False)
            i = self.out_codec.findData(self.cfg.get("out_codec", {}).get(ext) if isinstance(
                self.cfg.get("out_codec"), dict) else None)
            self.out_codec.setCurrentIndex(max(0, i))
            self.out_codec.setEnabled(True)
        else:
            self.out_codec.addItem("(built in)", None)
            self.out_codec.setEnabled(False)
        q = self.out_quality.currentData() or self.cfg.get("out_quality", "medium")
        self.out_quality.clear()
        names = {"high": "High", "medium": "Medium", "small": "Small file"}
        for key in ctl.QUALITIES:
            extra = f"  ({ctl.GIF_COLORS[key]} colors)" if ext == ".gif" else \
                "" if kind == "video" or ext != ".webp" else f"  (quality {ctl.WEBP_QUALITY[key]})"
            self.out_quality.addItem(names[key] + extra, key)
        self.out_quality.setEnabled(ext != ".apng")
        self.out_quality.setCurrentIndex(max(0, self.out_quality.findData(q)))

    def export(self):
        if not self.renderer:
            QMessageBox.information(self, "Export", "Pick or record something first.")
            return
        ext = self.out_format.currentData()
        codec, quality = self.out_codec.currentData(), self.out_quality.currentData()
        self.export_settings_changed()
        name = re.sub(r"^\d{8}-\d{6}-", "", os.path.basename(self.take)) + ext
        label = ctl.FORMATS[ext][0]
        path, _ = QFileDialog.getSaveFileName(self, f"Export {label}", os.path.join(DATA, "out", name),
                                              f"{label} (*{ext})")
        if not path:
            return
        if os.path.splitext(path)[1].lower() != ext:
            path += ext
        folder, edit = self.take, json.loads(json.dumps(self.edit))
        fps, scale = self.out_fps.value(), self.out_scale.value()
        self.show_tab("Export")
        codecs = self.cfg.get("out_codec") if isinstance(self.cfg.get("out_codec"), dict) else {}
        if codec:
            codecs[ext] = codec
        self.cfg.update(out_format=ext, out_codec=codecs, out_quality=quality)

        def progress(i, n):
            if i % 10 == 0 or i == n:
                self.bridge.progress.emit(i, n)

        def go():
            ctl.render(folder, path, fps=fps, scale=scale, edit=edit, progress=progress, codec=codec,
                       quality=quality)
            return [path]

        def done(paths):
            for p in paths:
                size = os.path.getsize(p) / 1e6 if os.path.exists(p) else 0
                it = QListWidgetItem(f"{os.path.basename(p)}   ({size:.1f} MB)")
                it.setData(Qt.ItemDataRole.UserRole, p)
                self.out_list.insertItem(0, it)
        self.jobs.run("export", go, done)

    # ======================================================================= script
    def new_script(self):
        self.script.setPlainText("# Tutorial: one step per line (see tutorials/README.md)\ntitle: My tutorial\nfps: 4\n\n"
                                 "# setup steps run before recording starts\nsetup expect #selectionButton\n\n"
                                 "caption First step\nwait 1000\n")
        self.script_path = None
        self.script_name.setText("(new script)")

    def open_script(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open tutorial", os.path.join(DATA, "tutorials"),
                                           "Tutorial (*.tut);;All (*)")
        if p:
            self.load_script(p)

    def load_script(self, p):
        with open(p, encoding="utf-8") as f:
            self.script.setPlainText(f.read())
        self.script_path = p
        self.script_name.setText(p)

    def save_script(self, ask=False):
        if ask or not self.script_path:
            p, _ = QFileDialog.getSaveFileName(self, "Save tutorial", os.path.join(DATA, "tutorials", "tutorial.tut"),
                                               "Tutorial (*.tut)")
            if not p:
                return
            self.script_path = p
        with open(self.script_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.script.toPlainText())
        self.script_name.setText(self.script_path)
        self.save_settings()

    def insert_step(self, line):
        c = self.script.textCursor()
        c.movePosition(QTextCursor.MoveOperation.EndOfLine)
        c.insertText("\n" + line)
        self.script.setTextCursor(c)
        self.script.ensureCursorVisible()

    def insert_caption(self):
        t, ok = QInputDialog.getText(self, "Caption", "Caption text (shown from this step on):")
        if ok:
            self.insert_step(f"caption {t}")

    def insert_expect(self):
        def go():
            m = re.search(r"focus \S+ \S+ \S+ #(\S+)", self.tablet().ui("info"))
            return m.group(1) if m else None
        self.jobs.run("expect", go, lambda name: self.insert_step(f"expect #{name}") if name else
                      self.statusBar().showMessage("No named focus item; pick one with Find / Look", 6000))

    def run_script(self, record):
        if not self.conn:
            return
        if self.jobs.busy:
            self.statusBar().showMessage("Busy: wait for the current command", 5000)
            return
        settings, steps = ctl.parse_tutorial(self.script.toPlainText())
        name = settings.get("title") or (os.path.splitext(os.path.basename(self.script_path))[0]
                                         if self.script_path else "script")
        folder = self.new_take_folder(name)
        self.stop_event.clear()
        self.show_tab("Script")

        def log(s):
            self.jobs.log.emit(s)
            m = re.match(r"\[(\d+)\]", s)
            if m:
                self.bridge.script_line.emit(int(m.group(1)))

        def go():
            tab = self.tablet()
            if ctl.run_steps(tab, settings, steps, record=record, stop=self.stop_event, log=log, shot_dir=folder):
                tab.pull_recording(folder)
                return folder
            return None

        def done(f):
            self.script.setExtraSelections([])
            if f:
                self.refresh_takes(select=f)
        if record:
            self.set_recording(True)
            self.jobs.run("run script", go, lambda f: (self.set_recording(False), done(f)))
        else:
            self.jobs.run("try script", go, done)

    def mark_script_line(self, n):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(Qt.GlobalColor.darkYellow)
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        c = QTextCursor(self.script.document().findBlockByLineNumber(n - 1))
        sel.cursor = c
        self.script.setExtraSelections([sel])
        self.script.setTextCursor(c)
        self.refresh_preview()

    # ======================================================================= misc
    def show_shortcuts(self):
        QMessageBox.information(self, "Keyboard shortcuts", (
            "Space  play / pause the result\n←  →  previous / next change\nHome  start\nI / O  set trim in / out\n"
            "Ctrl+R  record / stop\nCtrl+M  caption mark while recording\nCtrl+wheel on the timeline  zoom"))

    def about(self):
        QMessageBox.about(self, "rmpp-studio", (
            f"<b>rmpp-studio {ctl.__version__}</b><br>Record, edit and export reMarkable Paper Pro tutorials over "
            f"SSH.<br><br>MP4 export: {ctl.find_ffmpeg() or 'ffmpeg not found (GIF only)'}<br>User files: {DATA}"
            "<br>License: GPL-3.0-only"))

    def save_settings(self):
        self.cfg.update(conn=self.conn, recordings=self.rec_dir, script=self.script_path, live=self.live.isChecked(),
                        rec_fps=self.rec_fps.value(), out_fps=self.out_fps.value(), out_scale=self.out_scale.value(),
                        geometry=bytes(self.saveGeometry()).hex())
        self.cfg.pop("host", None)
        common.save_settings(self.cfg)

    def closeEvent(self, ev):
        self.pointer_cb.setChecked(False)
        self.toggle_pointer(False)
        self.save_settings()
        super().closeEvent(ev)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lorancecall.rmpp-studio")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("rmpp-studio")
    common.apply_theme(app)
    w = Studio()
    w.show()
    return app.exec()
