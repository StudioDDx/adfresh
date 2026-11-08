"""Lava Lamp: warm wax metaballs rising and sinking inside a frosted cone.

The wax is a real metaball field — each blob contributes r²/d², the surface
is the threshold — evaluated with numpy on a coarse grid covering the lamp
and upscaled, so blobs genuinely merge and pinch. Blob motion is a pure
function of ``self.t`` and the seeded rng (no per-frame randomness), which
keeps the simulation identical on every monitor of a spanned layout.
"""

from __future__ import annotations

import math

import numpy as np
import pygame

from adfresh.drawutil import radial, vertical_gradient
from adfresh.modules.base import Module

GRID_W = 120  # coarse field resolution inside the lamp bounding box
BLOBS = 9

# Hot-to-cool wax ramp sampled by field strength.
WAX_CORE = (255, 214, 110)
WAX_MID = (235, 110, 40)
WAX_EDGE = (150, 30, 24)


class Lava(Module):
    id = "lava"
    title = "Lava Lamp"

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        span = min(w, h)
        self.lamp_h = span * 0.72
        self.lamp_w = self.lamp_h * 0.46
        self.cx = w / 2
        self.top_y = h * 0.5 - self.lamp_h / 2
        self.bot_y = self.top_y + self.lamp_h
        self.halo = radial(int(self.lamp_h * 1.7), (150, 60, 30), 90)
        self.room = vertical_gradient(
            w, h, [(0.0, (8, 6, 12)), (0.6, (14, 8, 14)), (1.0, (20, 10, 12))]
        )
        self.blobs = []
        for i in range(BLOBS):
            self.blobs.append(
                {
                    # vertical cycle: blobs drift up, linger, sink
                    "cycle": self.rng.uniform(14.0, 30.0),
                    "phase": self.rng.uniform(0, 1.0),
                    "rx": self.rng.uniform(0.5, 1.0),  # horizontal sway, cone fraction
                    "kx": self.rng.uniform(0.5, 1.5),
                    "px": self.rng.uniform(0, math.tau),
                    "r": self.rng.uniform(0.065, 0.115),  # radius, lamp-height fraction
                    "big": i < 2,  # a couple of anchors that stay low and merge
                }
            )
        grid_h = int(GRID_W * self.lamp_h / max(1.0, self.lamp_w))
        self.gx = np.linspace(-0.5, 0.5, GRID_W, dtype=np.float32)[:, None]
        self.gy = np.linspace(0.0, 1.0, grid_h, dtype=np.float32)[None, :]
        self.grid_size = (GRID_W, grid_h)

    def _cone_half(self, frac: float) -> float:
        """Half-width of the cone at vertical fraction ``frac`` (0 top, 1 bottom)."""
        return 0.16 + 0.34 * frac

    def _blob_positions(self) -> list[tuple[float, float, float]]:
        """Blob (x, y, radius) in lamp-local fractions for the current time."""
        out = []
        for b in self.blobs:
            if b["big"]:
                fy = 0.88 + 0.05 * math.sin(self.t * 0.35 + b["px"])
            else:
                # smooth up-down loop: 0 = bottom, 1 = top
                u = (self.t / b["cycle"] + b["phase"]) % 1.0
                fy = 0.9 - 0.82 * (0.5 - 0.5 * math.cos(math.tau * u))
            sway = math.sin(self.t * b["kx"] + b["px"]) * b["rx"]
            fx = sway * max(0.0, self._cone_half(fy) - b["r"] * 0.5) * 0.8
            # wax shrinks a touch as it rises (cooling), plumps at the bottom
            r = b["r"] * (1.12 - 0.3 * (1.0 - fy))
            out.append((fx, fy, r))
        return out

    def _wax_surface(self) -> pygame.Surface:
        """Thresholded metaball field for the lamp interior, wax colors."""
        gw, gh = self.grid_size
        # grid units: x in cone-fraction units of lamp height, so distance is isotropic
        aspect = self.lamp_w / self.lamp_h
        field = np.zeros((gw, gh), dtype=np.float32)
        for fx, fy, r in self._blob_positions():
            dx = (self.gx - fx) * aspect / r
            dy = (self.gy - fy) / r
            field += 1.0 / np.maximum(dx * dx + dy * dy, 1e-4)
        edge = np.clip((field - 1.0) / 0.3, 0.0, 1.0)
        core = np.clip((field - 2.1) / 1.4, 0.0, 1.0)
        arr = np.zeros((gw, gh, 3), dtype=np.float32)
        for ch in range(3):
            mid = WAX_EDGE[ch] + (WAX_MID[ch] - WAX_EDGE[ch]) * edge
            arr[:, :, ch] = mid + (WAX_CORE[ch] - mid) * core
        # hard cutoff outside the threshold, soft one-pixel lip
        mask = field >= 1.0
        arr *= mask[:, :, None]
        surf = pygame.Surface((gw, gh))
        pygame.surfarray.blit_array(surf, arr.astype(np.uint8))
        return pygame.transform.smoothscale(surf, (int(self.lamp_w), int(self.lamp_h)))

    def draw(self, surf: pygame.Surface) -> None:
        surf.blit(self.room, (0, 0))
        cx, top, bot = self.cx, self.top_y, self.bot_y
        lamp_w, lamp_h = self.lamp_w, self.lamp_h

        halo = self.halo
        cy = top + lamp_h * 0.5
        surf.blit(halo, (int(cx - halo.get_width() / 2), int(cy - halo.get_height() / 2)))

        # Frosted cone glass with the wax clipped inside it.
        glass = pygame.Surface((int(lamp_w) + 2, int(lamp_h) + 2), pygame.SRCALPHA)
        cone = [
            (lamp_w / 2 - self._cone_half(0.0) * lamp_w, 0),
            (lamp_w / 2 + self._cone_half(0.0) * lamp_w, 0),
            (lamp_w / 2 + self._cone_half(1.0) * lamp_w, lamp_h),
            (lamp_w / 2 - self._cone_half(1.0) * lamp_w, lamp_h),
        ]
        pygame.draw.polygon(glass, (26, 10, 14, 255), cone)
        wax = self._wax_surface()
        # Keep only wax pixels that fall inside the cone.
        cone_mask = pygame.Surface((int(lamp_w), int(lamp_h)), pygame.SRCALPHA)
        inner = [
            (lamp_w / 2 - self._cone_half(0.0) * lamp_w, 0),
            (lamp_w / 2 + self._cone_half(0.0) * lamp_w, 0),
            (lamp_w / 2 + self._cone_half(1.0) * lamp_w, lamp_h),
            (lamp_w / 2 - self._cone_half(1.0) * lamp_w, lamp_h),
        ]
        pygame.draw.polygon(cone_mask, (255, 255, 255, 255), inner)
        wax.blit(cone_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        glass.blit(wax, (1, 1), special_flags=pygame.BLEND_RGB_ADD)
        # Liquid line glow near the bottom.
        pygame.draw.line(
            glass,
            (255, 120, 50, 60),
            (lamp_w / 2 - self._cone_half(0.93) * lamp_w, lamp_h * 0.93),
            (lamp_w / 2 + self._cone_half(0.93) * lamp_w, lamp_h * 0.93),
            2,
        )
        surf.blit(glass, (int(cx - lamp_w / 2) - 1, int(top) - 1))

        # Cap and base, brushed warm metal.
        cap_w = lamp_w * 0.42
        pygame.draw.polygon(
            surf,
            (52, 34, 30),
            [
                (cx - cap_w * 0.7, top - lamp_h * 0.06),
                (cx + cap_w * 0.7, top - lamp_h * 0.06),
                (cx + cap_w, top + 2),
                (cx - cap_w, top + 2),
            ],
        )
        pygame.draw.line(surf, (120, 70, 50), (cx - cap_w * 0.6, top - lamp_h * 0.045), (cx + cap_w * 0.6, top - lamp_h * 0.045), 2)
        base_top = bot + 2
        pygame.draw.polygon(
            surf,
            (46, 28, 26),
            [
                (cx - lamp_w * 0.55, base_top),
                (cx + lamp_w * 0.55, base_top),
                (cx + lamp_w * 0.68, base_top + lamp_h * 0.09),
                (cx - lamp_w * 0.68, base_top + lamp_h * 0.09),
            ],
        )
        pygame.draw.line(surf, (110, 60, 44), (cx - lamp_w * 0.5, base_top + 4), (cx + lamp_w * 0.5, base_top + 4), 2)
