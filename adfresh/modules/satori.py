"""Slow fields of color. Nothing to track, which is the point."""

from __future__ import annotations

import math

import pygame

from adfresh.drawutil import additive_orb
from adfresh.modules.base import Module

HUES = (
    (220, 90, 70),
    (230, 170, 70),
    (70, 180, 170),
    (150, 90, 210),
    (210, 100, 140),
    (80, 120, 220),
    (90, 190, 120),
)


class Satori(Module):
    id = "satori"
    title = "Satori"

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        self.orbs = []
        span = min(w, h)
        for i, color in enumerate(HUES):
            d = int(span * self.rng.uniform(0.45, 0.85))
            self.orbs.append(
                {
                    "sprite": additive_orb(d, color),
                    "ax": self.rng.uniform(0.15, 0.5),
                    "ay": self.rng.uniform(0.12, 0.4),
                    "sx": self.rng.uniform(0.08, 0.2),
                    "sy": self.rng.uniform(0.06, 0.18),
                    "px": self.rng.uniform(0, math.tau),
                    "py": self.rng.uniform(0, math.tau),
                }
            )

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill((6, 4, 12))
        for orb in self.orbs:
            sprite = orb["sprite"]
            x = self.w * (0.5 + math.sin(self.t * orb["sx"] + orb["px"]) * orb["ax"])
            y = self.h * (0.5 + math.cos(self.t * orb["sy"] + orb["py"]) * orb["ay"])
            surf.blit(
                sprite,
                (int(x - sprite.get_width() / 2), int(y - sprite.get_height() / 2)),
                special_flags=pygame.BLEND_RGB_ADD,
            )
