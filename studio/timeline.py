"""Timeline of the edited sequence: the recording is cut into clips (source ranges) that can be split, trimmed,
reordered, duplicated and deleted. Tracks: time ruler, clips with thumbnails, captions. Positions on the timeline
are sequence milliseconds; clips and captions keep source milliseconds."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .common import fmt_ms

RULER, CLIPS, CAPS = 24, 76, 38
PAD = 12
EDGE = 6   # px around a clip edge that grabs the edge (trim) instead of the clip (move)


class Timeline(QWidget):
    seek = Signal(int)               # playhead moved by the user (sequence ms)
    clipsChanged = Signal(str)       # segments changed (description for undo)
    clipSelected = Signal(int)
    captionsChanged = Signal()       # caption moved
    captionSelected = Signal(int)    # index into self.captions
    captionEdit = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(RULER + CLIPS + CAPS + 16)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.src_length = 0
        self.segments = []        # [[a, b]] source ranges, in output order (shared with the edit dict)
        self.thumbs = []          # [(source ms, QImage)]
        self.captions = []        # [[source ms, text]] (shared)
        self.playhead = 0         # sequence ms
        self.selected = -1        # caption index
        self.clip = -1            # selected clip
        self.zoom = 0.0           # px per ms; 0 = fit
        self.offset = 0.0         # sequence ms at the left edge
        self.drag = None

    # ---------- model ----------
    def set_take(self, src_length, thumbs, captions, segments):
        self.src_length = max(1, src_length)
        self.thumbs, self.captions, self.segments = thumbs, captions, segments
        self.playhead, self.selected, self.clip, self.zoom, self.offset = 0, -1, -1, 0.0, 0.0
        self.update()

    def clear(self):
        self.src_length, self.segments, self.thumbs, self.captions = 0, [], [], []
        self.update()

    @property
    def length(self):
        return sum(b - a for a, b in self.segments)

    def offsets(self):
        out, off = [], 0
        for a, b in self.segments:
            out.append(off)
            off += b - a
        return out

    def seq_to_src(self, ms):
        off = 0
        for i, (a, b) in enumerate(self.segments):
            if ms < off + (b - a) or i == len(self.segments) - 1:
                return min(b, a + max(0, ms - off)), i
            off += b - a
        return 0, -1

    def clip_at(self, ms):
        return self.seq_to_src(ms)[1]

    def set_playhead(self, ms):
        self.playhead = max(0, min(self.length, int(ms)))
        x = self.x_of(self.playhead)
        if x < PAD or x > self.width() - PAD:
            self.offset = max(0.0, self.playhead - (self.width() - 2 * PAD) / self.scale() / 3)
        self.update()

    # ---------- geometry ----------
    def scale(self):
        fit = (self.width() - 2 * PAD) / max(1, self.length)
        return max(fit, self.zoom) if self.zoom else fit

    def x_of(self, ms):
        return PAD + (ms - self.offset) * self.scale()

    def ms_of(self, x):
        return int(max(0, min(self.length, (x - PAD) / self.scale() + self.offset)))

    def clip_rect(self, i):
        o = self.offsets()[i]
        a, b = self.segments[i]
        return QRectF(self.x_of(o), RULER + 2, max(2.0, (b - a) * self.scale()), CLIPS - 4)

    def caption_blocks(self):
        """per clip: [(clip, caption index or -1 when carried over from before the clip, seq start, seq end, text)]"""
        caps = sorted(range(len(self.captions)), key=lambda i: self.captions[i][0])
        blocks = []
        for ci, ((a, b), o) in enumerate(zip(self.segments, self.offsets())):
            inside = [i for i in caps if a < self.captions[i][0] < b]
            before = [i for i in caps if self.captions[i][0] <= a]
            starts = ([(a, before[-1] if before else None, True)] +
                      [(self.captions[i][0], i, False) for i in inside])
            for n, (src, idx, carried) in enumerate(starts):
                end = starts[n + 1][0] if n + 1 < len(starts) else b
                text = self.captions[idx][1] if idx is not None else ""
                if text:
                    blocks.append((ci, -1 if carried and (idx is None or self.captions[idx][0] < a) else idx,
                                   o + src - a, o + end - a, text))
        return blocks

    # ---------- painting ----------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(28, 29, 32))
        if not self.segments:
            p.setPen(QColor(150, 150, 150))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Record something or pick a recording on the left")
            return
        w = self.width()
        p.fillRect(QRectF(0, RULER, w, CLIPS), QColor(34, 36, 40))
        p.fillRect(QRectF(0, RULER + CLIPS, w, CAPS), QColor(31, 33, 37))
        f = QFont(p.font())
        f.setPointSizeF(8)
        p.setFont(f)
        # ruler
        p.setPen(QColor(150, 150, 150))
        step = self.tick_step()
        t = (int(self.offset) // step) * step
        while self.x_of(t) < w:
            x = self.x_of(t)
            if x >= 0:
                p.drawLine(QPointF(x, RULER - 6), QPointF(x, RULER))
                p.drawText(QPointF(x + 3, RULER - 9), fmt_ms(t)[:-2] if step >= 1000 else fmt_ms(t))
            t += step
        # clips with their thumbnails
        th_h = CLIPS - 14
        tw = th_h * 3 / 4
        for i, (a, b) in enumerate(self.segments):
            r = self.clip_rect(i)
            if r.right() < 0 or r.left() > w:
                continue
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(52, 62, 80) if i % 2 == 0 else QColor(60, 56, 78))
            p.drawRoundedRect(r, 5, 5)
            p.save()
            p.setClipRect(r.adjusted(2, 0, -2, 0))
            last_right = -1e9
            visible = [(ms, img) for ms, img in self.thumbs if a <= ms < b]
            if not visible or visible[0][0] > a:   # the picture at the clip start comes from before it
                before = [t for t in self.thumbs if t[0] <= a]
                if before:
                    visible.insert(0, (a, before[-1][1]))
            for ms, img in visible:
                x = r.left() + (ms - a) * self.scale() + 2
                if x < last_right + 2:
                    continue
                p.drawImage(QRectF(x, r.top() + 5, tw, th_h), img)
                last_right = x + tw
            p.restore()
            sel = i == self.clip
            p.setPen(QPen(QColor(250, 200, 60) if sel else QColor(20, 20, 24), 3 if sel else 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 5, 5)
            if r.width() > 60:
                p.setPen(QColor(220, 220, 220))
                p.drawText(QRectF(r.left() + 5, r.bottom() - 14, r.width() - 10, 12),
                           Qt.AlignmentFlag.AlignRight, fmt_ms(b - a)[:-2] if b - a >= 10000 else fmt_ms(b - a))
        # captions
        fm = QFontMetrics(p.font())
        for ci, idx, s0, s1, text in self.caption_blocks():
            r = QRectF(self.x_of(s0), RULER + CLIPS + 6, max(4.0, (s1 - s0) * self.scale()), CAPS - 10)
            carried = idx == -1
            sel = idx == self.selected and idx >= 0
            p.setPen(QPen(QColor(255, 255, 255) if sel else QColor(80, 50, 50), 2 if sel else 1))
            p.setBrush(QColor(84, 44, 44) if carried else QColor(150, 48, 48) if sel else QColor(112, 40, 40))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor(200, 200, 200) if carried else QColor(240, 240, 240))
            p.drawText(r.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(text, Qt.TextElideMode.ElideRight, int(r.width() - 10)))
        # drop marker while moving a clip
        if self.drag and self.drag[0] == "move" and self.drag[3]:
            x = self.drop_x(self.drag[4])
            p.setPen(QPen(QColor(250, 200, 60), 3))
            p.drawLine(QPointF(x, RULER), QPointF(x, RULER + CLIPS))
        # playhead
        x = self.x_of(self.playhead)
        p.setPen(QPen(QColor(240, 70, 70), 2))
        p.drawLine(QPointF(x, 2), QPointF(x, self.height()))
        p.setBrush(QColor(240, 70, 70))
        p.drawPolygon([QPointF(x - 6, 2), QPointF(x + 6, 2), QPointF(x, 10)])

    def tick_step(self):
        px_per_s = self.scale() * 1000
        for step in (100, 250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000):
            if step / 1000 * px_per_s >= 70:
                return step
        return 120000

    # ---------- mouse ----------
    def hit(self, pos):
        x, y = pos.x(), pos.y()
        if RULER <= y <= RULER + CLIPS:
            for i in range(len(self.segments)):
                r = self.clip_rect(i)
                if abs(x - r.left()) <= EDGE and r.top() <= y <= r.bottom():
                    return "left", i
                if abs(x - r.right()) <= EDGE and r.top() <= y <= r.bottom():
                    return "right", i
            for i in range(len(self.segments)):
                if self.clip_rect(i).contains(pos):
                    return "clip", i
        if RULER + CLIPS <= y <= RULER + CLIPS + CAPS:
            for ci, idx, s0, s1, _ in self.caption_blocks():
                if idx >= 0 and self.x_of(s0) - 3 <= x <= self.x_of(s1) + 3:
                    return "cap", idx
        return "playhead", None

    def drop_index(self, x):
        offs = self.offsets()
        for i, (a, b) in enumerate(self.segments):
            if x < self.x_of(offs[i] + (b - a) / 2):
                return i
        return len(self.segments)

    def drop_x(self, index):
        offs = self.offsets() + [self.length]
        return self.x_of(offs[index]) if index < len(offs) else self.x_of(self.length)

    def mousePressEvent(self, ev):
        if not self.segments or ev.button() != Qt.MouseButton.LeftButton:
            return
        kind, i = self.hit(ev.position())
        x = ev.position().x()
        if kind == "clip":
            self.clip = i
            self.clipSelected.emit(i)
            self.drag = ["move", i, x, False, i]
            self.set_playhead(self.ms_of(x))
            self.seek.emit(self.playhead)
        elif kind in ("left", "right"):
            self.clip = i
            self.clipSelected.emit(i)
            self.drag = [kind, i, x, list(self.segments[i])]
        elif kind == "cap":
            self.selected = i
            self.captionSelected.emit(i)
            src0 = self.captions[i][0]
            self.drag = ["cap", i, x, src0]
            self.seek_src(src0)
        else:
            self.drag = ["playhead"]
            self.set_playhead(self.ms_of(x))
            self.seek.emit(self.playhead)
        self.update()

    def seek_src(self, src):
        """move the playhead to the first place this source time appears"""
        for (a, b), o in zip(self.segments, self.offsets()):
            if a <= src < b:
                self.set_playhead(o + src - a)
                self.seek.emit(self.playhead)
                return

    def mouseMoveEvent(self, ev):
        x = ev.position().x()
        if not self.drag:
            kind, _ = self.hit(ev.position())
            self.setCursor(Qt.CursorShape.SizeHorCursor if kind in ("left", "right") else
                           Qt.CursorShape.OpenHandCursor if kind in ("clip", "cap") else Qt.CursorShape.ArrowCursor)
            return
        kind = self.drag[0]
        if kind == "playhead":
            self.set_playhead(self.ms_of(x))
            self.seek.emit(self.playhead)
        elif kind == "move":
            if abs(x - self.drag[2]) > 8:
                self.drag[3] = True
                self.drag[4] = self.drop_index(x)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif kind in ("left", "right"):
            i, (a, b) = self.drag[1], self.drag[3]
            d = int((x - self.drag[2]) / self.scale())
            if kind == "left":
                self.segments[i][0] = max(0, min(b - 100, a + d))
            else:
                self.segments[i][1] = min(self.src_length, max(a + 100, b + d))
            self.seek_src(self.segments[i][0] if kind == "left" else self.segments[i][1] - 1)
        elif kind == "cap":
            i, src0 = self.drag[1], self.drag[3]
            # stay inside the clip the caption was in
            clip = next(((a, b) for a, b in self.segments if a <= src0 < b), None)
            new = src0 + int((x - self.drag[2]) / self.scale())
            if clip:
                new = max(clip[0], min(clip[1] - 1, new))
            self.captions[i][0] = max(0, min(self.src_length, new))
            self.seek_src(self.captions[i][0])
        self.update()

    def mouseReleaseEvent(self, ev):
        if not self.drag:
            return
        kind = self.drag[0]
        if kind == "move" and self.drag[3]:
            i, to = self.drag[1], self.drag[4]
            if to not in (i, i + 1):
                seg = self.segments.pop(i)
                self.segments.insert(to - 1 if to > i else to, seg)
                self.clip = to - 1 if to > i else to
                self.clipsChanged.emit("move clip")
        elif kind in ("left", "right") and self.segments[self.drag[1]] != self.drag[3]:
            self.clipsChanged.emit("trim clip")
        elif kind == "cap" and self.captions[self.drag[1]][0] != self.drag[3]:
            self.captionsChanged.emit()
        self.drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, ev):
        kind, i = self.hit(ev.position())
        if kind == "cap":
            self.captionEdit.emit(i)

    def wheelEvent(self, ev):
        if not self.segments:
            return
        d = ev.angleDelta().y() or ev.angleDelta().x()
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:   # zoom around the mouse
            at = self.ms_of(ev.position().x())
            self.zoom = max(self.scale() * (1.25 if d > 0 else 0.8), (self.width() - 2 * PAD) / max(1, self.length))
            self.offset = max(0.0, at - (ev.position().x() - PAD) / self.scale())
        else:
            visible = (self.width() - 2 * PAD) / self.scale()
            self.offset = max(0.0, min(max(0.0, self.length - visible), self.offset - d / 120 * visible / 8))
        self.update()
