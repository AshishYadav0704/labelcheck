"""Renders the long-term illustration as a short MP4 (portrait, phone-friendly).

Frames are drawn with Pillow from the simulation timeline (a templated
animation, not generative AI video), then encoded with ffmpeg via imageio-ffmpeg.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("labelcheck.video")

W, H = 540, 960
FPS = 12
INTRO_S, GROW_S, HOLD_S, OUTRO_S = 1.5, 7.0, 1.0, 3.5

# Same palette as the web app (rice white, curry-leaf ink, grade colours).
BG = (245, 247, 244)
INK = (28, 43, 37)
MUTED = (82, 99, 90)
SKIN = (228, 216, 201)
SKIN_EDGE = (196, 182, 166)
GREEN, AMBER, RED = (46, 139, 87), (210, 154, 28), (194, 55, 45)
PANEL = (255, 255, 255)
OY = 26  # vertical offset of the figure below the title block

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]
BOLD_PATHS = [p.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf") for p in FONT_PATHS]

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
MAX_CACHED_VIDEOS = 400


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (BOLD_PATHS if bold else FONT_PATHS):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def strain_colour(s: float) -> tuple[int, int, int]:
    return _mix(GREEN, AMBER, s / 0.45) if s < 0.45 else _mix(AMBER, RED, (s - 0.45) / 0.4)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


class Renderer:
    def __init__(self) -> None:
        self.f_title = _font(30, bold=True)
        self.f_sub = _font(19)
        self.f_year = _font(38, bold=True)
        self.f_label = _font(17)
        self.f_small = _font(15)
        self.f_caption = _font(20)

    def _figure(self, d: ImageDraw.ImageDraw, systems: dict[str, dict[str, float]], t: float) -> None:
        cx = W // 2
        metab = systems["metabolism"]["strain"]
        widen = 1 + 0.28 * metab  # waist grows with the blood-sugar & weight strain

        # legs and arms
        for dx in (-38, 38):
            d.rounded_rectangle([cx + dx - 24, 470 + OY, cx + dx + 24, 572 + OY], 22, fill=SKIN, outline=SKIN_EDGE, width=2)
        arm_off = int(92 * widen)
        for sx in (-1, 1):
            x = cx + sx * arm_off
            d.rounded_rectangle([x - 16, 262 + OY, x + 16, 440 + OY], 16, fill=SKIN, outline=SKIN_EDGE, width=2)
        # torso
        half = int(78 * widen)
        d.rounded_rectangle([cx - half, 250 + OY, cx + half, 500 + OY], 46, fill=SKIN, outline=SKIN_EDGE, width=2)
        # neck and head
        d.rectangle([cx - 15, 214 + OY, cx + 15, 256 + OY], fill=SKIN)
        d.ellipse([cx - 52, 112 + OY, cx + 52, 224 + OY], fill=SKIN, outline=SKIN_EDGE, width=2)
        # teeth (smile)
        tooth = strain_colour(systems["teeth"]["strain"])
        d.rounded_rectangle([cx - 24, 188 + OY, cx + 24, 204 + OY], 6, fill=(255, 255, 255), outline=tooth, width=3)
        for x in range(cx - 16, cx + 24, 10):
            d.line([x, 189 + OY, x, 203 + OY], fill=tooth, width=2)
        d.ellipse([cx - 24, 150 + OY, cx - 12, 162 + OY], fill=INK)
        d.ellipse([cx + 12, 150 + OY, cx + 24, 162 + OY], fill=INK)

        # heart: beats faster as strain rises
        hs = systems["heart"]["strain"]
        beat = 1 + 0.08 * math.sin(t * (6 + 8 * hs)) * (0.6 + hs)
        r = 15 * beat
        hx, hy = cx - 26, 300 + OY
        col = strain_colour(hs)
        d.ellipse([hx - r * 1.9, hy - r, hx, hy + r * 0.6], fill=col)
        d.ellipse([hx - 2, hy - r, hx + r * 1.9 - 2, hy + r * 0.6], fill=col)
        d.polygon([(hx - r * 1.85, hy + 0.1 * r), (hx + r * 1.85 - 2, hy + 0.1 * r), (hx - 1, hy + 2.3 * r)], fill=col)
        # liver
        d.ellipse([cx - 10, 330 + OY, cx + 66, 376 + OY], fill=strain_colour(systems["liver"]["strain"]))
        # kidneys
        kc = strain_colour(systems["kidneys"]["strain"])
        d.ellipse([cx - 52, 386 + OY, cx - 30, 420 + OY], fill=kc)
        d.ellipse([cx + 30, 386 + OY, cx + 52, 420 + OY], fill=kc)
        # gut
        gc = strain_colour(systems["gut"]["strain"])
        d.rounded_rectangle([cx - 44, 428 + OY, cx + 44, 482 + OY], 18, fill=gc)
        for y in (442 + OY, 456 + OY, 470 + OY):
            d.line([cx - 32, y, cx + 32, y], fill=_mix(gc, (255, 255, 255), 0.45), width=3)

    def _bars(self, d: ImageDraw.ImageDraw, labels: dict[str, str], systems: dict[str, dict[str, float]]) -> None:
        top, row = 622, 32
        d.rounded_rectangle([24, top - 14, W - 24, top + row * 6 + 4], 14, fill=PANEL)
        for i, key in enumerate(["heart", "metabolism", "liver", "kidneys", "teeth", "gut"]):
            y = top + i * row
            s = systems[key]["strain"]
            d.text((40, y + 3), labels[key], font=self.f_label, fill=INK)
            x0, x1 = 262, W - 44
            d.rounded_rectangle([x0, y + 5, x1, y + 23], 9, fill=(232, 230, 224))
            if s > 0.005:
                d.rounded_rectangle([x0, y + 5, x0 + max(18, int((x1 - x0) * s)), y + 23], 9, fill=strain_colour(s))

    def frame(self, sim: dict[str, Any], product_name: str, frequency_label: str, year_f: float,
              caption: str, t: float) -> Image.Image:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        timeline = sim["timeline"]
        lo = min(int(year_f), len(timeline) - 1)
        hi = min(lo + 1, len(timeline) - 1)
        frac = year_f - lo
        systems = {k: {"strain": timeline[lo]["systems"][k]["strain"] * (1 - frac) + timeline[hi]["systems"][k]["strain"] * frac}
                   for k in timeline[0]["systems"]}

        d.text((W // 2, 26), "If eaten " + frequency_label, font=self.f_sub, fill=MUTED, anchor="mm")
        name = product_name if len(product_name) <= 34 else product_name[:33] + "…"
        d.text((W // 2, 56), name, font=self.f_title, fill=INK, anchor="mm")
        year_text = f"Year {int(round(year_f))}" if year_f > 0 else "Today"
        d.text((W // 2, 96), year_text, font=self.f_year, fill=INK, anchor="mm")
        self._figure(d, systems, t)
        self._bars(d, sim["systems"], systems)

        lines = _wrap(d, caption, self.f_caption, W - 72)[:3]
        for i, line in enumerate(lines):
            d.text((W // 2, 840 + i * 26), line, font=self.f_caption, fill=INK, anchor="mm")
        d.text((W // 2, 930), "Illustration of general evidence — not a medical prediction", font=self.f_small,
               fill=MUTED, anchor="mm")
        return img

    def summary(self, sim: dict[str, Any], product_name: str, frequency_label: str, swap: str | None) -> Image.Image:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.text((W // 2, 70), f"After {sim['years']} years", font=self.f_year, fill=INK, anchor="mm")
        d.text((W // 2, 116), "eating it " + frequency_label, font=self.f_sub, fill=MUTED, anchor="mm")
        y = 170
        findings = sim["findings"][:3]
        if not findings:
            for line in _wrap(d, "At this amount, this product adds little extra strain. Balance and variety still matter.",
                              self.f_caption, W - 80):
                d.text((W // 2, y), line, font=self.f_caption, fill=INK, anchor="mm")
                y += 30
        for f in findings:
            col = strain_colour(f["strain"])
            lines = _wrap(d, f["caption"], self.f_small, W - 112)[:4]
            h = 62 + 21 * len(lines)
            d.rounded_rectangle([32, y, W - 32, y + h], 16, fill=PANEL)
            d.rounded_rectangle([32, y, 44, y + h], 6, fill=col)
            d.text((60, y + 16), f"{f['label']} — {f['stage']}", font=self.f_label, fill=INK)
            for i, line in enumerate(lines):
                d.text((60, y + 46 + i * 21), line, font=self.f_small, fill=MUTED)
            y += h + 16
        if swap:
            lines = _wrap(d, swap, self.f_small, W - 104)[:3]
            h = 60 + 21 * len(lines)
            d.rounded_rectangle([32, y + 6, W - 32, y + 6 + h], 16, fill=_mix(GREEN, (255, 255, 255), 0.85))
            d.text((52, y + 22), "Try instead", font=self.f_label, fill=_mix(GREEN, INK, 0.5))
            for i, line in enumerate(lines):
                d.text((52, y + 50 + i * 21), line, font=self.f_small, fill=INK)
        for i, line in enumerate(_wrap(d, sim["model_note"], self.f_small, W - 72)[:4]):
            d.text((W // 2, 846 + i * 21), line, font=self.f_small, fill=MUTED, anchor="mm")
        return img


def frequency_label(per_week: float) -> str:
    if per_week >= 13.5:
        return f"{per_week / 7:g} times a day"
    if per_week >= 6.5:
        return "every day"
    if per_week == 1:
        return "once a week"
    return f"{per_week:g} times a week"


def _caption_for(sim: dict[str, Any], year_index: int) -> str:
    from .simulation import CAPTIONS, _stage  # local import keeps module load light
    systems = sim["timeline"][year_index]["systems"]
    key = max(systems, key=lambda k: systems[k]["strain"])
    stage = _stage(systems[key]["strain"])
    if stage == "minimal":
        return "So far, little extra strain at this amount."
    return f"{sim['systems'][key]}: {CAPTIONS[key][stage]}"


# H.264 MP4 plays on Android, iPhone and in the Flutter app; VP9 WebM is a
# fallback for browsers built without H.264 (some Linux/open-source builds).
FORMATS = {
    "mp4": {"codec": "libx264", "media_type": "video/mp4",
            "params": ["-crf", "26", "-preset", "veryfast", "-movflags", "+faststart"]},
    "webm": {"codec": "libvpx-vp9", "media_type": "video/webm",
             "params": ["-crf", "38", "-b:v", "0", "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1"]},
}


def render_video(sim: dict[str, Any], product_name: str, swap: str | None, out_path: Path, fmt: str = "mp4") -> Path:
    spec = FORMATS[fmt]
    renderer = Renderer()
    freq = frequency_label(sim["servings_per_week"])
    years = sim["years"]
    tmp = out_path.with_name(out_path.stem + ".tmp" + out_path.suffix)
    writer = imageio_ffmpeg.write_frames(
        str(tmp), (W, H), fps=FPS, codec=spec["codec"], quality=None, macro_block_size=4,
        output_params=spec["params"], ffmpeg_log_level="error",
    )
    writer.send(None)
    try:
        frame_no = 0

        def emit(img: Image.Image, count: int) -> None:
            nonlocal frame_no
            data = img.tobytes()
            for _ in range(count):
                writer.send(data)
                frame_no += 1

        intro = renderer.frame(sim, product_name, freq, 0, "Here is what regular intake could mean over time.", 0)
        emit(intro, int(INTRO_S * FPS))
        grow_frames = int(GROW_S * FPS)
        for i in range(grow_frames):
            year_f = years * (i + 1) / grow_frames
            caption = _caption_for(sim, min(int(round(year_f)), years))
            emit(renderer.frame(sim, product_name, freq, year_f, caption, (frame_no) / FPS), 1)
        last_caption = _caption_for(sim, years)
        for i in range(int(HOLD_S * FPS)):
            emit(renderer.frame(sim, product_name, freq, years, last_caption, frame_no / FPS), 1)
        emit(renderer.summary(sim, product_name, freq, swap), int(OUTRO_S * FPS))
    finally:
        writer.close()
    os.replace(tmp, out_path)
    return out_path


def video_cache_key(report_id: str, sim: dict[str, Any], age_group: str) -> str:
    raw = f"{report_id}|{sim['servings_per_week']}|{sim['years']}|{age_group}|v3"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def video_path(video_dir: Path, key: str, fmt: str) -> Path:
    return video_dir / f"{key}.{fmt}"


def get_or_render(video_dir: Path, key: str, sim: dict[str, Any], product_name: str, swap: str | None,
                  fmt: str = "mp4") -> Path:
    video_dir.mkdir(parents=True, exist_ok=True)
    path = video_path(video_dir, key, fmt)
    key = f"{key}.{fmt}"
    if path.exists():
        return path
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if not path.exists():
            started = time.perf_counter()
            render_video(sim, product_name, swap, path, fmt)
            log.info("Rendered video %s in %.1fs", key, time.perf_counter() - started)
            _prune(video_dir)
    with _locks_guard:
        _locks.pop(key, None)
    return path


def _prune(video_dir: Path) -> None:
    files = sorted([*video_dir.glob("*.mp4"), *video_dir.glob("*.webm")], key=lambda p: p.stat().st_mtime)
    for old in files[:-MAX_CACHED_VIDEOS]:
        try:
            old.unlink()
        except OSError:
            pass
