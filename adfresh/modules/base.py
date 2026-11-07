"""Module interface."""

from __future__ import annotations

import random

import pygame


class Module:
    id = "base"
    title = "Base"

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.t = 0.0
        self.w = 1
        self.h = 1

    def resize(self, w: int, h: int) -> None:
        self.w = max(1, int(w))
        self.h = max(1, int(h))

    def tick(self, dt: float) -> None:
        self.t += dt
        self.step(dt)

    def step(self, dt: float) -> None:
        return None

    def draw(self, surf: pygame.Surface) -> None:
        raise NotImplementedError
