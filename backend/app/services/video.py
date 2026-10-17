"""Renders the long-term illustration as a short portrait video (MP4 / WebM).

The figure is drawn like an anatomy-book illustration: a proportioned human
body with shaded skin, organs visible through the torso, and close-up insets
for the arteries, liver and teeth. Organ colours, belly fat and the insets
change with the simulated strain over the years. Frames are drawn with Pillow
from the simulation timeline (a templated animation, not generative video) and
encoded with ffmpeg via imageio-ffmpeg.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import random
import threading
import time
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger("labelcheck.video")

W, H = 720, 1280
FPS = 12
INTRO_S, GROW_S, HOLD_S, OUTRO_S = 1.5, 7.0, 1.0, 3.5

# Same palette as the web app (rice white, curry-leaf ink, grade colours).
BG = (245, 247, 244)
INK = (28, 43, 37)
MUTED = (82, 99, 90)
LINE = (210, 219, 212)
PANEL = (255, 255, 255)
GREEN, AMBER, RED = (46, 139, 87), (210, 154, 28), (194, 55, 45)
SKIN = (190, 141, 108)        # medium brown skin tone
SHORTS = (54, 66, 74)
HAIR = (32, 27, 25)

CX = 250                      # body centre line
LABEL_X = 22                  # left label column
INSET_X, INSET_R = 612, 68    # right inset column

FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF"]

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
MAX_CACHED_VIDEOS = 400

STAGE_TEXT = {"minimal": "No extra strain", "mild": "Mild strain", "moderate": "Moderate strain", "high": "High strain"}


def _font(size: int, kind: str = "sans") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = {"sans": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf", "serif": "DejaVuSerif-Bold.ttf"}[kind]
    for d in FONT_DIRS:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _mix(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(len(a)))


def strain_colour(s: float) -> tuple[int, int, int]:
    return _mix(GREEN, AMBER, s / 0.45) if s < 0.45 else _mix(AMBER, RED, (s - 0.45) / 0.4)  # type: ignore[return-value]


def _stage(s: float) -> str:
    return "minimal" if s < 0.2 else "mild" if s < 0.45 else "moderate" if s < 0.7 else "high"


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


def _spline(points: list[tuple[float, float]], closed: bool = True, steps: int = 10) -> list[tuple[float, float]]:
    """Catmull-Rom spline through the points, for smooth anatomical outlines."""
    pts = list(points)
    n = len(pts)
    out: list[tuple[float, float]] = []
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0 = pts[(i - 1) % n] if closed else pts[max(i - 1, 0)]
        p1 = pts[i]
        p2 = pts[(i + 1) % n] if closed else pts[min(i + 1, n - 1)]
        p3 = pts[(i + 2) % n] if closed else pts[min(i + 2, n - 1)]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in range(2)))  # type: ignore[arg-type]
    if not closed:
        out.append(pts[-1])
    return out


def _mirror(right: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Right-half outline (x offsets from the centre line, top to bottom) -> closed full outline."""
    return [(CX + x, y) for x, y in right] + [(CX - x, y) for x, y in reversed(right)]


def _side(points: list[tuple[float, float]], sign: int) -> list[tuple[float, float]]:
    return [(CX + sign * x, y) for x, y in points]


# ---------------------------------------------------------------------------
# Body geometry (design coordinates: x = offset from centre line, y = absolute)
# ---------------------------------------------------------------------------
def _head(fat: float) -> list[tuple[float, float]]:
    cheek = 1 + 0.12 * fat
    right = [(0, 182), (24, 186), (38, 200), (43, 222), (42 * cheek, 246), (37 * cheek, 265), (26 * cheek, 282),
             (12, 291), (0, 293)]
    return _spline([(CX + x, y) for x, y in right] + [(CX - x, y) for x, y in reversed(right[1:-1])])


def _torso(fat: float) -> list[tuple[float, float]]:
    waist, hip = 64 * (1 + 0.8 * fat), 78 * (1 + 0.42 * fat)
    right = [(0, 304), (22, 306), (48, 314), (78, 323), (97, 337), (104, 356), (100, 378), (88, 394), (84, 430),
             (waist, 500), (hip, 566), (hip, 612), (58, 638), (22, 650)]
    return _spline(_mirror(right))


