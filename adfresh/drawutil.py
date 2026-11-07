"""Shared drawing helpers. Surfaces are cached by size and color."""

from __future__ import annotations

import math

import pygame

from pathlib import Path

NOTO = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
NOTO_MED = "/usr/share/fonts/truetype/noto/NotoSans-Medium.ttf"
NOTO_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
MONO_CANDIDATES = [
    str(Path.home() / ".local/share/fonts/JetBrainsMonoNerdFont-Regular.ttf"),
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]

_fonts: dict[tuple[str, int], pygame.font.Font] = {}
_grads: dict[tuple, pygame.Surface] = {}
_vignettes: dict[tuple[int, int], pygame.Surface] = {}


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def font(which: str, size: int) -> pygame.font.Font:
    size = max(8, int(size))
    key = (which, size)
    hit = _fonts.get(key)
    if hit is not None:
        return hit
    path = {"regular": NOTO, "medium": NOTO_MED, "bold": NOTO_BOLD}.get(which)
    face = None
    if path and Path(path).is_file():
        try:
            face = pygame.font.Font(path, size)
        except (FileNotFoundError, OSError):
            face = None
    elif which == "mono":
        for cand in MONO_CANDIDATES:
            if Path(cand).is_file():
                try:
                    face = pygame.font.Font(cand, size)
                    break
                except (FileNotFoundError, OSError):
                    continue
    if face is None:
        face = pygame.font.SysFont("monospace" if which == "mono" else "sans", size)
    _fonts[key] = face
    return face


def rrect(
    surf: pygame.Surface,
    color: tuple,
    rect: tuple | pygame.Rect,
    radius: int,
    width: int = 0,
) -> None:
    box = pygame.Rect(rect)
    if box.w < 2 or box.h < 2:
        return
    radius = max(0, min(int(radius), box.w // 2, box.h // 2))
    pygame.draw.rect(surf, color, box, width, border_radius=radius)


def vertical_gradient(
    w: int,
    h: int,
    stops: list[tuple[float, tuple[int, int, int]]],
) -> pygame.Surface:
    w = max(1, int(w))
    h = max(1, int(h))
    key = (w, h, tuple((round(t, 3), c) for t, c in stops))
    hit = _grads.get(key)
    if hit is not None:
        return hit
    column = pygame.Surface((1, h))
    ordered = sorted(stops, key=lambda s: s[0])
    for y in range(h):
        t = y / max(1, h - 1)
        color = ordered[-1][1]
        for i in range(len(ordered) - 1):
            t0, c0 = ordered[i]
            t1, c1 = ordered[i + 1]
            if t0 <= t <= t1:
                span = max(1e-6, t1 - t0)
                color = mix(c0, c1, (t - t0) / span)
                break
        column.set_at((0, y), color)
    image = pygame.transform.scale(column, (w, h))
    _grads[key] = image
    return image


def radial(diameter: int, rgb: tuple[int, int, int], alpha: int = 255) -> pygame.Surface:
    diameter = max(4, int(diameter))
    key = ("radial", diameter, rgb, alpha)
    hit = _grads.get(key)
    if hit is not None:
        return hit
    surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    cx = cy = (diameter - 1) / 2
    radius = diameter / 2
    for y in range(diameter):
        for x in range(diameter):
            d = math.hypot(x - cx, y - cy) / radius
            if d >= 1:
                continue
            fall = (1 - d) ** 2
            surf.set_at((x, y), (rgb[0], rgb[1], rgb[2], int(alpha * fall)))
    _grads[key] = surf
    return surf


def additive_orb(diameter: int, rgb: tuple[int, int, int]) -> pygame.Surface:
    """Soft disc whose RGB falls off to black, for BLEND_RGB_ADD."""
    diameter = max(4, int(diameter))
    key = ("orb", diameter, rgb)
    hit = _grads.get(key)
    if hit is not None:
        return hit
    surf = pygame.Surface((diameter, diameter))
    cx = cy = (diameter - 1) / 2
    radius = diameter / 2
    for y in range(diameter):
        for x in range(diameter):
            d = math.hypot(x - cx, y - cy) / radius
            if d >= 1:
                continue
            fall = (1 - d) ** 2.2
            surf.set_at(
                (x, y),
                (int(rgb[0] * fall), int(rgb[1] * fall), int(rgb[2] * fall)),
            )
    _grads[key] = surf
    return surf


def vignette(w: int, h: int) -> pygame.Surface:
    key = (w, h)
    hit = _vignettes.get(key)
    if hit is not None:
        return hit
    sw, sh = 160, 90
    small = pygame.Surface((sw, sh), pygame.SRCALPHA)
    cx, cy = (sw - 1) / 2, (sh - 1) / 2
    for y in range(sh):
        for x in range(sw):
            dx = (x - cx) / cx
            dy = (y - cy) / cy
            d = math.hypot(dx, dy)
            if d <= 0.62:
                continue
            a = min(150, int((d - 0.62) / 0.7 * 150))
            small.set_at((x, y), (0, 0, 0, a))
    image = pygame.transform.smoothscale(small, (max(1, w), max(1, h)))
    _vignettes[key] = image
    return image


def blit_alpha(dest: pygame.Surface, src: pygame.Surface, pos: tuple[int, int], alpha: float) -> None:
    if alpha <= 0:
        return
    if alpha >= 0.999:
        dest.blit(src, pos)
        return
    ghost = src.copy()
    ghost.fill((255, 255, 255, int(255 * alpha)), special_flags=pygame.BLEND_RGBA_MULT)
    dest.blit(ghost, pos)


def tracked(text: str, face: pygame.font.Font, color: tuple[int, int, int], tracking: int) -> pygame.Surface:
    glyphs = [face.render(ch, True, color) for ch in text]
    if not glyphs:
        return pygame.Surface((1, 1), pygame.SRCALPHA)
    width = sum(g.get_width() for g in glyphs) + tracking * (len(glyphs) - 1)
    height = max(g.get_height() for g in glyphs)
    surf = pygame.Surface((max(1, width), height), pygame.SRCALPHA)
    x = 0
    for glyph in glyphs:
        surf.blit(glyph, (x, 0))
        x += glyph.get_width() + tracking
    return surf


def shade_sphere(diameter: int, base: tuple[int, int, int]) -> pygame.Surface:
    diameter = max(8, int(diameter))
    key = ("sphere", diameter, base)
    hit = _grads.get(key)
    if hit is not None:
        return hit
    surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    radius = (diameter - 1) / 2
    light = mix(base, (255, 255, 255), 0.72)
    dark = mix(base, (0, 0, 0), 0.62)
    lx, ly, lz = -0.42, -0.58, 0.70
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / norm, ly / norm, lz / norm
    for y in range(diameter):
        for x in range(diameter):
            nx = (x - radius) / radius
            ny = (y - radius) / radius
            n2 = nx * nx + ny * ny
            if n2 > 1:
                continue
            nz = math.sqrt(1 - n2)
            lambert = max(0.0, nx * lx + ny * ly + nz * lz)
            # A little wrap so the shadow side stays jewel-toned.
            lit = 0.18 + 0.82 * lambert
            color = mix(dark, light, lit)
            hx, hy, hz = lx, ly, lz + 1
            hn = math.sqrt(hx * hx + hy * hy + hz * hz)
            spec = max(0.0, nx * hx / hn + ny * hy / hn + nz * hz / hn)
            spec = spec ** 18
            color = mix(color, (255, 255, 255), spec * 0.85)
            surf.set_at((x, y), (*color, 255))
    _grads[key] = surf
    return surf
