"""Playback, scheduling, and offscreen previews."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

import pygame

from adfresh.drawutil import blit_alpha, font, tracked, vignette
from adfresh.modules import BY_ID, CATALOG
from adfresh.runtime import log
from adfresh.sprites import icon_surface

FPS = 60.0
FIXED_DT = 1.0 / FPS
MAX_CATCHUP_TICKS = 10

DIGIT_KEYS = {
    pygame.K_1: 0,
    pygame.K_2: 1,
    pygame.K_3: 2,
    pygame.K_4: 3,
    pygame.K_5: 4,
    pygame.K_6: 5,
    pygame.K_7: 6,
    pygame.K_8: 7,
    pygame.K_9: 8,
    pygame.K_0: 9,
    pygame.K_MINUS: 10,
}


def build_playlist(epoch: float, only: str | None, allowed: list[str] | None = None) -> list[str]:
    ids = [cls.id for cls in CATALOG]
    if allowed:
        wanted = set(allowed)
        filtered = [name for name in ids if name in wanted]
        if filtered:
            ids = filtered
    if only:
        if only not in BY_ID:
            raise SystemExit(f"unknown module {only!r}")
        return [only]
    rest = [name for name in ids if name != "toasters"]
    rng = random.Random(int(epoch * 1000) & 0xFFFFFFFF)
    rng.shuffle(rest)
    if "toasters" in ids:
        return ["toasters", *rest]
    return rest


def fixed_step_target(now: float, epoch: float, fps: float = FPS) -> int:
    """Frame index the shared simulation clock should be at ``now``."""
    return max(0, int((now - epoch) * fps))


def fixed_step_steps(frame_index: int, target: int, cap: int = MAX_CATCHUP_TICKS) -> int:
    """How many fixed ticks to run this frame, never rewinding or over-catch-up."""
    if target <= frame_index:
        return 0
    return min(target - frame_index, max(0, int(cap)))


@dataclass
class Schedule:
    playlist: list[str]
    dwell: float
    fade: float
    epoch: float

    def at(self, now: float) -> tuple[str, str, float]:
        if len(self.playlist) == 1 or self.dwell <= 0:
            name = self.playlist[0]
            return name, name, 0.0
        elapsed = max(0.0, now - self.epoch)
        index = int(elapsed // self.dwell) % len(self.playlist)
        into = elapsed % self.dwell
        current = self.playlist[index]
        nxt = self.playlist[(index + 1) % len(self.playlist)]
        if into >= self.dwell - self.fade and self.fade > 0:
            alpha = (into - (self.dwell - self.fade)) / self.fade
            return current, nxt, max(0.0, min(1.0, alpha))
        return current, nxt, 0.0


class Player:
    def __init__(
        self,
        *,
        display_index: int,
        seed: int,
        schedule: Schedule,
        saver: bool,
        speed: float,
        virtual_size: tuple[int, int] | None = None,
        offset: tuple[int, int] = (0, 0),
        fixed_step: bool = False,
    ):
        self.display_index = display_index
        self.rng = random.Random(seed)
        self.schedule = schedule
        self.saver = saver
        self.speed = speed
        self.paused = False
        self.locked: str | None = None
        self.modules: dict = {}
        self.virtual_size = (
            (max(1, int(virtual_size[0])), max(1, int(virtual_size[1])))
            if virtual_size
            else None
        )
        self.offset = (int(offset[0]), int(offset[1]))
        self.fixed_step = bool(fixed_step)
        self.w = 1
        self.h = 1
        self.window_w = 1
        self.window_h = 1
        self.crop = pygame.Rect(0, 0, 1, 1)
        self.frame_index = 0
        self.selection: tuple[str, str, float] | None = None
        self.selection_time = 0.0
        if self.fixed_step:
            # Both children share the supervisor epoch, so every scheduled
            # switch and chrome fade lands on exactly the same frame index.
            self.chrome_started = float(schedule.epoch)
            self.help_until = float(schedule.epoch) + (0.0 if saver else 6.0)
        else:
            self.chrome_started = time.monotonic()
            self.help_until = time.monotonic() + (6.0 if not saver else 0.0)
        self.buf_a: pygame.Surface | None = None
        self.buf_b: pygame.Surface | None = None
        self.vig: pygame.Surface | None = None
        self.frames = 0
        self.fps_clock = time.monotonic()

    def now(self) -> float:
        """Simulation clock in spanning mode, wall clock in demo mode."""
        if self.fixed_step:
            return self.schedule.epoch + self.frame_index / FPS
        return time.monotonic()

    def resize(self, w: int, h: int) -> None:
        self.window_w, self.window_h = max(1, int(w)), max(1, int(h))
        if self.virtual_size is None:
            self.w, self.h = self.window_w, self.window_h
            self.crop = pygame.Rect(0, 0, self.w, self.h)
        else:
            self.w, self.h = self.virtual_size
            ox, oy = self.offset
            self.crop = pygame.Rect(ox, oy, self.window_w, self.window_h)
            self.crop = self.crop.clip(pygame.Rect(0, 0, self.w, self.h))
            if self.crop.size != (self.window_w, self.window_h):
                log(
                    f"display {self.display_index} crop {self.crop.size} "
                    f"does not match window {(self.window_w, self.window_h)}"
                )
        self.buf_a = pygame.Surface((self.w, self.h))
        self.buf_b = pygame.Surface((self.w, self.h))
        self.vig = vignette(self.w, self.h)
        for module in self.modules.values():
            module.resize(self.w, self.h)

    def module(self, name: str):
        hit = self.modules.get(name)
        if hit is None:
            hit = BY_ID[name](random.Random(self.rng.randrange(1 << 30)))
            hit.resize(self.w, self.h)
            self.modules[name] = hit
        return hit

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """Offer a click to the active module; return True if it consumed it.

        The position is translated from window coordinates into the virtual
        canvas so interactive modules work in spanning mode.
        """
        if self.selection is None:
            return False
        current, nxt, alpha = self.selection
        name = current if alpha < 0.5 else nxt
        module = self.module(name)
        tap = getattr(module, "tap", None)
        if tap is None:
            return False
        try:
            tap(pos[0] + self.crop.x, pos[1] + self.crop.y)
        except Exception:  # noqa: BLE001 - a bad interaction must not kill the saver
            return False
        return True

    def lock(self, name: str) -> None:
        self.locked = name
        self.chrome_started = self.now()

    def cycle(self, step: int) -> None:
        ids = self.schedule.playlist
        if self.locked is None:
            now = self.now()
            current, _, _ = self.schedule.at(now)
        else:
            current = self.locked
        index = ids.index(current) if current in ids else 0
        self.lock(ids[(index + step) % len(ids)])

    def advance(self, dt: float) -> None:
        """Tick the current (and fading) module for one step.

        Schedule and chrome time come from :meth:`now`, which is the shared
        simulation clock when ``fixed_step`` is on.
        """
        now = self.now()
        if self.locked:
            current = nxt = self.locked
            alpha = 0.0
        else:
            current, nxt, alpha = self.schedule.at(now)
        self.selection = (current, nxt, alpha)
        self.selection_time = now
        if not self.paused:
            self.module(current).tick(dt)
            if alpha > 0 and nxt != current:
                self.module(nxt).tick(dt)
        self.frame_index += 1

    def render(self, screen: pygame.Surface | None = None) -> pygame.Surface:
        """Draw the current simulation frame and blit its crop to ``screen``.

        Returns the full virtual canvas (window-sized in independent mode), so
        callers and tests can inspect the one logical image before splitting.
        """
        if self.selection is None:
            now = self.now()
            current, nxt, alpha = self.schedule.at(now)
            self.selection = (current, nxt, alpha)
            self.selection_time = now
        current, nxt, alpha = self.selection
        now = self.selection_time
        assert self.buf_a is not None and self.buf_b is not None
        self.buf_a.fill((0, 0, 0))
        self.module(current).draw(self.buf_a)
        if alpha > 0 and nxt != current:
            self.buf_b.fill((0, 0, 0))
            self.module(nxt).draw(self.buf_b)
            self.buf_b.set_alpha(int(255 * alpha))
            self.buf_a.blit(self.buf_b, (0, 0))
            self.buf_b.set_alpha(255)
        if self.vig is not None:
            self.buf_a.blit(self.vig, (0, 0))
        self._chrome(self.buf_a, current if alpha < 0.5 else nxt, now)
        self.frames += 1
        if self.frames % 300 == 0:
            elapsed = time.monotonic() - self.fps_clock
            if elapsed > 0:
                log(f"display {self.display_index} fps {self.frames / elapsed:.1f} module {current}")
            self.frames = 0
            self.fps_clock = time.monotonic()
        if screen is not None:
            screen.blit(self.buf_a, (0, 0), area=self.crop)
        return self.buf_a

    def step_and_draw(self, screen: pygame.Surface, dt: float) -> None:
        self.advance(dt)
        self.render(screen)

    def _chrome(self, screen: pygame.Surface, name: str, now: float) -> None:
        age = now - self.chrome_started
        if age < 2.6:
            alpha = 1.0
        elif age < 4.0:
            alpha = 1 - (age - 2.6) / 1.4
        else:
            alpha = 0.0
        scale = max(0.75, self.h / 1080)
        if alpha > 0:
            brand = tracked("AD FRESH", font("medium", int(18 * scale)), (236, 230, 216), 3)
            title = font("regular", int(22 * scale)).render(BY_ID[name].title, True, (236, 230, 216))
            pad = int(28 * scale)
            blit_alpha(screen, brand, (pad, self.h - pad - brand.get_height()), alpha)
            blit_alpha(
                screen,
                title,
                (self.w - pad - title.get_width(), self.h - pad - title.get_height()),
                alpha,
            )
        if not self.saver and now < self.help_until:
            hint = font("regular", int(16 * scale)).render(
                "arrows  modules     1-0 -  jump     space  pause     f  fullscreen     r  cycle     =  speed     esc  quit",
                True,
                (236, 232, 220),
            )
            pad = int(22 * scale)
            bar = pygame.Surface((hint.get_width() + 28, hint.get_height() + 14), pygame.SRCALPHA)
            bar.fill((0, 0, 0, 150))
            screen.blit(bar, (pad - 10, pad - 6))
            blit_alpha(screen, hint, (pad, pad), 1)


def open_window(display: int, fullscreen: bool, size: tuple[int, int]) -> pygame.Surface:
    pygame.display.init()
    pygame.font.init()
    pygame.display.set_allow_screensaver(True)
    pygame.display.set_caption("AD Fresh")
    if fullscreen:
        flags = pygame.FULLSCREEN | pygame.NOFRAME
        try:
            screen = pygame.display.set_mode((0, 0), flags, display=display, vsync=1)
        except pygame.error:
            screen = pygame.display.set_mode((0, 0), flags, display=display)
        pygame.mouse.set_visible(False)
    else:
        try:
            screen = pygame.display.set_mode(size, pygame.RESIZABLE, vsync=1)
        except pygame.error:
            screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        pygame.mouse.set_visible(True)
    return screen


def run_player(
    player: Player,
    screen: pygame.Surface,
    *,
    fullscreen: bool,
    should_stop,
    spanning: bool = False,
    epoch: float | None = None,
) -> None:
    clock = pygame.time.Clock()
    origin = None
    armed_at = time.monotonic() + 0.4
    player.__dict__["_fullscreen"] = fullscreen
    running = True
    while running:
        if should_stop():
            break
        raw_dt = clock.tick(60) / 1000
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE and not fullscreen:
                screen = pygame.display.get_surface()
                player.resize(screen.get_width(), screen.get_height())
            elif event.type == pygame.KEYDOWN:
                if player.saver:
                    running = False
                    break
                running = _demo_key(player, event.key, fullscreen, screen)
                if fullscreen != player.__dict__.get("_fullscreen", fullscreen):
                    fullscreen = player.__dict__["_fullscreen"]
                    screen = pygame.display.get_surface()
                    player.resize(screen.get_width(), screen.get_height())
            elif player.saver and event.type == pygame.MOUSEMOTION:
                if time.monotonic() < armed_at or origin is None:
                    origin = event.pos
                elif math.hypot(event.pos[0] - origin[0], event.pos[1] - origin[1]) > 18:
                    running = False
            elif player.saver and event.type == pygame.MOUSEBUTTONDOWN and time.monotonic() >= armed_at:
                if event.button != 1 or not player.handle_click(event.pos):
                    running = False
        if not running:
            break
        if spanning and epoch is not None:
            # Fixed timestep driven by the shared epoch: every child advances
            # the same number of ticks, so both crops are the same image.
            target = fixed_step_target(time.monotonic(), epoch)
            steps = fixed_step_steps(player.frame_index, target)
            if steps:
                dt = FIXED_DT * player.speed
                for _ in range(steps):
                    player.advance(dt)
                player.render(screen)
                pygame.display.flip()
            continue
        dt = min(0.05, raw_dt) * player.speed
        player.step_and_draw(screen, dt if not player.paused else 0)
        pygame.display.flip()


def _demo_key(player: Player, key: int, fullscreen: bool, screen: pygame.Surface) -> bool:
    if key in (pygame.K_ESCAPE, pygame.K_q):
        return False
    if key in (pygame.K_RIGHT, pygame.K_n):
        player.cycle(1)
    elif key in (pygame.K_LEFT, pygame.K_p):
        player.cycle(-1)
    elif key == pygame.K_r:
        player.locked = None
        player.chrome_started = time.monotonic()
    elif key == pygame.K_SPACE:
        player.paused = not player.paused
    elif key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
        player.speed = min(4.0, player.speed + 0.25)
    elif key in (pygame.K_MINUS, pygame.K_KP_MINUS) and pygame.key.get_mods() & pygame.KMOD_SHIFT:
        player.speed = max(0.25, player.speed - 0.25)
    elif key == pygame.K_f:
        _toggle_fullscreen(player, fullscreen)
    elif key == pygame.K_SLASH or key == pygame.K_QUESTION:
        player.help_until = time.monotonic() + 6
    elif key in DIGIT_KEYS and not (key == pygame.K_MINUS):
        index = DIGIT_KEYS[key]
        ids = [cls.id for cls in CATALOG]
        if index < len(ids):
            player.lock(ids[index])
    elif key == pygame.K_MINUS and not (pygame.key.get_mods() & pygame.KMOD_SHIFT):
        ids = [cls.id for cls in CATALOG]
        if len(ids) > 10:
            player.lock(ids[10])
    return True


def _toggle_fullscreen(player: Player, fullscreen: bool) -> None:
    display = player.display_index
    if fullscreen:
        screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
        pygame.mouse.set_visible(True)
        player.__dict__["_fullscreen"] = False
    else:
        flags = pygame.FULLSCREEN | pygame.NOFRAME
        screen = pygame.display.set_mode((0, 0), flags, display=display, vsync=1)
        pygame.mouse.set_visible(False)
        player.__dict__["_fullscreen"] = True
    player.resize(screen.get_width(), screen.get_height())


def render_previews(directory, size: tuple[int, int] = (1280, 720), steps: int = 50) -> None:
    from pathlib import Path

    pygame.display.init()
    pygame.font.init()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    screen = pygame.display.set_mode(size)
    for index, cls in enumerate(CATALOG, start=1):
        module = cls(random.Random(1000 + index))
        module.resize(*size)
        for _ in range(steps):
            module.tick(1 / 30)
        screen.fill((0, 0, 0))
        module.draw(screen)
        path = directory / f"{index:02d}-{cls.id}.png"
        pygame.image.save(screen, path)
        _assert_picture(screen, cls.id)
    icon = icon_surface(256)
    share = Path(__file__).resolve().parents[1] / "share"
    share.mkdir(parents=True, exist_ok=True)
    pygame.image.save(icon, share / "adfresh.png")
    pygame.image.save(icon, directory / "icon.png")


def _assert_picture(screen: pygame.Surface, name: str) -> None:
    colors = set()
    w, h = screen.get_size()
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            colors.add(screen.get_at((x, y))[:3])
            if len(colors) > 12:
                return
    raise RuntimeError(f"{name} rendered only {len(colors)} colors")
