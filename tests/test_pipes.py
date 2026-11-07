"""Tests for the Pipes 3D pipe-maze module."""

from __future__ import annotations

import os
import random
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from adfresh.modules import BY_ID, CATALOG
from adfresh.modules.base import Module
from adfresh.modules.pipes import (
    GRID_X,
    GRID_Y,
    GRID_Z,
    NUM_SYSTEMS,
    Pipes,
)


def _all_nodes(pipes: Pipes) -> list[tuple[int, int, int]]:
    return [node for system in pipes.systems for node in system.nodes]


class PipesTest(unittest.TestCase):
    def setUp(self) -> None:
        pygame.display.init()
        pygame.font.init()

    def test_module_contract(self) -> None:
        rng = random.Random(42)
        pipes = Pipes(rng)
        self.assertIsInstance(pipes, Module)
        self.assertEqual(pipes.id, "pipes")
        self.assertEqual(pipes.title, "Pipes")
        self.assertIn(Pipes, CATALOG)
        self.assertIs(BY_ID["pipes"], Pipes)

    def test_resize_initialises_scene(self) -> None:
        pipes = Pipes(random.Random(7))
        pipes.resize(1280, 720)
        self.assertEqual(pipes.w, 1280)
        self.assertEqual(pipes.h, 720)
        self.assertEqual(len(pipes.systems), NUM_SYSTEMS)
        self.assertGreaterEqual(NUM_SYSTEMS, 3)
        self.assertLessEqual(NUM_SYSTEMS, 5)
        self.assertIsNotNone(pipes._bg)
        assert pipes._bg is not None
        self.assertIsNotNone(pipes._layer)
        assert pipes._layer is not None
        # The frame is rendered into a (possibly supersampled) layer that
        # covers the requested size, then presented scaled down.
        self.assertEqual(pipes._bg.get_size(), pipes._layer.get_size())
        layer_w, layer_h = pipes._layer.get_size()
        self.assertGreaterEqual(layer_w, 1280)
        self.assertGreaterEqual(layer_h, 720)

        segments = 0
        for system in pipes.systems:
            self.assertGreaterEqual(len(system.nodes), 1)
            self.assertLessEqual(len(system.nodes) - 1, system.max_len)
            for node in system.nodes:
                self.assertTrue(0 <= node[0] < GRID_X)
                self.assertTrue(0 <= node[1] < GRID_Y)
                self.assertTrue(0 <= node[2] < GRID_Z)
            segments += len(system.nodes) - 1
        self.assertGreater(segments, 20, "scene should already show a maze at t=0")

        nodes = _all_nodes(pipes)
        self.assertEqual(len(nodes), len(set(nodes)), "systems must not share grid nodes")
        self.assertEqual(len({system.pal for system in pipes.systems}), NUM_SYSTEMS)

    def test_stepping_grows_and_advances(self) -> None:
        pipes = Pipes(random.Random(11))
        pipes.resize(1280, 720)
        before = sum(len(system.nodes) - 1 for system in pipes.systems)
        for _ in range(20):
            pipes.tick(1 / 30)
        after = sum(len(system.nodes) - 1 for system in pipes.systems)
        self.assertGreater(after, before)
        self.assertAlmostEqual(pipes.t, 20 / 30, places=5)

        for system in pipes.systems:
            self.assertIn(system.state, {"grow", "wait", "fade"})
            self.assertGreaterEqual(system.alpha, 0.0)
            self.assertLessEqual(system.alpha, 1.0)
            for node in system.nodes:
                self.assertTrue(0 <= node[0] < GRID_X)
                self.assertTrue(0 <= node[1] < GRID_Y)
                self.assertTrue(0 <= node[2] < GRID_Z)

    def test_long_run_stays_healthy_and_reseeds(self) -> None:
        pipes = Pipes(random.Random(23))
        pipes.resize(1280, 720)
        screen = pygame.Surface((1280, 720))
        list_ids = [id(system.nodes) for system in pipes.systems]
        seeds = [system.nodes[0] for system in pipes.systems]

        for step in range(1200):  # 20 seconds at 60 fps
            pipes.tick(1 / 60)
            if step % 10 == 0:
                pipes.draw(screen)

        self.assertEqual(len(pipes.systems), NUM_SYSTEMS)
        self.assertGreater(pipes.t, 19.9)
        total = 0
        for system in pipes.systems:
            self.assertGreaterEqual(len(system.nodes), 1)
            self.assertLessEqual(len(system.nodes) - 1, system.max_len)
            self.assertIn(system.state, {"grow", "wait", "fade"})
            self.assertGreaterEqual(system.alpha, 0.0)
            self.assertLessEqual(system.alpha, 1.0)
            for node in system.nodes:
                self.assertTrue(0 <= node[0] < GRID_X)
                self.assertTrue(0 <= node[1] < GRID_Y)
                self.assertTrue(0 <= node[2] < GRID_Z)
            for a, b in system.edges:
                self.assertEqual(abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]), 1)
            total += len(system.nodes) - 1

        self.assertGreater(total, 0)
        self.assertTrue(any(system.state == "grow" for system in pipes.systems))
        nodes = _all_nodes(pipes)
        self.assertEqual(len(nodes), len(set(nodes)), "systems must not share grid nodes")

        # Over 20 seconds at least one run must have ended and reseeded: either
        # the node list was replaced or the seed joint moved.
        reseeded = any(
            id(system.nodes) != list_ids[i] for i, system in enumerate(pipes.systems)
        ) or any(system.nodes[0] != seeds[i] for i, system in enumerate(pipes.systems))
        self.assertTrue(reseeded, "long runs should terminate and reseed")

    def test_renders_rich_shaded_scene(self) -> None:
        pipes = Pipes(random.Random(31))
        pipes.resize(960, 540)
        screen = pygame.Surface((960, 540))
        for _ in range(90):
            pipes.tick(1 / 30)
        pipes.draw(screen)

        colors: set[tuple[int, int, int]] = set()
        bright = 0
        for y in range(0, 540, 4):
            for x in range(0, 960, 4):
                color = screen.get_at((x, y))[:3]
                colors.add(color)
                if max(color) > 90:
                    bright += 1
        self.assertGreater(len(colors), 12)
        self.assertGreater(bright, 300, "pipes should cover a solid part of the frame")
        self.assertNotEqual(tuple(screen.get_at((4, 4))[:3]), (0, 0, 0))

    def test_deterministic_from_seed(self) -> None:
        def build() -> list:
            module = Pipes(random.Random(99))
            module.resize(960, 540)
            for _ in range(150):
                module.tick(1 / 30)
            return [
                [list(system.nodes), list(system.turns), system.dir, system.max_len, system.state]
                for system in module.systems
            ]

        self.assertEqual(build(), build())

    def test_60_fps_performance(self) -> None:
        pipes = Pipes(random.Random(707))
        screen = pygame.Surface((1920, 1080))
        pipes.resize(1920, 1080)

        for _ in range(10):
            pipes.tick(1 / 60)
            pipes.draw(screen)

        frames = 120
        start = time.perf_counter()
        for _ in range(frames):
            pipes.tick(1 / 60)
            pipes.draw(screen)
        duration = time.perf_counter() - start

        fps = frames / duration
        # Must comfortably exceed 60 FPS (typically >150 FPS).
        self.assertGreater(fps, 60.0)


if __name__ == "__main__":
    unittest.main()