def _arm(fat: float, sign: int) -> list[tuple[float, float]]:
    upper = 6 * fat
    pts = [(100, 350), (110 + upper, 382), (116 + upper, 430), (118 + upper * 0.6, 480), (116, 522), (112, 570),
           (108, 610), (114, 632), (116, 660), (110, 686), (100, 698), (90, 694), (85, 672), (86, 640), (90, 612),
           (94, 570), (98, 522), (98, 480), (94, 432), (86, 398)]
    return _spline(_side(pts, sign))


def _leg(fat: float, sign: int) -> list[tuple[float, float]]:
    hip = 78 * (1 + 0.42 * fat)
    pts = [(hip - 6, 600), (hip - 2, 642), (78 + 10 * fat, 702), (66, 782), (64, 842), (56, 892), (44, 930),
           (54, 946), (56, 958), (14, 961), (12, 948), (16, 930), (14, 892), (12, 842), (14, 782), (8 + 3 * fat, 702),
           (3, 660), (0, 640)]
    return _spline(_side(pts, sign), steps=8)


def _shorts(fat: float, sign: int) -> list[tuple[float, float]]:
    hip = 78 * (1 + 0.42 * fat)
    pts = [(0, 618), (hip * 0.99, 618), (hip + 2, 640), (80 + 10 * fat, 738), (16 + 3 * fat, 742), (5, 690), (0, 680)]
    return _side(pts, sign)


# Organs: (x offset, y) outlines; viewer's left is the person's right side.
LUNG_R = [(-10, 338), (-34, 342), (-56, 360), (-66, 400), (-68, 445), (-58, 468), (-30, 462), (-14, 450), (-10, 400)]
LUNG_L = [(10, 338), (34, 342), (56, 360), (66, 400), (68, 445), (58, 468), (34, 464), (24, 448), (28, 420), (12, 400)]
HEART = [(-22, -10), (-10, -22), (6, -22), (20, -12), (26, 4), (24, 20), (14, 34), (0, 26), (-14, 14), (-24, 2)]
LIVER = [(-72, 448), (-30, 442), (10, 446), (30, 452), (22, 468), (-8, 486), (-44, 506), (-66, 500), (-76, 474)]
STOMACH = [(16, 456), (42, 452), (60, 466), (60, 492), (46, 510), (26, 512), (18, 500), (32, 488), (30, 472), (16, 468)]
PANCREAS = [(-8, 518), (20, 512), (52, 507), (55, 515), (22, 522), (-6, 527)]
KIDNEY = [(0, -15), (9, -12), (11, 0), (9, 12), (0, 15), (-6, 10), (-3, 0), (-6, -10)]
COLON = [(-50, 630), (-56, 592), (-52, 556), (-20, 548), (20, 548), (52, 554), (56, 592), (48, 628), (16, 640)]
LIVER_DROPS = [(-50, 462), (-28, 458), (-6, 462), (14, 458), (-58, 480), (-36, 476), (-14, 474), (6, 468),
               (-46, 494), (-24, 488), (-62, 466), (-40, 468), (-18, 482), (-30, 498), (-52, 486), (-8, 476)]


def _abs(points: list[tuple[float, float]], dx: float = 0, dy: float = 0, k: float = 1.0,
         about: tuple[float, float] | None = None) -> list[tuple[float, float]]:
    if about is None:
        return [(CX + dx + x * k, dy + y) for x, y in points]
    ax, ay = about
    return [(CX + ax + (x - ax) * k + dx, ay + (y - ay) * k + dy) for x, y in points]


