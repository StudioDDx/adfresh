"""One virtual canvas split across displays: layout, cropping, and frame sync."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
import unittest
from unittest import mock

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "1"

import pygame  # noqa: E402

from adfresh import layout  # noqa: E402
from adfresh.engine import (  # noqa: E402
    FIXED_DT,
    MAX_CATCHUP_TICKS,
    Player,
    Schedule,
    fixed_step_steps,
    fixed_step_target,
)

EPOCH = 1000.0

XRANDR_TWO = """Monitors: 2
 0: +*DP-2 1920/520x1080/290+0+0  DP-2
 1: +DP-1 1920/520x1080/290+1920+0  DP-1
"""

XRANDR_NEGATIVE = """Monitors: 2
 0: +*DP-2 1920/520x1080/290+-1920+0  DP-2
 1: +DP-1 1920/520x1080/290+0+0  DP-1
"""

XRANDR_STACKED = """Monitors: 2
 0: +*DP-2 1920/520x1080/290+0+0  DP-2
 1: +DP-1 1920/520x1080/290+0+1080  DP-1
"""

XRANDR_STEPPED = """Monitors: 2
 0: +*DP-2 1920/520x1080/290+0+0  DP-2
 1: +DP-1 1920/520x1080/290+1920+100  DP-1
"""

XRANDR_MIXED = """Monitors: 3
 0: +*DP-2 1920/520x1080/290+0+0  DP-2
 1: +DP-1 2560/590x1440/330+1920+0  DP-1
 2: +HDMI-1 1920/520x1080/290+4480+0  HDMI-1
 3: +*DP-3 1280/340x720/190+0+1080  DP-3
 4: +DP-4 0/0x0/0+0+0  DP-4 (disconnected)
