"""After Dark-style 3D pipes: glossy tubes that grow through a night-time grid.

A handful of independent pipe systems grow one grid cell at a time along
orthogonal directions, never reversing and never intersecting themselves or
each other.  Each system has its own material (brushed chrome, teal, copper,
blue steel, muted rose), is shaded as a lit cylinder with a specular stripe,
and ends in shaded joint spheres / elbow rings.  The whole lattice is viewed
through an isometric-ish 3/4 camera that drifts very slowly, with painter's
sorting and depth fog so the maze reads as a real object in space.

Rendering is deliberately cheap: tubes are drawn as a handful of flat shading
bands with cached quantised colours, joint spheres are cached per colour/size,
and the whole scene is supersampled (1.3x) then smooth-scaled once per frame, so
the silhouettes look clean while the module still holds well over 60 fps at
1080p.
"""

from __future__ import annotations

import math
import random

import numpy as np
import pygame

from adfresh.drawutil import additive_orb, mix, vertical_gradient, vignette
from adfresh.modules.base import Module

try:  # gfxdraw gives us anti-aliased silhouettes; plain polygons are the fallback.
    import pygame.gfxdraw as _gfxdraw
except Exception:  # pragma: no cover - only on exotic pygame builds
    _gfxdraw = None

# --- lattice / scene tuning -------------------------------------------------
GRID_X, GRID_Y, GRID_Z = 10, 6, 10
NUM_SYSTEMS = 5
PIPE_R = 0.20

FOG_RGB = (8, 12, 21)
FOG_NEAR = 13.0
FOG_FAR = 28.5

SPAWN_FADE = 0.45
SUPERSAMPLE = 1.3
FADE_TIME = 0.85
INTERVAL_RANGE = (0.09, 0.20)
MAX_LEN_RANGE = (26, 58)

# Screen-space direction of the key light (upper-left), used to place the
# specular stripe across each tube.
LIGHT2 = (-0.55, -0.835)
LIGHT_Z = 0.56
DIRS = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)

# Materials: brushed chrome, cool teal, copper, blue steel, muted rose.
PALETTES = (
    (150, 158, 174),
    (40, 146, 156),
    (201, 120, 62),
    (108, 134, 176),
    (166, 92, 108),
)

# Per-material shade ramp: (body, shadow side, mid shadow, lit glow, lit, specular, ring).
_SHADE_CACHE: dict[tuple[int, int, int], tuple] = {}
# Joint spheres are immutable and shared between instances; key on quantised
# colour and diameter bucket so the cache stays small and safe.
_SPHERE_CACHE: dict[tuple[tuple[int, int, int], int], pygame.Surface] = {}
_GLOW_CACHE: dict[tuple[tuple[int, int, int], int], pygame.Surface] = {}


def _shades(base: tuple[int, int, int]) -> tuple:
    hit = _SHADE_CACHE.get(base)
    if hit is None:
        body = mix(base, (0, 0, 0), 0.06)
        shadow = mix(base, (0, 0, 0), 0.66)
        mid = mix(base, (0, 0, 0), 0.38)
        glow = mix(base, (255, 255, 255), 0.16)
        lit = mix(base, (255, 255, 255), 0.34)
        spec = mix(base, (255, 255, 255), 0.74)
        ring = mix(base, (255, 255, 255), 0.32)
        hit = (body, shadow, mid, glow, lit, spec, ring)
        _SHADE_CACHE[base] = hit
    return hit


def _dim(color: tuple[int, int, int], fog: float) -> tuple[int, int, int]:
    """Blend a material colour toward the night fog colour."""
    if fog > 0.0:
        return mix(color, FOG_RGB, min(1.0, fog))
    return color


# Quantised shading palettes, keyed by (material, fog step).  This keeps the
# per-segment colour work to a dict lookup even with ~200 tubes.
_BAND_CACHE: dict[tuple, tuple] = {}


