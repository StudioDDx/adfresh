"""Aurora: charged curtains of light over a subarctic ridge.

Each curtain is an emissive field evaluated on a coarse grid with numpy and
upscaled, so the ribbons stay silky at any resolution. Everything is a pure
function of ``self.t`` and the seeded rng, so every monitor in a spanned
layout renders the same sky.
"""

from __future__ import annotations

import math

import numpy as np
import pygame

from adfresh.drawutil import radial, vertical_gradient
from adfresh.modules.base import Module

FIELD_W = 192  # coarse emission grid; upscaled to the canvas
FIELD_H = 96

CURTAINS = (
    # base height, two sine bands, fold frequency, hue pair, falloff
    {"base": 0.30, "a1": 0.11, "k1": 2.1, "w1": 0.21, "a2": 0.05, "k2": 5.3, "w2": -0.34,
     "fold": 7.0, "fall": 0.16, "top": (110, 255, 170), "low": (60, 90, 255), "gain": 1.0},
    {"base": 0.42, "a1": 0.09, "k1": 1.6, "w1": -0.16, "a2": 0.06, "k2": 4.1, "w2": 0.27,
     "fold": 9.0, "fall": 0.13, "top": (170, 255, 150), "low": (170, 70, 255), "gain": 0.75},
    {"base": 0.22, "a1": 0.07, "k1": 2.8, "w1": 0.12, "a2": 0.04, "k2": 6.4, "w2": 0.19,
     "fold": 5.0, "fall": 0.10, "top": (90, 210, 255), "low": (120, 60, 230), "gain": 0.5},
)


class Aurora(Module):
    id = "aurora"
    title = "Aurora"

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        self.stars = [
            (
                self.rng.uniform(0, w),
                self.rng.uniform(0, h * 0.55),
                self.rng.uniform(0.5, 1.6),
                self.rng.uniform(1.2, 3.2),
                self.rng.uniform(0, math.tau),
            )
            for _ in range(max(60, w // 14))
        ]
        self.moon_glow = radial(int(min(w, h) * 0.5), (150, 170, 220), 110)
        # Precompute the coarse grid axes.
        self.gx = np.linspace(0.0, 1.0, FIELD_W, dtype=np.float32)[:, None]
        self.gy = np.linspace(0.0, 1.0, FIELD_H, dtype=np.float32)[None, :]
        self.sky = vertical_gradient(
            w, h, [(0.0, (2, 6, 14)), (0.55, (6, 14, 26)), (1.0, (10, 18, 30))]
        )

    def _field(self) -> np.ndarray:
        """Emission field, shape (FIELD_W, FIELD_H, 3), float in [0, 255]."""
        out = np.zeros((FIELD_W, FIELD_H, 3), dtype=np.float32)
        for c in CURTAINS:
            top = (
                c["base"]
                + c["a1"] * np.sin(self.gx * math.tau * c["k1"] + self.t * c["w1"] * math.tau)
                + c["a2"] * np.sin(self.gx * math.tau * c["k2"] + self.t * c["w2"] * math.tau)
            )
            depth = (self.gy - top) / c["fall"]
            glow = np.exp(-np.maximum(depth, 0.0)) * (depth >= 0.0)
            folds = 0.55 + 0.45 * np.sin(
                self.gx * math.tau * c["fold"] + self.t * 0.5 + depth * 1.5
            )
            energy = np.clip(glow * folds, 0.0, 1.0) ** 1.4 * c["gain"]
            blend = np.clip(depth * 0.9, 0.0, 1.0)  # 0 at the hot lip, 1 deep in the fall
            for ch in range(3):
                color = c["top"][ch] + (c["low"][ch] - c["top"][ch]) * blend
                out[:, :, ch] += energy * color
        return np.clip(out, 0.0, 255.0).astype(np.uint8)

    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self.sky, (0, 0))
        for x, y, size, speed, phase in self.stars:
            twinkle = 0.55 + 0.45 * math.sin(self.t * speed + phase)
            level = int(120 + 135 * twinkle)
            surf.set_at((int(x), int(y)), (level, level, min(255, level + 12)))
            if size > 1.2 and twinkle > 0.85:
                surf.set_at((int(x) + 1, int(y)), (level // 2, level // 2, level // 2))
        mx, my = int(self.w * 0.8), int(self.h * 0.16)
        glow = self.moon_glow
        surf.blit(glow, (mx - glow.get_width() // 2, my - glow.get_height() // 2))
        pygame.draw.circle(surf, (238, 240, 244), (mx, my), int(min(self.w, self.h) * 0.035))

        field = self._field()
        image = pygame.Surface((FIELD_W, FIELD_H))
        pygame.surfarray.blit_array(image, field)
        image = pygame.transform.smoothscale(image, (self.w, self.h))
        surf.blit(image, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

        # Treeline silhouette anchors the horizon.
        pts = [(0, self.h)]
        x = 0
        while x <= self.w:
            n = math.sin(x * 0.006 + 2.0) * 0.5 + math.sin(x * 0.021 + 0.7) * 0.35
            y = self.h * (0.9 + n * 0.035)
            pts.append((x, y))
            x += 8
        pts.append((self.w, self.h))
        pygame.draw.polygon(surf, (3, 8, 10), pts)
