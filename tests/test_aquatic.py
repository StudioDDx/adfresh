"""Aquatic module: the tank renders at every display size, fish included."""

from __future__ import annotations

import os
import random
import unittest
from unittest import mock

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from adfresh.engine import Player
from adfresh.modules.aquatic import (
    FISH_TAIL_FRAMES,
    SPECIES,
    Aquatic,
    get_fish_frames,
    get_fish_surface,
)


def _colors(surface: pygame.Surface) -> int:
    seen = set()
    w, h = surface.get_size()
    for y in range(0, h, max(4, h // 90)):
        for x in range(0, w, max(4, w // 120)):
            seen.add(surface.get_at((x, y))[:3])
            if len(seen) > 400:
                return len(seen)
    return len(seen)


class AquaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.display.init()
        pygame.display.set_mode((64, 64))

    def _module(self, w: int = 960, h: int = 540) -> Aquatic:
        module = Aquatic(random.Random(7))
        module.resize(w, h)
        return module

    def test_scene_has_tank_frame_and_picture(self) -> None:
        with mock.patch.dict(os.environ, {"ADFRESH_NIGHT": "0"}):
            module = self._module(960, 540)
        surface = pygame.Surface((960, 540))
        for _ in range(12):
            module.tick(1 / 30)
        module.draw(surface)
        self.assertGreater(_colors(surface), 80)

        # Frame: the outer rows/columns are the near-black rim.
        self.assertLess(sum(surface.get_at((480, 2))[:3]), 160)
        self.assertLess(sum(surface.get_at((2, 270))[:3]), 160)
        # Palette checks use the pre-rendered layers so a fish can't land on
        # the sample point.
        water = module.water_bg.get_at((480, 240))
        self.assertGreater(water.b, water.r)
        sand = module.seabed_surf.get_at((480, int(540 * 0.85)))
        self.assertGreater(sand.r + sand.g, sand.b * 2)

    def test_draws_at_supported_sizes(self) -> None:
        for w, h in ((640, 360), (1280, 720), (1920, 1080), (3840, 1080)):
            with self.subTest(size=(w, h)):
                module = self._module(w, h)
                surface = pygame.Surface((w, h))
                for _ in range(6):
                    module.tick(1 / 30)
                module.draw(surface)
                self.assertGreater(_colors(surface), 60)
                self.assertEqual(len(module.fish), max(8, min(18, w // 110)))

    def test_fish_assets_are_available(self) -> None:
        # The module uses four raster species; the fifth SPECIES entry is a
        # procedural-fallback colour only.
        for idx in range(4):
            sprite = get_fish_surface(idx, 120, flip_x=False)
            self.assertIsNotNone(sprite, f"missing fish_{idx}.png")
            assert sprite is not None
            self.assertEqual(sprite.get_width(), 120)
        self.assertIs(get_fish_surface(0, 120, False), get_fish_surface(0, 120, False))

    def test_tail_animation_frames_swish(self) -> None:
        left = get_fish_frames(0, 120, flip_x=False)
        right = get_fish_frames(0, 120, flip_x=True)
        self.assertIsNotNone(left)
        self.assertIsNotNone(right)
        assert left is not None and right is not None
        self.assertEqual(len(left), FISH_TAIL_FRAMES)
        self.assertEqual(len(right), FISH_TAIL_FRAMES)
        signatures = {pygame.image.tobytes(frame, "RGBA") for frame in left}
        self.assertGreaterEqual(len(signatures), FISH_TAIL_FRAMES - 1)
        # Flipped frames are the mirror of the unflipped cycle.
        mirrored = pygame.image.tobytes(pygame.transform.flip(left[0], True, False), "RGBA")
        self.assertEqual(mirrored, pygame.image.tobytes(right[0], "RGBA"))

    def test_tap_ripples_and_startles_fish(self) -> None:
        with mock.patch.dict(os.environ, {"ADFRESH_NIGHT": "0"}):
            module = self._module(960, 540)
        for _ in range(10):
            module.tick(1 / 30)
        module.tap(480, 260)
        self.assertEqual(len(module.ripples), 1)
        self.assertTrue(any(f["fright"] > 0 for f in module.fish))
        surface = pygame.Surface((960, 540))
        for _ in range(20):
            module.tick(1 / 30)
        module.draw(surface)
        # Repeated taps must not grow the particle list without bound.
        for _ in range(20):
            module.tap(100, 100)
        self.assertLessEqual(len(module.bubbles), 80)

    def test_night_mode_is_darker(self) -> None:
        def average_water(night: str) -> float:
            with mock.patch.dict(os.environ, {"ADFRESH_NIGHT": night}):
                module = self._module(640, 360)
            surface = pygame.Surface((640, 360))
            module.draw(surface)
            total = 0
            for x in range(0, 640, 16):
                for y in range(0, 200, 16):
                    r, g, b, _ = surface.get_at((x, y))
                    total += r + g + b
            return total

        self.assertGreater(average_water("0"), average_water("1"))

    def test_handle_click_uses_virtual_canvas_offset(self) -> None:
        class Stub:
            def __init__(self) -> None:
                self.points: list[tuple[int, int]] = []

            def tap(self, x: int, y: int) -> None:
                self.points.append((x, y))

        player = Player.__new__(Player)
        stub = Stub()
        player.selection = ("aquatic", "aquatic", 0.0)
        player.crop = pygame.Rect(1920, 0, 1920, 1080)
        player.modules = {"aquatic": stub}
        self.assertTrue(player.handle_click((10, 20)))
        self.assertEqual(stub.points, [(1930, 20)])

    def test_resize_is_repeatable(self) -> None:
        module = self._module(800, 450)
        module.resize(1600, 900)
        module.resize(800, 450)
        surface = pygame.Surface((800, 450))
        for _ in range(4):
            module.tick(1 / 30)
        module.draw(surface)
        self.assertGreater(_colors(surface), 50)


if __name__ == "__main__":
    unittest.main()
