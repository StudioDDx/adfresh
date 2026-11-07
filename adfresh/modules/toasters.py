"""Flying toasters and flying toast. Side-lit chrome, cream wings, black night."""

from __future__ import annotations

import math
import random

import pygame

from adfresh.modules.base import Module
from adfresh.sprites import WING_FRAMES, toast, toaster

KINDS = ("plain", "butter", "butter", "jam", "dark")

# Depth planes configuration:
# Layer 0: Distant miniature layer - slow, soft, dimmer atmospheric perspective
# Layer 1: Far-mid layer - gentle dimming, steady glide
# Layer 2: Midground layer - classic After Dark presence
# Layer 3: Near-mid layer - prominent, energetic
# Layer 4: Foreground hero layer - giant, swift, crisp, brilliant chrome
DEPTH_PLANES: tuple[dict[str, tuple[float, float] | float | int], ...] = (
    {
        "depth_range": (0.40, 0.48),
        "speed_range": (80.0, 105.0),
        "alpha": 145,
        "bob_amp": 1.4,
        "flap_range": (2.2, 2.6),
    },
    {
        "depth_range": (0.58, 0.68),
        "speed_range": (110.0, 140.0),
        "alpha": 175,
        "bob_amp": 2.0,
        "flap_range": (2.4, 2.8),
    },
    {
        "depth_range": (0.80, 0.92),
        "speed_range": (145.0, 175.0),
        "alpha": 210,
        "bob_amp": 2.8,
        "flap_range": (2.6, 3.1),
    },
    {
        "depth_range": (1.02, 1.14),
        "speed_range": (180.0, 215.0),
        "alpha": 240,
        "bob_amp": 3.6,
        "flap_range": (2.8, 3.3),
    },
    {
        "depth_range": (1.22, 1.36),
        "speed_range": (220.0, 260.0),
        "alpha": 255,
        "bob_amp": 4.6,
        "flap_range": (3.0, 3.5),
    },
)


class _Flyer:
    def __init__(
        self,
        rng: random.Random,
        plane_idx_or_w: int = 2,
        kind_or_h: int | str = "toaster",
        kind: str = "toaster",
        x: float | None = None,
        y: float | None = None,
    ):
        if isinstance(kind_or_h, (int, float)):
            w = int(plane_idx_or_w)
            h = int(kind_or_h)
            actual_kind = kind
            plane_idx = rng.randrange(len(DEPTH_PLANES))
            actual_x = rng.uniform(0, w) if x is None else float(x)
            actual_y = rng.uniform(0, h) if y is None else float(y)
        else:
            plane_idx = int(plane_idx_or_w)
            actual_kind = str(kind_or_h)
            actual_x = 0.0 if x is None else float(x)
            actual_y = 0.0 if y is None else float(y)

        self.plane_idx = max(0, min(len(DEPTH_PLANES) - 1, plane_idx))
        self.kind = actual_kind
        self.x = actual_x
        self.y = actual_y
        self.variant = rng.choice((0, 1, 2))
        self.phase = rng.uniform(0, WING_FRAMES)
        self.depth = 1.0
        self.alpha = 255
        self.bob_amp = 7.0
        self.bob_w = 1.0
        self.bob_p = 0.0
        self.flap_rate = 3.0
        self.vx = -150.0
        self.vy = 75.0
        self.drift_freq = 1.0
        self.drift_phase = 0.0
        self.drift_amp_x = 0.0
        self.drift_amp_y = 0.0
        self.configure(rng)

    def configure(self, rng: random.Random) -> None:
        plane = DEPTH_PLANES[self.plane_idx]
        depth_min, depth_max = plane["depth_range"]  # type: ignore[misc]
        self.depth = rng.uniform(depth_min, depth_max)
        self.alpha = int(plane["alpha"])
        self.bob_amp = float(plane["bob_amp"]) * rng.uniform(0.90, 1.10)
        flap_min, flap_max = plane["flap_range"]  # type: ignore[misc]
        self.flap_rate = rng.uniform(flap_min, flap_max)

        # Organic diagonal descent: soar down and to the left (vx < 0, vy > 0)
        speed_min, speed_max = plane["speed_range"]  # type: ignore[misc]
        if self.kind == "toaster":
            # Classic After Dark 2:1 diagonal flight slope (~26.5 deg)
            slope = rng.uniform(0.46, 0.54)
            speed = rng.uniform(speed_min, speed_max)
        else:
            # Toast drifts among toasters with subtle buoyant variation
            slope = rng.uniform(0.40, 0.60)
            speed = rng.uniform(speed_min, speed_max) * rng.uniform(0.90, 1.05)
            self.drift_freq = rng.uniform(0.4, 0.9)
            self.drift_phase = rng.uniform(0, math.tau)
            self.drift_amp_x = rng.uniform(1.5, 3.5) * self.depth
            self.drift_amp_y = rng.uniform(1.5, 3.5) * self.depth

        speed_mag = speed * rng.uniform(0.96, 1.04)
        self.vx = -speed_mag / math.sqrt(1 + slope * slope)
        self.vy = slope * (-self.vx)

    @property
    def flap(self) -> float:
        return self.flap_rate

    @flap.setter
    def flap(self, value: float) -> None:
        self.flap_rate = value

    @property
    def bob_a(self) -> float:
        return self.bob_amp

    @bob_a.setter
    def bob_a(self, value: float) -> None:
        self.bob_amp = value

    def width(self) -> int:
        base = 281 if self.kind == "toaster" else 146
        return int(base * self.depth)


