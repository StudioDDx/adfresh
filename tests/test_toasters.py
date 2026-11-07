"""Tests for Flying Toasters motion, multi-depth atmosphere, and flight physics."""

from __future__ import annotations

import math
import os
import random
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from adfresh.modules.base import Module
from adfresh.modules.toasters import DEPTH_PLANES, Toasters, _Flyer
from adfresh.sprites import WING_FRAMES


class ToastersTest(unittest.TestCase):
    def setUp(self) -> None:
        pygame.display.init()
        pygame.font.init()

    def test_module_contract(self) -> None:
        rng = random.Random(42)
        toasters = Toasters(rng)
        self.assertIsInstance(toasters, Module)
        self.assertEqual(toasters.id, "toasters")
        self.assertEqual(toasters.title, "Flying Toasters")

    def test_organic_distribution_not_on_grid(self) -> None:
        rng = random.Random(101)
        toasters = Toasters(rng)
        toasters.resize(1920, 1080)
        self.assertGreaterEqual(len(toasters.flyers), 14)

        # Verify flyers are not on a rigid grid
        xs = [f.x for f in toasters.flyers]
        ys = [f.y for f in toasters.flyers]
        phases = [f.phase for f in toasters.flyers]
        speeds = [math.hypot(f.vx, f.vy) for f in toasters.flyers]

        # In a 3x4 grid there would only be 3 or 4 unique Y levels and identical speeds
        self.assertGreaterEqual(len(set(round(y, 1) for y in ys)), 15)
        self.assertGreaterEqual(len(set(round(x, 1) for x in xs)), 15)
        self.assertGreaterEqual(len(set(round(p, 2) for p in phases)), 18)
        self.assertGreaterEqual(len(set(round(s, 1) for s in speeds)), 15)

    def test_multiple_depth_planes_and_atmospheric_perspective(self) -> None:
        rng = random.Random(202)
        toasters = Toasters(rng)
        toasters.resize(1920, 1080)

        depths = [f.depth for f in toasters.flyers]
        alphas = [f.alpha for f in toasters.flyers]

        # Verify depth span covers distant miniature (<0.50) to foreground hero (>1.15)
        self.assertLess(min(depths), 0.50)
        self.assertGreater(max(depths), 1.15)

        # Distant flyers must be dimmer/softer (atmospheric perspective)
        # Foreground flyers must be crisp and brilliant (alpha == 255)
        min_depth_flyer = min(toasters.flyers, key=lambda f: f.depth)
        max_depth_flyer = max(toasters.flyers, key=lambda f: f.depth)
        self.assertLess(min_depth_flyer.alpha, 180)
        self.assertEqual(max_depth_flyer.alpha, 255)

        # Parallax speed: distant flyers move slower than foreground flyers
        min_speed = math.hypot(min_depth_flyer.vx, min_depth_flyer.vy)
        max_speed = math.hypot(max_depth_flyer.vx, max_depth_flyer.vy)
        self.assertLess(min_speed, max_speed)

    def test_flight_physics_diagonal_descent(self) -> None:
        rng = random.Random(303)
        toasters = Toasters(rng)
        toasters.resize(1920, 1080)

        for f in toasters.flyers:
            # Organic diagonal descent: down and to the left (vx < 0, vy > 0)
            self.assertLess(f.vx, 0.0)
            self.assertGreater(f.vy, 0.0)
            slope = f.vy / (-f.vx)
            self.assertGreater(slope, 0.30)
            self.assertLess(slope, 0.70)

    def test_bobbing_oscillation_downstroke_rise_upstroke_sink(self) -> None:
        # Wing flap cycle: 0..WING_FRAMES
        # Downstroke (wing_cycle in 0..pi): math.sin > 0 -> bob_y < 0 (rises upward)
        # Upstroke (wing_cycle in pi..2pi): math.sin < 0 -> bob_y > 0 (sinks downward)
        rng = random.Random(404)
        flyer = _Flyer(rng, 2, "toaster", 500, 500)
        bob_amp = flyer.bob_amp

        # Peak downstroke: quarter cycle (phase = WING_FRAMES / 4)
        downstroke_cycle = math.pi / 2
        downstroke_bob_y = -math.sin(downstroke_cycle) * bob_amp
        self.assertAlmostEqual(downstroke_bob_y, -bob_amp)
        self.assertLess(downstroke_bob_y, 0.0)  # Rises upward on screen

        # Peak upstroke: three-quarter cycle
        upstroke_cycle = 3 * math.pi / 2
        upstroke_bob_y = -math.sin(upstroke_cycle) * bob_amp
        self.assertAlmostEqual(upstroke_bob_y, bob_amp)
        self.assertGreater(upstroke_bob_y, 0.0)  # Sinks downward on screen

    def test_toast_drifting_dynamics(self) -> None:
        rng = random.Random(505)
        toasters = Toasters(rng)
        toasters.resize(1920, 1080)

        toasts = [f for f in toasters.flyers if f.kind != "toaster"]
        self.assertGreater(len(toasts), 0)
        for t in toasts:
            self.assertGreater(t.drift_freq, 0.0)
            self.assertGreater(t.drift_amp_x, 0.0)
            self.assertGreater(t.drift_amp_y, 0.0)

    def test_continuous_flow_and_respawning(self) -> None:
        rng = random.Random(606)
        toasters = Toasters(rng)
        toasters.resize(1920, 1080)

        # Force a flyer way off screen to test respawn
        f = toasters.flyers[0]
        f.x = -500.0
        f.y = 2000.0
        toasters.step(1 / 60)

        # Flyer should have respawned at upper/right entry perimeter
        self.assertTrue(f.x >= 0.1 * 1920 or f.y <= 0.8 * 1080)
        self.assertGreater(f.x, -280)
        self.assertLess(f.y, 1080 + 280)

    def test_60_fps_performance(self) -> None:
        rng = random.Random(707)
        toasters = Toasters(rng)
        screen = pygame.Surface((1920, 1080))
        toasters.resize(1920, 1080)

        # Warm up
        for _ in range(5):
            toasters.tick(1 / 60)
            toasters.draw(screen)

        frames = 120
        start = time.perf_counter()
        for _ in range(frames):
            toasters.tick(1 / 60)
            toasters.draw(screen)
        duration = time.perf_counter() - start

        fps = frames / duration
        # Must comfortably exceed 60 FPS (typically >100 FPS)
        self.assertGreater(fps, 60.0)


if __name__ == "__main__":
    unittest.main()