class Renderer:
    def __init__(self) -> None:
        self.f_sub = _font(22)
        self.f_title = _font(34, "serif")
        self.f_year = _font(46, "serif")
        self.f_label = _font(19, "bold")
        self.f_small = _font(16)
        self.f_bar = _font(19)
        self.f_caption = _font(23)
        self._body_cache: dict[int, tuple[Image.Image, Image.Image]] = {}
        rnd = random.Random(7)
        self._liver_drops = [(x + rnd.uniform(-3, 3), y + rnd.uniform(-3, 3), rnd.uniform(2.2, 4.2)) for x, y in LIVER_DROPS]
        self._inset_drops = [(rnd.uniform(-0.85, 0.85), rnd.uniform(-0.85, 0.85), rnd.uniform(0.05, 0.13)) for _ in range(34)]
        self._visceral = [(rnd.uniform(-48, 48), rnd.uniform(560, 628), rnd.uniform(6, 11)) for _ in range(12)]

    # ---- the body (skin, shorts, face); depends only on body fat -----------
    def body_layer(self, fat: float) -> tuple[Image.Image, Image.Image]:
        key = int(round(fat * 100))
        cached = self._body_cache.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        fat = key / 100
        mask = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(mask)
        for part in (_head(fat), _torso(fat), _arm(fat, 1), _arm(fat, -1), _leg(fat, 1), _leg(fat, -1)):
            md.polygon(part, fill=255)
        md.polygon([(CX - 17, 278), (CX + 17, 278), (CX + 20, 316), (CX - 20, 316)], fill=255)  # neck

        # Soft 3D shading: darker towards the outline, light from the upper left.
        m = np.asarray(mask, dtype=np.float32) / 255.0
        blur = np.asarray(mask.filter(ImageFilter.GaussianBlur(11)), dtype=np.float32) / 255.0
        inner = np.clip((blur - 0.5) * 2.2, 0, 1)
        light = 0.74 + 0.26 * inner
        light *= np.linspace(1.06, 0.92, W, dtype=np.float32)[None, :]
        light *= np.linspace(1.03, 0.95, H, dtype=np.float32)[:, None]
        rgb = np.clip(np.asarray(SKIN, dtype=np.float32)[None, None, :] * light[..., None], 0, 255)
        layer = Image.fromarray(np.dstack([rgb, m * 255]).astype(np.uint8), "RGBA")

        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        shadow = (*_mix(SKIN, (90, 60, 45), 0.55), 90)
        # collarbones, chest, knees, elbows: faint anatomy lines
        for sign in (1, -1):
            d.line(_spline(_side([(14, 322), (40, 318), (70, 324)], sign), closed=False), fill=shadow, width=2)
            d.line(_spline(_side([(60, 790), (40, 800), (20, 792)], sign), closed=False), fill=shadow, width=2)
            d.line(_spline(_side([(104, 488), (110, 494)], sign), closed=False), fill=shadow, width=2)
        d.ellipse([CX - 22, 284, CX + 22, 300], fill=(*_mix(SKIN, (70, 45, 35), 0.5), 70))  # shadow under the chin
        overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))
        layer.alpha_composite(overlay)

        face = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self._face(ImageDraw.Draw(face), fat)
        layer.alpha_composite(face)

        # shorts: their own layer, drawn above the organs
        shorts = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shorts)
        for sign in (1, -1):
            sd.polygon(_shorts(fat, sign), fill=(*SHORTS, 255))
        hip = 78 * (1 + 0.42 * fat)
        sd.line([(CX - hip * 0.99, 622), (CX + hip * 0.99, 622)], fill=(*_mix(SHORTS, (0, 0, 0), 0.35), 255), width=6)
        sd.line([(CX, 626), (CX, 680)], fill=(*_mix(SHORTS, (0, 0, 0), 0.25), 255), width=2)
        self._body_cache[key] = (layer, shorts)  # type: ignore[assignment]
        return self._body_cache[key]  # type: ignore[return-value]

    @staticmethod
    def _face(d: ImageDraw.ImageDraw, fat: float) -> None:
        dark = (*_mix(SKIN, (60, 38, 28), 0.45), 255)
        # hair
        hair = [(0, 177), (26, 180), (42, 195), (47, 221), (44, 234), (37, 214), (22, 204), (6, 207), (0, 205)]
        d.polygon(_spline([(CX + x, y) for x, y in hair] + [(CX - x, y) for x, y in reversed(hair[1:-1])]), fill=(*HAIR, 255))
        d.line(_spline([(CX - 30, 188), (CX - 8, 182), (CX + 20, 186)], closed=False), fill=(70, 60, 55, 160), width=2)
        for sign in (1, -1):
            d.ellipse([CX + sign * 43 - 5, 228, CX + sign * 43 + 5, 252], fill=dark)                      # ears
            x0 = CX + sign * 16
            d.line([(x0 - 9 * sign, 225), (x0 + 8 * sign, 223)], fill=(*HAIR, 230), width=3)            # eyebrows
            d.ellipse([x0 - 8, 232, x0 + 8, 241], fill=(246, 242, 236, 255))                             # eye white
            d.ellipse([x0 - 4, 232, x0 + 4, 241], fill=(62, 42, 32, 255))                                # iris
            d.ellipse([x0 - 1.8, 234.6, x0 + 1.8, 238.4], fill=(15, 12, 10, 255))                        # pupil
            d.point((x0 + 1.5, 234.5), fill=(255, 255, 255, 255))
            d.line([(x0 - 8, 232), (x0 + 8, 232)], fill=(*HAIR, 200), width=1)                           # lash line
            d.arc([CX + sign * 6 - 4, 254, CX + sign * 6 + 4, 261], 200 if sign < 0 else -20, 340 if sign < 0 else 160,
                  fill=dark, width=2)                                                                     # nostrils
        d.line([(CX - 1, 242), (CX - 3, 256)], fill=(*_mix(SKIN, (60, 38, 28), 0.3), 200), width=2)    # nose
        d.ellipse([CX - 11, 266, CX + 11, 272], fill=(160, 92, 84, 255))                                 # upper lip
        d.ellipse([CX - 10, 269, CX + 10, 278], fill=(176, 106, 96, 255))                                # lower lip
        d.line([(CX - 11, 270), (CX + 11, 270)], fill=(120, 66, 60, 255), width=1)
        if fat > 0.1:  # fuller cheeks
            for sign in (1, -1):
                d.arc([CX + sign * 24 - 12, 250, CX + sign * 24 + 12, 274], 0, 180, fill=(*_mix(SKIN, (90, 60, 45), 0.4), int(120 * fat * 2)), width=2)

    # ---- organs: change with strain ------------------------------------
    def organs(self, systems: dict[str, float], t: float) -> Image.Image:
        heart, metab, liver = systems["heart"], systems["metabolism"], systems["liver"]
        kidneys, gut = systems["kidneys"], systems["gut"]
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)

        d.polygon(_spline(_abs(LUNG_R)), fill=(228, 160, 164, 150))
        d.polygon(_spline(_abs(LUNG_L)), fill=(228, 160, 164, 150))

        # arteries: narrower with strain
        artery = (*_mix((196, 40, 46), (150, 30, 36), heart), 235)
        aw = max(3, int(round(7 * (1 - 0.4 * heart))))
        aorta = _spline(_abs([(4, 398), (2, 374), (8, 357), (20, 364), (18, 392), (10, 440), (4, 520), (2, 600)]),
                        closed=False)
        for sign in (1, -1):
            d.line(_spline(_abs([(2, 600), (sign * 22, 640), (sign * 40, 700), (sign * 42, 800), (sign * 36, 920)]),
                           closed=False), fill=artery, width=max(2, aw - 3), joint="curve")
            d.line(_spline(_abs([(8, 358), (sign * 40, 340), (sign * 86, 350), (sign * 106, 430), (sign * 106, 600)]),
                           closed=False), fill=artery, width=2, joint="curve")
            d.line(_spline(_abs([(8 + sign * 2, 358), (sign * 9, 330), (sign * 10, 292)]), closed=False), fill=artery, width=2)
        d.line(aorta, fill=artery, width=aw, joint="curve")
        descending = [pt for pt in aorta if 420 <= pt[1] <= 595]
        n_plaque = int(heart * 12)
        for i in range(n_plaque):  # plaque spots along the descending aorta
            x, y = descending[int(i * (len(descending) - 1) / max(1, n_plaque - 1))] if n_plaque > 1 else descending[0]
            d.ellipse([x - 3.5, y - 3.5, x + 3.5, y + 3.5], fill=(240, 204, 110, 255))

        # heart: darker and slightly enlarged with strain, beats faster
        beat = 1 + 0.06 * math.sin(t * (7 + 7 * heart)) * (0.6 + heart)
        k = (1 + 0.14 * heart) * beat
        hx, hy = CX + 12, 412
        heart_pts = _spline([(hx + x * k, hy + y * k) for x, y in HEART])
        d.polygon(heart_pts, fill=(*_mix((186, 34, 44), (118, 18, 28), heart), 255))
        d.ellipse([hx - 14 * k, hy - 16 * k, hx - 2 * k, hy - 6 * k], fill=(232, 120, 120, 120))

        # liver: fills with fat (yellows) and enlarges
        lk = 1 + 0.08 * liver
        d.polygon(_spline(_abs(LIVER, k=lk, about=(-24, 474))), fill=(*_mix((126, 46, 38), (204, 162, 92), liver ** 0.9), 240))
        for x, y, r in self._liver_drops[: int(liver * len(self._liver_drops))]:
            px, py = CX + -24 + (x + 24) * lk, 474 + (y - 474) * lk
            d.ellipse([px - r, py - r, px + r, py + r], fill=(250, 232, 170, 230))

        d.polygon(_spline(_abs(STOMACH)), fill=(214, 138, 128, 240))
        d.polygon(_spline(_abs(PANCREAS)), fill=(*_mix((232, 176, 124), (220, 112, 82), metab), 240))

        # kidneys: paler with scarring under strain
        kid = (*_mix((146, 52, 50), (160, 120, 110), kidneys), 245)
        for sign, (kx, ky) in ((-1, (-42, 534)), (1, (46, 538))):
            pts = [(CX + kx + sign * -x, ky + y) for x, y in KIDNEY]
            d.polygon(_spline(pts), fill=kid)
            for i in range(int(kidneys * 4)):
                yy = ky - 8 + i * 5
                d.line([(CX + kx - 4, yy), (CX + kx + 4, yy + 2)], fill=(96, 60, 56, 220), width=2)

        # gut: duller and inflamed with strain
        colon = (*_mix((198, 142, 112), (176, 92, 80), gut * 0.85), 245)
        d.line(_spline(_abs(COLON), closed=False), fill=colon, width=14, joint="curve")
        small = (*_mix((232, 158, 148), (196, 98, 92), gut * 0.85), 245)
        rows = []
        for i, y in enumerate(range(566, 628, 10)):
            xs = (-36, 36) if i % 2 == 0 else (36, -36)
            rows += [(xs[0], y), (xs[1], y)]
        d.line(_spline(_abs(rows), closed=False, steps=6), fill=small, width=8, joint="curve")

        # visceral fat around the organs as weight goes up
        for x, y, r in self._visceral[: int(metab * len(self._visceral) * 1.3)]:
            d.ellipse([CX + x - r, y - r, CX + x + r, y + r], fill=(244, 210, 126, 200))
        return layer

    def fat_band(self, metab: float, fat: float, body: Image.Image) -> Image.Image | None:
        """Subcutaneous fat along the waist, clipped to the body outline."""
        if metab < 0.05:
            return None
        band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(band)
        torso = _torso(fat)
        thickness = 4 + 24 * metab                      # px of fat under the skin at the waist
        f = max(0.4, 1 - thickness / (64 * (1 + 0.8 * fat)))
        d.polygon(torso, fill=(246, 214, 138, int(120 + 90 * metab)))
        d.polygon([(CX + (x - CX) * f, y) for x, y in torso], fill=(0, 0, 0, 0))
        # keep it to the belly, fading in and out at the ends
        rows = np.zeros(H, dtype=np.float32)
        ys = np.arange(H)
        rows[(ys >= 440) & (ys <= 610)] = 1.0
        rows = np.convolve(rows, np.ones(31) / 31, mode="same")
        fade = Image.fromarray((np.tile(rows[:, None], (1, W)) * 255).astype(np.uint8), "L")
        alpha = ImageChops.multiply(ImageChops.multiply(band.getchannel("A"), fade), body.getchannel("A"))
        band.putalpha(alpha)
        return band

    # ---- close-up insets -----------------------------------------------
    def inset(self, img: Image.Image, cy: int, kind: str, s: float, label: str, target: tuple[float, float]) -> None:
        r = INSET_R
        size = 2 * r
        tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        c = r
        if kind == "artery":
            d.ellipse([0, 0, size, size], fill=(250, 236, 232, 255))
            d.ellipse([c - r * 0.86, c - r * 0.86, c + r * 0.86, c + r * 0.86], fill=(206, 112, 104, 255))   # wall
            d.ellipse([c - r * 0.66, c - r * 0.66, c + r * 0.66, c + r * 0.66], fill=(236, 200, 112, 255))   # plaque layer
            lumen = r * 0.67 * (1 - 0.6 * s)
            ox = r * 0.67 * 0.6 * s * 0.55
            d.ellipse([c - lumen + ox, c - lumen, c + lumen + ox, c + lumen], fill=(150, 22, 32, 255))     # open channel
            for i in range(7):
                a = i / 7 * 2 * math.pi
                rr = lumen * 0.55
                x, y = c + ox + math.cos(a) * rr, c + math.sin(a) * rr
                d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(214, 60, 66, 255))
        elif kind == "liver":
            d.ellipse([0, 0, size, size], fill=(*_mix((142, 56, 44), (196, 148, 92), s ** 0.9), 255))
            for i in range(-3, 4):  # lobule texture
                d.line([(c + i * 22 - 40, 0), (c + i * 22 + 40, size)], fill=(0, 0, 0, 22), width=2)
            for x, y, rr in self._inset_drops[: int(s * len(self._inset_drops))]:
                px, py, pr = c + x * r * 0.9, c + y * r * 0.9, rr * r
                d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(252, 238, 190, 245))
        else:  # teeth
            d.ellipse([0, 0, size, size], fill=(120, 44, 52, 255))
            d.rectangle([0, 0, size, c - 30], fill=(214, 120, 128, 255))   # upper gum
            d.rectangle([0, c + 30, size, size], fill=(214, 120, 128, 255))  # lower gum
            enamel = _mix((248, 246, 238), (226, 204, 156), s)
            for row, (y0, y1) in enumerate(((c - 34, c - 2), (c + 2, c + 34))):
                for i in range(5):
                    x0 = 8 + i * 25
                    d.rounded_rectangle([x0, y0, x0 + 22, y1], radius=7, fill=(*enamel, 255))
            spots = [(33, c - 14), (84, c + 18), (58, c - 20), (108, c + 12), (16, c + 20), (96, c - 16)]
            for x, y in spots[: int(s * len(spots) + 0.3)]:
                rr = 3 + 3 * s
                d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(92, 62, 40, 255))
        circle = Image.new("L", (size, size), 0)
        ImageDraw.Draw(circle).ellipse([0, 0, size - 1, size - 1], fill=255)
        tile.putalpha(ImageChops.multiply(tile.getchannel("A"), circle))

        ring = strain_colour(s)
        dd = ImageDraw.Draw(img)
        x0, y0 = INSET_X - r, cy - r
        tx, ty = target
        dd.line([(x0 + 4, cy), (tx + 4, ty)], fill=(120, 134, 126), width=2)
        dd.ellipse([tx - 4, ty - 4, tx + 4, ty + 4], fill=INK)
        img.alpha_composite(tile, (x0, y0))
        dd.ellipse([x0 - 3, y0 - 3, x0 + size + 3, y0 + size + 3], outline=ring, width=5)
        dd.text((INSET_X, y0 - 14), label, font=self.f_label, fill=INK, anchor="ms")
        dd.text((INSET_X, y0 + size + 26), STAGE_TEXT[_stage(s)], font=self.f_small, fill=ring, anchor="ms")

    def label(self, img: Image.Image, y: int, text: str, s: float, target: tuple[float, float]) -> None:
        d = ImageDraw.Draw(img)
        col = strain_colour(s)
        d.ellipse([LABEL_X, y - 6, LABEL_X + 12, y + 6], fill=col)
        d.text((LABEL_X + 20, y), text, font=self.f_label, fill=INK, anchor="lm")
        end = LABEL_X + 20 + d.textlength(text, font=self.f_label) + 8
        d.line([(end, y), target], fill=MUTED, width=2)
        d.ellipse([target[0] - 4, target[1] - 4, target[0] + 4, target[1] + 4], fill=INK)

    def bars(self, d: ImageDraw.ImageDraw, labels: dict[str, str], systems: dict[str, float]) -> None:
        top, row = 990, 31
        d.rounded_rectangle([24, top - 22, W - 24, top + row * 6 - 6], 20, fill=PANEL, outline=LINE)
        for i, key in enumerate(["heart", "metabolism", "liver", "kidneys", "teeth", "gut"]):
            y = top + i * row
            s = systems[key]
            d.text((48, y + 3), labels[key], font=self.f_bar, fill=INK)
            x0, x1 = 300, W - 52
            d.rounded_rectangle([x0, y + 7, x1, y + 19], 6, fill=(234, 239, 235))
            if s > 0.005:
                d.rounded_rectangle([x0, y + 7, x0 + max(14, int((x1 - x0) * s)), y + 19], 6, fill=strain_colour(s))

    # ---- frames --------------------------------------------------------
    def frame(self, sim: dict[str, Any], product_name: str, frequency_label: str, year_f: float,
              caption: str, t: float) -> Image.Image:
        timeline = sim["timeline"]
        lo = min(int(year_f), len(timeline) - 1)
        hi = min(lo + 1, len(timeline) - 1)
        frac = year_f - lo
        systems = {k: timeline[lo]["systems"][k]["strain"] * (1 - frac) + timeline[hi]["systems"][k]["strain"] * frac
                   for k in timeline[0]["systems"]}
        fat = 0.35 * systems["metabolism"]

        img = Image.new("RGBA", (W, H), (*BG, 255))
        d = ImageDraw.Draw(img)
        d.text((W // 2, 40), "If eaten " + frequency_label, font=self.f_sub, fill=MUTED, anchor="mm")
        name = product_name if len(product_name) <= 30 else product_name[:29] + "…"
        d.text((W // 2, 82), name, font=self.f_title, fill=INK, anchor="mm")
        d.text((W // 2, 134), f"Year {int(round(year_f))}" if year_f > 0 else "Today", font=self.f_year, fill=INK, anchor="mm")

        body, shorts = self.body_layer(fat)
        img.alpha_composite(body)
        img.alpha_composite(self.organs(systems, t))
        band = self.fat_band(systems["metabolism"], int(round(fat * 100)) / 100, body)
        if band is not None:
            img.alpha_composite(band)
        img.alpha_composite(shorts)

        self.label(img, 412, "Heart", systems["heart"], (CX + 4, 412))
        self.label(img, 500, "Waist", systems["metabolism"], (CX - 64 * (1 + 0.8 * fat) + 8, 500))
        self.label(img, 548, "Kidneys", systems["kidneys"], (CX - 44, 536))
        self.label(img, 596, "Gut", systems["gut"], (CX - 26, 590))
        self.inset(img, 270, "teeth", systems["teeth"], "Teeth", (CX + 12, 272))
        self.inset(img, 480, "liver", systems["liver"], "Liver", (CX + 16, 466))
        self.inset(img, 690, "artery", systems["heart"], "Arteries", (CX + 42, 790))

        d = ImageDraw.Draw(img)
        self.bars(d, sim["systems"], systems)
        for i, line in enumerate(_wrap(d, caption, self.f_caption, W - 80)[:2]):
            d.text((W // 2, 1200 + i * 30), line, font=self.f_caption, fill=INK, anchor="mm")
        d.text((W // 2, 1258), "Illustration of general evidence — not a medical prediction", font=self.f_small,
               fill=MUTED, anchor="mm")
        return img.convert("RGB")

    def summary(self, sim: dict[str, Any], product_name: str, frequency_label: str, swap: str | None) -> Image.Image:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.text((W // 2, 110), f"After {sim['years']} years", font=self.f_year, fill=INK, anchor="mm")
        d.text((W // 2, 164), "eating it " + frequency_label, font=self.f_sub, fill=MUTED, anchor="mm")
        y = 230
        findings = sim["findings"][:3]
        if not findings:
            for line in _wrap(d, "At this amount, this product adds little extra strain. Balance and variety still matter.",
                              self.f_caption, W - 120):
                d.text((W // 2, y), line, font=self.f_caption, fill=INK, anchor="mm")
                y += 34
        for f in findings:
            col = strain_colour(f["strain"])
            lines = _wrap(d, f["caption"], self.f_bar, W - 150)[:4]
            h = 74 + 26 * len(lines)
            d.rounded_rectangle([40, y, W - 40, y + h], 22, fill=PANEL, outline=LINE)
            d.rounded_rectangle([40, y, 54, y + h], 7, fill=col)
            d.text((76, y + 22), f"{f['label']}", font=self.f_label, fill=INK)
            d.text((76, y + 48), STAGE_TEXT.get(f["stage"], f["stage"]), font=self.f_small, fill=col)
            for i, line in enumerate(lines):
                d.text((76, y + 74 + i * 26), line, font=self.f_bar, fill=MUTED)
            y += h + 18
        if swap:
            lines = _wrap(d, swap, self.f_bar, W - 140)[:3]
            h = 70 + 26 * len(lines)
            d.rounded_rectangle([40, y + 8, W - 40, y + 8 + h], 22, fill=(226, 238, 231))
            d.text((66, y + 30), "Try instead", font=self.f_label, fill=_mix(GREEN, INK, 0.4))
            for i, line in enumerate(lines):
                d.text((66, y + 60 + i * 26), line, font=self.f_bar, fill=INK)
        for i, line in enumerate(_wrap(d, sim["model_note"], self.f_small, W - 100)[:4]):
            d.text((W // 2, 1150 + i * 24), line, font=self.f_small, fill=MUTED, anchor="mm")
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
    from .simulation import CAPTIONS, _stage as sim_stage  # local import keeps module load light
    systems = sim["timeline"][year_index]["systems"]
    key = max(systems, key=lambda k: systems[k]["strain"])
    stage = sim_stage(systems[key]["strain"])
    if stage == "minimal":
        return "So far, little extra strain at this amount."
    return f"{sim['systems'][key]}: {CAPTIONS[key][stage]}"


# H.264 MP4 plays on Android, iPhone and most browsers; VP9 WebM is a
# fallback for browsers built without H.264 (some Linux/open-source builds).
FORMATS = {
    "mp4": {"codec": "libx264", "media_type": "video/mp4",
            "params": ["-crf", "24", "-preset", "veryfast", "-movflags", "+faststart", "-pix_fmt", "yuv420p"]},
    "webm": {"codec": "libvpx-vp9", "media_type": "video/webm",
             "params": ["-crf", "36", "-b:v", "0", "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1"]},
}


def render_video(sim: dict[str, Any], product_name: str, swap: str | None, out_path: Path, fmt: str = "mp4") -> Path:
    spec = FORMATS[fmt]
    renderer = Renderer()
    freq = frequency_label(sim["servings_per_week"])
    years = sim["years"]
    tmp = out_path.with_name(out_path.stem + ".tmp" + out_path.suffix)
    writer = imageio_ffmpeg.write_frames(
        str(tmp), (W, H), fps=FPS, codec=spec["codec"], quality=None, macro_block_size=8,
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

        emit(renderer.frame(sim, product_name, freq, 0, "Here is what regular intake could mean over time.", 0),
             int(INTRO_S * FPS))
        grow_frames = int(GROW_S * FPS)
        for i in range(grow_frames):
            year_f = years * (i + 1) / grow_frames
            caption = _caption_for(sim, min(int(round(year_f)), years))
            emit(renderer.frame(sim, product_name, freq, year_f, caption, frame_no / FPS), 1)
        last_caption = _caption_for(sim, years)
        for _ in range(int(HOLD_S * FPS)):
            emit(renderer.frame(sim, product_name, freq, years, last_caption, frame_no / FPS), 1)
        emit(renderer.summary(sim, product_name, freq, swap), int(OUTRO_S * FPS))
    finally:
        writer.close()
    os.replace(tmp, out_path)
    return out_path


def video_cache_key(report_id: str, sim: dict[str, Any], age_group: str) -> str:
    raw = f"{report_id}|{sim['servings_per_week']}|{sim['years']}|{age_group}|v4"
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
