#!/usr/bin/env python3
"""rmpp-ctl: drive and record a reMarkable Paper Pro from the PC over SSH.

Needs the tablet parts from this repository (deploy.sh): /usr/lib/rmpp-remote/rmpp-remote (input injection and
add-on client) and librmpp-remote.so loaded in xochitl. Coordinates are xochitl screen pixels (portrait 1620 x 2160,
origin top left), the same as in screenshots.

  rmpp-ctl [--host H] shot [out.png]
  rmpp-ctl tap X Y | tap "<ui query>"            (query: words, #objectName or "exact text"; see `find`)
  rmpp-ctl longpress X Y [ms] | swipe X1 Y1 X2 Y2 [ms]
  rmpp-ctl line X1 Y1 X2 Y2 [pressure]
  rmpp-ctl draw rect|circle|arrow ... | draw points X,Y X,Y ...
  rmpp-ctl lasso X1 Y1 X2 Y2                     (lasso tool must be active: draws a closed loop)
  rmpp-ctl text "hello" | key enter | key ctrl+z
  rmpp-ctl find <query> | tree [depth] | hit X Y | prop <name> <query> | props <query> | info | pointers
  rmpp-ctl open "<notebook name>" | expect <query> [timeout ms] | tool <query> | tap-if <query> | wait <ms> | ui <raw add-on command>
  rmpp-ctl input < script.txt                    (raw rmpp-remote script, one ssh call)
  rmpp-ctl record start [fps] | record mark <caption> | record stop out.gif|out.mp4
  rmpp-ctl run tutorial.tut [-o out.mp4]         (see tutorials/README.md)
  rmpp-ctl render <recording folder> out.mp4|.webm|.mov|.gif|.webp|.apng [fps] [scale]
              [--codec h264|h265|av1|vp9|prores] [--quality high|medium|small]   (uses the recording's edit.json)

Environment: RMPP_HOST (ssh host, default "rmpp").
"""
import argparse
import io
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

__version__ = "0.3.0"

TOOL = "/usr/lib/rmpp-remote/rmpp-remote"
REC_DIR = "/tmp/rmpp-remote/rec"
W, H = 1620, 2160


USB_HOST = "10.11.99.1"   # the tablet's address over the USB cable


def ssh_config_hosts(path=None):
    """Host entries of ~/.ssh/config (no wildcard patterns): [{alias, hostname, user, port, identity}]."""
    path = path or os.path.join(os.path.expanduser("~"), ".ssh", "config")
    hosts, cur = [], []
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return hosts
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace("=", " ", 1).split(None, 1)
        key, val = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        if key == "host":
            cur = [{"alias": a, "hostname": "", "user": "", "port": "", "identity": ""}
                   for a in val.split() if not any(ch in a for ch in "*?!")]
            hosts += cur
        elif key == "match":
            cur = []
        elif key in ("hostname", "user", "port", "identityfile"):
            for h in cur:
                h["identity" if key == "identityfile" else key] = val
    return hosts


def looks_like_tablet(h):
    a = (h["alias"] + " " + h["hostname"]).lower()
    return h["user"] == "root" or USB_HOST in a or "remarkable" in a or a.startswith(("rm", "rmpp"))


