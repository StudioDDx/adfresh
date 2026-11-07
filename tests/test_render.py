"""Render every module once and keep the marbles inside the frame."""

from __future__ import annotations

import os
import tempfile
import unittest

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "1"

from adfresh.engine import build_playlist, render_previews  # noqa: E402
from adfresh.modules import CATALOG  # noqa: E402
from adfresh.modules.marbles import Marbles  # noqa: E402
import random  # noqa: E402


class RenderTest(unittest.TestCase):
    def test_playlist_starts_with_toasters_and_stays_shared(self) -> None:
        one = build_playlist(12345.0, None)
        two = build_playlist(12345.0, None)
        self.assertEqual(one[0], "toasters")
        self.assertEqual(one, two)
        self.assertEqual(len(one), len(CATALOG))
        self.assertEqual(build_playlist(1.0, "rain"), ["rain"])
        self.assertEqual(
            build_playlist(12345.0, None, [cls.id for cls in CATALOG]),
            one,
        )
        subset = build_playlist(12345.0, None, ["warp", "toasters", "rain"])
        self.assertEqual(subset[0], "toasters")
        self.assertEqual(set(subset), {"toasters", "rain", "warp"})
        self.assertEqual(subset, build_playlist(12345.0, None, ["rain", "warp", "toasters"]))
        self.assertEqual(build_playlist(1.0, "rain", ["toasters"]), ["rain"])
        self.assertEqual(build_playlist(1.0, None, ["nope"])[0], "toasters")

    def test_marbles_stay_in_frame(self) -> None:
        import pygame

        pygame.display.init()
        pygame.display.set_mode((640, 360))
        module = Marbles(random.Random(7))
        module.resize(640, 360)
        for _ in range(90):
            module.tick(1 / 30)
        self.assertTrue(module.contained())

    def test_previews_are_pictures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            render_previews(directory, (960, 540), steps=36)
            names = sorted(os.listdir(directory))
            pngs = [name for name in names if name.endswith(".png") and name[:2].isdigit()]
            self.assertEqual(len(pngs), len(CATALOG))
            for name in pngs:
                path = os.path.join(directory, name)
                self.assertGreater(os.path.getsize(path), 2500, name)


if __name__ == "__main__":
    unittest.main()
