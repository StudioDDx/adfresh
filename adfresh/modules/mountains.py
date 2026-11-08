"""Dusk ridges scrolling in parallax, with one cabin light.

Twinkling stars, a haloed moon, two cloud wisps on their own drift, and a
cabin whose chimney breathes smoke into the cold air.
"""

from __future__ import annotations

import math

import pygame

from adfresh.drawutil import additive_orb, radial, vertical_gradient
from adfresh.modules.base import Module

SMOKE_PUFFS = 7


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
        self.stars = [
            (
                (i * 97) % w,
                (i * 53) % int(h * 0.45),
                self.rng.uniform(0.6, 2.2),  # twinkle speed
                self.rng.uniform(0, math.tau),  # twinkle phase
                self.rng.uniform(0.6, 1.0),  # base brightness
            )
            for i in range(70)
        ]
        self.moon_halo = radial(int(min(w, h) * 0.45), (210, 190, 190), 70)
        self.clouds = [
            {"y": h * 0.2, "speed": 6.0, "width": w * 0.5, "height": h * 0.045, "alpha": 26, "offset": self.rng.uniform(0, w)},
            {"y": h * 0.32, "speed": -4.0, "width": w * 0.62, "height": h * 0.06, "alpha": 20, "offset": self.rng.uniform(0, w)},
        ]

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

    def _draw_cloud(self, surf: pygame.Surface, cloud: dict) -> None:
        span = self.w + cloud["width"] * 2
        x = (cloud["offset"] + self.t * cloud["speed"]) % span - cloud["width"]
        wisp = pygame.Surface((int(cloud["width"]), int(cloud["height"])), pygame.SRCALPHA)
        cw, ch = wisp.get_size()
        for i in range(3):
            inset = i * cw * 0.12
            alpha = cloud["alpha"] - i * 7
            if alpha <= 0:
                break
            pygame.draw.ellipse(
                wisp,
                (190, 170, 180, alpha),
                (inset, ch * 0.15 * i, cw - inset * 2, ch * (1 - 0.2 * i)),
            )
        surf.blit(wisp, (int(x), int(cloud["y"])))

    def _draw_smoke(self, surf: pygame.Surface, chimney_x: float, chimney_y: float) -> None:
        for i in range(SMOKE_PUFFS):
            age = (self.t * 0.22 + i / SMOKE_PUFFS) % 1.0
            px = chimney_x + math.sin(self.t * 0.8 + i * 1.7) * 8 * age + age * 14
            py = chimney_y - age * self.h * 0.16
            size = 3 + age * 12
            alpha = int(70 * (1 - age) ** 1.5)
            if alpha <= 2:
                continue
            puff = pygame.Surface((int(size * 2), int(size * 2)), pygame.SRCALPHA)
            pygame.draw.circle(puff, (150, 150, 160, alpha), (int(size), int(size)), int(size))
            surf.blit(puff, (int(px - size), int(py - size)))

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
        for x, y, speed, phase, base in self.stars:
            level = int(base * (120 + 110 * (0.5 + 0.5 * math.sin(self.t * speed + phase))))
            surf.set_at((int(x), int(y)), (level, level, min(255, level + 10)))
        mx, my, mr = int(self.w * 0.72), int(self.h * 0.22), int(min(self.w, self.h) * 0.06)
        halo = self.moon_halo
        surf.blit(halo, (mx - halo.get_width() // 2, my - halo.get_height() // 2))
        pygame.draw.circle(surf, (255, 236, 214), (mx, my), mr)
        pygame.draw.circle(surf, (255, 214, 186), (mx + 6, my + 4), int(mr * 0.72))
        for cloud in self.clouds:
            self._draw_cloud(surf, cloud)
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
        # Chimney and its smoke.
        pygame.draw.rect(surf, (30, 18, 16), (self.cabin_x + 13, cy - 25, 4, 9))
        self._draw_smoke(surf, self.cabin_x + 15, cy - 25)
        glow = (255, 186, 90) if int(self.t * 2) % 5 else (255, 150, 60)
        pygame.draw.rect(surf, glow, (self.cabin_x + 4, cy - 11, 5, 5))
        # Warm spill on the snow in front of the window.
        spill = additive_orb(30, (90, 55, 22))
        surf.blit(spill, (int(self.cabin_x + 6 - 13), int(cy - 8 - 13)), special_flags=pygame.BLEND_RGB_ADD)
