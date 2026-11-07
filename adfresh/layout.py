"""One virtual canvas across every monitor.

The supervisor asks for a :class:`Layout`, which maps each SDL display index to
a crop rectangle on a single logical canvas.  Geometry comes from the session's
display server when possible:

* X11 / XWayland (``DISPLAY`` set): ``xrandr --listmonitors``.
* Hyprland: ``hyprctl monitors -j``.
* Anything else: :func:`fallback_layout` lays the known desktop sizes out
  left-to-right at ``y=0``.

Every path then goes through :func:`build_layout`, which validates that the
monitor rectangles tile the bounding box exactly and match the SDL display
sizes.  When validation fails the caller falls back to the old independent
per-display mode, so a bad parse can never break the saver.

No pygame import happens here; the parsers and bounding-box maths are pure.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass

XANDR_LINE = re.compile(
    r"^\s*(?P<number>\d+):\s*(?P<flags>[+*]*)(?P<name>\S+)\s+"
    r"(?P<geometry>\S+)(?:\s+(?P<output>\S+))?\s*$"
)

# ``1920/520x1080/290+1920+0`` — the ``/mm`` parts are optional in xrandr's
# output depending on version, and offsets are signed and may be negative.
GEOMETRY = re.compile(r"^(?P<w>\d+)(?:/\d+)?x(?P<h>\d+)(?:/\d+)?(?P<rest>.*)$")
OFFSETS = re.compile(r"(?P<x>[+-]\d+)(?P<y>[+-]\d+)$")


@dataclass(frozen=True)
class Monitor:
    """One monitor's place on the virtual canvas."""

    index: int
    name: str
    x: int
    y: int
    w: int
    h: int

    @property
    def offset(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def size(self) -> tuple[int, int]:
        return self.w, self.h


@dataclass(frozen=True)
class Layout:
    """A validated virtual canvas split into per-display crops."""

    width: int
    height: int
    monitors: tuple[Monitor, ...]
    source: str

    def monitor(self, index: int) -> Monitor:
        return self.monitors[index]

    @property
    def virtual_size(self) -> tuple[int, int]:
        return self.width, self.height

    def describe(self) -> str:
        parts = " ".join(f"{m.index}:{m.name}={m.w}x{m.h}+{m.x}+{m.y}" for m in self.monitors)
        return f"{self.width}x{self.height} source={self.source} {parts}"


def _geometry(token: str) -> tuple[int, int, int, int] | None:
    match = GEOMETRY.match(token)
    if match is None:
        return None
    offsets = OFFSETS.search(match.group("rest"))
    if offsets is None:
        return None
    return (
        int(match.group("w")),
        int(match.group("h")),
        int(offsets.group("x")),
        int(offsets.group("y")),
    )


def parse_xrandr_monitors(text: str) -> list[dict]:
    """Parse ``xrandr --listmonitors`` output into raw monitor dicts.

    ``index`` is inferred from line order, which matches SDL's display order
    under XWayland.  Disconnected output lines are ignored when present.
    """
    monitors: list[dict] = []
    for line in text.splitlines():
        if "disconnected" in line.lower():
            continue
        match = XANDR_LINE.match(line)
        if match is None:
            continue
        parsed = _geometry(match.group("geometry"))
        if parsed is None:
            continue
        width, height, x, y = parsed
        if width <= 0 or height <= 0:
            continue
        monitors.append(
            {
                "index": len(monitors),
                "name": match.group("name"),
                "x": x,
                "y": y,
                "w": width,
                "h": height,
            }
        )
    return monitors


def parse_hyprctl_monitors(text: str) -> list[dict]:
    """Parse ``hyprctl monitors -j`` output into raw monitor dicts.

    Best effort: hyprctl's order is preserved, disabled/zero-sized monitors are
    skipped.  Returns an empty list for malformed JSON.
    """
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    monitors: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if item.get("disabled"):
            continue
        try:
            width = int(item["width"])
            height = int(item["height"])
            x = int(item["x"])
            y = int(item["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        monitors.append(
            {
                "index": len(monitors),
                "name": str(item.get("name") or f"monitor{len(monitors)}"),
                "x": x,
                "y": y,
                "w": width,
                "h": height,
            }
        )
    return monitors


def monitors_from_sizes(display_sizes: list[tuple[int, int]]) -> list[dict]:
    """Lay out the known display sizes left-to-right at ``y=0``."""
    monitors: list[dict] = []
    x = 0
    for index, size in enumerate(display_sizes):
        try:
            width, height = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError):
            return []
        if width <= 0 or height <= 0:
            return []
        monitors.append(
            {"index": index, "name": f"display{index}", "x": x, "y": 0, "w": width, "h": height}
        )
        x += width
    return monitors


def build_layout(
    monitors: list[dict],
    display_sizes: list[tuple[int, int]] | None = None,
    source: str = "",
) -> Layout | None:
    """Normalize raw monitors into a validated virtual-canvas layout.

    Returns ``None`` unless the crops tile the bounding box exactly, the count
    matches the SDL displays, and every crop matches its SDL display size.
    """
    if not monitors:
        return None
    if display_sizes is not None and len(monitors) != len(display_sizes):
        return None

    rows: list[tuple[str, int, int, int, int]] = []
    try:
        for entry in monitors:
            rows.append(
                (
                    str(entry.get("name") or ""),
                    int(entry["x"]),
                    int(entry["y"]),
                    int(entry["w"]),
                    int(entry["h"]),
                )
            )
    except (KeyError, TypeError, ValueError):
        return None
    if any(w <= 0 or h <= 0 for _, _, _, w, h in rows):
        return None

    min_x = min(x for _, x, _, _, _ in rows)
    min_y = min(y for _, _, y, _, _ in rows)
    max_x = max(x + w for _, x, _, w, _ in rows)
    max_y = max(y + h for _, _, y, _, h in rows)
    width, height = max_x - min_x, max_y - min_y
    if width <= 0 or height <= 0:
        return None

    crops = [(x - min_x, y - min_y, w, h) for _, x, y, w, h in rows]

    # Exact tiling: no overlaps, no holes.  Area equality plus pairwise
    # non-overlap is sufficient for integer rectangles.
    if sum(w * h for _, _, w, h in crops) != width * height:
        return None
    for i, (ax, ay, aw, ah) in enumerate(crops):
        for bx, by, bw, bh in crops[i + 1 :]:
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                return None

    if display_sizes is not None:
        for index, (cx, cy, cw, ch) in enumerate(crops):
            try:
                size = display_sizes[index]
                expected = (int(size[0]), int(size[1]))
            except (TypeError, ValueError, IndexError):
                return None
            if (cw, ch) != expected:
                return None

    monitors_out = tuple(
        Monitor(index=index, name=rows[index][0], x=crop[0], y=crop[1], w=crop[2], h=crop[3])
        for index, crop in enumerate(crops)
    )
    return Layout(width=width, height=height, monitors=monitors_out, source=source)


def fallback_layout(display_sizes: list[tuple[int, int]]) -> Layout | None:
    """Left-to-right layout from the sizes SDL reports."""
    sizes = [tuple(int(part) for part in size) for size in display_sizes]
    return build_layout(monitors_from_sizes(sizes), sizes, source="sizes")


def _run_text(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout


def _is_hyprland(env) -> bool:
    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return True
    desktop = str(env.get("XDG_CURRENT_DESKTOP") or "").lower()
    return "hyprland" in desktop


def virtual_layout(
    display_sizes: list[tuple[int, int]],
    *,
    env=None,
    xrandr_text: str | None = None,
    hyprctl_text: str | None = None,
) -> Layout | None:
    """Detect the desktop layout for ``display_sizes`` (SDL display order).

    ``xrandr_text``/``hyprctl_text`` are injected by tests; production reads the
    live session.  Returns ``None`` whenever the geometry cannot be trusted, so
    the caller keeps today's independent-per-display behavior.
    """
    env = dict(os.environ) if env is None else env
    if _is_hyprland(env):
        text = hyprctl_text if hyprctl_text is not None else _run_text(["hyprctl", "monitors", "-j"])
        if not text:
            return None
        return build_layout(parse_hyprctl_monitors(text), list(display_sizes), source="hyprctl")
    if env.get("DISPLAY"):
        text = (
            xrandr_text
            if xrandr_text is not None
            else _run_text(["xrandr", "--listmonitors"])
        )
        if not text:
            return None
        return build_layout(parse_xrandr_monitors(text), list(display_sizes), source="xrandr")
    # Without a display-server coordinate source we cannot know whether SDL's
    # display 0 is the left or the right monitor (Wayland may enumerate it
    # right-to-left).  Guessing left-to-right is what swapped screens on this
    # desk, so prefer independent per-display windows until the supervisor can
    # provide real SDL bounds.
    return None


def sdl_display_bounds(count: int | None = None) -> list[dict] | None:
    """Return each SDL display index with its true virtual-canvas rectangle.

    SDL under Wayland does not necessarily enumerate displays left-to-right
    (on this desk display 0 is the *right* monitor), and xrandr is unavailable
    without ``DISPLAY``.  Asking SDL for the bounds of each display index gives
    an exact index → rectangle map, which is what the span layout needs.

    Must be called while pygame's display subsystem is initialised.  Returns
    ``None`` when the bounds cannot be read, so callers can fall back.
    """
    try:
        import ctypes
        import glob

        import pygame
    except Exception:  # pragma: no cover - pygame is a hard dependency in practice
        return None
    if not pygame.display.get_init():
        return None
    try:
        if count is None:
            count = int(pygame.display.get_num_displays())
    except Exception:
        return None
    if count is None or count <= 0:
        return None

    class _Rect(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_int),
            ("y", ctypes.c_int),
            ("w", ctypes.c_int),
            ("h", ctypes.c_int),
        ]

    package = os.path.dirname(os.path.dirname(os.path.abspath(pygame.__file__)))
    candidates: list[str] = []
    for pattern in (
        os.path.join(package, "pygame_ce.libs", "libSDL2-2-*.so*"),
        os.path.join(package, "pygame.libs", "libSDL2-2-*.so*"),
        os.path.join(package, "pygame_ce.libs", "libSDL2*.so*"),
    ):
        candidates.extend(sorted(glob.glob(pattern)))
    try:
        from ctypes.util import find_library

        found = find_library("SDL2")
        if found:
            candidates.append(found)
    except Exception:
        pass

    for candidate in candidates:
        try:
            library = ctypes.CDLL(candidate)
            get_bounds = getattr(library, "SDL_GetDisplayBounds")
        except (OSError, AttributeError):
            continue
        get_bounds.argtypes = [ctypes.c_int, ctypes.POINTER(_Rect)]
        get_bounds.restype = ctypes.c_int
        monitors: list[dict] = []
        for index in range(count):
            rect = _Rect()
            if get_bounds(index, ctypes.byref(rect)) != 0:
                monitors = []
                break
            if rect.w <= 0 or rect.h <= 0:
                monitors = []
                break
            monitors.append(
                {
                    "index": index,
                    "name": f"display{index}",
                    "x": int(rect.x),
                    "y": int(rect.y),
                    "w": int(rect.w),
                    "h": int(rect.h),
                }
            )
        if monitors:
            return monitors
    return None