class Tablet:
    """SSH access to the tablet: an ~/.ssh/config alias, or user@host with port and key."""

    def __init__(self, host, verbose=False, port=None, user=None, key=None):
        self.host = host
        self.verbose = verbose
        self.port, self.user, self.key = port, user, key

    @classmethod
    def from_conn(cls, conn):
        conn = conn or {}
        if conn.get("mode") == "direct":
            return cls(conn.get("host") or USB_HOST, port=conn.get("port") or 22, user=conn.get("user") or "root",
                       key=conn.get("key") or None)
        return cls(conn.get("alias") or os.environ.get("RMPP_HOST", "rmpp"))

    def describe(self):
        if self.user or self.port or self.key:
            return f"{self.user or 'root'}@{self.host}:{self.port or 22}"
        return f"{self.host} (ssh config)"

    def ssh_args(self, batch=True):
        a = ["-o", "ConnectTimeout=8"]
        if batch:
            a += ["-o", "BatchMode=yes"]
        if self.port:
            a += ["-p", str(self.port)]
        if self.key:
            a += ["-i", self.key, "-o", "IdentitiesOnly=yes"]
        if self.user or self.port or self.key:   # direct connection: remember the tablet's host key on first use
            a += ["-o", "StrictHostKeyChecking=accept-new"]
        return a + [f"{self.user}@{self.host}" if self.user else self.host]

    def ssh(self, remote, data=None, binary=False, check=True):
        if self.verbose:
            print(f"[ssh] {remote}", file=sys.stderr)
        r = subprocess.run(["ssh"] + self.ssh_args() + [remote], input=data,
                           capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if check and r.returncode != 0:
            msg = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
            raise SystemExit(f"rmpp-ctl: {remote!r} failed: {msg}")
        return r.stdout if binary else r.stdout.decode("utf-8", "replace")

    def probe(self):
        """(ok, summary): can we log in, is rmpp-preload there, is the rmpp-remote add-on installed and loaded"""
        r = subprocess.run(["ssh"] + self.ssh_args() + [
            "echo ssh-ok; uname -m; test -d /usr/lib/rmpp-preload.d && echo preload; "
            f"test -x {TOOL} && echo tool; {TOOL} ui ping 2>/dev/null"],
            capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = r.stdout.decode("utf-8", "replace").split()
        if "ssh-ok" not in out:
            err = r.stderr.decode("utf-8", "replace").strip().splitlines()
            return False, "SSH failed: " + (err[-1] if err else f"exit {r.returncode}")
        arch = out[1] if len(out) > 1 else "?"
        parts = [f"SSH ok ({arch})", "rmpp-preload: " + ("yes" if "preload" in out else "NOT installed")]
        if "ok" in out:
            parts.append("rmpp-remote: running")
        elif "tool" in out:
            parts.append("rmpp-remote: installed, not loaded (restart xochitl)")
        else:
            parts.append("rmpp-remote: not installed (Tablet > Install)")
        return True, " | ".join(parts)

    def ui(self, cmd, check=True):
        # the remote shell sees one single-quoted argument; quotes inside are escaped by shlex
        return self.ssh(f"{TOOL} ui {shlex.quote(cmd)}", check=check).rstrip("\n")

    def script(self, lines):
        text = "\n".join(lines) + "\n"
        return self.ssh(TOOL, data=text.encode("utf-8"))

    def center(self, query):
        out = self.ui(f"center {query}", check=False)
        m = re.match(r"^(-?\d+) (-?\d+)$", out.strip())
        if not m:
            raise SystemExit(f"rmpp-ctl: cannot tap {query!r}: {out.strip()}")
        return int(m.group(1)), int(m.group(2))

    def shot(self, out):
        self.ui("shot /tmp/rmpp-remote/shot.png")
        data = self.ssh("cat /tmp/rmpp-remote/shot.png", binary=True)
        with open(out, "wb") as f:
            f.write(data)
        return out

    def pull_recording(self, dest):
        data = self.ssh(f"tar -C {REC_DIR} -cf - .", binary=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(dest, filter="data")


# ---------- shapes -> rmpp-remote script lines ----------

def pts_cmd(points, pressure=0.5, speed=1200):
    return f"stroke {pressure} {speed} : " + " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def circle(cx, cy, r, n=72):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def rect(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]


def arrow(x1, y1, x2, y2, head=40):
    a = math.atan2(y2 - y1, x2 - x1)
    l = (x2 - head * math.cos(a - 0.45), y2 - head * math.sin(a - 0.45))
    r = (x2 - head * math.cos(a + 0.45), y2 - head * math.sin(a + 0.45))
    return [[(x1, y1), (x2, y2)], [l, (x2, y2), r]]


def lasso_loop(x1, y1, x2, y2):
    # a closed loop around the box, with a little overlap so xochitl closes it
    pts = rect(x1, y1, x2, y2) + [(x2, y1)]
    return pts


def draw_lines(kind, args):
    f = [float(a) for a in args if re.match(r"^-?\d+(\.\d+)?$", a)]
    if kind == "rect":
        return [pts_cmd(rect(*f[:4]))]
    if kind == "circle":
        return [pts_cmd(circle(*f[:3]))]
    if kind == "arrow":
        return [pts_cmd(s) for s in arrow(*f[:4])]
    if kind == "points":
        pts = [tuple(map(float, a.split(",")[:2])) for a in args if "," in a]
        return [pts_cmd(pts)]
    raise SystemExit(f"rmpp-ctl: unknown shape {kind}")


# ---------- recording -> GIF / MP4 ----------

def load_timeline(folder):
    """frames.txt: '<ms> <file>' samples and '<ms> # <caption>' marks."""
    samples, marks = [], []
    with open(os.path.join(folder, "frames.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            ms, rest = line.split(" ", 1)
            if rest.startswith("# "):
                marks.append((int(ms), rest[2:]))
            elif rest.startswith("#"):
                marks.append((int(ms), ""))
            else:
                samples.append((int(ms), rest))
    return samples, marks


def caption_font(size):
    from PIL import ImageFont
    # Malgun Gothic first: it has Hangul and Latin; Arial has no Hangul
    for name in ("malgun.ttf", "segoeui.ttf", "arial.ttf", "NotoSansCJK-Regular.ttc", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def load_edit(folder):
    """Edit settings for a recording: edit.json if present, else the marks from frames.txt.
       {"captions": [[ms, text], ...], "segments": [[start ms, end ms], ...] (the clips of the result, in order;
        absent = the whole recording), "in"/"out" (older single trim), "max_still": seconds|0, "hold_end": seconds}"""
    samples, marks = load_timeline(folder)
    edit = {"captions": [list(m) for m in marks], "in": 0, "out": None, "max_still": 0, "hold_end": 1.5}
    path = os.path.join(folder, "edit.json")
    if os.path.exists(path):
        import json
        with open(path, encoding="utf-8") as f:
            edit.update(json.load(f))
    return samples, edit


def save_edit(folder, edit):
    import json
    with open(os.path.join(folder, "edit.json"), "w", encoding="utf-8") as f:
        json.dump(edit, f, ensure_ascii=False, indent=1)


class Renderer:
    """Turns a recording folder + edit settings into output frames (also used by the GUI preview)."""

    def __init__(self, folder, edit=None, scale=0.5):
        from PIL import ImageFont  # noqa: F401  (fail early without Pillow)
        self.folder = folder
        self.samples, e = load_edit(folder)
        self.edit = edit if edit is not None else e
        if not self.samples:
            raise SystemExit("rmpp-ctl: empty recording")
        self.scale = scale
        self.w, self.h = int(W * scale) // 2 * 2, int(H * scale) // 2 * 2
        self.font = caption_font(max(12, int(44 * scale * 2 * 0.6)))
        self.cache = {}

    @property
    def length(self):
        return self.samples[-1][0]

    def name_at(self, t):
        name = self.samples[0][1]
        for ms, n in self.samples:
            if ms > t:
                break
            name = n
        return name

    def caption_at(self, t):
        cap = ""
        for ms, c in sorted(self.edit.get("captions", []), key=lambda x: x[0]):
            if ms > t:
                break
            cap = c
        return cap

    def frame(self, t):
        from PIL import Image, ImageDraw
        name, cap = self.name_at(t), self.caption_at(t)
        key = (name, cap)
        if key not in self.cache:
            w, h = self.w, self.h
            im = Image.open(os.path.join(self.folder, name)).convert("RGB").resize((w, h), Image.LANCZOS)
            if cap:
                d = ImageDraw.Draw(im)
                font = self.font
                pad = max(6, int(18 * self.scale * 2))
                lines = wrap(d, cap, font, w - 4 * pad)
                lh = font.size + pad // 2
                box_h = lh * len(lines) + pad
                d.rectangle([0, h - box_h - pad, w, h - pad], fill=(30, 30, 30))
                for i, ln in enumerate(lines):
                    tw = d.textlength(ln, font=font)
                    d.text(((w - tw) / 2, h - box_h - pad + pad // 2 + i * lh), ln, font=font, fill=(255, 255, 255))
            if len(self.cache) > 64:
                self.cache.clear()
            self.cache[key] = im
        return self.cache[key]

    # ---- the clips of the result: source ranges in output order
    def segments(self):
        segs = self.edit.get("segments")
        if segs:
            return [[int(a), int(b)] for a, b in segs if b > a]
        t_in = int(self.edit.get("in") or 0)
        t_out = int(self.edit.get("out") or self.length)
        return [[t_in, max(t_in + 1, t_out)]]

    def sequence_length(self):
        return sum(b - a for a, b in self.segments())

    def seq_to_src(self, ms):
        """position in the edited sequence -> (source time, clip index)"""
        off = 0
        segs = self.segments()
        for i, (a, b) in enumerate(segs):
            if ms < off + (b - a) or i == len(segs) - 1:
                return min(b, a + max(0, ms - off)), i
            off += b - a
        return 0, 0

    def src_to_seq(self, ms):
        """source time -> sequence positions (one per clip that contains it)"""
        out, off = [], 0
        for a, b in self.segments():
            if a <= ms < b or (ms == b and b == self.length):
                out.append(off + ms - a)
            off += b - a
        return out

    def change_times(self):
        """times where the picture or the caption changes"""
        ts = {ms for ms, _ in self.samples} | {ms for ms, _ in self.edit.get("captions", [])}
        return sorted(ts)

    def frames_plan(self, fps):
        """[(sequence ms, source ms)] of the output frames: the clips in order, still stretches cut to max_still
        seconds, the last picture held for hold_end seconds"""
        hold = int(float(self.edit.get("hold_end", 1.5)) * 1000)
        max_still = float(self.edit.get("max_still") or 0) * 1000
        changes = self.change_times()
        step = 1000.0 / fps
        out, off, last, still = [], 0, None, 0.0
        for a, b in self.segments():
            t = float(a)
            while t < b:
                key = (self.name_at(t), self.caption_at(t))
                still = still + step if key == last else 0.0
                last = key
                if max_still and still > max_still:
                    nxt = next((c for c in changes if c > t), None)
                    if nxt is None or nxt >= b:
                        break
                    t, still = float(nxt), 0.0
                    continue
                out.append((int(off + t - a), int(t)))
                t += step
            off += b - a
        if out:
            out += [out[-1]] * int(hold / step)   # hold the last picture
        return out

    def times(self, fps):
        """source times of the output frames (see frames_plan)"""
        return [src for _, src in self.frames_plan(fps)]


# ---------- output formats ----------
# extension -> (label, kind, codecs for video formats)
FORMATS = {
    ".mp4": ("MP4 video", "video", ["h264", "h265", "av1"]),
    ".webm": ("WebM video", "video", ["vp9", "av1"]),
    ".mov": ("MOV video", "video", ["h264", "h265", "prores"]),
    ".gif": ("GIF animation", "anim", []),
    ".webp": ("WebP animation", "anim", []),
    ".apng": ("APNG animation (animated PNG)", "anim", []),
}
# codec -> (label, ffmpeg encoder, extra args, quality -> value for the quality option, quality option)
CODECS = {
    "h264": ("H.264 (plays everywhere)", "libx264", ["-pix_fmt", "yuv420p", "-preset", "medium"],
             {"high": 18, "medium": 23, "small": 28}, "-crf"),
    "h265": ("H.265 / HEVC (smaller files)", "libx265", ["-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-x265-params",
                                                         "log-level=error"],
             {"high": 20, "medium": 26, "small": 31}, "-crf"),
    "av1": ("AV1 (smallest, slower)", "libsvtav1", ["-pix_fmt", "yuv420p", "-preset", "8"],
            {"high": 24, "medium": 32, "small": 40}, "-crf"),
    "vp9": ("VP9", "libvpx-vp9", ["-pix_fmt", "yuv420p", "-b:v", "0", "-row-mt", "1"],
            {"high": 24, "medium": 32, "small": 40}, "-crf"),
    "prores": ("ProRes 422 (for video editors, large)", "prores_ks", ["-pix_fmt", "yuv422p10le"],
               {"high": 3, "medium": 2, "small": 0}, "-profile:v"),
}
QUALITIES = ("high", "medium", "small")
GIF_COLORS = {"high": 256, "medium": 128, "small": 64}
WEBP_QUALITY = {"high": 90, "medium": 75, "small": 50}

_encoders = None


def ffmpeg_encoders():
    """names of the encoders the installed ffmpeg has (empty without ffmpeg)"""
    global _encoders
    if _encoders is None:
        _encoders = set()
        ff = find_ffmpeg()
        if ff:
            r = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in r.stdout.decode("utf-8", "replace").splitlines():
                parts = line.split()
                if len(parts) >= 2 and len(parts[0]) == 6:
                    _encoders.add(parts[1])
    return _encoders


def available_codecs(ext):
    return [c for c in FORMATS.get(ext, ("", "", []))[2] if CODECS[c][1] in ffmpeg_encoders()]


def render(folder, out, fps=8, scale=0.5, edit=None, progress=None, codec=None, quality="medium"):
    """Encode a recording. The extension picks the format (FORMATS): .gif / .webp / .apng with Pillow, .mp4 / .webm /
    .mov with ffmpeg and the given codec (CODECS; default: the format's first). quality: high | medium | small.
    progress(i, n) is called per frame."""
    from PIL import Image
    ext = os.path.splitext(out)[1].lower()
    if ext not in FORMATS:
        raise SystemExit(f"rmpp-ctl: unknown format {ext!r} (use {', '.join(FORMATS)})")
    quality = quality if quality in QUALITIES else "medium"
    r = Renderer(folder, edit, scale)
    times = r.times(fps)
    if not times:
        raise SystemExit("rmpp-ctl: nothing to render (check the clips)")
    n = len(times)
    detail = ""
    if FORMATS[ext][1] == "anim":
        frames, durs = [], []
        for i, t in enumerate(times):   # merge identical consecutive frames into longer frames
            im = r.frame(t)
            if frames and frames[-1] is im:
                durs[-1] += 1000 / fps
            else:
                frames.append(im)
                durs.append(1000 / fps)
            if progress:
                progress(i + 1, n)
        durs = [int(d) for d in durs]
        if ext == ".gif":
            colors = GIF_COLORS[quality]
            pal = [f.convert("P", palette=Image.ADAPTIVE, colors=colors) for f in frames]
            pal[0].save(out, save_all=True, append_images=pal[1:], duration=durs, loop=0, optimize=True)
            detail = f"GIF, {colors} colors"
        elif ext == ".webp":
            frames[0].save(out, format="WEBP", save_all=True, append_images=frames[1:], duration=durs, loop=0,
                           quality=WEBP_QUALITY[quality], method=4)
            detail = f"WebP, quality {WEBP_QUALITY[quality]}"
        else:
            frames[0].save(out, format="PNG", save_all=True, append_images=frames[1:], duration=durs, loop=0)
            detail = "APNG"
    else:
        ff = find_ffmpeg()
        if not ff:
            raise SystemExit(f"rmpp-ctl: ffmpeg not found (needed for {ext}; .gif / .webp / .apng work without it)")
        codec = codec or (available_codecs(ext) or FORMATS[ext][2])[0]
        if codec not in FORMATS[ext][2]:
            raise SystemExit(f"rmpp-ctl: {codec} does not go into {ext} (use {', '.join(FORMATS[ext][2])})")
        label, encoder, args, qmap, qopt = CODECS[codec]
        if encoder not in ffmpeg_encoders():
            raise SystemExit(f"rmpp-ctl: this ffmpeg has no {encoder} encoder")
        cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{r.w}x{r.h}",
               "-r", str(fps), "-i", "-", "-c:v", encoder] + args + [qopt, str(qmap[quality])]
        if ext in (".mp4", ".mov"):
            cmd += ["-movflags", "+faststart"]
        p = subprocess.Popen(cmd + [out], stdin=subprocess.PIPE,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for i, t in enumerate(times):
            p.stdin.write(r.frame(t).tobytes())
            if progress:
                progress(i + 1, n)
        p.stdin.close()
        if p.wait() != 0:
            raise SystemExit("rmpp-ctl: ffmpeg failed")
        detail = f"{label.split(' (')[0]}, {quality}"
    size = os.path.getsize(out) / 1e6
    msg = f"{out}: {detail}, {n} frames, {n / fps:.1f} s, {size:.1f} MB"
    print(msg)
    return msg


def find_ffmpeg():
    """$FFMPEG, PATH, or a winget install whose PATH entry is not in this shell yet."""
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    import glob
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet")
    hits = glob.glob(os.path.join(base, "Links", "ffmpeg.exe")) + \
        sorted(glob.glob(os.path.join(base, "Packages", "*FFmpeg*", "*", "bin", "ffmpeg.exe")))
    return hits[-1] if hits else None


def wrap(d, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=font) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines or [""]


# ---------- commands ----------

def point_args(tab, args):
    """'X Y' or a UI query -> (x, y), remaining args"""
    if len(args) >= 2 and re.match(r"^-?\d+$", args[0]) and re.match(r"^-?\d+$", args[1]):
        return (int(args[0]), int(args[1])), args[2:]
    return tab.center(" ".join(args)), []


def do(tab, argv, state):
    """Run one command (a list of words). Shared by the CLI and the tutorial runner."""
    if not argv:
        return
    c, a = argv[0], argv[1:]
    if c == "shot":   # in a tutorial run, relative names go into the run's folder (screenshots per step)
        path = a[0] if a else "shot.png"
        if state.get("shot_dir") and not os.path.isabs(path):
            os.makedirs(state["shot_dir"], exist_ok=True)
            path = os.path.join(state["shot_dir"], path)
        print(tab.shot(path))
    elif c in ("tap", "longpress"):
        (x, y), rest = point_args(tab, a)
        ms = rest[0] if rest else ("60" if c == "tap" else "900")
        tab.script([f"{c} {x} {y} {ms}"])
    elif c == "open":     # open "<notebook name>": close the open document, tap the notebook in the library
        open_document(tab, " ".join(a).strip('"'))
    elif c == "tap-if":   # tap a UI item if it is there, otherwise do nothing
        out = tab.ui("center " + " ".join(a), check=False)
        m = re.match(r"^(-?\d+) (-?\d+)$", out.strip())
        if m:
            tab.script([f"tap {m.group(1)} {m.group(2)} 60"])
    elif c == "tool":     # tool <query>: make a toolbar tool active (tapping an active tool would open its menu)
        q = " ".join(a)
        if tab.ui(f"prop selected {q}").strip() != "true":
            x, y = tab.center(q)
            tab.script([f"tap {x} {y} 60"])
            time.sleep(0.6)
            if tab.ui(f"prop selected {q}").strip() != "true":
                raise SystemExit(f"rmpp-ctl: tool {q!r} did not become active")
    elif c == "swipe":
        tab.script(["swipe " + " ".join(a)])
    elif c == "line":
        tab.script(["line " + " ".join(a)])
    elif c == "draw":
        tab.script(draw_lines(a[0], a[1:]))
    elif c == "lasso":
        tab.script([pts_cmd(lasso_loop(*map(float, a[:4])), 0.5, 1500)])
    elif c == "text":
        print(tab.ui("text " + " ".join(a)))
    elif c == "key":
        print(tab.ui("key " + a[0]))
    elif c in ("find", "tree", "info", "pointers", "hit", "prop", "props"):
        print(tab.ui(" ".join([c] + a)))
    elif c == "expect":   # expect <query> [timeout ms]: wait until a UI item matches, else stop
        timeout = 3000
        if len(a) > 1 and re.match(r"^\d+$", a[-1]):
            timeout = int(a.pop())
        q = " ".join(a)
        t_end = time.time() + timeout / 1000
        while True:
            out = tab.ui(f"find {q}", check=False)
            if not out.startswith("error"):
                break
            if time.time() > t_end:
                raise SystemExit(f"rmpp-ctl: expected UI item {q!r} not found (wrong screen?)")
            time.sleep(0.4)
    elif c == "ui":
        print(tab.ui(" ".join(a)))
    elif c == "input":
        sys.stdout.write(tab.ssh(TOOL, data=sys.stdin.buffer.read()))
    elif c == "wait":
        time.sleep(float(a[0]) / 1000 if a else 1)
    elif c == "record":
        sub = a[0] if a else ""
        if sub == "start":
            fps = a[1] if len(a) > 1 else "4"
            tab.ssh(f"rm -rf {REC_DIR}")
            print(tab.ui(f"rec start {REC_DIR} {fps}"))
        elif sub == "mark":
            print(tab.ui("rec mark " + " ".join(a[1:])))
        elif sub == "stop":
            print(tab.ui("rec stop"))
            out = a[1] if len(a) > 1 else None
            if out:
                save_recording(tab, out, state)
        else:
            raise SystemExit("rmpp-ctl: record start [fps] | record mark <caption> | record stop [out.gif|out.mp4]")
    else:
        raise SystemExit(f"rmpp-ctl: unknown command {c!r}")


def wait_for(tab, query, timeout=6.0):
    t_end = time.time() + timeout
    while time.time() < t_end:
        out = tab.ui(f"find {query}", check=False)
        if not out.startswith("error"):
            return out
        time.sleep(0.4)
    return None


def open_document(tab, name):
    """Open a notebook by its name from the library (My files, top level). Tutorials start with this so they never
    work on whatever notebook happens to be open."""
    if not tab.ui("find #close-documentview-button", check=False).startswith("error"):
        x, y = tab.center("#close-documentview-button")
        tab.script([f"tap {x} {y} 60"])
    if not wait_for(tab, "#library-action"):
        raise SystemExit("rmpp-ctl: open: the library did not show up")
    out = wait_for(tab, f'"{name}"', 3)
    for line in (out or "").splitlines():   # the thumbnail item, not its label under it
        m = re.match(r"\s*(-?\d+),(-?\d+) (\d+)x(\d+) ContentGridItem", line)
        if m:
            x, y, w, h = map(int, m.groups())
            tab.script([f"tap {x + w // 2} {y + h // 3} 60"])
            break
    else:
        raise SystemExit(f"rmpp-ctl: open: no notebook named {name!r} in My files")
    if not wait_for(tab, "#hide-show-toolbar-button", 8):
        raise SystemExit(f"rmpp-ctl: open: {name!r} did not open")
    time.sleep(1.0)


def save_recording(tab, out, state):
    tmp = tempfile.mkdtemp(prefix="rmpp-rec-")
    try:
        tab.pull_recording(tmp)
        keep = state.get("keep_frames")
        if keep:
            shutil.copytree(tmp, keep, dirs_exist_ok=True)
        for o in out.split(","):
            render(tmp, o, fps=state.get("out_fps", 8), scale=state.get("scale", 0.5))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


INSTALL_SCRIPT = """set -e
D=/usr/lib/rmpp-remote
N=/tmp/rmpp-remote-new
mount -o remount,rw /
mkdir -p $D
for f in librmpp-remote.so rmpp-remote; do cp $N/$f $D/$f.new; chmod 755 $D/$f.new; mv $D/$f.new $D/$f; done
rm -rf $N
ln -sf $D/librmpp-remote.so /usr/lib/rmpp-preload.d/40-rmpp-remote.so
rm -f /usr/lib/rmpp-preload.d/40-rmpp-tester.so; rm -rf /usr/lib/rmpp-tester   # its old name
sync
systemctl reset-failed xochitl; systemctl restart xochitl
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do sleep 1; $D/rmpp-remote ui ping >/dev/null 2>&1 && break; done
P=$(pidof rmpp-remote); [ -n "$P" ] && kill $P; sleep 1
mount -o remount,ro / || echo "warning: / is still read-write"
$D/rmpp-remote ui info
"""

REMOVE_SCRIPT = """mount -o remount,rw /
rm -f /usr/lib/rmpp-preload.d/40-rmpp-remote.so
rm -rf /usr/lib/rmpp-remote
rm -f /usr/lib/rmpp-preload.d/40-rmpp-tester.so; rm -rf /usr/lib/rmpp-tester
sync
systemctl reset-failed xochitl; systemctl restart xochitl
sleep 5
mount -o remount,ro / || echo "warning: / is still read-write"
echo removed
"""


def recent_restarts(tab):
    """xochitl restarts in the last 10 minutes (more than 4 reboot the tablet)"""
    out = tab.ssh("journalctl -u xochitl --since -10min | grep -c Consumed", check=False).strip()
    return int(out) if out.isdigit() else 0


def install_tablet(tab, so_path, bin_path, log=print):
    """Copy the add-on and the tablet tool to /usr/lib/rmpp-remote, link it into rmpp-preload.d, restart xochitl."""
    if not tab.ssh("ls /usr/lib/rmpp-preload.d >/dev/null 2>&1 && echo ok", check=False).strip() == "ok":
        raise SystemExit("rmpp-preload is not installed on the tablet (/usr/lib/rmpp-preload.d missing)")
    if recent_restarts(tab) >= 3:
        raise SystemExit("xochitl restarted 3+ times in the last 10 minutes; wait a few minutes (it reboots after 4)")
    tab.ssh("rm -rf /tmp/rmpp-remote-new && mkdir -p /tmp/rmpp-remote-new")
    for src, name in ((so_path, "librmpp-remote.so"), (bin_path, "rmpp-remote")):
        with open(src, "rb") as f:
            tab.ssh(f"cat > /tmp/rmpp-remote-new/{name}", data=f.read())
        log(f"copied {name}")
    log("installing, restarting xochitl (the tablet may ask for its passcode) ...")
    return tab.ssh("sh -s", data=INSTALL_SCRIPT.encode())


def remove_tablet(tab):
    if recent_restarts(tab) >= 3:
        raise SystemExit("xochitl restarted 3+ times in the last 10 minutes; wait a few minutes (it reboots after 4)")
    return tab.ssh("sh -s", data=REMOVE_SCRIPT.encode())


def parse_tutorial(text):
    """Tutorial text -> (settings, steps). One command per line (same words as the CLI), plus
         title: / fps: / scale: / out-fps: / output:     settings
         setup <command>                                 run before recording starts (all setup steps come first)
         caption <text>                                  caption from now on (empty = none)
         expect <query> [ms]                             stop unless the UI item shows up (guards against wrong screens)
         wait <ms>                                       pause (recorded)
    Lines starting with # are comments. Recording starts at the first step that is not setup."""
    settings = {"fps": "4", "scale": 0.5, "out_fps": 8, "output": "", "title": ""}
    steps = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(title|fps|scale|out-fps|output):\s*(.*)$", line)
        if m:
            k, v = m.groups()
            if k == "scale": settings["scale"] = float(v)
            elif k == "out-fps": settings["out_fps"] = int(v)
            else: settings[k] = v
            continue
        steps.append((n, line))
    return settings, steps


def run_steps(tab, settings, steps, record=True, stop=None, log=print, shot_dir=None):
    """Run parsed tutorial steps; with record=True the steps after the setup ones are recorded on the tablet
    (pull the result with tab.pull_recording). stop: a threading.Event checked between steps."""
    state = {"scale": settings["scale"], "out_fps": settings["out_fps"], "shot_dir": shot_dir}
    recording = False
    try:
        for n, line in steps:
            if stop is not None and stop.is_set():
                raise SystemExit("stopped")
            words = shlex.split(line)
            c = words[0]
            log(f"[{n}] {line}")
            if c == "setup":       # setup <command ...>: run before recording starts
                if recording:
                    raise SystemExit(f"rmpp-ctl: line {n}: setup steps must come before the first recorded step")
                do(tab, words[1:], state)
                continue
            if record and not recording:
                tab.ssh(f"rm -rf {REC_DIR}")
                log(tab.ui(f"rec start {REC_DIR} {settings['fps']}"))
                recording = True
            if c == "caption":
                if recording:
                    tab.ui("rec mark " + line[len("caption"):].strip())
            else:
                do(tab, words, state)
    except BaseException:
        if recording:
            tab.ui("rec stop", check=False)
        raise
    if recording:
        time.sleep(0.8)
        log(tab.ui("rec stop"))
    return recording


def run_tutorial(tab, path, outs, keep_frames=None):
    with open(path, encoding="utf-8") as f:
        settings, steps = parse_tutorial(f.read())
    outs = outs or settings["output"] or os.path.splitext(path)[0] + ".gif"
    if run_steps(tab, settings, steps, shot_dir=os.path.splitext(outs.split(",")[0])[0] + "-shots"):
        save_recording(tab, outs, {"keep_frames": keep_frames, "scale": settings["scale"],
                                   "out_fps": settings["out_fps"]})


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="rmpp-ctl", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("RMPP_HOST", "rmpp"))
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-o", "--output", help="run: output file(s), comma separated (.gif, .mp4)")
    ap.add_argument("--keep-frames", help="run/record stop: also copy the raw frames + frames.txt here")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    o = ap.parse_args()
    # options may also follow the command words (run x.tut -o out.mp4 --keep-frames dir)
    rest, i = [], 0
    while i < len(o.command):
        w = o.command[i]
        if w in ("-o", "--output", "--keep-frames", "--host", "--codec", "--quality") and i + 1 < len(o.command):
            setattr(o, {"-o": "output", "--output": "output", "--keep-frames": "keep_frames", "--host": "host",
                        "--codec": "codec", "--quality": "quality"}[w], o.command[i + 1])
            i += 2
        elif w in ("-v", "--verbose"):
            o.verbose = True
            i += 1
        else:
            rest.append(w)
            i += 1
    o.command = rest
    if not o.command:
        ap.print_help()
        return
    tab = Tablet(o.host, o.verbose)
    if o.command[0] == "run":
        run_tutorial(tab, o.command[1], o.output, o.keep_frames)
    elif o.command[0] == "render":   # render <frames dir> <out> [fps] [scale]: re-encode kept frames (+ edit.json)
        if len(o.command) < 3:
            raise SystemExit("usage: rmpp-ctl render <recording folder> <out.mp4|.webm|.mov|.gif|.webp|.apng> "
                             "[fps] [scale] [--codec h264|h265|av1|vp9|prores] [--quality high|medium|small]")
        nums = [float(x) for x in o.command[3:5]]
        render(o.command[1], o.command[2], *nums, codec=getattr(o, "codec", None),
               quality=getattr(o, "quality", None) or "medium")
    else:
        do(tab, o.command, {"keep_frames": o.keep_frames})


if __name__ == "__main__":
    main()