class Toasters(Module):
    id = "toasters"
    title = "Flying Toasters"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.flyers: list[_Flyer] = []
        self._sprite_cache: dict[tuple, pygame.Surface] = {}

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        area_ratio = (w * h) / (1920 * 1080)
        count = max(14, min(24, int(15 * area_ratio + 5)))

        # Distribute flyers across the 5 depth planes:
        # miniature distant backdrop -> prominent midground -> majestic hero foreground
        plane_distribution = self._plan_distribution(count)
        self.flyers = []
        margin = 280.0

        # Stratified journey progression prevents clumping or initial empty screen
        order = list(range(count))
        self.rng.shuffle(order)

        for i, plane_idx in enumerate(plane_distribution):
            # Maintain ~65% toasters, 35% toast
            kind = "toaster" if self.rng.random() < 0.65 else self.rng.choice(KINDS)
            flyer = _Flyer(self.rng, plane_idx, kind)

            x0, y0, t_exit = self._sample_entry(flyer, margin)

            # Pre-populate screen organically in mid-flight
            prog = (order[i] + self.rng.uniform(0.08, 0.92)) / count
            flyer.x = x0 + flyer.vx * (prog * t_exit)
            flyer.y = y0 + flyer.vy * (prog * t_exit)
            flyer.phase = self.rng.uniform(0, WING_FRAMES)

            self.flyers.append(flyer)

    def _plan_distribution(self, count: int) -> list[int]:
        weights = (0.25, 0.25, 0.25, 0.15, 0.10)
        counts = [max(1, int(round(w * count))) for w in weights]
        diff = count - sum(counts)
        counts[2] += diff
        result: list[int] = []
        for plane_idx, c in enumerate(counts):
            result.extend([plane_idx] * max(1, c))
        return result[:count]

    def _sample_entry(self, flyer: _Flyer, margin: float) -> tuple[float, float, float]:
        top_span = self.w * 0.90 + margin
        right_span = self.h * 0.75 + margin
        if self.rng.random() < (top_span / (top_span + right_span)):
            x0 = self.rng.uniform(self.w * 0.10, self.w + margin)
            y0 = -self.rng.uniform(20.0, margin)
        else:
            x0 = self.w + self.rng.uniform(20.0, margin)
            y0 = self.rng.uniform(-margin * 0.5, self.h * 0.75)

        tx = (-margin - x0) / flyer.vx
        ty = (self.h + margin - y0) / flyer.vy
        t_exit = max(1.0, min(tx, ty))
        return x0, y0, t_exit

    def _respawn(self, flyer: _Flyer, margin: float) -> None:
        # Dynamic variety on respawn while preserving depth plane balance
        if flyer.kind == "toaster":
            if self.rng.random() < 0.15:
                flyer.kind = self.rng.choice(KINDS)
            else:
                flyer.variant = self.rng.choice((0, 1, 2))
        else:
            if self.rng.random() < 0.30:
                flyer.kind = "toaster"
                flyer.variant = self.rng.choice((0, 1, 2))
            else:
                flyer.kind = self.rng.choice(KINDS)

        flyer.phase = self.rng.uniform(0, WING_FRAMES)
        flyer.configure(self.rng)
        x0, y0, _ = self._sample_entry(flyer, margin)
        flyer.x = x0
        flyer.y = y0

    def step(self, dt: float) -> None:
        margin = 280.0
        for flyer in self.flyers:
            flyer.x += flyer.vx * dt
            flyer.y += flyer.vy * dt
            flyer.phase = (flyer.phase + dt * flyer.flap_rate * WING_FRAMES) % WING_FRAMES
            if flyer.x < -margin or flyer.y > self.h + margin:
                self._respawn(flyer, margin)

    def _get_sprite(
        self,
        kind: str,
        frame: int,
        width: int,
        variant: int,
        alpha: int,
    ) -> pygame.Surface:
        if kind == "toaster":
            key = ("toaster", frame, width, variant, alpha)
        else:
            key = ("toast", kind, frame, width, alpha)

        hit = self._sprite_cache.get(key)
        if hit is not None:
            return hit

        if kind == "toaster":
            base = toaster(frame, width, variant)
        else:
            base = toast(kind, frame, width)

        if alpha < 255:
            shaded = base.copy()
            shaded.set_alpha(alpha)
        else:
            shaded = base

        # Cap cache size to avoid unbounded memory over long sessions
        if len(self._sprite_cache) > 800:
            self._sprite_cache.clear()

        self._sprite_cache[key] = shaded
        return shaded

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill((0, 0, 0))
        ordered = sorted(self.flyers, key=lambda f: f.depth)
        for flyer in ordered:
            frame = int(flyer.phase) % WING_FRAMES
            width = flyer.width()

            image = self._get_sprite(flyer.kind, frame, width, flyer.variant, flyer.alpha)

            # Bobbing oscillation:
            # During the downstroke (sin(wing_cycle) > 0), aerodynamic lift pushes
            # the flyer upward (negative y offset). During the upstroke (sin < 0),
            # the flyer sinks downward (positive y offset).
            wing_cycle = (flyer.phase / WING_FRAMES) * math.tau
            bob_y = -math.sin(wing_cycle) * flyer.bob_amp
            # Silky smooth flight: no horizontal counter-jitter for toasters
            bob_x = 0.0

            if flyer.kind != "toaster":
                # Toast drifting: floating gently through space on thermal air currents
                bob_x += math.cos(self.t * flyer.drift_freq + flyer.drift_phase) * flyer.drift_amp_x
                bob_y += math.sin(self.t * flyer.drift_freq * 0.8 + flyer.drift_phase) * flyer.drift_amp_y

            rx = flyer.x + bob_x
            ry = flyer.y + bob_y
            surf.blit(image, (round(rx - image.get_width() / 2), round(ry - image.get_height() / 2)))