def _band_colors(base: tuple[int, int, int], fog_idx: int) -> tuple:
    key = (base, fog_idx)
    hit = _BAND_CACHE.get(key)
    if hit is not None:
        return hit
    if len(_BAND_CACHE) > 4000:
        _BAND_CACHE.clear()
    body_c, shadow_c, mid_c, glow_c, lit_c, spec_c, ring_c = _shades(base)
    fog = fog_idx / 12.0
    hit = (
        _dim(body_c, fog),
        _dim(shadow_c, fog),
        _dim(mid_c, fog),
        _dim(glow_c, fog * 0.9),
        _dim(lit_c, fog * 0.85),
        _dim(spec_c, fog * 0.6),
        _dim(mix(shadow_c, body_c, 0.28), fog),
        _dim(body_c, fog),
        _dim(ring_c, fog),
    )
    _BAND_CACHE[key] = hit
    return hit


def _sphere_sprite(color: tuple[int, int, int], diameter: float) -> pygame.Surface:
    """Cached, anti-aliased shaded joint sphere (numpy, generated on demand)."""
    d = max(6, int(round(diameter / 3.0)) * 3)
    d = min(d, 150)
    key = ((color[0] // 8 * 8, color[1] // 8 * 8, color[2] // 8 * 8), d)
    hit = _SPHERE_CACHE.get(key)
    if hit is not None:
        return hit
    if len(_SPHERE_CACHE) > 1200:
        _SPHERE_CACHE.clear()

    n = d
    axis = np.linspace(-1.0, 1.0, n, dtype=np.float32)
    u, v = np.meshgrid(axis, axis)
    r2 = u * u + v * v
    nz = np.sqrt(np.maximum(0.0, 1.0 - r2))

    # Same studio key light as the tubes (upper-left-front).
    lx, ly, lz = -0.42, -0.60, 0.68
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / norm, ly / norm, lz / norm
    diffuse = np.clip(u * lx + v * ly + nz * lz, 0.0, 1.0)
    lit = 0.16 + 0.84 * diffuse

    dark = np.array(color, dtype=np.float32) * 0.28
    bright = np.array(color, dtype=np.float32)
    bright = bright + (255.0 - bright) * 0.34
    rgb = dark + (bright - dark) * lit[..., None]

    hx, hy, hz = lx, ly, lz + 1.0
    hn = math.sqrt(hx * hx + hy * hy + hz * hz)
    ndoth = np.clip(u * (hx / hn) + v * (hy / hn) + nz * (hz / hn), 0.0, 1.0)
    spec = (ndoth ** 34) * 0.56
    rgb = rgb * (1.0 - spec[..., None]) + 255.0 * spec[..., None]

    # Gentle rim darkening keeps the balls from looking like flat badges.
    rgb *= (0.76 + 0.24 * np.sqrt(nz))[..., None]

    dist = 1.0 - np.sqrt(np.clip(r2, 0.0, 1.0))
    alpha = np.clip(dist * (n / 2.0) / 1.45, 0.0, 1.0)

    rgba = np.zeros((n, n, 4), dtype=np.uint8)
    rgba[..., 0] = np.clip(rgb[..., 0], 0.0, 255.0).astype(np.uint8)
    rgba[..., 1] = np.clip(rgb[..., 1], 0.0, 255.0).astype(np.uint8)
    rgba[..., 2] = np.clip(rgb[..., 2], 0.0, 255.0).astype(np.uint8)
    rgba[..., 3] = (alpha * 255.0).astype(np.uint8)

    surf = pygame.image.frombuffer(rgba.tobytes(), (n, n), "RGBA")
    _SPHERE_CACHE[key] = surf
    return surf


def _glow_sprite(color: tuple[int, int, int], diameter: int) -> pygame.Surface:
    key = (color, diameter)
    hit = _GLOW_CACHE.get(key)
    if hit is None:
        if len(_GLOW_CACHE) > 48:
            _GLOW_CACHE.clear()
        small = additive_orb(64, color)
        hit = pygame.transform.smoothscale(small, (diameter, diameter))
        _GLOW_CACHE[key] = hit
    return hit


class _PipeSystem:
    """One independently growing pipe run."""

    __slots__ = (
        "pal",
        "nodes",
        "edges",
        "turns",
        "dir",
        "max_len",
        "interval",
        "grow_t",
        "state",
        "alpha",
    )

    def __init__(self, pal: int) -> None:
        self.pal = pal
        self.nodes: list[tuple[int, int, int]] = []
        self.edges: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
        self.turns: list[int] = []
        self.dir: tuple[int, int, int] | None = None
        self.max_len = 30
        self.interval = 0.16
        self.grow_t = 0.0
        self.state = "grow"
        self.alpha = 1.0


class Pipes(Module):
    id = "pipes"
    title = "Pipes"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.systems: list[_PipeSystem] = []
        self._bg: pygame.Surface | None = None
        self._focal = 1200.0
        self._cam_dist = 20.5
        self._base_yaw = 0.70
        self._base_pitch = 0.33
        self._glows: list[pygame.Surface | None] = []
        self._layer: pygame.Surface | None = None
        self._scaled: pygame.Surface | None = None
        self._ghost: pygame.Surface | None = None
        self._layer_size = (1, 1)
        self._occ_nodes: set[tuple[int, int, int]] = set()
        self._occ_edges: set[tuple[tuple[int, int, int], tuple[int, int, int]]] = set()
        # Half extents of the lattice, used to centre world coordinates.
        self._cx = (GRID_X - 1) * 0.5
        self._cy = (GRID_Y - 1) * 0.5
        self._cz = (GRID_Z - 1) * 0.5

    # -- lifecycle ---------------------------------------------------------
    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        # Supersample only when the supersampled layer stays inside a ~7MP
        # fill-rate budget.  A single 1080p screen supersamples as before; the
        # spanning saver's 3840x1080 virtual canvas would blow the budget
        # (4992x1404, ~7MP) and is rendered 1:1 instead -- at 2x the visible
        # pixel density that still looks crisp and keeps both monitors at 60fps.
        ss = (
            SUPERSAMPLE
            if self.w * self.h * SUPERSAMPLE * SUPERSAMPLE <= 7_000_000
            else 1.0
        )
        lw = max(1, int(round(self.w * ss)))
        lh = max(1, int(round(self.h * ss)))
        self._layer_size = (lw, lh)
        self._layer = pygame.Surface(self._layer_size)
        self._scaled = pygame.Surface((self.w, self.h))
        dim = min(lw, lh)
        self._focal = dim * 1.72
        self._cam_dist = 20.5
        self._build_background()
        glow_d = max(40, int(dim * 0.10))
        self._glows = [
            _glow_sprite(mix(base, (0, 0, 0), 0.52), glow_d) for base in PALETTES
        ]
        self._reset_scene()

    def _build_background(self) -> None:
        w, h = self.w, self.h
        bg = vertical_gradient(
            w,
            h,
            [
                (0.0, (3, 5, 10)),
                (0.42, (6, 9, 17)),
                (0.72, (9, 13, 23)),
                (1.0, (4, 6, 11)),
            ],
        ).copy()
        # Soft cool glow behind the labyrinth so the void has some atmosphere.
        gd = int(min(w, h) * 1.55)
        if gd > 8:
            small = additive_orb(96, (15, 27, 52))
            glow = pygame.transform.smoothscale(small, (gd, gd))
            bg.blit(glow, (w // 2 - gd // 2, int(h * 0.5) - gd // 2), special_flags=pygame.BLEND_RGB_ADD)
        # Very faint dust motes give the void a little depth without becoming
        # a starfield; baked once into the background surface.
        dust = random.Random(self.rng.randrange(1 << 30))
        for _ in range(max(40, (w * h) // 18000)):
            x = dust.randrange(w)
            y = dust.randrange(h)
            v = dust.randrange(14, 34)
            tint = dust.randrange(0, 3)
            col = (v - 4, v, v + 6) if tint == 0 else (v, v + 1, v + 4)
            bg.set_at((x, y), col)
        bg.blit(vignette(w, h), (0, 0))
        if self._layer_size != (w, h):
            bg = pygame.transform.smoothscale(bg, self._layer_size)
        self._bg = bg

    def _reset_scene(self) -> None:
        self._occ_nodes = set()
        self._occ_edges = set()
        self.systems = []
        order = list(range(len(PALETTES)))
        self.rng.shuffle(order)
        for i in range(NUM_SYSTEMS):
            system = _PipeSystem(order[i % len(order)])
            self.systems.append(system)
            self._spawn(system, initial=True, slot=i)

    # -- growth ------------------------------------------------------------
    def _pick_seed(self) -> tuple[int, int, int] | None:
        # Prefer the interior so pipes do not constantly hug the lattice walls,
        # and score a few free candidates by how open their neighbourhood is so
        # a fresh run does not immediately grow into a dead end.
        best: tuple[int, int, int] | None = None
        best_score = -1
        for attempt in range(34):
            if attempt < 24:
                node = (
                    self.rng.randrange(1, GRID_X - 1),
                    self.rng.randrange(1, GRID_Y - 1),
                    self.rng.randrange(1, GRID_Z - 1),
                )
            else:
                node = (
                    self.rng.randrange(GRID_X),
                    self.rng.randrange(GRID_Y),
                    self.rng.randrange(GRID_Z),
                )
            if node in self._occ_nodes:
                continue
            free = 0
            for nd in DIRS:
                nxt = (node[0] + nd[0], node[1] + nd[1], node[2] + nd[2])
                if 0 <= nxt[0] < GRID_X and 0 <= nxt[1] < GRID_Y and 0 <= nxt[2] < GRID_Z:
                    if nxt not in self._occ_nodes:
                        free += 1
            if free > best_score:
                best, best_score = node, free
                if free >= 6:
                    break
        if best is not None:
            return best
        for i in range(GRID_X):
            for j in range(GRID_Y):
                for k in range(GRID_Z):
                    node = (i, j, k)
                    if node not in self._occ_nodes:
                        return node
        return None

    def _spawn(self, system: _PipeSystem, *, initial: bool, slot: int = 0) -> None:
        seed = self._pick_seed()
        if seed is None:
            seed = (GRID_X // 2, GRID_Y // 2, GRID_Z // 2)
        system.nodes = [seed]
        system.edges = []
        system.turns = []
        system.dir = None
        system.max_len = self.rng.randrange(*MAX_LEN_RANGE)
        system.interval = self.rng.uniform(*INTERVAL_RANGE)
        system.grow_t = self.rng.uniform(0.0, system.interval)
        system.state = "grow"
        system.alpha = 1.0 if initial else 0.0
        self._occ_nodes.add(seed)
        if initial:
            pre = 7 + slot * 4 + self.rng.randrange(3)
        else:
            pre = 2 + self.rng.randrange(3)
        for _ in range(pre):
            if not self._grow(system):
                break

    def _grow(self, system: _PipeSystem) -> bool:
        nodes = system.nodes
        if len(nodes) - 1 >= system.max_len:
            self._finish(system)
            return False

        head = nodes[-1]
        reverse = None
        if system.dir is not None:
            reverse = (-system.dir[0], -system.dir[1], -system.dir[2])

        candidates: list[tuple[tuple[int, int, int], tuple[int, int, int], tuple]] = []
        for nd in DIRS:
            if nd == reverse:
                continue
            nxt = (head[0] + nd[0], head[1] + nd[1], head[2] + nd[2])
            if not (0 <= nxt[0] < GRID_X and 0 <= nxt[1] < GRID_Y and 0 <= nxt[2] < GRID_Z):
                continue
            if nxt in self._occ_nodes:
                continue
            edge = (head, nxt) if head < nxt else (nxt, head)
            if edge in self._occ_edges:
                continue
            candidates.append((nd, nxt, edge))

        if not candidates:
            self._finish(system)
            return False

        # Mostly continue straight, otherwise pick any legal turn.
        straight = [c for c in candidates if c[0] == system.dir]
        if straight and self.rng.random() < 0.70:
            nd, nxt, edge = straight[0]
        else:
            nd, nxt, edge = candidates[self.rng.randrange(len(candidates))]

        if system.dir is not None and nd != system.dir:
            system.turns.append(len(nodes) - 1)
        system.dir = nd
        system.nodes.append(nxt)
        system.edges.append(edge)
        self._occ_nodes.add(nxt)
        self._occ_edges.add(edge)

        if len(system.nodes) - 1 >= system.max_len:
            self._finish(system)
        return True

    def _finish(self, system: _PipeSystem) -> None:
        if system.state != "grow":
            return
        system.state = "fade"
        system.alpha = 1.0

    def _respawn(self, system: _PipeSystem) -> None:
        for node in system.nodes:
            self._occ_nodes.discard(node)
        for edge in system.edges:
            self._occ_edges.discard(edge)
        self._spawn(system, initial=False)

    # -- animation ---------------------------------------------------------
    def step(self, dt: float) -> None:
        if not self.systems:
            return
        for system in self.systems:
            if system.state == "grow":
                if system.alpha < 1.0:
                    system.alpha = min(1.0, system.alpha + dt / SPAWN_FADE)
                system.grow_t += dt
                budget = 8
                while system.grow_t >= system.interval and system.state == "grow" and budget > 0:
                    system.grow_t -= system.interval
                    self._grow(system)
                    budget -= 1
            elif system.state == "fade":
                system.alpha -= dt / FADE_TIME
                if system.alpha <= 0.0:
                    self._respawn(system)

    # -- camera ------------------------------------------------------------
    def _camera(self) -> tuple[float, ...]:
        t = self.t
        yaw = self._base_yaw + 0.085 * math.sin(t * 0.075) + 0.026 * math.sin(t * 0.031 + 1.7)
        pitch = self._base_pitch + 0.034 * math.sin(t * 0.058 + 0.9)
        radius = self._cam_dist
        cp, sp = math.cos(pitch), math.sin(pitch)
        cy, sy = math.cos(yaw), math.sin(yaw)
        ex, ey, ez = radius * cp * sy, radius * sp, radius * cp * cy
        tx, ty, tz = 0.0, -0.95, 0.0
        fx, fy, fz = tx - ex, ty - ey, tz - ez
        fl = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
        fx, fy, fz = fx / fl, fy / fl, fz / fl
        # right = normalize(cross(forward, world_up))
        rx, ry, rz = -fz, 0.0, fx
        rl = math.hypot(rx, rz) or 1.0
        rx, rz = rx / rl, rz / rl
        # up = cross(right, forward)
        ux = ry * fz - rz * fy
        uy = rz * fx - rx * fz
        uz = rx * fy - ry * fx
        return ex, ey, ez, fx, fy, fz, rx, ry, rz, ux, uy, uz

    # -- rendering ---------------------------------------------------------
    def _present(self, surf: pygame.Surface) -> None:
        assert self._layer is not None and self._scaled is not None
        if self._layer.get_size() == (self.w, self.h):
            surf.blit(self._layer, (0, 0))
        else:
            pygame.transform.smoothscale(self._layer, self._scaled.get_size(), self._scaled)
            surf.blit(self._scaled, (0, 0))

    def draw(self, surf: pygame.Surface) -> None:
        w, h = self._layer_size
        if self._layer is None or self._scaled is None:
            # Defensive: draw() before resize() should still produce a frame.
            self.resize(self.w, self.h)
            w, h = self._layer_size
        assert self._layer is not None and self._scaled is not None
        if self._bg is None or self._bg.get_size() != (w, h):
            self._build_background()
        assert self._bg is not None
        target = self._layer
        target.blit(self._bg, (0, 0))
        if not self.systems:
            self._present(surf)
            return

        ex, ey, ez, fx, fy, fz, rx, ry, rz, ux, uy, uz = self._camera()
        focal = self._focal
        hw, hh = w * 0.5, h * 0.5
        cx_w, cy_w, cz_w = self._cx, self._cy, self._cz
        margin = 80.0
        min_x, min_y = -margin, -margin
        max_x, max_y = w + margin, h + margin
        fog_span = FOG_FAR - FOG_NEAR
        light_x, light_y = LIGHT2
        solid: list[tuple] = []
        ghost: list[tuple] = []
        ghost_weight = 0.0
        ghost_alpha = 0.0
        # Bounding box of the translucent layer; only that region is cleared
        # and composited, which keeps respawn fades nearly free.
        g_minx = g_miny = 1e9
        g_maxx = g_maxy = -1e9

        for system in self.systems:
            nodes = system.nodes
            alpha = system.alpha
            if len(nodes) < 2 or alpha <= 0.13:
                continue
            base = PALETTES[system.pal]
            # Spawning and dissolving systems are composited with real alpha,
            # in a layer beneath the opaque pipes.
            translucent = alpha < 0.995
            bucket = ghost if translucent else solid
            if translucent:
                ghost_weight += len(nodes) - 1
                ghost_alpha += alpha * (len(nodes) - 1)
            proj: list[tuple[float, float, float] | None] = []
            for node in nodes:
                relx = node[0] - cx_w - ex
                rely = node[1] - cy_w - ey
                relz = node[2] - cz_w - ez
                depth = relx * fx + rely * fy + relz * fz
                if depth < 0.9:
                    proj.append(None)
                    continue
                inv = focal / depth
                sx = hw + (relx * rx + rely * ry + relz * rz) * inv
                sy = hh - (relx * ux + rely * uy + relz * uz) * inv
                proj.append((sx, sy, depth))

            # Tube segments.
            for i in range(len(nodes) - 1):
                a = proj[i]
                b = proj[i + 1]
                if a is None or b is None:
                    continue
                ax, ay, az = a
                bx, by, bz = b
                if (ax < min_x and bx < min_x) or (ax > max_x and bx > max_x):
                    continue
                if (ay < min_y and by < min_y) or (ay > max_y and by > max_y):
                    continue
                dx, dy = bx - ax, by - ay
                length = math.hypot(dx, dy)
                if length < 1e-4:
                    continue
                depth = (az + bz) * 0.5
                fog = (depth - FOG_NEAR) / fog_span
                if fog < 0.0:
                    fog = 0.0
                elif fog > 1.0:
                    fog = 1.0
                fog = int(fog * 0.78 * 12.0) / 12.0
                ra = PIPE_R * focal / az
                rb = PIPE_R * focal / bz
                px, py = -dy / length, dx / length
                ehx, ehy = dx / length, dy / length
                hf = px * light_x + py * light_y
                if hf > 0.82:
                    hf = 0.82
                elif hf < -0.82:
                    hf = -0.82
                body, shadow, mid, glow, lit, spec, edge, _, _ = _band_colors(
                    base, int(round(fog * 12.0))
                )
                bucket.append(
                    (depth, 0, ax, ay, ra, bx, by, rb, px, py, ehx, ehy, hf,
                     body, shadow, mid, glow, lit, spec, edge)
                )
                if translucent:
                    spread = (ra if ra > rb else rb) + 2.0
                    g_minx = min(g_minx, ax - spread, bx - spread)
                    g_maxx = max(g_maxx, ax + spread, bx + spread)
                    g_miny = min(g_miny, ay - spread, by - spread)
                    g_maxy = max(g_maxy, ay + spread, by + spread)

            # Joint spheres at elbows and free ends.
            last = len(nodes) - 1
            turn_set = set(system.turns)
            for idx in sorted(turn_set | {0, last}):
                p = proj[idx]
                if p is None:
                    continue
                sx, sy, depth = p
                if sx < min_x or sx > max_x or sy < min_y or sy > max_y:
                    continue
                fog = (depth - FOG_NEAR) / fog_span
                if fog < 0.0:
                    fog = 0.0
                elif fog > 1.0:
                    fog = 1.0
                fog = int(fog * 0.78 * 12.0) / 12.0
                is_turn = idx in turn_set
                scale = 1.16 if is_turn else 1.0
                diameter = 2.0 * PIPE_R * scale * focal / depth
                cached = _band_colors(base, int(round(fog * 12.0)))
                sprite = _sphere_sprite(cached[7], diameter)
                ring = cached[8] if is_turn else None
                bucket.append((depth - 0.06, 1, sx, sy, sprite, ring))
                if translucent:
                    spread = diameter * 0.62 + 2.0
                    g_minx = min(g_minx, sx - spread)
                    g_maxx = max(g_maxx, sx + spread)
                    g_miny = min(g_miny, sy - spread)
                    g_maxy = max(g_maxy, sy + spread)

        # Recycling / spawning runs are semi-transparent: composite them in a
        # real alpha layer beneath the opaque maze so a dissolving system never
        # shows up as a black silhouette against the night sky.
        if ghost:
            gsurf = self._ghost
            if gsurf is None or gsurf.get_size() != (w, h):
                gsurf = pygame.Surface((w, h), pygame.SRCALPHA)
                self._ghost = gsurf
            area = pygame.Rect(
                int(g_minx) - 2,
                int(g_miny) - 2,
                int(g_maxx - g_minx) + 6,
                int(g_maxy - g_miny) + 6,
            ).clip(pygame.Rect(0, 0, w, h))
            if area.w > 0 and area.h > 0:
                gsurf.fill((0, 0, 0, 0), area)
                self._render_items(ghost, gsurf)
                weight = ghost_weight if ghost_weight > 0.0 else 1.0
                gsurf.set_alpha(max(0, min(255, int(255.0 * ghost_alpha / weight))))
                target.blit(gsurf, area.topleft, area)
                gsurf.set_alpha(255)
        if solid:
            self._render_items(solid, target)

        # Faint additive bloom at the growing head of every active system.
        for system in self.systems:
            if system.state != "grow" or system.alpha < 0.55 or not system.nodes:
                continue
            node = system.nodes[-1]
            relx = node[0] - cx_w - ex
            rely = node[1] - cy_w - ey
            relz = node[2] - cz_w - ez
            depth = relx * fx + rely * fy + relz * fz
            if depth < 0.9:
                continue
            inv = focal / depth
            sx = hw + (relx * rx + rely * ry + relz * rz) * inv
            sy = hh - (relx * ux + rely * uy + relz * uz) * inv
            glow = self._glows[system.pal]
            if glow is None:
                continue
            size = glow.get_width()
            target.blit(
                glow,
                (int(sx - size * 0.5), int(sy - size * 0.5)),
                special_flags=pygame.BLEND_RGB_ADD,
            )

        self._present(surf)

    def _render_items(self, items: list[tuple], target: pygame.Surface) -> None:
        # Painter's algorithm: far to near, joints on top of their own tube ends.
        items.sort(key=lambda it: (-it[0], it[1]))
        gfx = _gfxdraw
        ax = ay = ra = bx = by = rb = px = py = 0.0
        ax0 = ay0 = bx0 = by0 = 0.0

        def band(color: tuple[int, int, int], s0: float, s1: float) -> None:
            pygame.draw.polygon(
                target,
                color,
                (
                    (ax0 + px * s0 * ra, ay0 + py * s0 * ra),
                    (bx0 + px * s0 * rb, by0 + py * s0 * rb),
                    (bx0 + px * s1 * rb, by0 + py * s1 * rb),
                    (ax0 + px * s1 * ra, ay0 + py * s1 * ra),
                ),
            )

        for item in items:
            if item[1] == 0:
                (_, _, ax, ay, ra, bx, by, rb, px, py, ehx, ehy, hf,
                 body, shadow, mid, glow, lit, spec, edge) = item
                # Extend the silhouette a hair along the tube axis so adjacent
                # segments overlap instead of leaving a 1px background seam.
                ax0, ay0 = ax - ehx, ay - ehy
                bx0, by0 = bx + ehx, by + ehy
                p0x, p0y = ax0 - px * ra, ay0 - py * ra
                p1x, p1y = ax0 + px * ra, ay0 + py * ra
                p2x, p2y = bx0 + px * rb, by0 + py * rb
                p3x, p3y = bx0 - px * rb, by0 - py * rb
                big = gfx is not None and ra + rb > 5.0
                if big:
                    pts = [
                        (int(p0x), int(p0y)),
                        (int(p3x), int(p3y)),
                        (int(p2x), int(p2y)),
                        (int(p1x), int(p1y)),
                    ]
                    try:
                        gfx.filled_polygon(target, pts, body)
                    except (TypeError, ValueError):  # pragma: no cover
                        pygame.draw.polygon(target, body, pts)
                        big = False
                else:
                    pygame.draw.polygon(target, body, ((p0x, p0y), (p3x, p3y), (p2x, p2y), (p1x, p1y)))

                if ra > 1.8 or rb > 1.8:
                    # Dark side opposite the key light, in two steps for a smooth roll-off.
                    if hf >= 0.0:
                        band(shadow, -1.07, -0.56)
                        band(mid, -0.60, -0.14)
                    else:
                        band(shadow, 1.07, 0.56)
                        band(mid, 0.60, 0.14)
                    # Broad lit glow, then the hot specular stripe.
                    band(glow, max(-1.0, hf - 0.41), min(1.0, hf + 0.41))
                    band(lit, max(-1.0, hf - 0.22), min(1.0, hf + 0.22))
                    if ra > 3.4 or rb > 3.4:
                        band(spec, max(-1.0, hf - 0.065), min(1.0, hf + 0.065))
            else:
                _, _, sx, sy, sprite, ring = item
                diameter = sprite.get_width()
                if ring is not None and diameter >= 12:
                    pygame.draw.circle(target, ring, (int(sx), int(sy)), diameter // 2, max(1, diameter // 22))
                target.blit(sprite, (int(sx - diameter * 0.5), int(sy - diameter * 0.5)))
