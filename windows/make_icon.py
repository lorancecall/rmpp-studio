"""Draw the rmpp-studio icon (a paper tablet with a pen stroke and a record dot) -> rmpp-studio.ico / .png.

python windows/make_icon.py   (Pillow)
"""
import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024


def draw(size=S):
    k = size / S
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # tablet body
    d.rounded_rectangle([130 * k, 40 * k, 894 * k, 984 * k], radius=100 * k, fill=(38, 41, 46, 255))
    # paper screen
    d.rounded_rectangle([190 * k, 100 * k, 834 * k, 924 * k], radius=40 * k, fill=(244, 241, 232, 255))
    # ruled lines
    for y in range(260, 860, 90):
        d.line([(265 * k, y * k), (760 * k, y * k)], fill=(205, 200, 188, 255), width=max(1, int(6 * k)))
    # handwritten stroke
    pts = []
    for i in range(0, 101):
        t = i / 100
        x = 290 + 430 * t
        y = 560 + 120 * math.sin(t * math.pi * 2.6) * (1 - 0.35 * t) - 90 * t
        pts.append((x * k, y * k))
    w = max(2.0, 32 * k)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):   # round pen: discs along the path
        for j in range(6):
            x, y = x0 + (x1 - x0) * j / 6, y0 + (y1 - y0) * j / 6
            d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=(25, 25, 28, 255))
    # record dot with a white ring
    cx, cy, r = 735 * k, 245 * k, 120 * k
    d.ellipse([cx - r - 18 * k, cy - r - 18 * k, cx + r + 18 * k, cy + r + 18 * k], fill=(244, 241, 232, 255))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(222, 52, 52, 255))
    return im


def pen_cursor(path, size=32):
    """A pen cursor image (PNG); rmpp-studio uses it with the hotspot at the nib (3, 29)."""
    from PIL import Image as I, ImageDraw as D
    big = I.new("RGBA", (size * 8, size * 8), (0, 0, 0, 0))
    d = D.Draw(big)
    k = size * 8 / 32
    # pen body along the diagonal from the nib (2,30) to the end (29,3)
    body = [(9, 19), (25, 3), (29, 7), (13, 23)]
    d.polygon([(x * k, y * k) for x, y in body], fill=(40, 40, 44, 255), outline=(255, 255, 255, 255))
    d.polygon([(x * k, y * k) for x, y in [(9, 19), (13, 23), (3, 29)]], fill=(244, 241, 232, 255),
              outline=(40, 40, 44, 255))
    d.polygon([(x * k, y * k) for x, y in [(3, 29), (5.5, 26.5), (5.5, 29), (3, 29)]], fill=(20, 20, 20, 255))
    big.resize((size, size), I.LANCZOS).save(path)


if __name__ == "__main__":
    big = draw(2048).resize((S, S), Image.LANCZOS)   # supersampled
    big.save(os.path.join(HERE, "rmpp-studio.png"))
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    # small sizes drawn from the big one with good downsampling
    big.save(os.path.join(HERE, "rmpp-studio.ico"), sizes=[(s, s) for s in sizes])
    print("wrote rmpp-studio.ico / .png")
    pen_cursor(os.path.join(HERE, "pen-cursor.png"))
    print("wrote pen-cursor.png")
