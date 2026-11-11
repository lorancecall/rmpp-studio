"""The big picture in the middle: the tablet's screen (interactive) or a frame of the take being edited."""
import os
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .common import PEN_CURSOR, ctl

TW, TH = ctl.W, ctl.H   # tablet screen size (portrait)


class Viewer(QWidget):
    """Shows an image scaled to fit (aspect kept). In 'tablet' mode the mouse drives the tablet:
       click = tap, hold = long press, drag = swipe; in pen mode drag = pen stroke; right click = what is there."""
    action = Signal(str, object)      # rmpp-ctl command, (x, y) or None
    look = Signal(int, int)           # right click: items under this tablet point
    hover = Signal(int, int)          # tablet coordinates under the mouse
    penEntered = Signal()             # the real pen came into range (time to ask which pen is active)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 400)
        self.setMouseTracking(True)
        self.image = QImage()
        self.scaled = QImage()        # self.image downscaled for the current size (good filtering, cached)
        self.interactive = True
        self.input_mode = "tap"       # tap | pen | look
        self.placeholder = "Not connected"
        self.dim = False              # take frame outside the trim range
        self.drag = None
        self.press_time = 0.0
        self.pen = None               # (x, y, pressure, state) from rmpp-remote watch
        self.touches = []
        self.stroke = []              # stroke being written on the tablet: [(x, y, pressure)]
        self.strokes = []             # finished strokes not yet in a LIVE frame: [(points, style, menu, t_end)]
        self.ink_style = None         # InkStyle of the active pen (None: not a pen or not known)
        self.ink_menu = ""            # active tool menu: primary / secondary / eraserMenu / selectionButton / ...
        self.box = None               # highlighted UI item (tablet coordinates)
        self.update_cursor()

    # ---------- content ----------
    def set_image(self, img, taken_at=None):
        """taken_at: when a LIVE screenshot was requested; strokes finished before that are in the picture now"""
        self.image = img if img is not None else QImage()
        self.scaled = QImage()
        if taken_at is not None:
            self.strokes = [s for s in self.strokes if s[3] > taken_at - 0.3]
        self.update()

    def scaled_image(self, r):
        """The picture at the on-screen pixel size. QPainter's own scaling while drawing samples too few pixels
        when shrinking ~3x (thin e-paper lines turn into dashes), so shrink once with Qt's smooth (averaging)
        scaler, at the real device pixel size (HiDPI), and reuse it until the image or the size changes."""
        dpr = self.devicePixelRatioF()
        w, h = max(1, round(r.width() * dpr)), max(1, round(r.height() * dpr))
        if self.scaled.isNull() or self.scaled.width() != w or self.scaled.height() != h:
            img = self.image
            # shrink in halving steps first (each step averages 2x2 pixels), then to the exact size
            while img.width() >= 2 * w and img.height() >= 2 * h:
                img = img.scaled(img.width() // 2, img.height() // 2, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            self.scaled = img.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            self.scaled.setDevicePixelRatio(dpr)
        return self.scaled

    def set_mode(self, interactive):
        self.interactive = interactive
        if not interactive:
            self.pen, self.touches, self.stroke, self.strokes, self.box = None, [], [], [], None
        self.update_cursor()
        self.update()

    def set_input_mode(self, mode):
        self.input_mode = mode
        self.update_cursor()

    def update_cursor(self):
        if not self.interactive:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self.input_mode == "pen" and os.path.exists(PEN_CURSOR):
            self.setCursor(QCursor(QPixmap(PEN_CURSOR), 3, 29))
        elif self.input_mode == "pen":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self.input_mode == "look":
            self.setCursor(Qt.CursorShape.WhatsThisCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ---------- geometry ----------
    def screen_rect(self):
        w, h = self.width() - 16, self.height() - 16
        s = min(w / TW, h / TH)
        return QRectF((self.width() - TW * s) / 2, (self.height() - TH * s) / 2, TW * s, TH * s)

    def to_tablet(self, pos):
        r = self.screen_rect()
        return (int((pos.x() - r.x()) / r.width() * TW), int((pos.y() - r.y()) / r.height() * TH))

    def to_widget(self, x, y):
        r = self.screen_rect()
        return QPointF(r.x() + x / TW * r.width(), r.y() + y / TH * r.height())

    # ---------- painting ----------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(24, 25, 28))
        r = self.screen_rect()
        p.fillRect(r.adjusted(-6, -6, 6, 6), QColor(12, 12, 14))   # the device bezel
        if self.image.isNull():
            p.fillRect(r, QColor(60, 60, 64))
            p.setPen(QColor(180, 180, 180))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.placeholder)
        else:
            p.drawImage(QPointF(round(r.x()), round(r.y())), self.scaled_image(r))
            if self.dim:
                p.fillRect(r, QColor(0, 0, 0, 120))
        if self.box:
            x, y, w, h = self.box
            a, b = self.to_widget(x, y), self.to_widget(x + w, y + h)
            p.setPen(QPen(QColor(230, 60, 60), 2))
            p.drawRect(QRectF(a, b))
        if self.drag and len(self.drag) > 1:
            p.setPen(QPen(QColor(220, 50, 50) if self.input_mode == "pen" else QColor(60, 120, 230), 3))
            for a, b in zip(self.drag, self.drag[1:]):
                p.drawLine(a, b)
        for pts, style, menu, _ in self.strokes:
            self.draw_stroke(p, pts, style, menu)
        if len(self.stroke) > 1:
            self.draw_stroke(p, self.stroke, self.ink_style, self.ink_menu)
        if self.pen:
            x, y, pr, state = self.pen
            c = self.to_widget(x, y)
            color = QColor(194, 24, 91) if state.startswith("eraser") else QColor(21, 101, 192)
            if state.endswith("down"):
                rad = 3 + 6 * pr
                p.setPen(QPen(Qt.GlobalColor.white, 1))
                p.setBrush(color)
                p.drawEllipse(c, rad, rad)
            else:
                p.setPen(QPen(color, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, 8, 8)
                p.drawLine(c + QPointF(-4, 0), c + QPointF(4, 0))
                p.drawLine(c + QPointF(0, -4), c + QPointF(0, 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(46, 125, 50), 3))
        for x, y in self.touches:
            p.drawEllipse(self.to_widget(x, y), 14, 14)

    def draw_stroke(self, p, pts, style, menu):
        """a stroke written on the tablet, drawn like the tablet will show it"""
        k = self.screen_rect().width() / TW
        if style is not None:   # a pen: its color, width (and pressure), opacity
            if style.pressure > 0:
                for (x0, y0, p0), (x1, y1, p1) in zip(pts, pts[1:]):
                    pen = QPen(style.color, max(0.8, style.width_at((p0 + p1) / 2) * k))
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    p.setPen(pen)
                    p.drawLine(self.to_widget(x0, y0), self.to_widget(x1, y1))
            else:   # one path, so translucent tools (highlighter) do not darken where segments overlap
                path = QPainterPath(self.to_widget(pts[0][0], pts[0][1]))
                for x, y, _ in pts[1:]:
                    path.lineTo(self.to_widget(x, y))
                pen = QPen(style.color, max(0.8, style.width * k))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
        elif menu == "selectionButton":   # lasso: thin dashed line
            p.setPen(QPen(QColor(90, 90, 90), 1, Qt.PenStyle.DashLine))
            for (x0, y0, _), (x1, y1, _) in zip(pts, pts[1:]):
                p.drawLine(self.to_widget(x0, y0), self.to_widget(x1, y1))
        elif menu in ("eraserMenu",) or menu.startswith("eraser"):
            return   # the eraser leaves no ink
        else:   # tool not known (older add-on): a thin blue trace
            p.setPen(QPen(QColor(21, 101, 192), 2))
            for (x0, y0, _), (x1, y1, _) in zip(pts, pts[1:]):
                p.drawLine(self.to_widget(x0, y0), self.to_widget(x1, y1))

    # ---------- pointer stream from the tablet ----------
    def pointer_line(self, line):
        parts = line.split()
        if parts[0] == "pen":
            if parts[1] == "out":
                self.finish_stroke()
                self.pen = None
            else:
                x, y, pr, state = int(parts[1]), int(parts[2]), float(parts[3]), parts[4]
                if self.pen is None:
                    self.penEntered.emit()
                if state.endswith("down"):
                    menu = "eraserMenu" if state.startswith("eraser") else self.ink_menu
                    if not self.stroke:
                        self.stroke_menu = menu
                    self.stroke.append((x, y, pr))
                else:
                    self.finish_stroke()
                self.pen = (x, y, pr, state)
        elif parts[0] == "touch":
            self.touches = []
            if parts[1] != "none":
                for pt in " ".join(parts[1:]).split(";"):
                    xs, ys = pt.split()
                    self.touches.append((int(xs), int(ys)))
        self.update()

    def finish_stroke(self):
        if len(self.stroke) > 1:
            menu = getattr(self, "stroke_menu", self.ink_menu)
            style = None if menu.startswith("eraser") else self.ink_style
            self.strokes.append((self.stroke, style, menu, time.time()))
        self.stroke = []

    # ---------- mouse -> tablet ----------
    def mousePressEvent(self, ev):
        if not self.interactive:
            return
        if ev.button() == Qt.MouseButton.RightButton:
            self.look.emit(*self.to_tablet(ev.position()))
            return
        self.drag = [ev.position()]
        self.press_time = time.time()

    def mouseMoveEvent(self, ev):
        x, y = self.to_tablet(ev.position())
        if 0 <= x < TW and 0 <= y < TH:
            self.hover.emit(x, y)
        if self.drag is not None:
            last = self.drag[-1]
            if abs(ev.position().x() - last.x()) + abs(ev.position().y() - last.y()) >= 3:
                self.drag.append(ev.position())
                self.update()

    def mouseReleaseEvent(self, ev):
        if self.drag is None or ev.button() != Qt.MouseButton.LeftButton:
            return
        pts = [self.to_tablet(p) for p in self.drag]
        held = time.time() - self.press_time
        self.drag = None
        self.update()
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        moved = abs(x1 - x0) + abs(y1 - y0) > 30 or len(pts) > 4
        if self.input_mode == "look":
            self.look.emit(x0, y0)
        elif self.input_mode == "pen":
            if len(pts) == 1:
                pts.append((x0 + 2, y0 + 2))
            self.action.emit("draw points " + " ".join(f"{x},{y}" for x, y in pts), None)
        elif moved:
            self.action.emit(f"swipe {x0} {y0} {x1} {y1} {max(200, int(held * 1000))}", None)
        elif held > 0.6:
            self.action.emit(f"longpress {x0} {y0}", (x0, y0))
        else:
            self.action.emit(f"tap {x0} {y0}", (x0, y0))
