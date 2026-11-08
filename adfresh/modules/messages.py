"""Short lines drift across the dark. Every so often one stops to be read."""

from __future__ import annotations

import math
import random

import pygame

from adfresh.drawutil import font
from adfresh.modules.base import Module

LINES = (
    "The night shift is winged and chrome.",
    "Do not adjust your display.",
    "Somewhere, a slice of bread is learning to fly.",
    "This screen is resting its eyes.",
    "Be right back. Toasting.",
    "Starlight, compiled.",
    "The fish are fine.",
    "Idle, with style.",
    "After hours, the desktop dreams.",
    "Wings on. Crust set.",
    "No mail worth waking for.",
    "The mountains are moving slowly, on purpose.",
    "Back in a moment. Or an hour.",
    "Leave the cursor where it is.",
    "A quiet machine is still a machine.",
    "Butter side up, always.",
    "The glass is doing most of the work.",
    "Count the streaks, lose the count.",
)

COLORS = (
    (236, 226, 206),
    (232, 176, 92),
    (168, 196, 214),
    (214, 164, 156),
    (186, 214, 190),
)

FEATURE_PERIOD = 24.0  # seconds between centered feature lines
FEATURE_WINDOW = 9.0  # feature visible within this window


class Messages(Module):
    id = "messages"
    title = "Messages"

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        self.items = []
        lanes = 5
        for i in range(lanes):
            self.items.append(self._make(y=h * (0.18 + i * 0.14), on_screen=True))

    def _make(self, y: float | None = None, on_screen: bool = False) -> dict:
        scale = max(0.7, self.h / 1080)
        size = int(self.rng.uniform(26, 54) * scale)
        text = self.rng.choice(LINES)
        color = self.rng.choice(COLORS)
        image = font("medium", size).render(text, True, color)
        while image.get_width() > self.w * 0.8 and size > 18:
            size -= 2
            image = font("medium", size).render(text, True, color)
        direction = self.rng.choice((-1, 1))
        speed = self.rng.uniform(36, 80)
        if on_screen:
            room = max(24, self.w - image.get_width() - 24)
            x = self.rng.uniform(24, room)
        elif direction < 0:
            x = self.w + 20
        else:
            x = -image.get_width() - 20
        if y is None:
            y = self.rng.uniform(40, max(41, self.h - size - 40))
        return {
            "image": image,
            "x": x,
            "y": y,
            "v": speed * direction,
            "age": 0.0,
            "fade": 0.7,
            "phase": self.rng.uniform(0, math.tau),
        }

    def step(self, dt: float) -> None:
        alive = []
        for item in self.items:
            item["x"] += item["v"] * dt
            item["age"] += dt
            image = item["image"]
            off = item["v"] < 0 and item["x"] < -image.get_width() - 30
            off = off or (item["v"] > 0 and item["x"] > self.w + 30)
            if off:
                alive.append(self._make())
            else:
                alive.append(item)
        self.items = alive

    def _edge_alpha(self, item: dict) -> float:
        """Fade out as the text approaches the edge it is heading toward."""
        image = item["image"]
        margin = 140.0
        if item["v"] < 0:
            remaining = item["x"] + image.get_width()
        else:
            remaining = self.w - item["x"]
        return max(0.0, min(1.0, remaining / margin))

    def _feature_alpha(self) -> float:
        phase = self.t % FEATURE_PERIOD
        if phase >= FEATURE_WINDOW:
            return 0.0
        fade = 1.8
        if phase < fade:
            return phase / fade
        if phase > FEATURE_WINDOW - fade:
            return (FEATURE_WINDOW - phase) / fade
        return 1.0

    def draw(self, surf: pygame.Surface) -> None:
        surf.fill((0, 0, 0))
        # While a feature line has the stage, the drifters fall back.
        stage = 1.0 - 0.75 * self._feature_alpha()
        for item in self.items:
            alpha = min(1.0, item["age"] / item["fade"]) * self._edge_alpha(item) * stage
            if alpha <= 0.01:
                continue
            bob = math.sin(self.t * 0.9 + item["phase"]) * 4.0
            ghost = item["image"].copy()
            ghost.fill((255, 255, 255, int(255 * alpha)), special_flags=pygame.BLEND_RGBA_MULT)
            x, y = int(item["x"]), int(item["y"] + bob)
            shadow = item["image"].copy()
            shadow.fill((0, 0, 0, int(160 * alpha)), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(shadow, (x + 2, y + 3))
            surf.blit(ghost, (x, y))
        self._draw_feature(surf)

    def _draw_feature(self, surf: pygame.Surface) -> None:
        """One line, large and centered, that fades in, holds, and fades out."""
        alpha = self._feature_alpha()
        if alpha <= 0.0:
            return
        index = int(self.t // FEATURE_PERIOD) % len(LINES)
        scale = max(0.7, self.h / 1080)
        size = int(64 * scale)
        color = COLORS[index % len(COLORS)]
        image = font("medium", size).render(LINES[index], True, color)
        while image.get_width() > self.w * 0.84 and size > 18:
            size -= 2
            image = font("medium", size).render(LINES[index], True, color)
        x = int((self.w - image.get_width()) / 2)
        y = int(self.h * 0.46 - image.get_height() / 2)
        a = int(255 * max(0.0, min(1.0, alpha)))
        shadow = image.copy()
        shadow.fill((0, 0, 0, int(a * 0.7)), special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(shadow, (x + 3, y + 4))
        ghost = image.copy()
        ghost.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(ghost, (x, y))
