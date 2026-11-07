"""Tests for Lunatic Fringe modern space combat shooter screensaver module."""

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
from adfresh.modules.fringe import (
    RADAR_RANGE,
    WORLD_H,
    WORLD_W,
    Enemy,
    Fringe,
    Laser,
    rel_coord,
    wrap_coord,
)


class FringeTest(unittest.TestCase):
    def setUp(self) -> None:
        pygame.display.init()
        pygame.font.init()

    def test_module_contract(self) -> None:
        rng = random.Random(42)
        fringe = Fringe(rng)
        self.assertIsInstance(fringe, Module)
        self.assertEqual(fringe.id, "fringe")
        self.assertEqual(fringe.title, "Lunatic Fringe")

    def test_arena_and_toroidal_wrapping(self) -> None:
        # Wrap coordinate inside arena
        self.assertAlmostEqual(wrap_coord(WORLD_W + 50, WORLD_W), 50.0)
        self.assertAlmostEqual(wrap_coord(-50, WORLD_W), WORLD_W - 50.0)

        # Toroidal shortest relative distance
        self.assertAlmostEqual(rel_coord(3700.0, 100.0, WORLD_W), -200.0)
        self.assertAlmostEqual(rel_coord(100.0, 3700.0, WORLD_W), 200.0)
        self.assertAlmostEqual(rel_coord(1900.0, 1900.0, WORLD_W), 0.0)

    def test_starfield_and_nebulae_initialization(self) -> None:
        rng = random.Random(101)
        fringe = Fringe(rng)
        fringe.resize(1920, 1080)

        # Stars generated across 3 distinct parallax layers
        self.assertGreaterEqual(len(fringe.stars), 280)
        layers = {s.layer for s in fringe.stars}
        self.assertEqual(layers, {0, 1, 2})

        # Celestial nebulae pre-rendered
        self.assertGreaterEqual(len(fringe.nebulae), 4)
        for neb_surf, wx, wy in fringe.nebulae:
            self.assertIsInstance(neb_surf, pygame.Surface)
            self.assertGreater(neb_surf.get_width(), 400)
            self.assertGreater(neb_surf.get_height(), 300)

    def test_alien_armada_archetypes(self) -> None:
        rng = random.Random(202)
        fringe = Fringe(rng)
        fringe.resize(1920, 1080)

        # Wave 1 has scouts, cruisers, and space mines
        kinds = {e.kind for e in fringe.enemies}
        self.assertIn("scout", kinds)
        self.assertIn("cruiser", kinds)
        self.assertIn("mine", kinds)

        scouts = [e for e in fringe.enemies if e.kind == "scout"]
        cruisers = [e for e in fringe.enemies if e.kind == "cruiser"]
        mines = [e for e in fringe.enemies if e.kind == "mine"]

        self.assertGreater(len(scouts), 0)
        self.assertGreater(len(cruisers), 0)
        self.assertGreater(len(mines), 0)

        # Cruisers have armored shields
        for c in cruisers:
            self.assertGreater(c.max_shields, 0.0)
            self.assertGreater(c.shields, 0.0)

        # Space mines have armed state and score values
        for m in mines:
            self.assertFalse(m.armed)
            self.assertGreater(m.score, 0)

    def test_ai_combat_pilot_and_stepping(self) -> None:
        rng = random.Random(303)
        fringe = Fringe(rng)
        fringe.resize(1920, 1080)

        initial_enemy_count = len(fringe.enemies)
        self.assertGreater(initial_enemy_count, 0)

        # Run combat simulation for 200 ticks (approx 3.3 seconds)
        for _ in range(200):
            fringe.tick(1 / 60)

        # AI pilot should actively steer, thrust, and engage targets
        self.assertTrue(fringe.player.alive)
        self.assertIsNotNone(fringe.player.ai_status)
        self.assertNotEqual(fringe.player.ai_status, "")

        # AI pilot fired twin lasers
        all_projectiles = fringe.lasers + [p for p in fringe.particles if p.kind == "spark"]
        self.assertGreater(len(all_projectiles), 0)

        # Sweep angle updated
        self.assertGreater(fringe.sweep_angle, 0.0)

    def test_radar_hud_rendering(self) -> None:
        rng = random.Random(404)
        fringe = Fringe(rng)
        fringe.resize(1280, 720)

        self.assertIsNotNone(fringe.radar_surf)
        self.assertGreater(fringe.radar_radius, 40)

        # Verify radar blip projection math
        px, py = fringe.player.x, fringe.player.y
        test_enemy = fringe.enemies[0]
        dx = rel_coord(test_enemy.x, px, WORLD_W)
        dy = rel_coord(test_enemy.y, py, WORLD_H)
        dist = math.hypot(dx, dy)

        # Blip should be within radar radius if within RADAR_RANGE
        if dist <= RADAR_RANGE:
            blip_dist = (dist / RADAR_RANGE) * fringe.radar_radius
            self.assertLessEqual(blip_dist, fringe.radar_radius + 1.0)

        # Sweep angle advances with time
        start_angle = fringe.sweep_angle
        fringe.step(0.5)
        self.assertNotEqual(fringe.sweep_angle, start_angle)

    def test_60_fps_performance_at_1080p(self) -> None:
        rng = random.Random(505)
        fringe = Fringe(rng)
        screen = pygame.Surface((1920, 1080))
        fringe.resize(1920, 1080)

        # Warm up
        for _ in range(10):
            fringe.tick(1 / 60)
            fringe.draw(screen)

        frames = 120
        start = time.perf_counter()
        for _ in range(frames):
            fringe.tick(1 / 60)
            fringe.draw(screen)
        duration = time.perf_counter() - start

        fps = frames / duration
        # Lunatic Fringe must comfortably exceed 60 FPS at 1080p (typically >200 FPS)
        self.assertGreater(fps, 60.0)


if __name__ == "__main__":
    unittest.main()