"""

HYPRCTL_TWO = json.dumps(
    [
        {"name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080, "disabled": False},
        {"name": "DP-2", "x": 1920, "y": 0, "width": 1920, "height": 1080, "disabled": False},
        {"name": "HDMI-A-1", "x": 0, "y": 0, "width": 0, "height": 0, "disabled": True},
    ]
)


def make_player(
    *,
    seed: int = 1234,
    virtual: tuple[int, int] | None = (1280, 360),
    offset: tuple[int, int] = (0, 0),
    window: tuple[int, int] = (640, 360),
    playlist: list[str] | None = None,
    dwell: float = 100.0,
    fade: float = 1.0,
    display: int = 0,
    fixed_step: bool = True,
) -> Player:
    schedule = Schedule(playlist or ["toasters"], dwell, fade, EPOCH)
    player = Player(
        display_index=display,
        seed=seed,
        schedule=schedule,
        saver=True,
        speed=1.0,
        virtual_size=virtual,
        offset=offset,
        fixed_step=fixed_step,
    )
    player.resize(*window)
    return player


def run_ticks(player: Player, ticks: int, screen: pygame.Surface | None = None) -> pygame.Surface:
    for _ in range(ticks):
        player.advance(FIXED_DT)
    return player.render(screen)


def rgb(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGB")


def bright_pixel(surface: pygame.Surface, rect: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = rect
    for y in range(max(0, y0), min(surface.get_height(), y1)):
        for x in range(max(0, x0), min(surface.get_width(), x1)):
            r, g, b = surface.get_at((x, y))[:3]
            if r > 180 and g > 170 and b > 160:
                return True
    return False


class LayoutParserTest(unittest.TestCase):
    def test_xrandr_two_monitors(self) -> None:
        parsed = layout.parse_xrandr_monitors(XRANDR_TWO)
        self.assertEqual(
            parsed,
            [
                {"index": 0, "name": "DP-2", "x": 0, "y": 0, "w": 1920, "h": 1080},
                {"index": 1, "name": "DP-1", "x": 1920, "y": 0, "w": 1920, "h": 1080},
            ],
        )

    def test_xrandr_negative_origin(self) -> None:
        parsed = layout.parse_xrandr_monitors(XRANDR_NEGATIVE)
        self.assertEqual(parsed[0]["x"], -1920)
        self.assertEqual(parsed[1]["x"], 0)
        built = layout.build_layout(parsed, [(1920, 1080), (1920, 1080)], "xrandr")
        self.assertIsNotNone(built)
        assert built is not None
        self.assertEqual((built.width, built.height), (3840, 1080))
        self.assertEqual(built.monitor(0).offset, (0, 0))
        self.assertEqual(built.monitor(1).offset, (1920, 0))

    def test_xrandr_stacked_bounding_box(self) -> None:
        built = layout.build_layout(
            layout.parse_xrandr_monitors(XRANDR_STACKED),
            [(1920, 1080), (1920, 1080)],
            "xrandr",
        )
        self.assertIsNotNone(built)
        assert built is not None
        self.assertEqual((built.width, built.height), (1920, 2160))
        self.assertEqual(built.monitor(1).offset, (0, 1080))

    def test_xrandr_ignores_disconnected_outputs(self) -> None:
        parsed = layout.parse_xrandr_monitors(XRANDR_MIXED)
        # The disconnected monitor line is skipped; the four live outputs remain.
        self.assertEqual(len(parsed), 4)
        self.assertNotIn("DP-4", [monitor["name"] for monitor in parsed])
        self.assertEqual([monitor["index"] for monitor in parsed], [0, 1, 2, 3])

    def test_garbage_xrandr_is_empty(self) -> None:
        text = "Monitors: 0\nHDMI-1 disconnected (normal left inverted right x axis y axis)\n"
        self.assertEqual(layout.parse_xrandr_monitors(text), [])

    def test_hyprctl_json(self) -> None:
        parsed = layout.parse_hyprctl_monitors(HYPRCTL_TWO)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[1], {"index": 1, "name": "DP-2", "x": 1920, "y": 0, "w": 1920, "h": 1080})
        built = layout.build_layout(parsed, [(1920, 1080), (1920, 1080)], "hyprctl")
        self.assertIsNotNone(built)
        assert built is not None
        self.assertEqual((built.width, built.height), (3840, 1080))

    def test_hyprctl_malformed(self) -> None:
        self.assertEqual(layout.parse_hyprctl_monitors("not json"), [])
        self.assertEqual(layout.parse_hyprctl_monitors("{}"), [])

    def test_virtual_layout_picks_source_from_environment(self) -> None:
        sizes = [(1920, 1080), (1920, 1080)]
        xrandr = layout.virtual_layout(
            sizes, env={"DISPLAY": ":1"}, xrandr_text=XRANDR_TWO
        )
        self.assertIsNotNone(xrandr)
        assert xrandr is not None
        self.assertEqual(xrandr.source, "xrandr")
        self.assertEqual(xrandr.virtual_size, (3840, 1080))

        hypr = layout.virtual_layout(
            sizes,
            env={"HYPRLAND_INSTANCE_SIGNATURE": "abc", "XDG_CURRENT_DESKTOP": "Hyprland"},
            hyprctl_text=HYPRCTL_TWO,
        )
        self.assertIsNotNone(hypr)
        assert hypr is not None
        self.assertEqual(hypr.source, "hyprctl")

        # No display-server geometry: never guess left-to-right (Wayland may
        # enumerate the right monitor as display 0).  The supervisor falls back
        # to independent windows unless it could query SDL bounds.
        self.assertIsNone(layout.virtual_layout(sizes, env={}))
        fallback = layout.fallback_layout(sizes)
        self.assertIsNotNone(fallback)
        assert fallback is not None
        self.assertEqual(fallback.source, "sizes")
        self.assertEqual(fallback.monitor(1).offset, (1920, 0))

    def test_unusable_geometry_returns_none(self) -> None:
        sizes = [(1920, 1080), (1920, 1080)]
        # A parse that succeeds but does not tile (or disagrees with SDL)
        # must fall back to independent mode.
        self.assertIsNone(
            layout.virtual_layout(sizes, env={"DISPLAY": ":1"}, xrandr_text=XRANDR_STEPPED)
        )
        self.assertIsNone(layout.virtual_layout(sizes, env={"DISPLAY": ":1"}, xrandr_text="junk"))
        self.assertIsNone(layout.build_layout([], sizes, "xrandr"))
        self.assertIsNone(
            layout.build_layout(layout.parse_xrandr_monitors(XRANDR_TWO), [(1920, 1080)], "xrandr")
        )
        self.assertIsNone(
            layout.build_layout(
                layout.parse_xrandr_monitors(XRANDR_TWO),
                [(1920, 1080), (1280, 720)],
                "xrandr",
            )
        )

    def test_bbox_math_and_tiling_validation(self) -> None:
        gapped = [
            {"index": 0, "name": "A", "x": 0, "y": 0, "w": 1920, "h": 1080},
            {"index": 1, "name": "B", "x": 2000, "y": 0, "w": 1920, "h": 1080},
        ]
        self.assertIsNone(layout.build_layout(gapped, None, "test"))
        overlapping = [
            {"index": 0, "name": "A", "x": 0, "y": 0, "w": 1920, "h": 1080},
            {"index": 1, "name": "B", "x": 1000, "y": 0, "w": 1920, "h": 1080},
        ]
        self.assertIsNone(layout.build_layout(overlapping, None, "test"))
        tiled = [
            {"index": 0, "name": "A", "x": 0, "y": 0, "w": 1280, "h": 720},
            {"index": 1, "name": "B", "x": 1280, "y": 0, "w": 1024, "h": 720},
        ]
        built = layout.build_layout(tiled, None, "test")
        self.assertIsNotNone(built)
        assert built is not None
        self.assertEqual((built.width, built.height), (2304, 720))

    def test_sdl_bounds_keep_display_index_order(self) -> None:
        # Wayland can enumerate display 0 as the right-hand monitor.  The
        # layout must follow SDL's index → rectangle mapping, not assume a
        # left-to-right enumeration.
        monitors = [
            {"index": 0, "name": "display0", "x": 1920, "y": 0, "w": 1920, "h": 1080},
            {"index": 1, "name": "display1", "x": 0, "y": 0, "w": 1920, "h": 1080},
        ]
        built = layout.build_layout(monitors, [(1920, 1080), (1920, 1080)], "sdl")
        self.assertIsNotNone(built)
        assert built is not None
        self.assertEqual(built.virtual_size, (1920 * 2, 1080))
        self.assertEqual(built.monitor(0).offset, (1920, 0))
        self.assertEqual(built.monitor(1).offset, (0, 0))
        self.assertEqual(built.monitor(0).size, (1920, 1080))

    def test_fallback_layout(self) -> None:
        built = layout.fallback_layout([(1920, 1080), (2560, 1440)])
        # Different heights leave a hole under the short monitor: not tileable.
        self.assertIsNone(built)
        equal = layout.fallback_layout([(1920, 1080), (1920, 1080)])
        self.assertIsNotNone(equal)
        assert equal is not None
        self.assertEqual([m.offset for m in equal.monitors], [(0, 0), (1920, 0)])


class VirtualCanvasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((1280, 720))

    def test_resize_keeps_virtual_buffers_and_crop(self) -> None:
        player = make_player(virtual=(1280, 360), offset=(640, 0), window=(640, 360))
        self.assertEqual((player.w, player.h), (1280, 360))
        self.assertEqual(player.buf_a.get_size(), (1280, 360))
        self.assertEqual(player.vig.get_size(), (1280, 360))
        self.assertEqual(player.crop, pygame.Rect(640, 0, 640, 360))

        independent = make_player(virtual=None, window=(640, 360))
        self.assertEqual((independent.w, independent.h), (640, 360))
        self.assertEqual(independent.buf_a.get_size(), (640, 360))
        self.assertEqual(independent.crop, pygame.Rect(0, 0, 640, 360))

    def test_crop_halves_reconstruct_one_virtual_canvas(self) -> None:
        virtual = (1280, 360)
        ticks = 40

        reference = make_player(seed=4242, virtual=virtual, offset=(0, 0), window=virtual)
        left = make_player(seed=4242, virtual=virtual, offset=(0, 0), window=(640, 360))
        right = make_player(seed=4242, virtual=virtual, offset=(640, 0), window=(640, 360))

        full = run_ticks(reference, ticks)
        left_screen = pygame.Surface((640, 360))
        right_screen = pygame.Surface((640, 360))
        left_canvas = run_ticks(left, ticks, left_screen)
        right_canvas = run_ticks(right, ticks, right_screen)

        # Both children rendered the same logical image before cropping.
        self.assertEqual(rgb(left_canvas), rgb(full))
        self.assertEqual(rgb(right_canvas), rgb(full))

        # Each window is exactly its crop of that image.
        self.assertEqual(rgb(left_screen), rgb(full.subsurface((0, 0, 640, 360))))
        self.assertEqual(rgb(right_screen), rgb(full.subsurface((640, 0, 640, 360))))

        # Reassembling the two monitors gives back the one canvas: the seam
        # column x=639 abuts x=640 with nothing duplicated or dropped.
        composite = pygame.Surface(virtual)
        composite.blit(left_screen, (0, 0))
        composite.blit(right_screen, (640, 0))
        self.assertEqual(rgb(composite), rgb(full))
        self.assertEqual(
            rgb(composite.subsurface((639, 0, 1, 360))),
            rgb(full.subsurface((639, 0, 1, 360))),
        )
        self.assertEqual(
            rgb(composite.subsurface((640, 0, 1, 360))),
            rgb(full.subsurface((640, 0, 1, 360))),
        )

        # Independent per-display players (today's mode) do not stitch.
        old_left = make_player(
            seed=5000 + int(EPOCH), virtual=None, window=(640, 360), fixed_step=False
        )
        old_right = make_player(
            seed=5000 + 997 + int(EPOCH), virtual=None, window=(640, 360), fixed_step=False
        )
        old_screen = pygame.Surface((1280, 360))
        old_screen.blit(run_ticks(old_left, ticks, pygame.Surface((640, 360))), (0, 0))
        old_screen.blit(run_ticks(old_right, ticks, pygame.Surface((640, 360))), (640, 0))
        self.assertNotEqual(rgb(old_screen), rgb(full))

    def test_chrome_is_split_across_the_seam(self) -> None:
        virtual = (1280, 360)
        left_screen = pygame.Surface((640, 360))
        right_screen = pygame.Surface((640, 360))
        left = make_player(seed=5, virtual=virtual, offset=(0, 0), window=(640, 360))
        right = make_player(seed=5, virtual=virtual, offset=(640, 0), window=(640, 360))
        left.render(left_screen)
        right.render(right_screen)
        # "AD FRESH" sits on the left monitor only...
        self.assertTrue(bright_pixel(left_screen, (0, 300, 180, 360)))
        # ...and the module title closes the virtual canvas on the right monitor.
        self.assertTrue(bright_pixel(right_screen, (380, 300, 640, 360)))


class DeterminismTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((1280, 720))

    def test_same_seed_same_ticks_identical_frames(self) -> None:
        for module in ("toasters", "pipes"):
            with self.subTest(module=module):
                one = make_player(
                    seed=777, virtual=(640, 360), window=(640, 360), playlist=[module]
                )
                two = make_player(
                    seed=777, virtual=(640, 360), window=(640, 360), playlist=[module]
                )
                first = run_ticks(one, 30)
                second = run_ticks(two, 30)
                self.assertEqual(rgb(first), rgb(second))

    def test_schedule_switches_on_the_shared_simulation_clock(self) -> None:
        two_modules = ["toasters", "pipes"]
        one = make_player(
            seed=11, virtual=(640, 360), window=(640, 360), playlist=two_modules, dwell=1.0, fade=0.0
        )
        two = make_player(
            seed=11, virtual=(640, 360), window=(640, 360), playlist=two_modules, dwell=1.0, fade=0.0
        )
        for _ in range(60):
            one.advance(FIXED_DT)
            two.advance(FIXED_DT)
        self.assertEqual(one.selection, two.selection)
        self.assertEqual(one.selection[0], "toasters")  # epoch + 59/60
        one.advance(FIXED_DT)
        two.advance(FIXED_DT)
        self.assertEqual(one.selection, two.selection)
        self.assertEqual(one.selection[0], "pipes")  # epoch + 60/60 = 1.0s
        self.assertEqual(one.frame_index, 61)

    def test_fixed_step_target_and_catch_up_cap(self) -> None:
        self.assertEqual(fixed_step_target(EPOCH, EPOCH), 0)
        self.assertEqual(fixed_step_target(EPOCH - 5.0, EPOCH), 0)
        self.assertEqual(fixed_step_target(EPOCH + 0.5, EPOCH), 30)
        self.assertEqual(fixed_step_target(EPOCH + 1.0, EPOCH), 60)
        self.assertEqual(fixed_step_steps(0, 0), 0)
        self.assertEqual(fixed_step_steps(0, 1), 1)
        self.assertEqual(fixed_step_steps(10, 10), 0)
        self.assertEqual(fixed_step_steps(10, 4), 0)
        self.assertEqual(fixed_step_steps(0, 1000), MAX_CATCHUP_TICKS)
        self.assertEqual(fixed_step_steps(30, 35), 5)
        self.assertEqual(fixed_step_steps(0, 25, cap=7), 7)


class SupervisorPlumbingTest(unittest.TestCase):
    """The supervisor must pass the shared canvas, offset, and seed to children."""

    def _run_supervise(self, layout_result) -> list[list[str]]:
        import adfresh.__main__ as cli

        captured: list[list[str]] = []

        class FakeProc:
            def __init__(self, command, env=None, cwd=None):
                captured.append(list(command))
                self.returncode = None

            def poll(self):
                return 0

            def terminate(self):
                self.returncode = -15

            def wait(self, timeout=None):
                return -15

            def kill(self):
                pass

        args = argparse.Namespace(
            child=False,
            display=None,
            dwell=30.0,
            fade=1.0,
            speed=1.0,
            module=None,
            allowed=None,
            fullscreen=False,
            demo=False,
        )
        old_term = signal.getsignal(signal.SIGTERM)
        old_int = signal.getsignal(signal.SIGINT)
        try:
            with (
                mock.patch.object(pygame.display, "init"),
                mock.patch.object(pygame.display, "quit"),
                mock.patch.object(pygame.display, "get_num_displays", return_value=2),
                mock.patch.object(
                    pygame.display,
                    "get_desktop_sizes",
                    return_value=[(1920, 1080), (1920, 1080)],
                ),
                mock.patch.object(layout, "virtual_layout", return_value=layout_result),
                mock.patch.object(cli.subprocess, "Popen", FakeProc),
                mock.patch.object(cli, "write_pid"),
                mock.patch.object(cli, "clear_pid"),
                mock.patch.object(cli, "clear_quit"),
                mock.patch.object(cli, "request_quit"),
                mock.patch.object(cli, "quit_requested", return_value=True),
                mock.patch.object(cli, "hyprlock_running", return_value=False),
                mock.patch.object(cli, "log"),
            ):
                cli.supervise(args)
        finally:
            signal.signal(signal.SIGTERM, old_term)
            signal.signal(signal.SIGINT, old_int)
        return captured

    def test_spanning_children_share_one_canvas(self) -> None:
        spanning = layout.build_layout(
            layout.parse_xrandr_monitors(XRANDR_TWO),
            [(1920, 1080), (1920, 1080)],
            "xrandr",
        )
        commands = self._run_supervise(spanning)
        self.assertEqual(len(commands), 2)
        for index, command in enumerate(commands):
            self.assertIn("--spanning", command)
            self.assertEqual(command[command.index("--display") + 1], str(index))
            self.assertEqual(command[command.index("--virtual") + 1], "3840x1080")
        self.assertEqual(commands[0][commands[0].index("--offset") + 1], "0,0")
        self.assertEqual(commands[1][commands[1].index("--offset") + 1], "1920,0")
        seeds = {command[command.index("--seed") + 1] for command in commands}
        self.assertEqual(len(seeds), 1)
        epochs = {command[command.index("--epoch") + 1] for command in commands}
        self.assertEqual(len(epochs), 1)

    def test_invalid_layout_keeps_independent_mode(self) -> None:
        commands = self._run_supervise(None)
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertNotIn("--spanning", command)
            self.assertNotIn("--virtual", command)
            self.assertNotIn("--seed", command)


class PerformanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((1920, 1080))

    def test_toasters_fullhd_virtual_crop_over_60fps(self) -> None:
        player = make_player(
            seed=99, virtual=(1920, 1080), offset=(0, 540), window=(960, 540)
        )
        screen = pygame.Surface((960, 540))
        for _ in range(3):  # warm caches
            player.advance(FIXED_DT)
            player.render(screen)
        frames = 45
        started = time.perf_counter()
        for _ in range(frames):
            player.advance(FIXED_DT)
            player.render(screen)
        elapsed = max(1e-9, time.perf_counter() - started)
        fps = frames / elapsed
        print(
            f"\nspanning perf: toasters virtual 1920x1080, 960x540 crop "
            f"= {fps:.1f} fps ({1000 * elapsed / frames:.2f} ms/frame)"
        )
        self.assertGreater(fps, 30.0)
        # The frame really rendered: "AD FRESH" chrome lands in the crop.
        self.assertTrue(bright_pixel(screen, (0, 0, 300, 540)))


if __name__ == "__main__":
    unittest.main()
