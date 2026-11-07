"""Planted freshwater aquarium: tank rim, glass, layered aquascape, god rays.

The fish sprites and their swimming logic are unchanged; this module builds the
tank and its surroundings around them.
"""

from __future__ import annotations

import datetime
import math
import os
from pathlib import Path
import random

import pygame
import pygame.gfxdraw

from adfresh.drawutil import mix
from adfresh.modules.base import Module

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

_fish_raw: dict[int, pygame.Surface | None] = {}
_fish_scaled_cache: dict[tuple[int, int, bool], pygame.Surface] = {}
_fish_frames_cache: dict[tuple[int, int, bool], list[pygame.Surface]] = {}
FISH_TAIL_FRAMES = 8

SPECIES = (
    ((232, 132, 64), (255, 196, 140), "spot"),
    ((48, 120, 196), (120, 190, 230), "stripe"),
    ((236, 232, 226), (214, 96, 48), "spot"),
    ((20, 40, 70), (64, 220, 196), "stripe"),
    ((186, 86, 120), (240, 170, 186), "plain"),
)


def _get_fish_raw(species_idx: int) -> pygame.Surface | None:
    if species_idx in _fish_raw:
        return _fish_raw[species_idx]
    path = ASSETS_DIR / f"fish_{species_idx}.png"
    if path.is_file():
        try:
            surf = pygame.image.load(str(path))
            try:
                surf = surf.convert_alpha()
            except Exception:
                pass
            _fish_raw[species_idx] = surf
            return surf
        except Exception:
            pass
    _fish_raw[species_idx] = None
    return None


