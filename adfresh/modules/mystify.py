"""Mystify: ribbon polygons tumbling through the dark, trailing afterimages.

A nod to the classic After Dark module. Vertices bounce off the frame at
their own velocities; the trail is a fixed-length history of snapshots kept
by ``step`` so the whole scene is deterministic from the seed and ``self.t``.
"""

from __future__ import annotations

import math

import pygame

from adfresh.drawutil import additive_orb, mix, vignette
from adfresh.modules.base import Module

TRAIL = 26  # snapshots kept per ribbon
RIBBONS = (
    {"vertices": 5, "speed": 150.0, "hue": 0.0, "spin": 0.021},
    {"vertices": 4, "speed": 190.0, "hue": 0.46, "spin": -0.017},
    {"vertices": 6, "speed": 115.0, "hue": 0.78, "spin": 0.013},
)


class Ribbon:
    """One polygon: corner positions, velocities, and a snapshot history."""

    def __init__(self, rng, w: int, h: int, count: int, speed: float) -> None:
        self.pts: list[list[float]] = []
        for _ in range(count):
            angle = rng.uniform(0, math.tau)
            pace = rng.uniform(0.6, 1.0) * speed
            self.pts.append(
                [
                    rng.uniform(0, w),
                    rng.uniform(0, h),
                    math.cos(angle) * pace,
                    math.sin(angle) * pace,
                ]
            )
        self.history: list[list[tuple[float, float]]] = []

    def advance(self, dt: float, w: int, h: int) -> None:
        for p in self.pts:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            if p[0] < 0:
                p[0] = -p[0]
                p[2] = -p[2]
            elif p[0] > w:
                p[0] = 2 * w - p[0]
                p[2] = -p[2]
            if p[1] < 0:
                p[1] = -p[1]
                p[3] = -p[3]
            elif p[1] > h:
                p[1] = 2 * h - p[1]
                p[3] = -p[3]
        self.history.append([(p[0], p[1]) for p in self.pts])
        if len(self.history) > TRAIL:
            self.history.pop(0)


def hue_color(hue: float) -> tuple[int, int, int]:
    """Saturated color for ``hue`` in [0, 1), without importing colorsys."""
    h = (hue % 1.0) * 6.0
    seg = int(h) % 6
    frac = h - int(h)
    up = int(255 * frac)
    down = 255 - up
    table = (
        (255, up, 0),
        (down, 255, 0),
        (0, 255, up),
        (0, down, 255),
        (up, 0, 255),
        (255, 0, down),
    )
    return table[seg]


class Mystify(Module):
    id = "mystify"
    title = "Mystify"

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        scale = min(w, h) / 720.0
        self.ribbons: list[Ribbon] = []
        for spec in RIBBONS:
            self.ribbons.append(
                Ribbon(self.rng, w, h, spec["vertices"], spec["speed"] * scale)
            )
        self.glow = additive_orb(max(12, int(min(w, h) * 0.05)), (255, 255, 255))

    def step(self, dt: float) -> None:
        for ribbon in self.ribbons:
            ribbon.advance(dt, self.w, self.h)

    def _trail_color(self, hue: float, age: float) -> tuple[int, int, int]:
        base = hue_color(hue)
        return mix((0, 0, 0), base, age ** 1.6)

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill((2, 2, 6))
        # Trails are rendered at half resolution and upscaled: cheap and soft.
        tw, th = max(1, self.w // 2), max(1, self.h // 2)
        trail = pygame.Surface((tw, th))
        for spec, ribbon in zip(RIBBONS, self.ribbons):
            hue = spec["hue"] + self.t * spec["spin"]
            total = len(ribbon.history)
            for i, snapshot in enumerate(ribbon.history[:-1]):
                age = (i + 1) / max(1, total)
                color = self._trail_color(hue, age * 0.55)
                pts = [(x * 0.5, y * 0.5) for x, y in snapshot]
                pygame.draw.polygon(trail, color, pts, 1)
        trail = pygame.transform.smoothscale(trail, (self.w, self.h))
        surf.blit(trail, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

        # The leading polygon, crisp, with a hot core and vertex glows.
        for spec, ribbon in zip(RIBBONS, self.ribbons):
            hue = spec["hue"] + self.t * spec["spin"]
            color = hue_color(hue)
            pts = [(p[0], p[1]) for p in ribbon.pts]
            pygame.draw.polygon(surf, color, pts, 2)
            inner = [((x * 3 + self.w / 2) / 4, (y * 3 + self.h / 2) / 4) for x, y in pts]
            pygame.draw.polygon(surf, mix(color, (255, 255, 255), 0.55), inner, 1)
            for x, y in pts:
                glow = self.glow
                surf.blit(
                    glow,
                    (int(x - glow.get_width() / 2), int(y - glow.get_height() / 2)),
                    special_flags=pygame.BLEND_RGB_ADD,
                )
        surf.blit(vignette(self.w, self.h), (0, 0))
