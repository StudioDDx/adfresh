"""Tests for the Mystify, Aurora, and Lava Lamp modules."""

from __future__ import annotations

import os
import random
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from adfresh.modules import BY_ID, CATALOG
from adfresh.modules.aurora import Aurora
from adfresh.modules.base import Module
from adfresh.modules.lava import Lava
from adfresh.modules.mystify import TRAIL, Mystify


class ContractTest(unittest.TestCase):
    def test_registered_in_catalog(self) -> None:
        ids = [cls.id for cls in CATALOG]
        for cls in (Mystify, Aurora, Lava):
            self.assertIn(cls.id, ids)
            self.assertIs(BY_ID[cls.id], cls)

    def test_module_basics(self) -> None:
        for cls, mid, title in (
            (Mystify, "mystify", "Mystify"),
            (Aurora, "aurora", "Aurora"),
            (Lava, "lava", "Lava Lamp"),
        ):
            module = cls(random.Random(1))
            self.assertIsInstance(module, Module)
            self.assertEqual(module.id, mid)
            self.assertEqual(module.title, title)


class DeterminismTest(unittest.TestCase):
    """Spanned layouts run the same seeded sim on every display process."""

    def setUp(self) -> None:
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((640, 360))

    def _run(self, cls, seed: int, ticks: int = 90):
        module = cls(random.Random(seed))
        module.resize(640, 360)
        for _ in range(ticks):
            module.tick(1 / 60)
        return module

    def test_mystify_same_seed_same_positions(self) -> None:
        one = self._run(Mystify, 11)
        two = self._run(Mystify, 11)
        for r1, r2 in zip(one.ribbons, two.ribbons):
            self.assertEqual(r1.pts, r2.pts)
        three = self._run(Mystify, 12)
        self.assertNotEqual(one.ribbons[0].pts, three.ribbons[0].pts)

    def test_mystify_trail_capped(self) -> None:
        module = self._run(Mystify, 11, ticks=TRAIL * 3)
        for ribbon in module.ribbons:
            self.assertLessEqual(len(ribbon.history), TRAIL)

    def test_mystify_vertices_stay_in_frame(self) -> None:
        module = self._run(Mystify, 11, ticks=600)
        for ribbon in module.ribbons:
            for x, y, _, _ in ribbon.pts:
                self.assertGreaterEqual(x, 0.0)
                self.assertLessEqual(x, module.w)
                self.assertGreaterEqual(y, 0.0)
                self.assertLessEqual(y, module.h)

    def test_aurora_field_deterministic(self) -> None:
        one = self._run(Aurora, 21)
        two = self._run(Aurora, 21)
        self.assertTrue((one._field() == two._field()).all())
        three = self._run(Aurora, 21, ticks=91)
        self.assertFalse((one._field() == three._field()).all())

    def test_lava_blobs_deterministic(self) -> None:
        one = self._run(Lava, 31)
        two = self._run(Lava, 31)
        self.assertEqual(one._blob_positions(), two._blob_positions())
        three = self._run(Lava, 32)
        self.assertNotEqual(one._blob_positions(), three._blob_positions())


class DrawTest(unittest.TestCase):
    def setUp(self) -> None:
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((480, 270))

    def test_each_draws_a_picture(self) -> None:
        for cls in (Mystify, Aurora, Lava):
            module = cls(random.Random(5))
            module.resize(480, 270)
            for _ in range(60):
                module.tick(1 / 60)
            screen = pygame.Surface((480, 270))
            screen.fill((0, 0, 0))
            module.draw(screen)
            colors = set()
            for y in range(0, 270, 4):
                for x in range(0, 480, 4):
                    colors.add(screen.get_at((x, y))[:3])
            self.assertGreater(len(colors), 12, cls.id)


if __name__ == "__main__":
    unittest.main()
