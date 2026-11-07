"""Tests for the layered wing/body sprite composition (adfresh.sprites).

These cover the contract that the toasters module relies on:
* the public sprite API returns stable sizes for every flap frame (no breathing),
* the derived body/wing layers exist for every family and the legacy sheet PNGs
  are still present (the composition is additive, never destructive),
* the body raster is identical between flap frames (no shimmer),
* near/far wings are layered at the expected scales (far wing smaller and dimmer),
* composing sprites stays comfortably above 60 fps.
"""

from __future__ import annotations

import math
import os
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np
import pygame

from adfresh import sprites
from adfresh.sprites import WING_FRAMES

TOAST_KINDS = ("plain", "butter", "jam", "dark")


def _brightness(surface: pygame.Surface) -> float:
    """Mean RGB brightness of the opaque part of an alpha surface."""
    total = 0.0
    count = 0
    width, height = surface.get_size()
    for x in range(0, width, 3):
        for y in range(0, height, 3):
            r, g, b, a = surface.get_at((x, y))
            if a > 160:
                total += 0.299 * r + 0.587 * g + 0.114 * b
                count += 1
    return total / max(1, count)


class SpritesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.display.init()
        pygame.font.init()
        # Force a fresh cache so cold-composition timings are meaningful.
        sprites._toasters.clear()
        sprites._toasts.clear()
        sprites._toaster_parts.clear()
        sprites._toast_parts.clear()

    # ------------------------------------------------------------------ #
    # Assets / layers
    # ------------------------------------------------------------------ #
    def test_layers_exist_for_every_family(self) -> None:
        assets = sprites.ASSETS_DIR
        self.assertTrue((assets / "wing_master.png").is_file())
        self.assertTrue((assets / "body_toaster.png").is_file())
        for kind in TOAST_KINDS:
            self.assertTrue((assets / f"body_toast_{kind}.png").is_file(), kind)

        meta = sprites._meta()
        pivot = meta["wing"]["pivot"]
        self.assertEqual(len(pivot), 2)
        wing = pygame.image.load(str(assets / "wing_master.png"))
        self.assertTrue(0 <= pivot[0] <= wing.get_width())
        self.assertTrue(0 <= pivot[1] <= wing.get_height())

        for kind in TOAST_KINDS:
            info = meta["toast"][kind]
            width, height = info["size"]
            for anchor in (info["near_anchor"], info["far_anchor"]):
                self.assertTrue(0 <= anchor[0] <= width, kind)
                self.assertTrue(0 <= anchor[1] <= height, kind)
            self.assertGreater(info["bread_w"], 0)
            self.assertLess(info["near_anchor"][0], info["far_anchor"][0])

    def test_original_sheet_assets_are_preserved(self) -> None:
        # The new layers are generated FROM these; they must never be deleted.
        for frame in range(WING_FRAMES):
            self.assertTrue((sprites.ASSETS_DIR / f"toaster_{frame}.png").is_file())
            for kind in TOAST_KINDS:
                self.assertTrue(
                    (sprites.ASSETS_DIR / f"toast_{kind}_{frame}.png").is_file()
                )

    # ------------------------------------------------------------------ #
    # API stability
    # ------------------------------------------------------------------ #
    def test_sprite_sizes_are_identical_across_all_frames(self) -> None:
        for width in (48, 100, 160, 244):
            sizes = {sprites.toaster(frame, width).get_size() for frame in range(WING_FRAMES)}
            self.assertEqual(len(sizes), 1, f"toaster width={width} sizes={sizes}")
            size = sizes.pop()
            self.assertEqual(size[0], width)
            # 600x668 source body aspect ratio.
            self.assertAlmostEqual(size[1], width * 668 / 600, delta=1.5)

        for kind in TOAST_KINDS:
            sizes = {
                sprites.toast(kind, frame, 144).get_size() for frame in range(WING_FRAMES)
            }
            self.assertEqual(len(sizes), 1, f"{kind} sizes={sizes}")
            size = sizes.pop()
            self.assertEqual(size[0], 144)
            self.assertGreater(size[1], 0)

        # All kinds share the same canvas -> same aspect at the same width.
        aspects = {
            round(sprites.toast(kind, 0, 144).get_height() / 146, 3)
            for kind in TOAST_KINDS
        }
        self.assertEqual(len(aspects), 1, aspects)

    def test_frame_index_wraps_and_unknown_kind_falls_back(self) -> None:
        self.assertEqual(
            sprites.toaster(0, 120).get_size(), sprites.toaster(WING_FRAMES, 120).get_size()
        )
        self.assertIs(sprites.toaster(0, 120), sprites.toaster(WING_FRAMES * 2, 120))
        fallback = sprites.toast("marmalade", 3, 100)
        plain = sprites.toast("plain", 3, 100)
        self.assertEqual(fallback.get_size(), plain.get_size())

    # ------------------------------------------------------------------ #
    # Body stability (no shimmer / drift between frames)
    # ------------------------------------------------------------------ #
    def test_toaster_body_pixels_are_stable_between_frames(self) -> None:
        width = 200
        frames = [sprites.toaster(frame, width) for frame in range(WING_FRAMES)]
        height = frames[0].get_height()
        # Front face / lower shell: never covered by either wing.  The body is
        # centred inside the frame (``body_scale``), so the probes live around
        # the middle of the canvas rather than the lower-left corner.
        probes = ((0.26, 0.58), (0.30, 0.62), (0.28, 0.66), (0.32, 0.56))
        for fx, fy in probes:
            point = (int(fx * width), int(fy * height))
            reference = frames[0].get_at(point)
            self.assertGreaterEqual(reference.a, 250, f"probe {point} not opaque")
            for index, frame in enumerate(frames):
                self.assertEqual(
                    frame.get_at(point),
                    reference,
                    f"toaster body pixel {point} changed on frame {index}",
                )

    def test_toast_body_pixels_are_stable_between_frames(self) -> None:
        width = 144
        for kind in TOAST_KINDS:
            frames = [sprites.toast(kind, frame, width) for frame in range(WING_FRAMES)]
            parts = sprites._toast_layer_parts(kind, width)
            self.assertIsNotNone(parts)
            _size, body, body_pos = parts[0], parts[1], parts[2]
            body_width, body_height = body.get_size()
            # Sample the bread face clear of both wing roots (the near wing
            # sweeps across the left shoulder; the far wing is behind the body).
            probes = [
                (
                    int(body_pos[0] + fx * body_width),
                    int(body_pos[1] + fy * body_height),
                )
                for fx, fy in ((0.50, 0.45), (0.53, 0.60), (0.62, 0.40), (0.56, 0.55))
            ]
            for point in probes:
                if not (0 <= point[0] < width and 0 <= point[1] < frames[0].get_height()):
                    continue
                reference = frames[0].get_at(point)
                self.assertGreaterEqual(
                    reference.a, 200, f"{kind} probe {point} not opaque"
                )
                for index, frame in enumerate(frames):
                    self.assertEqual(
                        frame.get_at(point),
                        reference,
                        f"{kind} body pixel {point} changed on frame {index}",
                    )

    def test_flap_animates_the_wings(self) -> None:
        frames = [sprites.toaster(frame, 200) for frame in range(WING_FRAMES)]
        signatures = {pygame.image.tobytes(frame, "RGBA") for frame in frames}
        self.assertGreaterEqual(len(signatures), 8)
        self.assertNotEqual(
            pygame.image.tobytes(frames[0], "RGBA"),
            pygame.image.tobytes(frames[4], "RGBA"),
        )

    # ------------------------------------------------------------------ #
    # Near / far layering
    # ------------------------------------------------------------------ #
    def test_wings_flap_as_a_mirrored_pair(self) -> None:
        """Both wing tips must rise and fall together, on opposite sides.

        A bird whose near wing flaps up/down while the far wing swivels
        sideways cannot fly.  Regression guard for the far-wing mirror fix:
        the far wing must be the mirrored near wing and flap in mirror phase.
        We track the wing-tip displacement (the alpha pixel farthest from the
        shoulder pivot, after the same rotation + foreshortening the composer
        applies) and require strongly correlated vertical motion plus opposite
        horizontal directions.
        """

        def tip_offset(
            layer: pygame.Surface,
            pivot: tuple[float, float],
            angle: float,
            scale: float,
        ) -> tuple[float, float]:
            scaled, scaled_pivot = sprites._scale_about_pivot(layer, pivot, scale)
            rotated, rotated_pivot = sprites._rotate_about(
                scaled, angle, scaled_pivot
            )
            alpha = pygame.surfarray.array_alpha(rotated)
            xs, ys = np.where(alpha > 40)
            distances = (xs - rotated_pivot[0]) ** 2 + (ys - rotated_pivot[1]) ** 2
            index = int(np.argmax(distances))
            return (
                float(xs[index] - rotated_pivot[0]),
                float(ys[index] - rotated_pivot[1]),
            )

        def correlation(a: list[float], b: list[float]) -> float:
            n = len(a)
            mean_a = sum(a) / n
            mean_b = sum(b) / n
            cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
            var_a = sum((x - mean_a) ** 2 for x in a)
            var_b = sum((y - mean_b) ** 2 for y in b)
            return cov / ((var_a * var_b) ** 0.5)

        def check(parts, near_index, far_index, pivot_index, angle_of, scale_of) -> None:
            near = parts[near_index]
            far = parts[far_index]
            near_pivot = parts[pivot_index]
            far_pivot = parts[pivot_index + 3]
            near_ys: list[float] = []
            far_ys: list[float] = []
            near_x = far_x = 0.0
            for frame in range(WING_FRAMES):
                near_angle, far_angle = angle_of(frame)
                near_scale, far_scale = scale_of(frame)
                nx, ny = tip_offset(near, near_pivot, near_angle, near_scale)
                fx, fy = tip_offset(far, far_pivot, far_angle, far_scale)
                near_x, far_x = nx, fx
                near_ys.append(ny)
                far_ys.append(fy)
            # Opposite sides of the body: one wing points left, the other right.
            self.assertLess(near_x * far_x, 0.0, (near_x, far_x))
            corr = correlation(near_ys, far_ys)
            self.assertGreater(corr, 0.9, f"wing tips are not in mirror phase: {corr:.3f}")

        toaster = sprites._toaster_layer_parts(240)
        self.assertIsNotNone(toaster)
        amp = sprites.TOASTER["amp"]

        def toaster_angles(frame: int):
            phase = math.sin(frame / WING_FRAMES * 2 * math.pi)
            flap = amp * phase
            far_amp = (
                sprites.TOASTER["far_amp_up"]
                if phase >= 0.0
                else sprites.TOASTER["far_amp_down"]
            )
            return (
                sprites.TOASTER["near_base"] + flap,
                sprites.TOASTER["far_base"] - far_amp * phase,
            )

        def toaster_scales(frame: int) -> tuple[float, float]:
            phase = math.sin(frame / WING_FRAMES * 2 * math.pi)
            return (
                1.0 - sprites.TOASTER["near_fore"] * phase,
                1.0 + sprites.TOASTER["far_fore"] * phase,
            )

        check(toaster, 1, 4, 2, toaster_angles, toaster_scales)

        toast = sprites._toast_layer_parts("plain", 300)
        self.assertIsNotNone(toast)
        near_base, far_base = toast[10], toast[11]
        toast_amp = sprites.TOAST["amp"]

        def toast_angles(frame: int):
            flap = toast_amp * math.sin(frame / WING_FRAMES * 2 * math.pi)
            return near_base - flap, far_base + flap

        def toast_scales(frame: int) -> tuple[float, float]:
            phase = math.sin(frame / WING_FRAMES * 2 * math.pi)
            return (
                1.0 - sprites.TOAST["near_fore"] * phase,
                1.0 + sprites.TOAST["far_fore"] * phase,
            )

        check(toast, 3, 6, 4, toast_angles, toast_scales)

    def test_wingbeat_poses_and_downstroke_far_wing_occlusion(self) -> None:
        """Upstroke and downstroke must be visually distinct, and the far wing
        should be most exposed at the top of the upstroke and sink behind the
        body on the downstroke (a 3D beat, not a flat screen-space swivel)."""
        width = 300
        frames = [sprites.toaster(frame, width) for frame in range(WING_FRAMES)]
        height = frames[0].get_height()

        up = pygame.image.tobytes(frames[4], "RGBA")
        down = pygame.image.tobytes(frames[12], "RGBA")
        self.assertNotEqual(up, down)

        import numpy as np

        def far_visible(frame: pygame.Surface) -> int:
            alpha = pygame.surfarray.array_alpha(frame)  # (w, h)
            window = alpha[: int(width * 0.5), : int(height * 0.42)]
            return int((window > 40).sum())

        up_area = far_visible(frames[4])
        down_area = far_visible(frames[12])
        self.assertGreater(
            up_area,
            down_area * 1.15,
            f"far wing should be exposed on the upstroke: up={up_area} down={down_area}",
        )

        # The two extreme poses change a meaningful part of the sprite.
        a = np.frombuffer(up, dtype=np.uint8).reshape(-1, 4).astype(int)
        b = np.frombuffer(down, dtype=np.uint8).reshape(-1, 4).astype(int)
        changed = float((np.abs(a - b).sum(axis=1) > 20).mean())
        self.assertGreater(changed, 0.10, f"poses too similar: {changed:.3f}")

    def test_far_wing_is_smaller_and_dimmer_than_near_wing(self) -> None:
        parts = sprites._toaster_layer_parts(200)
        self.assertIsNotNone(parts)
        _body, near, near_pivot, _shadow, far, far_pivot, _na, _fa = parts
        ratio = far.get_width() / near.get_width()
        self.assertAlmostEqual(ratio, sprites.TOASTER["far_scale"], delta=0.03)
        self.assertLess(_brightness(far), _brightness(near) * 0.95)
        for pivot, layer in ((near_pivot, near), (far_pivot, far)):
            self.assertTrue(0 <= pivot[0] <= layer.get_width())
            self.assertTrue(0 <= pivot[1] <= layer.get_height())

        for kind in TOAST_KINDS:
            toast_parts = sprites._toast_layer_parts(kind, 144)
            self.assertIsNotNone(toast_parts)
            near = toast_parts[3]
            far = toast_parts[6]
            ratio = far.get_width() / near.get_width()
            self.assertAlmostEqual(ratio, sprites.TOAST["far_scale"], delta=0.03)
            far_b = _brightness(far)
            near_b = _brightness(near)
            # The far wing is behind the bread, so it is slightly dimmer, but
            # the revised toast keeps it close to the near wing's brightness.
            self.assertLess(far_b, near_b, kind)
            self.assertGreater(far_b, near_b * 0.85, kind)

    def test_composed_frames_have_transparent_margins(self) -> None:
        # At the widths the module actually renders, the wings must be fully
        # inside the sprite canvas (no chopped tips).  Tiny widths (<140px) are
        # excluded: the source body plate itself sits flush with the canvas edge
        # and resampling leaves a 1px fringe there, which is invisible in-game.
        def edge_alpha(image: pygame.Surface) -> int:
            width, height = image.get_size()
            worst = max(image.get_at((x, 0)).a for x in range(width))
            worst = max(worst, max(image.get_at((x, height - 1)).a for x in range(width)))
            worst = max(worst, max(image.get_at((0, y)).a for y in range(height)))
            worst = max(worst, max(image.get_at((width - 1, y)).a for y in range(height)))
            return worst

        for width in (140, 200, 244):
            for frame in (0, 4, 8, 12):
                self.assertEqual(
                    edge_alpha(sprites.toaster(frame, width)), 0, f"toaster {width}"
                )
        for kind in TOAST_KINDS:
            for width in (100, 144, 184):
                for frame in (0, 4, 8, 12):
                    self.assertEqual(
                        edge_alpha(sprites.toast(kind, frame, width)),
                        0,
                        f"{kind} {width}",
                    )

    # ------------------------------------------------------------------ #
    # Performance
    # ------------------------------------------------------------------ #
    def test_60fps_composer_performance(self) -> None:
        # Cold: compose every frame for a handful of sizes of both families.
        start = time.perf_counter()
        for width in (88, 120, 152, 188, 220):
            for frame in range(WING_FRAMES):
                sprites.toaster(frame, width)
        for kind in TOAST_KINDS:
            for width in (72, 108, 146, 184):
                for frame in range(WING_FRAMES):
                    sprites.toast(kind, frame, width)
        cold = time.perf_counter() - start
        sprites_composed = 5 * WING_FRAMES + len(TOAST_KINDS) * 4 * WING_FRAMES
        self.assertLess(cold, 5.0, f"cold composition too slow: {cold:.2f}s")
        self.assertLess(cold / sprites_composed, 0.01)

        # Warm: a full 1080p frame of cached sprites must run far above 60 fps.
        screen = pygame.Surface((1920, 1080))
        flyers = [
            ("toaster", 88 + (i % 12) * 12, i % WING_FRAMES) for i in range(14)
        ] + [
            (TOAST_KINDS[i % 4], 72 + (i % 8) * 12, (i * 3) % WING_FRAMES)
            for i in range(8)
        ]
        frames = 180
        start = time.perf_counter()
        for step in range(frames):
            for kind, width, base_frame in flyers:
                frame = (base_frame + step) % WING_FRAMES
                if kind == "toaster":
                    image = sprites.toaster(frame, width)
                else:
                    image = sprites.toast(kind, frame, width)
                screen.blit(image, (step % 64, step % 32))
        elapsed = time.perf_counter() - start
        fps = frames / elapsed
        self.assertGreater(fps, 60.0, f"warm sprite loop only {fps:.1f} fps")


if __name__ == "__main__":
    unittest.main()