def get_fish_surface(species_idx: int, width: int, flip_x: bool) -> pygame.Surface | None:
    width = max(24, int(width) // 2 * 2)
    key = (species_idx, width, flip_x)
    if key in _fish_scaled_cache:
        return _fish_scaled_cache[key]

    raw = _get_fish_raw(species_idx)
    if raw is None:
        return None

    raw_w, raw_h = raw.get_size()
    height = max(1, int(round(raw_h * width / raw_w)))
    scaled = pygame.transform.smoothscale(raw, (width, height))
    if flip_x:
        scaled = pygame.transform.flip(scaled, True, False)
    _fish_scaled_cache[key] = scaled
    return scaled


# --------------------------------------------------------------------------- #
# Scene helpers
# --------------------------------------------------------------------------- #
def _vertical_gradient(w: int, h: int, stops: list[tuple[float, tuple[int, int, int]]]) -> pygame.Surface:
    w = max(1, int(w))
    h = max(1, int(h))
    column = pygame.Surface((1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        color = stops[-1][1]
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                u = (t - t0) / max(1e-6, t1 - t0)
                color = mix(c0, c1, u)
                break
        column.set_at((0, y), color)
    return pygame.transform.scale(column, (w, h))


def _jagged_ellipse(
    rng: random.Random,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    n: int = 26,
    jag: float = 0.16,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    phase = rng.uniform(0, math.tau)
    for i in range(n):
        ang = i / n * math.tau
        r = 1.0 + jag * math.sin(ang * 4.0 + phase) + jag * 0.6 * math.cos(ang * 7.0 - phase)
        pts.append((cx + math.cos(ang) * rx * r, cy + math.sin(ang) * ry * r))
    return pts


def _alpha_vignette(w: int, h: int, strength: int = 120) -> pygame.Surface:
    sw, sh = 96, 54
    small = pygame.Surface((sw, sh), pygame.SRCALPHA)
    cx, cy = sw / 2.0, sh / 2.0
    for y in range(sh):
        for x in range(sw):
            d = math.hypot((x - cx) / cx, (y - cy) / cy) / math.sqrt(2.0)
            a = int(strength * max(0.0, d - 0.45) ** 1.7)
            if a > 0:
                small.set_at((x, y), (2, 6, 10, min(255, a)))
    return pygame.transform.smoothscale(small, (w, h))


def _fill_poly(
    surf: pygame.Surface, color, pts: list[tuple[float, float]], *, aa: bool = False
) -> None:
    """Filled polygon, with optional antialiased edges for hardscape."""
    if len(pts) < 3:
        return
    ip = [(int(x), int(y)) for x, y in pts]
    pygame.draw.polygon(surf, color, ip)
    if aa:
        try:
            pygame.gfxdraw.aapolygon(surf, ip, color)
        except Exception:
            pass


def _shaded_leaf(
    surf: pygame.Surface,
    spine: list[tuple[float, float]],
    width: float,
    dark: tuple[int, int, int],
    light: tuple[int, int, int],
) -> None:
    left, right = [], []
    for k, (x, y) in enumerate(spine):
        r = k / max(1, len(spine) - 1)
        wdt = width * (0.18 + math.sin(r * math.pi) ** 0.75)
        wdt *= 0.92 + 0.08 * math.sin(r * 7.0 + width)
        if k + 1 < len(spine):
            dx, dy = spine[k + 1][0] - x, spine[k + 1][1] - y
        else:
            dx, dy = x - spine[k - 1][0], y - spine[k - 1][1]
        ln = max(1e-4, math.hypot(dx, dy))
        nx, ny = -dy / ln, dx / ln
        left.append((x + nx * wdt, y + ny * wdt))
        right.append((x - nx * wdt, y - ny * wdt))
    if len(left) < 3:
        return

    def band(a: float, b: float) -> list[tuple[float, float]]:
        oa = [(lx + (rx - lx) * a, ly + (ry - ly) * a) for (lx, ly), (rx, ry) in zip(left, right)]
        ob = [(lx + (rx - lx) * b, ly + (ry - ly) * b) for (lx, ly), (rx, ry) in zip(left, right)]
        return oa + ob[::-1]

    _fill_poly(surf, dark, band(0.0, 0.30))
    _fill_poly(surf, mix(dark, light, 0.55), band(0.30, 0.62))
    _fill_poly(surf, light, band(0.62, 1.0))
    # Central vein and two faint side veins.
    pygame.draw.lines(surf, mix(light, (235, 245, 200), 0.35), False, spine, 1)
    for frac, shade in ((0.28, 0.35), (0.72, 0.25)):
        vein = [
            (
                lx + (rx - lx) * frac,
                ly + (ry - ly) * frac,
            )
            for (lx, ly), (rx, ry) in zip(left, right)
        ]
        pygame.draw.lines(surf, mix(light, dark, 1.0 - shade), False, vein, 1)


def _leaf_polygon(
    spine: list[tuple[float, float]],
    width: float,
) -> list[tuple[float, float]]:
    left, right = [], []
    for k, (x, y) in enumerate(spine):
        r = k / max(1, len(spine) - 1)
        wdt = width * (0.20 + math.sin(r * math.pi) ** 0.75)
        if k + 1 < len(spine):
            dx, dy = spine[k + 1][0] - x, spine[k + 1][1] - y
        else:
            dx, dy = x - spine[k - 1][0], y - spine[k - 1][1]
        ln = max(1e-4, math.hypot(dx, dy))
        nx, ny = -dy / ln, dx / ln
        left.append((x + nx * wdt, y + ny * wdt))
        right.append((x - nx * wdt, y - ny * wdt))
    return left + right[::-1]


# --------------------------------------------------------------------------- #
# Module
# --------------------------------------------------------------------------- #
def _tail_frames(species_idx: int, width: int) -> list[pygame.Surface] | None:
    """Pre-render a tail-swish cycle for a fish (head stays put).

    The fish art is a single sprite facing left, so the rear columns are shifted
    vertically with a sine wave whose amplitude grows toward the tail.  Flipping
    the whole frame mirrors the motion for rightward swimmers.
    """
    base = get_fish_surface(species_idx, width, flip_x=False)
    if base is None:
        return None
    try:
        import numpy as np
    except Exception:  # pragma: no cover - numpy is a dependency
        return None
    w, h = base.get_size()
    rgb = pygame.surfarray.array3d(base)
    alpha = pygame.surfarray.array_alpha(base)
    xs = np.arange(w, dtype=np.float32) / max(1, w - 1)
    tail = np.clip((xs - 0.50) / 0.50, 0.0, 1.0) ** 1.7
    ys = np.arange(h)[None, :]
    frames: list[pygame.Surface] = []
    for f in range(FISH_TAIL_FRAMES):
        phase = f / FISH_TAIL_FRAMES * math.tau
        dy = (h * 0.075) * tail * np.sin(phase + xs * 3.6)
        dy += (h * 0.012) * np.sin(phase * 0.5 + xs * 5.2)
        idx = np.clip(ys - dy.astype(np.int32)[:, None], 0, h - 1)
        moved = np.take_along_axis(rgb, idx[:, :, None], axis=1)
        moved_a = np.take_along_axis(alpha, idx, axis=1)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pixels = pygame.surfarray.pixels3d(surf)
        pixels[:, :, :] = moved
        del pixels
        pa = pygame.surfarray.pixels_alpha(surf)
        pa[:, :] = moved_a
        del pa
        frames.append(surf)
    return frames


def get_fish_frames(
    species_idx: int, width: int, flip_x: bool
) -> list[pygame.Surface] | None:
    width = max(24, int(width) // 2 * 2)
    key = (species_idx, width, flip_x)
    hit = _fish_frames_cache.get(key)
    if hit is not None:
        return hit
    frames = _tail_frames(species_idx, width)
    if frames is None:
        return None
    if flip_x:
        frames = [pygame.transform.flip(frame, True, False) for frame in frames]
    if len(_fish_frames_cache) > 96:
        _fish_frames_cache.clear()
    _fish_frames_cache[key] = frames
    return frames


def _night_mode() -> bool:
    """True when the aquarium should use its dark, moonlight look."""
    override = os.environ.get("ADFRESH_NIGHT", "").strip().lower()
    if override in {"1", "true", "on", "yes", "night"}:
        return True
    if override in {"0", "false", "off", "no", "day"}:
        return False
    hour = datetime.datetime.now().hour
    return hour >= 19 or hour < 6


class Aquatic(Module):
    id = "aquatic"
    title = "Aquatic Realm"

    # ------------------------------------------------------------------ #
    # Scene construction
    # ------------------------------------------------------------------ #
    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        self.night = _night_mode()
        self.ripples: list[dict] = []
        self.scene_rng = random.Random(90210)
        self.rim = {
            "top": max(16, int(h * 0.048)),
            "bottom": max(12, int(h * 0.032)),
            "side": max(10, int(w * 0.008)),
        }
        self.waterline = self.rim["top"] + max(8, int(h * 0.020))
        self.seabed_y = h * 0.79

        self._build_water()
        self._build_caustics()
        self._build_rays()
        self._build_backdrop()
        self._build_substrate()
        self._build_flora()
        self._build_water_tint()
        self._build_foreground()
        self._build_overlay()
        self._spawn_fish()
        self._spawn_bubbles()
        self._spawn_marine_snow()

    def _build_water(self) -> None:
        w, h = self.w, self.h
        if self.night:
            stops = [
                (0.00, (24, 70, 86)),
                (0.10, (16, 54, 72)),
                (0.28, (9, 36, 56)),
                (0.52, (5, 24, 42)),
                (0.76, (3, 15, 30)),
                (1.00, (2, 9, 20)),
            ]
        else:
            stops = [
                (0.00, (54, 144, 152)),
                (0.10, (36, 122, 140)),
                (0.28, (18, 86, 116)),
                (0.52, (7, 46, 80)),
                (0.76, (5, 28, 56)),
                (1.00, (4, 18, 38)),
            ]
        self.water_bg = _vertical_gradient(w, h, stops)
        pool = pygame.Surface((w, h), pygame.SRCALPHA)
        glow_w = int(w * 0.9)
        for i in range(10):
            a = 6 - i // 2
            if a <= 0:
                break
            pygame.draw.ellipse(
                pool,
                (110, 190, 220, a) if self.night else (150, 235, 240, a),
                (
                    (w - glow_w) // 2 - i * 8,
                    self.waterline - 12 + i * 12,
                    glow_w + i * 16,
                    int(h * 0.10) + i * 18,
                ),
            )
        self.water_bg.blit(pool, (0, 0))

    def _build_caustics(self) -> None:
        w, h = self.w, self.h
        self.n_caust_frames = 28
        self.caust_duration = 3.2
        caust_w, caust_h = 150, 56
        self.caust_target_h = int(h * 0.30)
        self.caustic_frames: list[pygame.Surface] = []

        caust_fade = pygame.Surface((1, caust_h))
        for cy in range(caust_h):
            ny = cy / caust_h
            top = min(1.0, (ny / 0.22) ** 1.6)
            bottom = min(1.0, ((1.0 - ny) / 0.28) ** 1.2)
            iv = int(top * bottom * 255)
            caust_fade.set_at((0, cy), (iv, iv, iv))
        fade_scaled = pygame.transform.scale(caust_fade, (caust_w, caust_h))

        for f in range(self.n_caust_frames):
            ct = f * (self.caust_duration / self.n_caust_frames)
            buf = pygame.Surface((caust_w, caust_h))
            pa = pygame.PixelArray(buf)
            for cy in range(caust_h):
                ny = cy / caust_h
                for cx in range(caust_w):
                    nx = cx / caust_w
                    w1 = math.sin(nx * 13.0 + ny * 4.0 + ct * 1.9)
                    w2 = math.sin(nx * 8.0 - ny * 10.0 - ct * 2.6)
                    w3 = math.sin((nx + ny) * 10.0 + ct * 0.9)
                    val = (w1 + w2 + w3) / 3.0
                    sharp = max(0.0, 1.0 - abs(val)) ** 3.6
                    intensity = int(sharp * (58 if self.night else 118))
                    pa[cx, cy] = (
                        int(intensity * 0.62),
                        int(intensity * 0.88),
                        int(intensity * 0.82),
                    )
            del pa
            buf.blit(fade_scaled, (0, 0), special_flags=pygame.BLEND_MULT)
            self.caustic_frames.append(
                pygame.transform.smoothscale(buf, (w, self.caust_target_h))
            )

    def _build_rays(self) -> None:
        w, h = self.w, self.h
        self.ray_scale = 3
        self.rw, self.rh = max(1, w // self.ray_scale), max(1, h // self.ray_scale)
        self.god_rays_buf = pygame.Surface((self.rw, self.rh))
        fade = pygame.Surface((1, self.rh))
        for y in range(self.rh):
            t = y / max(1, self.rh)
            iv = int(max(0.0, (1.0 - t * 0.78) ** 1.8) * 255)
            fade.set_at((0, y), (iv, iv, iv))
        self.ray_fade = pygame.transform.scale(fade, (self.rw, self.rh))
        self.ray_strength = 0.55 if self.night else 1.0
        self.god_rays_config = [
            {"x": 0.08, "w0": 40, "w1": 210, "angle": 0.16, "speed": 0.24, "phase": 0.4, "intensity": 20},
            {"x": 0.24, "w0": 60, "w1": 260, "angle": 0.12, "speed": 0.28, "phase": 2.1, "intensity": 24},
            {"x": 0.44, "w0": 80, "w1": 320, "angle": 0.08, "speed": 0.22, "phase": 4.0, "intensity": 26},
            {"x": 0.64, "w0": 60, "w1": 260, "angle": 0.05, "speed": 0.26, "phase": 1.2, "intensity": 22},
            {"x": 0.84, "w0": 50, "w1": 230, "angle": 0.01, "speed": 0.23, "phase": 5.1, "intensity": 20},
        ]

    def _build_backdrop(self) -> None:
        w, h = self.w, self.h
        rng = self.scene_rng
        surf = pygame.Surface((w, h), pygame.SRCALPHA)

        # Smooth haze into the substrate (no hard band).
        haze_h = max(1, int(h * 0.30))
        haze = pygame.Surface((1, haze_h), pygame.SRCALPHA)
        for y in range(haze_h):
            t = y / max(1, haze_h - 1)
            haze.set_at((0, y), (12, 34, 42, int((t ** 1.4) * 78)))
        surf.blit(pygame.transform.scale(haze, (w, haze_h)), (0, h - haze_h))

        # Distant boulder masses: very dark, irregular, no outlines.
        for _ in range(8):
            cx = rng.uniform(-w * 0.04, w * 1.04)
            base_y = rng.uniform(h * 0.75, h * 0.83)
            rw = rng.uniform(w * 0.07, w * 0.20)
            rh = rng.uniform(h * 0.09, h * 0.20)
            pts = _jagged_ellipse(rng, cx, base_y - rh * 0.3, rw, rh, n=24, jag=0.10)
            pts = [(x, min(y, base_y)) for x, y in pts]
            pygame.draw.polygon(surf, (22, 42, 50, rng.randint(170, 225)), pts)
            top = [q for q in pts if q[1] < base_y - rh * 0.4]
            if len(top) >= 3:
                pygame.draw.lines(surf, (52, 82, 86, 80), False, top, 2)

        # Blurred distant plants, almost lost in the haze.
        for _ in range(10):
            px = rng.uniform(0, w)
            base_y = rng.uniform(h * 0.78, h * 0.85)
            ph = rng.uniform(h * 0.10, h * 0.22)
            pts = []
            for i in range(6):
                tt = i / 5.0
                pts.append((px + math.sin(tt * 2.1 + px * 0.01) * ph * 0.18, base_y - ph * tt))
            pygame.draw.lines(surf, (18, 50, 48, 95), False, pts, max(4, int(w * 0.0030)))
        for _ in range(6):
            fx = rng.uniform(0, w)
            fy = rng.uniform(h * 0.46, h * 0.62)
            fl = rng.uniform(w * 0.012, w * 0.026)
            pygame.draw.ellipse(
                surf,
                (10, 26, 32, 55),
                (fx - fl * 0.5, fy - fl * 0.16, fl, fl * 0.32),
            )
            pygame.draw.polygon(
                surf,
                (10, 26, 32, 55),
                [(fx - fl * 0.5, fy), (fx - fl * 0.72, fy - fl * 0.14), (fx - fl * 0.72, fy + fl * 0.14)],
            )
        for _ in range(90):
            surf.fill(
                (110, 170, 180, rng.randint(12, 55)),
                (int(rng.uniform(0, w)), int(rng.uniform(self.waterline, h * 0.82)), 2, 2),
            )
        self.backdrop = surf

    def _draw_rock_cluster(
        self,
        surf: pygame.Surface,
        cx: float,
        base_y: float,
        size: float,
        seed: int,
        *,
        dark: float = 0.0,
    ) -> None:
        rng = random.Random(seed)
        for _ in range(rng.randint(4, 7)):
            bx = cx + rng.uniform(-size * 0.52, size * 0.52)
            by = base_y + rng.uniform(-size * 0.05, size * 0.04)
            rw = rng.uniform(size * 0.20, size * 0.38)
            rh = rw * rng.uniform(0.60, 0.95)
            pts = _jagged_ellipse(rng, bx, by - rh * 0.45, rw, rh, n=20, jag=0.13)
            pts = [(x, min(y, by)) for x, y in pts]
            base = (int(66 - dark * 18), int(62 - dark * 16), int(54 - dark * 12))
            mid = (int(98 - dark * 22), int(92 - dark * 20), int(78 - dark * 14))
            lit = (int(138 - dark * 26), int(130 - dark * 22), int(108 - dark * 16))
            _fill_poly(surf, base, pts, aa=True)
            inner = [(bx + (x - bx) * 0.78, by - rh * 0.10 + (y - (by - rh * 0.10)) * 0.78) for x, y in pts]
            _fill_poly(surf, mid, inner, aa=True)
            top = [(x, y) for x, y in inner if y < by - rh * 0.35]
            if len(top) >= 3:
                _fill_poly(surf, lit, top, aa=True)
            for _ in range(rng.randint(2, 4)):
                sx = bx + rng.uniform(-rw * 0.55, rw * 0.55)
                sy = by - rng.uniform(rh * 0.3, rh * 1.0)
                pygame.draw.line(
                    surf,
                    (26, 25, 22),
                    (int(sx), int(sy)),
                    (int(sx + rng.uniform(-10, 10)), int(sy + rng.uniform(6, 20))),
                    1,
                )
            for _ in range(rng.randint(16, 30)):
                ang = rng.uniform(0, math.tau)
                rr = math.sqrt(rng.random())
                sx = bx + math.cos(ang) * rw * rr * 0.85
                sy = by - rh * 0.45 + math.sin(ang) * rh * rr * 0.75
                tone = rng.choice((32, 38, 46, 54, 120, 132, 144))
                pygame.draw.circle(
                    surf,
                    (int(tone - dark * 10), int(tone - dark * 9), int(tone * 0.88 - dark * 8)),
                    (int(sx), int(sy)),
                    rng.randint(1, 2),
                )
            for _ in range(rng.randint(3, 8)):
                pygame.draw.circle(
                    surf,
                    mix(
                        (36 - dark * 8, 78 - dark * 14, 44 - dark * 8),
                        (58 - dark * 12, 104 - dark * 18, 58 - dark * 10),
                        rng.random(),
                    ),
                    (int(bx + rng.uniform(-rw * 0.55, rw * 0.55)), int(by - rng.uniform(rh * 0.2, rh * 1.0))),
                    rng.randint(2, 5),
                )

    def _draw_driftwood(
        self,
        surf: pygame.Surface,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        thick: float,
        seed: int,
    ) -> None:
        rng = random.Random(seed)
        steps = 14
        left, right = [], []
        for i in range(steps + 1):
            t = i / steps
            x = x0 + (x1 - x0) * t + math.sin(t * 3.4 + 0.7) * (y1 - y0) * 0.10
            y = y0 + (y1 - y0) * t
            wdt = thick * (0.30 + 0.70 * math.sin(min(1.0, t * 1.15) * math.pi) ** 0.6)
            left.append((x, y - wdt * 0.5))
            right.append((x, y + wdt * 0.5))
        pygame.draw.polygon(surf, (54, 42, 32), left + right[::-1])
        pygame.draw.lines(surf, (88, 70, 48), False, left, max(2, int(thick * 0.10)))
        pygame.draw.lines(surf, (30, 24, 18), False, right, max(2, int(thick * 0.12)))
        for _ in range(20):
            t = rng.random()
            x = x0 + (x1 - x0) * t + rng.uniform(-thick * 0.25, thick * 0.25)
            y = y0 + (y1 - y0) * t
            pygame.draw.line(
                surf,
                (36, 29, 22),
                (int(x), int(y)),
                (int(x + rng.uniform(-10, 10)), int(y + rng.uniform(-4, 4))),
                1,
            )
        for _ in range(10):
            t = rng.random()
            x = x0 + (x1 - x0) * t + rng.uniform(-thick * 0.2, thick * 0.2)
            y = y0 + (y1 - y0) * t - thick * 0.30
            pygame.draw.circle(surf, (52, 92, 50), (int(x), int(y)), rng.randint(2, max(3, int(thick * 0.12))))

    def _build_substrate(self) -> None:
        w, h = self.w, self.h
        rng = self.scene_rng
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        base = self.seabed_y

        def dune(top: float, color: tuple[int, int, int], amp: float, phase: float) -> list[tuple[int, int]]:
            pts = [(0, h), (0, int(top))]
            x = 0
            while x <= w:
                y = top + math.sin(x * 0.0040 + phase) * amp + math.sin(x * 0.0105 + phase * 1.7) * amp * 0.45
                pts.append((x, int(y)))
                x += max(10, w // 200)
            pts.append((w, h))
            return pts

        pygame.draw.polygon(
            surf,
            (56, 62, 48),
            dune(base - h * 0.045, (56, 62, 48), h * 0.024, 1.2),
        )
        top = int(base - h * 0.035)
        sh = max(2, h - top)
        sand = _vertical_gradient(
            w,
            sh,
            [
                (0.00, (118, 108, 80)),
                (0.22, (146, 132, 98)),
                (0.55, (132, 118, 88)),
                (0.82, (102, 90, 68)),
                (1.00, (64, 58, 44)),
            ],
        ).convert_alpha()
        mask = pygame.Surface((w, sh), pygame.SRCALPHA)
        bed = [(x, y - top) for x, y in dune(base + h * 0.002, (0, 0, 0), h * 0.020, 3.1)]
        pygame.draw.polygon(mask, (255, 255, 255, 255), bed)
        sand.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(sand, (0, top))

        for _ in range(min(int(w * h / 140), 90000)):
            gx = rng.uniform(0, w)
            gy = rng.uniform(base - h * 0.02, h)
            col = rng.choice(
                [
                    (176, 154, 112),
                    (208, 186, 142),
                    (120, 102, 74),
                    (74, 62, 46),
                    (226, 210, 176),
                    (146, 118, 82),
                ]
            )
            surf.fill(col, (int(gx), int(gy), 2 if rng.random() < 0.10 else 1, 2 if rng.random() < 0.10 else 1))
        for _ in range(int(w * h / 7000)):
            px = rng.uniform(0, w)
            py = rng.uniform(base, h)
            pr = rng.uniform(2, 10)
            pygame.draw.ellipse(surf, (58, 50, 38), (px - pr, py - pr * 0.55, pr * 2, pr * 1.10))
            pygame.draw.ellipse(surf, (166, 146, 108), (px - pr * 0.8, py - pr * 0.55, pr * 1.6, pr * 0.8))
            pygame.draw.ellipse(surf, (214, 196, 156), (px - pr * 0.5, py - pr * 0.45, pr * 0.8, pr * 0.35))

        fg_h = max(2, int(h * 0.18))
        fg = pygame.Surface((1, fg_h), pygame.SRCALPHA)
        for y in range(fg_h):
            t = y / max(1, fg_h - 1)
            fg.set_at((0, y), (8, 12, 12, int((t ** 1.5) * 78)))
        surf.blit(pygame.transform.scale(fg, (w, fg_h)), (0, h - fg_h))
        self._draw_rock_cluster(surf, w * 0.180, base + h * 0.025, w * 0.185, 11)
        self._draw_rock_cluster(surf, w * 0.825, base + h * 0.040, w * 0.165, 21, dark=0.10)
        self._draw_rock_cluster(surf, w * 0.500, base + h * 0.065, w * 0.110, 31, dark=0.16)
        self._draw_rock_cluster(surf, w * 0.620, base + h * 0.095, w * 0.075, 41, dark=0.24)
        self._draw_driftwood(surf, w * 0.115, base + h * 0.030, w * 0.275, base + h * 0.105, w * 0.026, 71)

        for cx, cy, count, hue in (
            (w * 0.125, base + h * 0.005, 6, (196, 116, 92)),
            (w * 0.205, base + h * 0.028, 4, (160, 94, 124)),
            (w * 0.795, base + h * 0.030, 5, (116, 126, 176)),
            (w * 0.875, base + h * 0.045, 4, (186, 144, 88)),
            (w * 0.455, base + h * 0.060, 4, (112, 150, 136)),
        ):
            for _ in range(count):
                mx = cx + rng.uniform(-w * 0.022, w * 0.022)
                my = cy + rng.uniform(-h * 0.014, h * 0.014)
                mr = rng.uniform(w * 0.0060, w * 0.0125)
                pygame.draw.circle(surf, mix(hue, (22, 24, 28), 0.40), (int(mx), int(my - mr * 0.35)), int(mr * 1.25))
                pygame.draw.circle(surf, hue, (int(mx), int(my - mr * 0.45)), int(mr))
                # Radial ridges / stripes.
                for j in range(7):
                    ang = j / 7 * math.tau
                    pygame.draw.line(
                        surf,
                        mix(hue, (255, 240, 225), 0.35),
                        (int(mx), int(my - mr * 0.45)),
                        (int(mx + math.cos(ang) * mr * 0.8), int(my - mr * 0.45 + math.sin(ang) * mr * 0.45)),
                        1,
                    )
                pygame.draw.circle(
                    surf,
                    mix(hue, (255, 255, 255), 0.30),
                    (int(mx - mr * 0.30), int(my - mr * 0.70)),
                    max(2, int(mr * 0.40)),
                )
        # Brain coral on the centre-back rock.
        bcx, bcy, br = w * 0.455, base + h * 0.052, w * 0.022
        pygame.draw.ellipse(surf, (96, 86, 62), (bcx - br, bcy - br * 0.55, br * 2, br * 1.1))
        for j in range(8):
            pygame.draw.arc(
                surf,
                (132, 118, 84),
                (bcx - br * (0.9 - j * 0.08), bcy - br * 0.45, br * (1.8 - j * 0.16), br * 0.9),
                0.2,
                2.9,
                1,
            )
        for sx, sy in ((w * 0.26, base + h * 0.11), (w * 0.74, base + h * 0.12)):
            pygame.draw.ellipse(surf, (198, 184, 160), (int(sx), int(sy), int(w * 0.010), int(h * 0.012)))
            pygame.draw.arc(surf, (128, 112, 92), (int(sx), int(sy), int(w * 0.010), int(h * 0.012)), 0.2, 3.0, 1)

        pipe_x = w * 0.060
        pipe_top = self.waterline + h * 0.02
        pipe_bottom = base + h * 0.01
        pygame.draw.rect(surf, (34, 38, 40), (int(pipe_x), int(pipe_top), max(6, int(w * 0.006)), int(pipe_bottom - pipe_top)), border_radius=3)
        pygame.draw.rect(surf, (64, 70, 72), (int(pipe_x + w * 0.001), int(pipe_top), max(2, int(w * 0.0016)), int(pipe_bottom - pipe_top)), border_radius=2)
        strainer_y = int(base - h * 0.02)
        pygame.draw.rect(surf, (22, 25, 26), (int(pipe_x - w * 0.004), strainer_y, int(w * 0.014), int(h * 0.06)), border_radius=4)
        for i in range(7):
            yy = strainer_y + int(h * 0.006) + i * int(h * 0.007)
            pygame.draw.line(surf, (62, 68, 70), (int(pipe_x - w * 0.0025), yy), (int(pipe_x + w * 0.0085), yy), 1)

        heater_x = w * 0.945
        heater_top = self.waterline + h * 0.06
        heater_h = h * 0.34
        pygame.draw.rect(surf, (58, 72, 74), (int(heater_x), int(heater_top), max(5, int(w * 0.005)), int(heater_h)), border_radius=3)
        pygame.draw.rect(surf, (128, 156, 152), (int(heater_x + w * 0.0012), int(heater_top + h * 0.02), max(2, int(w * 0.0018)), int(heater_h * 0.55)), border_radius=2)
        pygame.draw.rect(surf, (222, 132, 78), (int(heater_x + w * 0.0014), int(heater_top + h * 0.23), max(2, int(w * 0.0014)), int(heater_h * 0.26)), border_radius=2)
        for sy in (heater_top + h * 0.03, heater_top + heater_h - h * 0.05):
            pygame.draw.rect(surf, (24, 26, 28), (int(heater_x - w * 0.002), int(sy), int(w * 0.009), int(h * 0.020)), border_radius=2)

        for _ in range(70):
            pygame.draw.circle(
                surf,
                mix((42, 104, 58), (22, 66, 42), rng.random()),
                (int(rng.uniform(w * 0.05, w * 0.95)), int(rng.uniform(base - h * 0.01, base + h * 0.05))),
                rng.randint(1, 3),
            )
        # Moss tufts over the rock bases.
        for _ in range(70):
            mx = rng.uniform(w * 0.04, w * 0.96)
            my = base + rng.uniform(-h * 0.02, h * 0.04)
            pygame.draw.circle(
                surf,
                mix((36, 92, 52), (24, 70, 44), rng.random()),
                (int(mx), int(my)),
                rng.randint(1, 3),
            )
        self.seabed_surf = surf

    # ------------------------------------------------------------------ #
    # Flora
    # ------------------------------------------------------------------ #
    def _build_flora(self) -> None:
        w, h = self.w, self.h
        rng = self.scene_rng
        base = self.seabed_y
        self.plants: list[dict] = []

        def add(
            kind: str,
            x: float,
            y: float,
            height: float,
            layer: str,
            seed: int,
            *,
            red: bool = False,
        ) -> None:
            self.plants.append(
                {
                    "kind": kind,
                    "x": x,
                    "y": y,
                    "h": height,
                    "layer": layer,
                    "seed": seed,
                    "phase": rng.uniform(0, math.tau),
                    "speed": rng.uniform(0.55, 0.95),
                    "tint": rng.uniform(-0.14, 0.14),
                    "red": red,
                }
            )

        for i, x in enumerate((0.050, 0.270, 0.720, 0.945)):
            add("kelp", w * x, base + h * rng.uniform(0.02, 0.08), h * rng.uniform(0.28, 0.44), "back", 500 + i)
        # Hardscape-first layout: plants cluster around the rocks, with an open
        # sand path through the centre.
        add("sword", w * 0.185, base + h * 0.020, h * 0.34, "mid", 101)
        add("sword", w * 0.800, base + h * 0.030, h * 0.32, "mid", 102)
        add("sword", w * 0.335, base + h * 0.055, h * 0.27, "mid", 103)
        add("sword", w * 0.875, base + h * 0.055, h * 0.22, "mid", 104)
        add("sword", w * 0.700, base + h * 0.075, h * 0.19, "mid", 105)
        add("sword", w * 0.245, base + h * 0.085, h * 0.17, "mid", 106, red=True)
        add("vallisneria", w * 0.065, base + h * 0.035, h * 0.34, "mid", 201)
        add("vallisneria", w * 0.120, base + h * 0.060, h * 0.28, "mid", 202)
        add("vallisneria", w * 0.285, base + h * 0.070, h * 0.30, "mid", 203)
        add("vallisneria", w * 0.740, base + h * 0.040, h * 0.33, "mid", 204)
        add("vallisneria", w * 0.915, base + h * 0.050, h * 0.30, "mid", 205)
        add("vallisneria", w * 0.960, base + h * 0.080, h * 0.24, "mid", 206)
        add("java_fern", w * 0.205, base + h * 0.015, h * 0.14, "mid", 301)
        add("java_fern", w * 0.795, base + h * 0.030, h * 0.13, "mid", 302)
        add("stem", w * 0.145, base + h * 0.070, h * 0.18, "mid", 701)
        add("stem", w * 0.860, base + h * 0.080, h * 0.16, "mid", 702)
        add("carpet", w * 0.400, base + h * 0.100, h * 0.050, "front", 601)
        add("carpet", w * 0.505, base + h * 0.115, h * 0.055, "front", 602)
        add("carpet", w * 0.600, base + h * 0.105, h * 0.050, "front", 603)
        add("carpet", w * 0.095, base + h * 0.115, h * 0.045, "front", 604)
        add("carpet", w * 0.900, base + h * 0.110, h * 0.045, "front", 605)
        add("vallisneria", w * 0.015, h - h * 0.060, h * 0.18, "front", 401)
        add("vallisneria", w * 0.988, h - h * 0.055, h * 0.16, "front", 402)

        self.sea_fans = [
            {"x": w * 0.105, "y": base + h * 0.035, "size": h * 0.15, "color": (146, 62, 88), "filigree": (188, 96, 118), "phase": 0.6, "tilt": 0.18},
            {"x": w * 0.895, "y": base + h * 0.050, "size": h * 0.13, "color": (104, 66, 132), "filigree": (150, 108, 176), "phase": 2.7, "tilt": -0.16},
        ]
        self.anemones = [
            {
                "x": w * 0.30,
                "y": base + h * 0.075,
                "base_w": max(26, int(w * 0.020)),
                "base_h": max(18, int(h * 0.030)),
                "color": (176, 102, 122),
                "tip_color": (232, 208, 210),
                "tentacles": 30,
                "length": h * 0.075,
                "wiggle_speed": 1.9,
                "phase": 0.4,
            },
            {
                "x": w * 0.735,
                "y": base + h * 0.090,
                "base_w": max(24, int(w * 0.018)),
                "base_h": max(16, int(h * 0.026)),
                "color": (134, 124, 176),
                "tip_color": (216, 210, 232),
                "tentacles": 26,
                "length": h * 0.065,
                "wiggle_speed": 2.2,
                "phase": 2.0,
            },
        ]

    def _draw_vallisneria(self, surf: pygame.Surface, plant: dict) -> None:
        rng = random.Random(plant["seed"])
        bx, by = plant["x"], plant["y"]
        ph, t = plant["phase"], self.t
        front = plant["layer"] == "front"
        back = plant["layer"] == "back"
        base_color = (48, 112, 64) if front else (40, 96, 58)
        if back:
            base_color = (18, 58, 56)
        tip_color = (104, 168, 92) if front else (72, 132, 76)
        if back:
            tip_color = (34, 86, 72)
        warm = max(0.0, plant.get("tint", 0.0))
        base_color = mix(base_color, (44, 92, 52), warm * 1.6)
        tip_color = mix(tip_color, (108, 146, 70), warm * 1.6)
        for i in range(rng.randint(7, 11)):
            ox = rng.uniform(-plant["h"] * 0.16, plant["h"] * 0.16)
            length = plant["h"] * rng.uniform(0.55, 1.0)
            width = max(3.0, plant["h"] * rng.uniform(0.016, 0.030))
            sway_phase = ph + i * 0.7 + rng.uniform(-0.4, 0.4)
            amp = plant["h"] * rng.uniform(0.05, 0.13)
            lean = rng.uniform(-0.28, 0.28)
            spine = []
            steps = 7
            for k in range(steps + 1):
                r = k / steps
                spine.append(
                    (
                        bx + ox + lean * length * r
                        + math.sin(t * plant["speed"] + sway_phase + r * 1.7) * amp * (r ** 1.6)
                        + math.sin(r * 4.0 + i * 0.9) * width * 0.7,
                        by - length * r,
                    )
                )
            poly = _leaf_polygon(spine, width)
            if len(poly) >= 3:
                _fill_poly(surf, base_color, poly)
                pygame.draw.lines(surf, mix(base_color, tip_color, 0.55), False, poly[: len(poly) // 2], max(1, int(width * 0.9)))
                pygame.draw.lines(surf, mix(tip_color, (200, 230, 170), 0.25), False, spine, 1)

    def _draw_sword(self, surf: pygame.Surface, plant: dict) -> None:
        rng = random.Random(plant["seed"])
        bx, by = plant["x"], plant["y"]
        ph, t = plant["phase"], self.t
        for i in range(rng.randint(6, 9)):
            ang = -math.pi * 0.5 + (i / max(1, 9) - 0.5) * 2.1 + rng.uniform(-0.10, 0.10)
            length = plant["h"] * rng.uniform(0.55, 1.0)
            width = plant["h"] * rng.uniform(0.055, 0.090)
            sway = math.sin(t * plant["speed"] + ph + i * 0.8) * plant["h"] * 0.045
            spine = []
            steps = 8
            curl = rng.uniform(-0.22, 0.22)
            for k in range(steps + 1):
                r = k / steps
                spine.append(
                    (
                        bx + math.cos(ang) * length * r + sway * (r ** 1.7) + curl * length * 0.35 * math.sin(r * math.pi) * -math.sin(ang),
                        by + math.sin(ang) * length * r - length * 0.18 * r * r + curl * length * 0.18 * r * r,
                    )
                )
            if plant.get("red"):
                dark = mix((52, 36, 28), (40, 28, 22), rng.random())
                light = mix((96, 60, 40), (118, 74, 46), rng.random())
            else:
                warm = max(0.0, plant.get("tint", 0.0))
                dark = mix((26, 74, 44), (34, 68, 36), warm + rng.random() * 0.4)
                light = mix((62, 126, 70), (104, 146, 74), warm + rng.random() * 0.4)
            _shaded_leaf(surf, spine, width, dark, light)
        pygame.draw.ellipse(
            surf,
            (42, 60, 38),
            (
                int(bx - plant["h"] * 0.03),
                int(by - plant["h"] * 0.02),
                int(plant["h"] * 0.06),
                int(plant["h"] * 0.03),
            ),
        )

    def _draw_java_fern(self, surf: pygame.Surface, plant: dict) -> None:
        rng = random.Random(plant["seed"])
        bx, by = plant["x"], plant["y"]
        ph, t = plant["phase"], self.t
        n = rng.randint(7, 9)
        for i in range(n):
            ang = -math.pi * 0.5 + (i / max(1, n - 1) - 0.5) * 1.9 + rng.uniform(-0.12, 0.12)
            length = plant["h"] * rng.uniform(0.55, 1.05)
            width = plant["h"] * rng.uniform(0.055, 0.085)
            sway = math.sin(t * plant["speed"] + ph + i * 0.9) * plant["h"] * 0.03
            spine = []
            for k in range(6):
                r = k / 5.0
                spine.append(
                    (
                        bx + math.cos(ang) * length * r + sway * r * r,
                        by + math.sin(ang) * length * r + length * 0.10 * r * r,
                    )
                )
            _shaded_leaf(surf, spine, width, (22, 58, 34), (52, 104, 54))

    def _draw_kelp(self, surf: pygame.Surface, plant: dict) -> None:
        rng = random.Random(plant["seed"])
        bx, by = plant["x"], plant["y"]
        ph, t = plant["phase"], self.t
        for i in range(rng.randint(2, 4)):
            length = plant["h"] * rng.uniform(0.75, 1.10)
            sway = math.sin(t * plant["speed"] + ph + i * 1.3) * plant["h"] * 0.045
            lean = rng.uniform(-0.22, 0.22)
            spine = []
            steps = 8
            for k in range(steps + 1):
                r = k / steps
                spine.append((bx + lean * length * r + sway * (r ** 1.5), by - length * r))
            col = mix((10, 34, 38), (20, 54, 46), rng.random())
            _shaded_leaf(surf, spine, plant["h"] * rng.uniform(0.020, 0.040), mix(col, (6, 22, 26), 0.4), mix(col, (70, 120, 90), 0.35))

    def _draw_flora_layer(self, surf: pygame.Surface, layer: str) -> None:
        for plant in self.plants:
            if plant["layer"] != layer:
                continue
            kind = plant["kind"]
            if kind == "vallisneria":
                self._draw_vallisneria(surf, plant)
            elif kind == "sword":
                self._draw_sword(surf, plant)
            elif kind == "java_fern":
                self._draw_java_fern(surf, plant)
            elif kind == "kelp":
                self._draw_kelp(surf, plant)
            elif kind == "carpet":
                self._draw_carpet(surf, plant)
            elif kind == "stem":
                self._draw_stem(surf, plant)

    def _draw_stem(self, surf: pygame.Surface, plant: dict) -> None:
        rng = random.Random(plant["seed"])
        bx, by = plant["x"], plant["y"]
        ph, t = plant["phase"], self.t
        for i in range(rng.randint(3, 5)):
            ox = rng.uniform(-plant["h"] * 0.22, plant["h"] * 0.22)
            length = plant["h"] * rng.uniform(0.7, 1.0)
            sway = math.sin(t * plant["speed"] + ph + i * 1.1) * plant["h"] * 0.05
            pts = []
            steps = 8
            for k in range(steps + 1):
                r = k / steps
                pts.append((bx + ox + sway * (r ** 1.5) + math.sin(r * 3.0 + i) * plant["h"] * 0.03, by - length * r))
            pygame.draw.lines(surf, (52, 86, 44), False, pts, 2)
            for k in range(1, steps):
                r = k / steps
                lx, ly = pts[k]
                leaf_len = plant["h"] * 0.05 * (1.0 - r * 0.5)
                side = 1 if k % 2 else -1
                tip = (lx + leaf_len * 1.3, ly - leaf_len * 0.4)
                pygame.draw.polygon(
                    surf,
                    mix((70, 124, 62), (118, 88, 52), rng.random()),
                    [(lx, ly), (lx + leaf_len * side * 0.3, ly - leaf_len * 0.7), tip],
                )

    def _draw_carpet(self, surf: pygame.Surface, plant: dict) -> None:
        rng = random.Random(plant["seed"])
        bx, by = plant["x"], plant["y"]
        t = self.t
        for i in range(rng.randint(14, 22)):
            ox = rng.uniform(-plant["h"] * 0.7, plant["h"] * 0.7)
            length = plant["h"] * rng.uniform(0.45, 1.0)
            sway = math.sin(t * 1.6 + plant["phase"] + ox * 0.1) * length * 0.18
            tip = (bx + ox + sway, by - length)
            mid = (bx + ox + sway * 0.4, by - length * 0.55)
            pygame.draw.line(
                surf,
                mix((44, 104, 56), (86, 148, 76), rng.random()),
                (bx + ox, by),
                mid,
                max(1, int(plant["h"] * 0.045)),
            )
            pygame.draw.line(surf, mix((64, 126, 66), (110, 170, 84), rng.random()), mid, tip, max(1, int(plant["h"] * 0.032)))

    def _draw_sea_fans(self, surf: pygame.Surface) -> None:
        for sf in self.sea_fans:
            sx, sy = sf["x"], sf["y"]
            sz = sf["size"]
            col = sf["color"]
            fili = sf["filigree"]
            sway = math.sin(self.t * 0.7 + sf["phase"]) * 0.09 + sf["tilt"]
            stem_top = (sx + math.sin(sway) * (sz * 0.30), sy - math.cos(sway) * (sz * 0.30))
            pygame.draw.line(surf, (34, 22, 26), (sx, sy), stem_top, max(2, int(sz * 0.04)))
            for i in range(7):
                frac = i / 6.0
                ang = sway + (-0.7 + frac * 1.4)
                ln = sz * (0.72 + 0.28 * math.sin(frac * math.pi))
                tip = (stem_top[0] + math.sin(ang) * ln, stem_top[1] - math.cos(ang) * ln)
                mid = (stem_top[0] + math.sin(ang) * (ln * 0.55), stem_top[1] - math.cos(ang) * (ln * 0.55))
                pygame.draw.line(surf, col, stem_top, tip, max(1, int(sz * 0.022)))
                pygame.draw.line(surf, fili, mid, tip, 1)

    def _draw_anemones(self, surf: pygame.Surface) -> None:
        for a in self.anemones:
            ax, ay = a["x"], a["y"]
            bw, bh = a["base_w"], a["base_h"]
            col = a["color"]
            tip_col = a["tip_color"]
            base_rect = pygame.Rect(int(ax - bw * 0.5), int(ay - bh * 0.25), int(bw), int(bh))
            pygame.draw.ellipse(surf, mix(col, (24, 22, 26), 0.45), base_rect)
            pygame.draw.ellipse(surf, mix(col, (255, 255, 255), 0.20), base_rect.inflate(-int(bw * 0.35), -int(bh * 0.35)))
            for j in range(a["tentacles"]):
                frac = j / max(1, a["tentacles"] - 1)
                base_angle = -math.pi * 0.08 - frac * math.pi * 0.84
                wobble = math.sin(self.t * a["wiggle_speed"] + a["phase"] + j * 0.5) * 0.36
                current = math.sin(self.t * 0.7 + a["phase"]) * (a["length"] * 0.18)
                t_len = a["length"] * (0.85 + 0.30 * math.sin(frac * math.pi))
                ang = base_angle + wobble
                p0 = (ax + (frac - 0.5) * bw * 0.72, ay - bh * 0.1)
                p1 = (p0[0] + math.cos(ang) * (t_len * 0.35) + current * 0.25, p0[1] + math.sin(ang) * (t_len * 0.35))
                p2 = (p1[0] + math.cos(ang + wobble * 0.5) * (t_len * 0.4) + current * 0.6, p1[1] + math.sin(ang + wobble * 0.5) * (t_len * 0.4))
                p3 = (p2[0] + math.cos(ang + wobble * 0.9) * (t_len * 0.35) + current * 0.95, p2[1] + math.sin(ang + wobble * 0.9) * (t_len * 0.35))
                pygame.draw.line(surf, mix(col, (16, 22, 30), 0.25), p0, p1, 6)
                pygame.draw.line(surf, col, p1, p2, 4)
                pygame.draw.line(surf, mix(col, tip_col, 0.45), p2, p3, 2)
                pygame.draw.circle(surf, mix(col, tip_col, 0.75), (int(p3[0]), int(p3[1])), 3)

    # ------------------------------------------------------------------ #
    # Overlay: frame, glass, waterline
    # ------------------------------------------------------------------ #
    def _build_water_tint(self) -> None:
        w, h = self.w, self.h
        tint = pygame.Surface((w, h), pygame.SRCALPHA)
        col = pygame.Surface((1, h), pygame.SRCALPHA)
        night = getattr(self, "night", False)
        for y in range(h):
            t = y / max(1, h - 1)
            if night:
                col.set_at((0, y), (4, 18, 34, int(26 + 58 * t)))
            else:
                col.set_at((0, y), (8, 34, 52, int(10 + 28 * t)))
        tint.blit(pygame.transform.scale(col, (w, h)), (0, 0))
        self.water_tint = tint

    def _build_foreground(self) -> None:
        w, h = self.w, self.h
        sw, sh = max(2, w // 3), max(2, h // 3)
        soft = pygame.Surface((sw, sh), pygame.SRCALPHA)
        rng = random.Random(4242)
        for side in (-1, 1):
            bx = 0 if side < 0 else sw
            base_y = sh + 8
            height = rng.uniform(sh * 0.22, sh * 0.34)
            for blade in range(5):
                lean = rng.uniform(-0.4, 0.4) + side * 0.25
                width = rng.uniform(10, 22)
                pts = []
                for i in range(10):
                    tt = i / 9.0
                    pts.append(
                        (
                            bx + (side * (0.02 * sw + blade * 0.03 * sw)) + lean * height * tt * 0.6
                            + math.sin(tt * 3.0 + blade) * 14,
                            base_y - height * tt,
                        )
                    )
                pygame.draw.lines(soft, (6, 24, 28, 150), False, pts, max(2, int(width)))
        soft = pygame.transform.smoothscale(soft, (w, h))
        self.foreground_blur = soft

    def _build_overlay(self) -> None:
        w, h = self.w, self.h
        rim_t, rim_b, rim_s = self.rim["top"], self.rim["bottom"], self.rim["side"]
        wl = self.waterline
        ov = pygame.Surface((w, h), pygame.SRCALPHA)

        air = _vertical_gradient(w, max(1, wl - rim_t), [(0.0, (16, 24, 30)), (1.0, (8, 16, 24))])
        ov.blit(air, (0, rim_t))
        cover = pygame.Surface((w, max(1, wl - rim_t)), pygame.SRCALPHA)
        pygame.draw.line(cover, (120, 170, 185, 70), (0, 8), (w, 8), 2)
        pygame.draw.line(cover, (70, 115, 135, 40), (0, 14), (w, 14), 1)
        pygame.draw.line(cover, (40, 76, 96, 55), (0, max(1, wl - rim_t - 3)), (w, max(1, wl - rim_t - 3)), 2)
        ov.blit(cover, (0, rim_t))

        def metal_band(rect: pygame.Rect, vertical: bool) -> None:
            steps = max(1, rect.w if vertical else rect.h)
            for i in range(steps):
                t = i / max(1, steps - 1)
                base = mix((66, 70, 74), (26, 28, 32), abs(t - 0.45) * 1.7)
                if vertical:
                    pygame.draw.line(ov, base, (rect.x + i, rect.y), (rect.x + i, rect.y + rect.h))
                else:
                    pygame.draw.line(ov, base, (rect.x, rect.y + i), (rect.x + rect.w, rect.y + i))
            pygame.draw.rect(ov, (12, 13, 15), rect, 2)

        metal_band(pygame.Rect(0, 0, w, rim_t), False)
        metal_band(pygame.Rect(0, h - rim_b, w, rim_b), False)
        metal_band(pygame.Rect(0, 0, rim_s, h), True)
        metal_band(pygame.Rect(w - rim_s, 0, rim_s, h), True)
        lip = max(2, rim_s // 3)
        pygame.draw.rect(ov, (8, 10, 12), (rim_s, rim_t, w - rim_s * 2, lip))
        pygame.draw.rect(ov, (8, 10, 12), (rim_s, h - rim_b - lip, w - rim_s * 2, lip))
        pygame.draw.rect(ov, (8, 10, 12), (rim_s, rim_t, lip, h - rim_t - rim_b))
        pygame.draw.rect(ov, (8, 10, 12), (w - rim_s - lip, rim_t, lip, h - rim_t - rim_b))
        pygame.draw.line(ov, (130, 170, 178, 110), (rim_s + lip, rim_t + lip + 1), (w - rim_s - lip, rim_t + lip + 1), 1)

        meniscus = pygame.Surface((w, 6), pygame.SRCALPHA)
        for x in range(w):
            a = int(90 + 55 * math.sin(x * 0.021) + 30 * math.cos(x * 0.061))
            meniscus.set_at((x, 0), (196, 240, 238, max(20, min(180, a))))
        ov.blit(meniscus, (0, wl - 2))

        glass = pygame.Surface((w, h), pygame.SRCALPHA)
        for i in range(6):
            x0 = int(w * (0.10 + i * 0.16))
            width = max(6, int(w * (0.020 + 0.012 * (i % 3))))
            for k in range(width):
                a = int(9 + 6 * math.sin((k / width) * math.pi))
                pygame.draw.line(glass, (190, 230, 236, a), (x0 + k, rim_t), (x0 + k + int(w * 0.05), h - rim_b))
        for cx, cy, rx, ry, a in (
            (w * 0.16, h * 0.24, w * 0.10, h * 0.035, 9),
            (w * 0.72, h * 0.14, w * 0.08, h * 0.030, 7),
            (w * 0.86, h * 0.62, w * 0.09, h * 0.070, 6),
        ):
            pygame.draw.ellipse(glass, (205, 235, 240, a), (cx - rx, cy - ry, rx * 2, ry * 2))
        if getattr(self, "night", False):
            moon = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.ellipse(
                moon,
                (120, 175, 215, 26),
                (w * 0.20, self.waterline - h * 0.10, w * 0.60, h * 0.34),
            )
            pygame.draw.ellipse(
                moon,
                (150, 205, 235, 18),
                (w * 0.34, self.waterline - h * 0.06, w * 0.32, h * 0.20),
            )
            ov.blit(moon, (0, 0))
        ov.blit(glass, (0, 0))
        ov.blit(_alpha_vignette(w, h, 195 if getattr(self, "night", False) else 150), (0, 0))
        self.overlay = ov

    # ------------------------------------------------------------------ #
    # Fish / particles
    # ------------------------------------------------------------------ #
    def _spawn_fish(self) -> None:
        w, h = self.w, self.h
        self.fish = []
        n_fish = max(8, min(18, w // 110))
        for i in range(n_fish):
            body, accent, pattern = self.rng.choice(SPECIES)
            length = self.rng.uniform(h * 0.14, h * 0.23)
            species_id = i % 4
            depth = self.rng.uniform(0.65, 1.0)
            self.fish.append(
                {
                    "x": self.rng.uniform(0, w),
                    "y": self.rng.uniform(h * 0.08, h * 0.72),
                    "v": self.rng.uniform(35, 95) * self.rng.choice((-1, 1)),
                    "len": length,
                    "species": species_id,
                    "body": body,
                    "accent": accent,
                    "pattern": pattern,
                    "phase": self.rng.uniform(0, math.tau),
                    "wag": self.rng.uniform(3.0, 5.5),
                    "depth": depth,
                    "fright": 0.0,
                    "fright_vx": 0.0,
                    "fright_vy": 0.0,
                }
            )

    def _spawn_bubbles(self) -> None:
        w, h = self.w, self.h
        base = self.seabed_y
        self.aerators = [
            {"x": w * 0.665, "y": base + h * 0.060, "w": max(18, int(w * 0.010)), "h": max(7, int(h * 0.010))},
            {"x": w * 0.775, "y": base + h * 0.085, "w": max(16, int(w * 0.009)), "h": max(6, int(h * 0.009))},
        ]
        for aero in self.aerators:
            ax, ay, aw, ah = aero["x"], aero["y"], aero["w"], aero["h"]
            pygame.draw.ellipse(self.seabed_surf, (24, 22, 20), (ax - aw * 0.55, ay + ah * 0.2, aw * 1.1, ah * 0.6))
            pygame.draw.rect(self.seabed_surf, (46, 46, 44), (ax - aw * 0.5, ay - ah * 0.5, aw, ah), border_radius=3)
            pygame.draw.rect(self.seabed_surf, (74, 74, 72), (ax - aw * 0.44, ay - ah * 0.44, aw * 0.88, ah * 0.34), border_radius=2)
        self.bubbles = []
        for _ in range(38):
            aero = self.rng.choice(self.aerators)
            self.bubbles.append(
                {
                    "x": aero["x"] + self.rng.uniform(-aero["w"] * 0.35, aero["w"] * 0.35),
                    "y": self.rng.uniform(self.waterline, aero["y"]),
                    "origin_x": aero["x"],
                    "origin_y": aero["y"] - aero["h"] * 0.4,
                    "r": self.rng.uniform(2.0, 7.5),
                    "v": self.rng.uniform(45, 100),
                    "wobble_freq": self.rng.uniform(2.2, 4.0),
                    "wobble_amp": self.rng.uniform(10, 22),
                    "phase": self.rng.uniform(0, math.tau),
                }
            )

    def _spawn_marine_snow(self) -> None:
        self.marine_snow = []
        for _ in range(110):
            self.marine_snow.append(
                {
                    "x": self.rng.uniform(0, self.w),
                    "y": self.rng.uniform(self.waterline, self.h * 0.90),
                    "r": self.rng.choice([1, 1, 1.5, 2]),
                    "vx": self.rng.uniform(-5, 5),
                    "vy": self.rng.uniform(8, 22),
                    "twinkle_speed": self.rng.uniform(1.8, 3.8),
                    "phase": self.rng.uniform(0, math.tau),
                }
            )

    # ------------------------------------------------------------------ #
    # Simulation / drawing
    # ------------------------------------------------------------------ #
    def step(self, dt: float) -> None:
        speed_scale = 0.62 if getattr(self, "night", False) else 1.0
        for f in self.fish:
            fright = f.get("fright", 0.0)
            if fright > 0.0:
                f["x"] += f.get("fright_vx", 0.0) * dt
                f["y"] += f.get("fright_vy", 0.0) * dt
                f["fright"] = max(0.0, fright - dt)
                f["phase"] += dt * f["wag"] * 2.2
                top = self.waterline + f["len"] * 0.25
                bottom = self.seabed_y - f["len"] * 0.40
                f["y"] = min(bottom, max(top, f["y"]))
                f["x"] = min(self.w + f["len"] * 1.5, max(-f["len"] * 1.5, f["x"]))
                continue
            f["x"] += f["v"] * dt * speed_scale
            f["phase"] += dt * f["wag"] * speed_scale
            pad = f["len"] * 1.5
            if f["v"] > 0 and f["x"] > self.w + pad:
                f["x"] = -pad
                f["y"] = self.rng.uniform(self.h * 0.08, self.h * 0.72)
            elif f["v"] < 0 and f["x"] < -pad:
                f["x"] = self.w + pad
                f["y"] = self.rng.uniform(self.h * 0.08, self.h * 0.72)

        for b in self.bubbles:
            b["y"] -= b["v"] * dt
            b["x"] += math.sin(self.t * b["wobble_freq"] + b["phase"]) * b["wobble_amp"] * dt
            if b["y"] < self.waterline - 20:
                aero = self.rng.choice(self.aerators)
                b["origin_x"] = aero["x"]
                b["origin_y"] = aero["y"] - aero["h"] * 0.4
                b["x"] = b["origin_x"] + self.rng.uniform(-aero["w"] * 0.35, aero["w"] * 0.35)
                b["y"] = b["origin_y"]

        for sn in self.marine_snow:
            current = math.sin(self.t * 0.65 + sn["y"] * 0.006) * 10
            sn["x"] += (sn["vx"] + current) * dt
            sn["y"] += sn["vy"] * dt
            if sn["x"] < -10:
                sn["x"] = self.w + 10
            elif sn["x"] > self.w + 10:
                sn["x"] = -10
            if sn["y"] > self.h * 0.93:
                sn["y"] = self.waterline
                sn["x"] = self.rng.uniform(0, self.w)

    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self.water_bg, (0, 0))
        self._draw_rays(surf)
        surf.blit(self.backdrop, (0, 0))
        self._draw_flora_layer(surf, "back")
        surf.blit(self.seabed_surf, (0, 0))
        caust_idx = int(self.t / self.caust_duration * self.n_caust_frames) % self.n_caust_frames
        surf.blit(
            self.caustic_frames[caust_idx],
            (0, self.h - self.caust_target_h),
            special_flags=pygame.BLEND_ADD,
        )
        self._draw_flora_layer(surf, "mid")
        self._draw_flora_layer(surf, "front")
        surf.blit(self.water_tint, (0, 0))
        for f in sorted(self.fish, key=lambda f: f["depth"]):
            self._draw_fish(surf, f)
        self._draw_bubbles(surf)
        self._draw_marine_snow(surf)
        self._draw_surface(surf)
        self._draw_ripples(surf)
        surf.blit(self.foreground_blur, (0, 0))
        surf.blit(self.overlay, (0, 0))

    def _draw_rays(self, surf: pygame.Surface) -> None:
        buf = self.god_rays_buf
        buf.fill((0, 0, 0))
        rw, rh = self.rw, self.rh
        wl_ratio = self.waterline / max(1, self.h)
        for r in self.god_rays_config:
            sway = math.sin(self.t * r["speed"] + r["phase"]) * (rw * 0.045)
            pulse = 0.75 + 0.25 * math.sin(self.t * (r["speed"] * 1.5) + r["phase"] * 1.7)
            top_x = r["x"] * rw + sway
            angle = r["angle"] + math.cos(self.t * (r["speed"] * 0.8) + r["phase"]) * 0.02
            bot_x = top_x + math.tan(angle) * rh
            w0, w1 = r["w0"] // 2, r["w1"] // 2
            inten = int(r["intensity"] * pulse * self.ray_strength)
            pygame.draw.polygon(
                buf,
                (int(inten * 0.6), int(inten * 0.88), inten),
                [(top_x - w0, wl_ratio * rh), (top_x + w0, wl_ratio * rh), (bot_x + w1, rh), (bot_x - w1, rh)],
            )
            pygame.draw.polygon(
                buf,
                (int(inten * 0.8), int(inten * 1.1), int(inten * 1.25)),
                [
                    (top_x - w0 * 0.45, wl_ratio * rh),
                    (top_x + w0 * 0.45, wl_ratio * rh),
                    (bot_x + w1 * 0.45, rh * 0.9),
                    (bot_x - w1 * 0.45, rh * 0.9),
                ],
            )
        buf.blit(self.ray_fade, (0, 0), special_flags=pygame.BLEND_MULT)
        surf.blit(pygame.transform.smoothscale(buf, (self.w, self.h)), (0, 0), special_flags=pygame.BLEND_ADD)

    def _draw_surface(self, surf: pygame.Surface) -> None:
        w, wl = self.w, self.waterline
        for i, color in enumerate(((150, 220, 226), (92, 172, 190), (58, 126, 148))):
            pts = []
            for x in range(0, w + 8, max(8, w // 220)):
                y = wl + 2 + i * 3 + math.sin(x * 0.020 + self.t * 1.4 + i * 1.7) * (3 - i)
                pts.append((x, y))
            pygame.draw.lines(surf, color, False, pts, 1)
        for j in range(18):
            gx = (j * 0.173 + self.t * 0.012) % 1.0 * w
            gy = wl + 2 + math.sin(self.t * 1.7 + j) * 2
            pygame.draw.circle(surf, (190, 240, 240), (int(gx), int(gy)), 1)

    def tap(self, x: float, y: float) -> None:
        """Tap on the glass: expanding ripple and a startled school."""
        self.ripples.append({"x": float(x), "y": float(y), "born": self.t, "life": 1.8})
        radius = max(self.w, self.h) * 0.34
        for f in self.fish:
            dx = f["x"] - x
            dy = f["y"] - y
            dist = math.hypot(dx, dy)
            if dist > radius:
                continue
            nx = dx / max(1.0, dist)
            ny = dy / max(1.0, dist)
            f["fright"] = 1.15
            f["fright_vx"] = nx * (210 + 90 * self.rng.random())
            f["fright_vy"] = ny * (150 + 70 * self.rng.random())
        if len(self.bubbles) > 70:
            self.bubbles = self.bubbles[-70:]
        for _ in range(10):
            self.bubbles.append(
                {
                    "x": x + self.rng.uniform(-18, 18),
                    "y": y + self.rng.uniform(-10, 10),
                    "origin_x": x,
                    "origin_y": y,
                    "r": self.rng.uniform(1.5, 4.5),
                    "v": self.rng.uniform(60, 120),
                    "wobble_freq": self.rng.uniform(2.0, 4.0),
                    "wobble_amp": self.rng.uniform(8, 16),
                    "phase": self.rng.uniform(0, math.tau),
                }
            )

    def _draw_ripples(self, surf: pygame.Surface) -> None:
        if not self.ripples:
            return
        keep: list[dict] = []
        for r in self.ripples:
            age = self.t - r["born"]
            if age > r["life"]:
                continue
            keep.append(r)
            prog = max(0.0, min(1.0, age / r["life"]))
            base = max(self.w, self.h) * 0.32
            for k in range(3):
                radius = int(base * prog + k * max(6, self.h * 0.012))
                if radius <= 0:
                    continue
                fade = int(170 * (1.0 - prog) * (1.0 - k * 0.22))
                if fade <= 2:
                    continue
                color = mix((70, 110, 130), (215, 245, 255), 1.0 - prog)
                pygame.draw.circle(surf, color, (int(r["x"]), int(r["y"])), radius, 1)
            if prog < 0.16:
                shine = pygame.Surface((80, 80), pygame.SRCALPHA)
                pygame.draw.circle(shine, (220, 250, 255, 60), (40, 40), 26)
                surf.blit(shine, (int(r["x"]) - 40, int(r["y"]) - 40))
        self.ripples = keep

    def _draw_fish(self, surf: pygame.Surface, fish: dict) -> None:
        x, y = fish["x"], fish["y"]
        length = int(fish["len"])
        moving_right = fish["v"] >= 0
        frames = get_fish_frames(fish.get("species", 0), length, flip_x=moving_right)
        sprite = None
        if frames:
            index = int(fish["phase"] / math.tau * len(frames)) % len(frames)
            sprite = frames[index]
        if sprite is not None:
            bob = math.sin(fish["phase"]) * 4.0
            pitch = math.cos(fish["phase"]) * (3.5 if moving_right else -3.5)
            if abs(pitch) > 0.5:
                rotated = pygame.transform.rotate(sprite, pitch)
                surf.blit(rotated, rotated.get_rect(center=(int(x), int(y + bob))))
            else:
                surf.blit(sprite, sprite.get_rect(center=(int(x), int(y + bob))))
            return

        sign = 1 if moving_right else -1
        wag = math.sin(fish["phase"]) * length * 0.16
        body = pygame.Rect(0, 0, int(length), int(length * 0.46))
        body.center = (int(x), int(y))
        pygame.draw.ellipse(surf, fish["body"], body)
        belly = body.inflate(-int(length * 0.25), -int(length * 0.16))
        belly.y += int(length * 0.05)
        pygame.draw.ellipse(surf, mix(fish["body"], (255, 255, 255), 0.28), belly)
        tail = [
            (x - sign * length * 0.32, y),
            (x - sign * length * 0.58, y - length * 0.16 + wag),
            (x - sign * length * 0.58, y + length * 0.16 + wag),
        ]
        pygame.draw.polygon(surf, fish["body"], tail)

    def _draw_bubbles(self, surf: pygame.Surface) -> None:
        for b in self.bubbles:
            bx, by = int(b["x"]), int(b["y"])
            expansion = 1.0 + (1.0 - max(0.0, by / self.h)) * 0.20
            br = max(2, int(b["r"] * expansion))
            bw, bh = int(br * 1.15), int(br * 0.90)
            bubble = pygame.Surface((bw * 2 + 6, bh * 2 + 6), pygame.SRCALPHA)
            center = (bw + 3, bh + 3)
            pygame.draw.ellipse(bubble, (190, 235, 255, 40), (center[0] - bw, center[1] - bh, bw * 2, bh * 2))
            pygame.draw.ellipse(bubble, (215, 248, 255, 170), (center[0] - bw, center[1] - bh, bw * 2, bh * 2), 1)
            pygame.draw.ellipse(
                bubble,
                (255, 255, 255, 235),
                (center[0] - bw * 0.65, center[1] - bh * 0.65, max(1, bw // 3), max(1, bh // 3)),
            )
            pygame.draw.ellipse(
                bubble,
                (180, 225, 255, 100),
                (center[0] + bw * 0.25, center[1] + bh * 0.25, max(1, bw // 4), max(1, bh // 4)),
            )
            surf.blit(bubble, (bx - bw - 3, by - bh - 3))

    def _draw_marine_snow(self, surf: pygame.Surface) -> None:
        for sn in self.marine_snow:
            sx, sy = sn["x"], sn["y"]
            if sy < self.waterline or sy > self.h:
                continue
            twinkle = 0.5 + 0.5 * math.sin(self.t * sn["twinkle_speed"] + sn["phase"])
            pygame.draw.circle(surf, (168, 214, 220), (int(sx), int(sy)), max(1, int(sn["r"])))
            if twinkle > 0.75:
                pygame.draw.circle(surf, (220, 246, 246), (int(sx), int(sy)), 1)
