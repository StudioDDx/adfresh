"""Tests for the sprite-map exporter (adfresh.export)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from adfresh import export, sprites
from adfresh.sprites import WING_FRAMES

TOAST_KINDS = ("plain", "butter", "jam", "dark")
TOASTER_WIDTH = 120
TOAST_WIDTH = 80


def _pixels(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGBA")


class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.display.init()
        pygame.font.init()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name) / "sprites"

    def _toaster(self) -> dict:
        return export.export_toaster_atlas(self.directory, width=TOASTER_WIDTH)

    def _toast(self, kind: str = "plain") -> dict:
        return export.export_toast_kind_atlas(
            self.directory, kind, width=TOAST_WIDTH
        )

    # ------------------------------------------------------------------ #
    # Flying toasters
    # ------------------------------------------------------------------ #
    def test_toaster_atlas_is_a_pixel_exact_frame_grid(self) -> None:
        result = self._toaster()
        atlas = pygame.image.load(str(result["atlas"]))
        frame_w, frame_h = result["frame_size"]
        self.assertEqual(atlas.get_size(), (frame_w * 4, frame_h * 4))
        self.assertEqual(atlas.get_at((0, 0)).a, 0, "cell corner must be transparent")
        for frame in range(WING_FRAMES):
            column = frame % 4
            row = frame // 4
            cell = atlas.subsurface(
                pygame.Rect(column * frame_w, row * frame_h, frame_w, frame_h)
            )
            expected = sprites.toaster(frame, TOASTER_WIDTH)
            self.assertEqual(_pixels(cell), _pixels(expected), f"frame {frame}")

    def test_toaster_metadata_map(self) -> None:
        result = self._toaster()
        data = json.loads(result["metadata"].read_text(encoding="utf-8"))
        self.assertEqual(data["atlas"]["frame_count"], WING_FRAMES)
        self.assertEqual(len(data["frames"]), WING_FRAMES)
        frame_w, frame_h = data["atlas"]["frame_size"]
        for frame in data["frames"]:
            x, y, w, h = frame["rect"]
            self.assertEqual((w, h), (frame_w, frame_h))
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, frame_w * 4)
            self.assertLessEqual(y + h, frame_h * 4)
            self.assertGreater(frame["near"]["scale"], 0)
            self.assertGreater(frame["far"]["scale"], 0)

        # The far wing tucks toward the body on the downstroke and is further
        # from the body at the top of the upstroke.
        up = data["frames"][WING_FRAMES // 4]
        down = data["frames"][3 * WING_FRAMES // 4]
        self.assertEqual(up["far"]["tuck"], 0.0)
        self.assertGreater(down["far"]["tuck"], 0.9)
        self.assertGreater(down["far"]["anchor"][0], up["far"]["anchor"][0])
        self.assertGreater(down["far"]["anchor"][1], up["far"]["anchor"][1])

        # The wings beat in mirror phase around their own rest angles; the far
        # wing sweeps a wider arc (its own amplitude), so compare each side to
        # its own amplitude rather than assuming equal amplitudes.
        near_base = data["parameters"]["near_base"]
        far_base = data["parameters"]["far_base"]
        near_amp = data["parameters"]["amp"]
        far_amp_up = data["parameters"]["far_amp_up"]
        far_amp_down = data["parameters"]["far_amp_down"]
        for frame in data["frames"]:
            phase = frame["phase"]
            far_amp = far_amp_up if phase >= 0.0 else far_amp_down
            self.assertAlmostEqual(
                frame["near"]["angle_deg"] - near_base,
                near_amp * phase,
                places=2,
            )
            self.assertAlmostEqual(
                frame["far"]["angle_deg"] - far_base,
                -far_amp * phase,
                places=2,
            )

        # Pivots sit inside the (scaled) wing layers.
        for frame in data["frames"]:
            for side in ("near", "far"):
                wing = frame[side]
                pivot = wing["pivot"]
                layer_w, layer_h = wing["layer_size"]
                self.assertTrue(0 <= pivot[0] <= layer_w)
                self.assertTrue(0 <= pivot[1] <= layer_h)

    # ------------------------------------------------------------------ #
    # Flying toast (per topping)
    # ------------------------------------------------------------------ #
    def test_plain_toast_atlas_is_a_pixel_exact_frame_grid(self) -> None:
        result = self._toast("plain")
        self.assertEqual(result["kind"], "plain")
        atlas = pygame.image.load(str(result["atlas"]))
        frame_w, frame_h = result["frame_size"]
        self.assertEqual(atlas.get_size(), (frame_w * 4, frame_h * 4))
        self.assertEqual(atlas.get_at((0, 0)).a, 0)
        for frame in range(WING_FRAMES):
            column = frame % 4
            row = frame // 4
            cell = atlas.subsurface(
                pygame.Rect(column * frame_w, row * frame_h, frame_w, frame_h)
            )
            expected = sprites.toast("plain", frame, TOAST_WIDTH)
            self.assertEqual(_pixels(cell), _pixels(expected), f"frame {frame}")

    def test_plain_toast_metadata_and_preview(self) -> None:
        result = self._toast("plain")
        self.assertTrue(Path(result["preview"]).is_file())
        self.assertGreater(Path(result["preview"]).stat().st_size, 1000)
        data = json.loads(result["metadata"].read_text(encoding="utf-8"))
        self.assertEqual(data["kind"], "plain")
        self.assertEqual(data["atlas"]["frame_count"], WING_FRAMES)
        self.assertEqual(len(data["frames"]), WING_FRAMES)
        self.assertEqual(data["kind_geometry"]["tilt_deg"], 20.0)
        for frame in data["frames"]:
            self.assertGreater(frame["near"]["scale"], 0)
            self.assertGreater(frame["far"]["scale"], 0)
        up = data["frames"][WING_FRAMES // 4]
        down = data["frames"][3 * WING_FRAMES // 4]
        self.assertEqual(up["far"]["tuck"], 0.0)
        self.assertGreater(down["far"]["tuck"], 0.9)
        self.assertGreater(down["far"]["anchor"][1], up["far"]["anchor"][1])

    def test_each_toast_kind_exports_and_renders(self) -> None:
        for kind in TOAST_KINDS:
            with self.subTest(kind=kind):
                result = self._toast(kind)
                atlas = pygame.image.load(str(result["atlas"]))
                frame_w, frame_h = result["frame_size"]
                cell = atlas.subsurface(pygame.Rect(0, 0, frame_w, frame_h))
                self.assertEqual(_pixels(cell), _pixels(sprites.toast(kind, 0, TOAST_WIDTH)))
                self.assertTrue(Path(result["atlas"]).name.startswith(f"toast-{kind}-"))
        with self.assertRaises(ValueError):
            export.export_toast_kind_atlas(self.directory, "marmalade")

    # ------------------------------------------------------------------ #
    # Whole export
    # ------------------------------------------------------------------ #
    def test_export_all_defaults_to_toaster_and_plain_toast(self) -> None:
        written = export.export_all(self.directory)
        names = {Path(path).name for path in written}
        self.assertEqual(
            names,
            {
                "toaster-sprite-map.png",
                "toaster-sprite-map-preview.png",
                "toaster-sprite-map.json",
                "toast-plain-sprite-map.png",
                "toast-plain-sprite-map-preview.png",
                "toast-plain-sprite-map.json",
                "README.md",
            },
        )
        for path in written:
            self.assertTrue(Path(path).is_file(), path)
            self.assertGreater(Path(path).stat().st_size, 100, path)
        readme = (self.directory / "README.md").read_text(encoding="utf-8")
        self.assertIn("scripts/export_sprites.py", readme)
        self.assertIn("toaster-sprite-map.png", readme)
        self.assertIn("toast-plain-sprite-map.png", readme)
        self.assertIn("--all-toasts", readme)

    def test_export_all_can_add_more_toast_kinds(self) -> None:
        written = export.export_all(
            self.directory, toast_kinds=("plain", "butter", "jam")
        )
        names = {Path(path).name for path in written}
        for kind in ("plain", "butter", "jam"):
            self.assertIn(f"toast-{kind}-sprite-map.png", names)
        self.assertNotIn("toast-dark-sprite-map.png", names)
        readme = (self.directory / "README.md").read_text(encoding="utf-8")
        self.assertIn("dark", readme)  # missing kinds are listed

    def test_export_is_deterministic(self) -> None:
        first = export.export_toast_kind_atlas(
            self.directory / "a", "plain", width=TOAST_WIDTH
        )
        second = export.export_toast_kind_atlas(
            self.directory / "b", "plain", width=TOAST_WIDTH
        )
        self.assertEqual(
            json.loads(Path(first["metadata"]).read_text(encoding="utf-8")),
            json.loads(Path(second["metadata"]).read_text(encoding="utf-8")),
        )
        atlas_a = pygame.image.load(str(first["atlas"]))
        atlas_b = pygame.image.load(str(second["atlas"]))
        self.assertEqual(_pixels(atlas_a), _pixels(atlas_b))


if __name__ == "__main__":
    unittest.main()
