"""Dusk ridges scrolling in parallax, with one cabin light."""

from __future__ import annotations

import math

import pygame

from adfresh.drawutil import vertical_gradient
from adfresh.modules.base import Module


class Mountains(Module):
    id = "mountains"
    title = "Mountains"

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        self.layers = [
            {"base": h * 0.58, "amp": h * 0.16, "seed": 1.2, "speed": 8, "color": (28, 36, 64)},
            {"base": h * 0.68, "amp": h * 0.18, "seed": 2.4, "speed": 16, "color": (18, 24, 44)},
            {"base": h * 0.78, "amp": h * 0.16, "seed": 4.1, "speed": 28, "color": (10, 12, 22)},
        ]
        self.cabin_x = w * 0.35

    def _y(self, x: float, layer: dict) -> float:
        seed = layer["seed"]
        n = math.sin(x * 0.0042 + seed) * 0.55
        n += math.sin(x * 0.011 + seed * 1.7) * 0.3
        n += math.sin(x * 0.023 + seed * 0.3) * 0.15
        return layer["base"] - (n * 0.5 + 0.5) * layer["amp"]

    def _ridge(self, layer: dict, shift: float) -> list[tuple[float, float]]:
        step = 10
        pts = [(-20, self.h + 4)]
        x = -20
        while x <= self.w + 20:
            pts.append((x, self._y(x + shift, layer)))
            x += step
        pts.append((self.w + 20, self.h + 4))
        return pts

    def step(self, dt: float) -> None:
        self.cabin_x -= 28 * dt
        if self.cabin_x < -40:
            self.cabin_x = self.w + 40

    def draw(self, surf: pygame.Surface) -> None:
        sky = vertical_gradient(
            self.w,
            self.h,
            [
                (0.0, (8, 10, 24)),
                (0.45, (28, 36, 72)),
                (0.72, (186, 104, 78)),
                (0.86, (232, 168, 110)),
                (1.0, (86, 64, 72)),
            ],
        )
        surf.blit(sky, (0, 0))
        mx, my, mr = int(self.w * 0.72), int(self.h * 0.22), int(min(self.w, self.h) * 0.06)
        pygame.draw.circle(surf, (255, 236, 214), (mx, my), mr)
        pygame.draw.circle(surf, (255, 214, 186), (mx + 6, my + 4), int(mr * 0.72))
        for i in range(40):
            x = (i * 97) % self.w
            y = (i * 53) % int(self.h * 0.45)
            surf.set_at((x, y), (230, 230, 240))
        for layer in self.layers:
            shift = self.t * layer["speed"]
            pygame.draw.polygon(surf, layer["color"], self._ridge(layer, shift))
        # Cabin rides the front layer.
        cy = self._y(self.cabin_x + self.t * self.layers[-1]["speed"], self.layers[-1])
        pygame.draw.rect(surf, (24, 16, 14), (self.cabin_x, cy - 16, 18, 14))
        pygame.draw.polygon(
            surf,
            (40, 22, 18),
            [(self.cabin_x - 2, cy - 16), (self.cabin_x + 9, cy - 24), (self.cabin_x + 20, cy - 16)],
        )
        glow = (255, 186, 90) if int(self.t * 2) % 5 else (255, 150, 60)
        pygame.draw.rect(surf, glow, (self.cabin_x + 4, cy - 11, 5, 5))
