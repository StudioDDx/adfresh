"""Stars rushing out of a vanishing point with relativistic Doppler warp effects."""

from __future__ import annotations

import math
import random
import pygame

from adfresh.drawutil import radial
from adfresh.modules.base import Module


class Warp(Module):
    id = "warp"
    title = "Warp"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.stars: list[list[float]] = []
        self.particles: list[list[float]] = []
        self.base_speed = 0.58
        self.current_speed = 0.58
        self.scale = 1.0
        self.core_aura: pygame.Surface | None = None
        self.core_bloom: pygame.Surface | None = None
        self.core_center: pygame.Surface | None = None

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        dim = min(w, h)
        self.scale = dim * 0.74

        # Pre-bake radiant hyperspace vanishing core layers
        # 1. Outer deep sapphire cosmic aura
        aura_diam = int(dim * 0.82)
        self.core_aura = radial(aura_diam, (25, 55, 120), 85)

        # 2. Middle radiant hyperdrive cyan bloom
        bloom_diam = int(dim * 0.38)
        self.core_bloom = radial(bloom_diam, (45, 140, 230), 120)

        # 3. Concentrated singularity core
        center_diam = int(dim * 0.12)
        self.core_center = radial(center_diam, (160, 235, 255), 220)

        # Initialize warp stars
        self.stars = []
        for _ in range(460):
            self.stars.append(self._make_star(far=False))

        # Initialize subtle quantum depth particles in vanishing core
        self.particles = []
        for _ in range(140):
            self.particles.append(self._make_particle(far=False))

    def _make_star(self, far: bool) -> list[float]:
        angle = self.rng.uniform(0, math.tau)
        r = (self.rng.uniform(0.04, 1.15)) ** 0.68
        x = math.cos(angle) * r
        y = math.sin(angle) * r
        z = self.rng.uniform(1.2, 2.4) if far else self.rng.uniform(0.08, 2.4)
        spectral_bias = self.rng.choice((0.0, 0.0, 0.0, 0.5, 1.0))
        return [x, y, z, spectral_bias]

    def _make_particle(self, far: bool) -> list[float]:
        angle = self.rng.uniform(0, math.tau)
        r = self.rng.uniform(0.02, 0.45)
        x = math.cos(angle) * r
        y = math.sin(angle) * r
        z = self.rng.uniform(1.4, 2.8) if far else self.rng.uniform(0.2, 2.8)
        return [x, y, z]

    def step(self, dt: float) -> None:
        # Variable speed acceleration: hyperdrive surges and pulses
        throttle = 1.0 + 0.38 * (math.sin(self.t * 0.75) ** 2) + 0.18 * math.sin(self.t * 1.6)
        self.current_speed = self.base_speed * throttle

        # Update warp stars with relativistic acceleration
        for star in self.stars:
            local_accel = 1.0 + 0.22 / max(0.05, star[2])
            star[2] -= dt * self.current_speed * local_accel
            if star[2] <= 0.04:
                born = self._make_star(far=True)
                star[0], star[1], star[2], star[3] = born

        # Update quantum depth particles (slower drift)
        for p in self.particles:
            p[2] -= dt * self.current_speed * 0.42
            if p[2] <= 0.08:
                born_p = self._make_particle(far=True)
                p[0], p[1], p[2] = born_p

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill((0, 2, 7))
        cx, cy = self.w / 2.0, self.h / 2.0

        # 1. Radiant hyperspace vanishing core
        if self.core_aura:
            surf.blit(
                self.core_aura,
                (int(cx - self.core_aura.get_width() / 2), int(cy - self.core_aura.get_height() / 2)),
                special_flags=pygame.BLEND_RGB_ADD,
            )
        if self.core_bloom:
            surf.blit(
                self.core_bloom,
                (int(cx - self.core_bloom.get_width() / 2), int(cy - self.core_bloom.get_height() / 2)),
                special_flags=pygame.BLEND_RGB_ADD,
            )
        if self.core_center:
            surf.blit(
                self.core_center,
                (int(cx - self.core_center.get_width() / 2), int(cy - self.core_center.get_height() / 2)),
                special_flags=pygame.BLEND_RGB_ADD,
            )

        # Singularity pinpoint
        pygame.draw.circle(surf, (255, 255, 255), (int(cx), int(cy)), 2)

        # 2. Subtle particle depth floating in the core
        for px_coord, py_coord, pz in self.particles:
            pt_x = cx + (px_coord / pz) * self.scale
            pt_y = cy + (py_coord / pz) * self.scale
            if 0 <= pt_x < self.w and 0 <= pt_y < self.h:
                p_lum = max(0, min(255, int(180 * (1.0 - pz / 2.8))))
                p_col = (int(p_lum * 0.55), int(p_lum * 0.85), p_lum)
                surf.set_at((int(pt_x), int(pt_y)), p_col)

        # 3. Motion-blurred hyperspace light streaks with Doppler color shifting & anti-aliasing
        streak_mult = 0.15 * (self.current_speed / self.base_speed)
        for x, y, z, spectral in self.stars:
            # Perspective projection of head (current position)
            px = cx + (x / z) * self.scale
            py = cy + (y / z) * self.scale

            # Relativistic streak tail calculation (past position)
            lorentz = 1.0 + 0.32 / (z * z)
            z_tail = z + streak_mult * lorentz
            ox = cx + (x / z_tail) * self.scale
            oy = cy + (y / z_tail) * self.scale

            # Clip off-screen streaks
            if not (-80 <= px <= self.w + 80 and -80 <= py <= self.h + 80):
                continue

            # Relativistic Doppler color shifting:
            # Head (approaching fastest): brilliant electric cyan/blue to blazing white
            # Trailing tail (origin): shifts towards warm white / golden amber / orange
            bright = max(0.12, min(1.0, 1.25 - (z / 2.1)))

            # Tail color: warm golden amber (255, 160, 60)
            tr = int(245 * bright * (0.85 + 0.15 * spectral))
            tg = int(160 * bright * (0.75 + 0.20 * spectral))
            tb = int(65 * bright * (0.60 + 0.30 * spectral))
            tail_color = (max(0, min(255, tr)), max(0, min(255, tg)), max(0, min(255, tb)))

            # Mid color: warm white / transition
            mr = int(230 * bright)
            mg = int(240 * bright)
            mb = int(255 * bright)
            mid_color = (max(0, min(255, mr)), max(0, min(255, mg)), max(0, min(255, mb)))

            # Head color: brilliant electric cyan/blue (110, 220, 255)
            hr = int(120 * bright * (0.75 + 0.25 * (1.0 - spectral)))
            hg = int(220 * bright)
            hb = int(255 * bright)
            head_color = (max(0, min(255, hr)), max(0, min(255, hg)), max(0, min(255, hb)))

            # Mid-point of the streak
            mid_x = (ox + px * 2.0) / 3.0
            mid_y = (oy + py * 2.0) / 3.0

            width = 1 if z > 0.65 else (2 if z > 0.32 else 3)

            if width == 1:
                # Anti-aliased 1px streak segments
                pygame.draw.aaline(surf, tail_color, (ox, oy), (mid_x, mid_y))
                pygame.draw.aaline(surf, head_color, (mid_x, mid_y), (px, py))
            else:
                # Core thick streak
                pygame.draw.line(surf, tail_color, (ox, oy), (mid_x, mid_y), width)
                pygame.draw.line(surf, head_color, (mid_x, mid_y), (px, py), width)
                # Anti-aliased outer edge smoothing
                pygame.draw.aaline(surf, head_color, (ox, oy), (px, py))

            # Blazing plasma tip for close approaching stars
            if z < 0.42:
                tip_rad = 1 if z > 0.22 else 2
                pygame.draw.circle(surf, (255, 255, 255), (int(px), int(py)), tip_rad)
