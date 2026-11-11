"""How xochitl's pens look, so strokes written on the tablet can be drawn on the PC right away (the LIVE monitor
refreshes once a second). Values are approximations in tablet pixels (1620 x 2160 screen)."""
from PySide6.QtGui import QColor

# tool name prefix -> (widths for thickness 1, 2, 3; how much pressure changes the width; opacity; gray-ish)
TOOLS = {
    "Ballpoint": ((2.2, 3.2, 4.8), 0.35, 1.0, False),
    "Fineliner": ((2.0, 3.2, 5.0), 0.0, 1.0, False),
    "Marker": ((5.0, 8.0, 12.0), 0.15, 1.0, False),
    "Highlighter": ((22.0, 30.0, 40.0), 0.0, 0.45, False),
    "SharpPencil": ((1.5, 2.2, 3.2), 0.2, 0.8, True),
    "Pencil": ((2.0, 3.0, 4.5), 0.4, 0.75, True),
    "Paintbrush": ((4.0, 8.0, 14.0), 0.8, 1.0, False),
    "Brush": ((4.0, 8.0, 14.0), 0.8, 1.0, False),
    "Calligraphy": ((3.0, 6.0, 9.0), 0.6, 1.0, False),
    "Shader": ((10.0, 16.0, 24.0), 0.0, 0.35, False),
}

COLORS = {   # Line::Color names (substring match, longest first)
    "HighlighterYellow": "#ffe94d", "HighlighterGreen": "#a6e36a", "HighlighterPink": "#ff9ad5",
    "HighlighterOrange": "#ffb45c", "HighlighterGray": "#c8c8c8", "HighlighterBlue": "#8fd0ff",
    "Black": "#000000", "Gray": "#7d7d7d", "White": "#ffffff", "Blue": "#1f4fd1", "Red": "#d32f2f",
    "Green": "#2e9b3c", "Yellow": "#f2c500", "Pink": "#e6508c", "Cyan": "#18a7c8", "Magenta": "#c2185b",
    "Orange": "#ef7d1a", "Purple": "#7b3fbf",
}


class InkStyle:
    def __init__(self, tool="Ballpointv2", color="Black", code=0xFF000000, thickness=2.0):
        self.tool = tool
        key = next((k for k in TOOLS if tool.startswith(k)), "Ballpoint")
        widths, self.pressure, self.opacity, gray = TOOLS[key]
        i = max(0, min(2, int(round(thickness)) - 1))
        self.width = widths[i]
        name = next((k for k in sorted(COLORS, key=len, reverse=True) if k in color), None)
        if name:
            self.color = QColor(COLORS[name])
        else:
            self.color = QColor.fromRgba(code) if code else QColor("#000000")
        if key == "Highlighter" and not name:
            self.color = QColor(COLORS["HighlighterYellow"])
        if gray and self.color == QColor("#000000"):
            self.color = QColor("#3c3c3c")
        self.color.setAlphaF(self.opacity)

    def width_at(self, pressure):
        return self.width * (1 - self.pressure + self.pressure * 2 * max(0.05, min(1.0, pressure)))

    @staticmethod
    def parse(reply):
        """'ok menu=primary tool=Ballpointv2 color=Black code=ff000000 thickness=2' -> InkStyle, or None for
        non-pen tools (eraser, selection, typing)"""
        kv = dict(part.split("=", 1) for part in reply.split()[1:] if "=" in part)
        if kv.get("tool", "none") == "none":
            return None
        try:
            code = int(kv.get("code", "ff000000"), 16)
            thickness = float(kv.get("thickness", 2))
        except ValueError:
            code, thickness = 0xFF000000, 2.0
        return InkStyle(kv["tool"], kv.get("color", "Black"), code, thickness)
