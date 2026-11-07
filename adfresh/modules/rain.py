"""Atmospheric night city behind rain-streaked glass, with parallax skyline, wet window pane, splashes, and fractal lightning."""

from __future__ import annotations

import math
import random

import pygame

from adfresh.drawutil import additive_orb, blit_alpha, mix, radial, vertical_gradient, vignette
from adfresh.modules.base import Module


class Rain(Module):
    id = "rain"
    title = "Hard Rain"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        # Parallax skyline layers
        self.cached_layers: list[tuple[pygame.Surface, pygame.Surface]] = []
        self.layer_offsets: list[float] = [0.0, 0.0, 0.0]
        self.beacons: list[dict] = []
        self.splash_surfaces: list[tuple[float, float, float]] = []

        # Sky and ambient glow
        self.sky_normal: pygame.Surface | None = None
        self.sky_flash: pygame.Surface | None = None
        self.horizon_glow: pygame.Surface | None = None

        # Lightning system
        self.bolt: dict | None = None
        self.lightning_time: float = 0.0
        self.lightning_duration: float = 0.0
        self.next_lightning: float = 5.0
        self.flash_intensity: float = 0.0

        # Falling rain streaks
        self.streaks: list[list[float]] = []

        # Wet glass & condensation
        self.glass_mist: pygame.Surface | None = None
        self.glass_dynamic: pygame.Surface | None = None
        self.drops: list[dict] = []

        # Rain splashes and ripples
        self.ripples: list[dict] = []
        self.spray_particles: list[dict] = []
        self.splash_surface: pygame.Surface | None = None

        # Pre-rendered lighting accents for high-performance 60 FPS rendering
        self.lightning_bloom: pygame.Surface | None = None
        self.red_halo: pygame.Surface | None = None
        self.white_halo: pygame.Surface | None = None

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        self.splash_surfaces = []
        self.beacons = []

        # Pre-render small halos and bloom orbs
        bloom_d = min(360, max(120, int(w * 0.35)))
        self.lightning_bloom = radial(bloom_d, (210, 225, 255), 255)
        self.red_halo = radial(12, (255, 30, 30), 255)
        self.white_halo = radial(14, (240, 245, 255), 255)

        # 1. Sky backgrounds
        self.sky_normal = vertical_gradient(
            w,
            h,
            [(0.0, (5, 7, 14)), (0.55, (10, 14, 24)), (1.0, (20, 18, 28))],
        )
        self.sky_flash = vertical_gradient(
            w,
            h,
            [(0.0, (190, 205, 235)), (0.45, (220, 230, 250)), (1.0, (130, 140, 175))],
        )

        # Soft city ambient horizon glow at the base of the skyline
        glow_h = max(10, int(h * 0.45))
        glow_base = vertical_gradient(
            w,
            glow_h,
            [
                (0.0, (0, 0, 0)),
                (0.5, (38, 22, 38)),
                (0.85, (56, 34, 48)),
                (1.0, (48, 28, 42)),
            ],
        )
        self.horizon_glow = pygame.Surface((w, glow_h), pygame.SRCALPHA)
        self.horizon_glow.blit(glow_base, (0, 0))
        # Fade the top so it blends smoothly into the sky
        for y in range(glow_h):
            alpha = int(140 * (y / glow_h) ** 1.8)
            pygame.draw.line(self.horizon_glow, (0, 0, 0, 255 - alpha), (0, y), (w, y), 1)

        # 2. Multi-tier parallax skyline layers
        # Layer 0: Background (distant towers, spires, low contrast)
        # Layer 1: Midground (skyscrapers, angled roofs, water towers)
        # Layer 2: Foreground (prominent towers, detailed crowns, bulkheads, water towers)
        self.cached_layers = []
        layer_specs = [
            {
                "tier": 0,
                "color_base": (16, 20, 32),
                "rim_color": (120, 140, 175, 160),
                "h_min": 0.38,
                "h_max": 0.68,
                "bw_min": 36,
                "bw_max": 80,
                "win_size": (2, 3),
                "win_density": 0.22,
                "allow_water_tower": False,
            },
            {
                "tier": 1,
                "color_base": (11, 14, 22),
                "rim_color": (150, 175, 210, 190),
                "h_min": 0.26,
                "h_max": 0.58,
                "bw_min": 55,
                "bw_max": 130,
                "win_size": (3, 5),
                "win_density": 0.26,
                "allow_water_tower": True,
            },
            {
                "tier": 2,
                "color_base": (6, 8, 14),
                "rim_color": (180, 205, 240, 220),
                "h_min": 0.16,
                "h_max": 0.46,
                "bw_min": 85,
                "bw_max": 200,
                "win_size": (4, 7),
                "win_density": 0.30,
                "allow_water_tower": True,
            },
        ]

        # Extra buffer width for parallax drift
        buf_w = w + 40
        for spec in layer_specs:
            norm_surf = pygame.Surface((buf_w, h), pygame.SRCALPHA)
            rim_surf = pygame.Surface((buf_w, h), pygame.SRCALPHA)
            self._generate_skyline_layer(norm_surf, rim_surf, spec, buf_w, h)
            self.cached_layers.append((norm_surf, rim_surf))

        # Bottom ledge of the window frame / screen is always a splash surface
        self.splash_surfaces.append((0.0, float(w), float(h)))

        # 3. Falling rain streaks (3 depth tiers)
        self.streaks = []
        for _ in range(150):  # Far
            self.streaks.append(self._create_streak(0.35))
        for _ in range(100):  # Mid
            self.streaks.append(self._create_streak(0.65))
        for _ in range(60):  # Near
            self.streaks.append(self._create_streak(1.0))

        # 4. Wet glass window pane: condensation & misty texture
        self.glass_mist = pygame.Surface((w, h), pygame.SRCALPHA)
        self._generate_glass_mist(self.glass_mist, w, h)
        self.glass_dynamic = pygame.Surface((w, h), pygame.SRCALPHA)
        self.splash_surface = pygame.Surface((w, h), pygame.SRCALPHA)

        # Sliding raindrops with surface tension
        self.drops = [self._create_drop(anywhere=True) for _ in range(32)]
        self.ripples = []
        self.spray_particles = []

    def _create_streak(self, depth: float) -> list[float]:
        return [
            self.rng.uniform(-20, self.w + 40),
            self.rng.uniform(-20, self.h),
            depth,
        ]

    def _create_drop(self, anywhere: bool) -> dict:
        r = self.rng.uniform(2.5, 6.5)
        return {
            "x": self.rng.uniform(8, self.w - 8),
            "y": self.rng.uniform(0, self.h) if anywhere else self.rng.uniform(-20, -5),
            "r": r,
            "state": "sticking" if anywhere and self.rng.random() < 0.65 else "sliding",
            "timer": self.rng.uniform(0.6, 2.8) if anywhere else self.rng.uniform(0.18, 0.45),
            "vy": self.rng.uniform(160, 380) * (r / 4.0),
            "wobble_seed": self.rng.uniform(0, math.tau),
            "trail": [],  # [(x, y, age)]
            "residuals": [],  # [(x, y, r, alpha)]
        }

    def _generate_glass_mist(self, surf: pygame.Surface, w: int, h: int) -> None:
        """Pre-renders misty window condensation beads and subtle edge vignette."""
        # 1. Micro-condensation beads scattered across the pane
        num_beads = min(1200, max(450, int(w * h / 1200)))
        for _ in range(num_beads):
            bx = self.rng.uniform(0, w)
            by = self.rng.uniform(0, h)
            br = self.rng.uniform(0.7, 2.2)
            alpha = self.rng.randint(35, 75)
            pygame.draw.circle(surf, (215, 230, 248, alpha), (int(bx), int(by)), int(br + 0.5))
            # Tiny off-center specular glint
            if br >= 1.2:
                pygame.draw.circle(
                    surf,
                    (255, 255, 255, min(255, alpha + 70)),
                    (int(bx - br * 0.3), int(by - br * 0.3)),
                    1,
                )

        # 2. Cool dark misty border vignette along window frame
        vg = vignette(w, h)
        surf.blit(vg, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    def _generate_skyline_layer(
        self,
        norm_surf: pygame.Surface,
        rim_surf: pygame.Surface,
        spec: dict,
        buf_w: int,
        h: int,
    ) -> None:
        """Generates architectural silhouettes, rooftop water towers, antennas, and glowing windows."""
        tier = spec["tier"]
        color_base = spec["color_base"]
        rim_color = spec["rim_color"]
        x = -15.0

        while x < buf_w:
            bw = self.rng.uniform(spec["bw_min"], spec["bw_max"])
            bh = self.rng.uniform(h * spec["h_min"], h * spec["h_max"])
            by = h - bh

            # Building crown type
            crown_type = self.rng.choice(
                ["flat", "spire", "stepped", "slanted", "bulkhead"]
                + (["water_tower"] if spec["allow_water_tower"] else [])
            )

            # Main building body
            pygame.draw.rect(norm_surf, color_base, (x, by, bw, bh))

            # Architectural crown construction
            if crown_type == "stepped" and bw > 45:
                # Art Deco tiered setbacks
                step1_w = bw * 0.72
                step1_h = self.rng.uniform(14, 28)
                step1_x = x + (bw - step1_w) / 2
                step1_y = by - step1_h
                pygame.draw.rect(norm_surf, color_base, (step1_x, step1_y, step1_w, step1_h))
                pygame.draw.line(rim_surf, rim_color, (step1_x, step1_y), (step1_x + step1_w, step1_y), 1)

                step2_w = step1_w * 0.6
                step2_h = self.rng.uniform(12, 22)
                step2_x = x + (bw - step2_w) / 2
                step2_y = step1_y - step2_h
                pygame.draw.rect(norm_surf, color_base, (step2_x, step2_y, step2_w, step2_h))
                pygame.draw.line(rim_surf, rim_color, (step2_x, step2_y), (step2_x + step2_w, step2_y), 1)

                # Spire on top of ziggurat
                spire_h = self.rng.uniform(18, 38)
                spire_x = x + bw / 2
                pygame.draw.line(norm_surf, color_base, (spire_x, step2_y), (spire_x, step2_y - spire_h), 2)
                pygame.draw.line(rim_surf, rim_color, (spire_x, step2_y), (spire_x, step2_y - spire_h), 1)

                self._add_beacon(spire_x, step2_y - spire_h, tier, is_strobe=(tier >= 1 and self.rng.random() < 0.4))
                if tier >= 1:
                    self.splash_surfaces.append((step1_x, step1_x + step1_w, step1_y))
                    self.splash_surfaces.append((step2_x, step2_x + step2_w, step2_y))

            elif crown_type == "spire":
                spire_h = self.rng.uniform(25, 65)
                spire_x = x + bw * self.rng.uniform(0.35, 0.65)
                # Tapered antenna mast with crossbars
                pygame.draw.line(norm_surf, color_base, (spire_x, by), (spire_x, by - spire_h), 2)
                pygame.draw.line(rim_surf, rim_color, (spire_x, by), (spire_x, by - spire_h), 1)
                # Crossbar
                cb_y = by - spire_h * 0.65
                cb_w = self.rng.uniform(4, 9)
                pygame.draw.line(norm_surf, color_base, (spire_x - cb_w, cb_y), (spire_x + cb_w, cb_y), 1)
                pygame.draw.line(rim_surf, rim_color, (spire_x - cb_w, cb_y), (spire_x + cb_w, cb_y), 1)

                self._add_beacon(spire_x, by - spire_h, tier, is_strobe=False)
                pygame.draw.line(rim_surf, rim_color, (x, by), (x + bw, by), 1)
                if tier >= 1:
                    self.splash_surfaces.append((x, x + bw, by))

            elif crown_type == "slanted" and bw > 40:
                # Angled rooftop
                slant_h = self.rng.uniform(15, 30)
                pts = [(x, by), (x + bw, by), (x + bw, by - slant_h)]
                pygame.draw.polygon(norm_surf, color_base, pts)
                pygame.draw.line(rim_surf, rim_color, (x, by), (x + bw, by - slant_h), 1)
                if tier >= 1:
                    self.splash_surfaces.append((x, x + bw, by - slant_h * 0.5))

            elif crown_type == "water_tower" and spec["allow_water_tower"] and bw > 55:
                # Classic NYC wooden rooftop water tank on stilt legs
                tw = self.rng.uniform(16, 24)
                th = self.rng.uniform(15, 22)
                stilt_h = self.rng.uniform(14, 22)
                tx = x + self.rng.uniform(10, max(12, bw - tw - 10))
                ty = by - stilt_h - th

                # 4 timber/steel stilt legs with X-bracing
                leg1, leg2 = tx + 2, tx + tw - 2
                pygame.draw.line(norm_surf, (20, 24, 32), (leg1, by), (leg1 + 1, ty + th), 2)
                pygame.draw.line(norm_surf, (20, 24, 32), (leg2, by), (leg2 - 1, ty + th), 2)
                pygame.draw.line(norm_surf, (24, 28, 36), (leg1, by), (leg2, ty + th), 1)
                pygame.draw.line(norm_surf, (24, 28, 36), (leg2, by), (leg1, ty + th), 1)

                # Cedar barrel tank
                wood_tone = (44, 32, 28) if tier == 2 else (30, 24, 24)
                pygame.draw.rect(norm_surf, wood_tone, (tx, ty, tw, th))
                # Metal compression hoop bands
                pygame.draw.line(norm_surf, (20, 18, 18), (tx, ty + th * 0.35), (tx + tw, ty + th * 0.35), 1)
                pygame.draw.line(norm_surf, (20, 18, 18), (tx, ty + th * 0.70), (tx + tw, ty + th * 0.70), 1)

                # Conical roof cap
                roof_pts = [(tx - 2, ty), (tx + tw + 2, ty), (tx + tw / 2, ty - 8)]
                pygame.draw.polygon(norm_surf, (28, 22, 20), roof_pts)
                pygame.draw.line(rim_surf, rim_color, (tx - 2, ty), (tx + tw / 2, ty - 8), 1)
                pygame.draw.line(rim_surf, rim_color, (tx + tw / 2, ty - 8), (tx + tw + 2, ty), 1)

                # Top finial with subtle red beacon
                if self.rng.random() < 0.6:
                    self._add_beacon(tx + tw / 2, ty - 9, tier, is_strobe=False)

                # Building roof rim & splashes
                pygame.draw.line(rim_surf, rim_color, (x, by), (x + bw, by), 1)
                if tier >= 1:
                    self.splash_surfaces.append((x, x + bw, by))
                    self.splash_surfaces.append((tx - 2, tx + tw + 2, ty - 4))

            elif crown_type == "bulkhead" and bw > 50:
                # Elevator penthouse bulkhead & HVAC box
                bh_w = bw * self.rng.uniform(0.35, 0.55)
                bh_h = self.rng.uniform(10, 18)
                bh_x = x + self.rng.uniform(6, bw - bh_w - 6)
                bh_y = by - bh_h
                pygame.draw.rect(norm_surf, color_base, (bh_x, bh_y, bh_w, bh_h))
                pygame.draw.line(rim_surf, rim_color, (bh_x, bh_y), (bh_x + bh_w, bh_y), 1)

                # Antenna mast on bulkhead
                if self.rng.random() < 0.5:
                    ant_h = self.rng.uniform(15, 30)
                    pygame.draw.line(norm_surf, color_base, (bh_x + 4, bh_y), (bh_x + 4, bh_y - ant_h), 1)
                    self._add_beacon(bh_x + 4, bh_y - ant_h, tier, is_strobe=False)

                pygame.draw.line(rim_surf, rim_color, (x, by), (x + bw, by), 1)
                if tier >= 1:
                    self.splash_surfaces.append((x, x + bw, by))
                    self.splash_surfaces.append((bh_x, bh_x + bh_w, bh_y))

            else:
                # Flat roof with parapet rim
                pygame.draw.line(rim_surf, rim_color, (x, by), (x + bw, by), 1)
                if self.rng.random() < 0.35:
                    ant_h = self.rng.uniform(15, 35)
                    ant_x = x + bw * self.rng.uniform(0.2, 0.8)
                    pygame.draw.line(norm_surf, color_base, (ant_x, by), (ant_x, by - ant_h), 1)
                    self._add_beacon(ant_x, by - ant_h, tier, is_strobe=False)
                if tier >= 1:
                    self.splash_surfaces.append((x, x + bw, by))

            # Windows generation: varied glowing palettes and patterns
            self._generate_windows(norm_surf, x, by, bw, bh, spec)

            # Spacing to next building
            x += bw + self.rng.uniform(2, 12 if tier == 0 else 18)

    def _generate_windows(
        self,
        surf: pygame.Surface,
        bx: float,
        by: float,
        bw: float,
        bh: float,
        spec: dict,
    ) -> None:
        """Draws realistic glowing windows: warm amber, cool cyan, dimmed lights, and blinds."""
        tier = spec["tier"]
        win_w, win_h = spec["win_size"]
        density = spec["win_density"]

        pad_x = 6.0
        pad_y = 8.0
        avail_w = bw - pad_x * 2
        avail_h = bh - pad_y * 2
        if avail_w < win_w or avail_h < win_h:
            return

        cols = max(2, int(avail_w // (win_w + 5)))
        rows = max(2, int(avail_h // (win_h + 6)))
        col_step = avail_w / cols
        row_step = avail_h / rows

        # Architectural style for this building
        building_theme = self.rng.choice(["warm_residential", "cool_office", "mixed", "corporate"])

        for r in range(rows):
            # Many office buildings have entire floors lit or unlit
            floor_lit = self.rng.random() < (density * 1.5) if building_theme == "corporate" else True

            for c in range(cols):
                if not floor_lit or self.rng.random() > density:
                    # Subtle unlit dark glass pane
                    if tier >= 1 and self.rng.random() < 0.35:
                        wx = bx + pad_x + c * col_step
                        wy = by + pad_y + r * row_step
                        pygame.draw.rect(surf, (14, 18, 28), (wx, wy, win_w, win_h))
                    continue

                wx = bx + pad_x + c * col_step
                wy = by + pad_y + r * row_step

                # Determine window color and type
                roll = self.rng.random()
                if building_theme == "warm_residential":
                    if roll < 0.70:
                        color = self.rng.choice([(255, 195, 110), (250, 165, 75), (255, 215, 140)])
                    elif roll < 0.88:
                        color = (90, 80, 68)  # dimmed cozy light
                    else:
                        color = (170, 220, 240)  # cool television/monitor
                elif building_theme == "cool_office":
                    if roll < 0.65:
                        color = self.rng.choice([(175, 225, 245), (140, 200, 230), (210, 235, 250)])
                    elif roll < 0.85:
                        color = (75, 90, 115)  # dimmed office
                    else:
                        color = (255, 190, 105)
                else:  # mixed / corporate
                    if roll < 0.45:
                        color = self.rng.choice([(255, 195, 110), (245, 160, 65)])
                    elif roll < 0.80:
                        color = self.rng.choice([(165, 215, 240), (195, 230, 250)])
                    else:
                        color = (80, 95, 115)

                # Mute background tier windows for depth
                if tier == 0:
                    color = (int(color[0] * 0.55), int(color[1] * 0.55), int(color[2] * 0.60))

                # Draw illuminated window
                pygame.draw.rect(surf, color, (wx, wy, win_w, win_h))

                # Rooms with blinds / louvers effect
                if tier >= 1 and win_h >= 5 and self.rng.random() < 0.35:
                    blind_color = spec["color_base"]
                    # Horizontal blind slat dividing the window pane
                    mid_y = wy + win_h // 2
                    pygame.draw.line(surf, blind_color, (wx, mid_y), (wx + win_w - 1, mid_y), 1)

    def _add_beacon(self, x: float, y: float, tier: int, is_strobe: bool) -> None:
        """Registers a rooftop hazard beacon light with distinct pulsing or strobe rhythm."""
        color = (250, 250, 255) if is_strobe else (255, 42, 42)
        period = self.rng.uniform(0.9, 1.4) if is_strobe else self.rng.uniform(1.2, 1.8)
        self.beacons.append(
            {
                "x": x,
                "y": y,
                "tier": tier,
                "color": color,
                "period": period,
                "phase": self.rng.uniform(0, math.tau),
                "is_strobe": is_strobe,
            }
        )

    def step(self, dt: float) -> None:
        # 1. Update falling rain streaks
        wind_angle = -0.11
        for streak in self.streaks:
            depth = streak[2]
            speed = (550 + 750 * depth) * dt
            streak[1] += speed
            streak[0] += speed * wind_angle
            if streak[1] > self.h + 10 or streak[0] < -30:
                streak[0] = self.rng.uniform(0, self.w + 50)
                streak[1] = self.rng.uniform(-25, -5)

        # 2. Update sliding raindrops on wet glass
        for drop in self.drops:
            if drop["state"] == "sticking":
                drop["timer"] -= dt
                if drop["timer"] <= 0:
                    # Break surface tension and slide downward
                    drop["state"] = "sliding"
                    drop["timer"] = self.rng.uniform(0.18, 0.48)
                    drop["vy"] = self.rng.uniform(180, 420) * (drop["r"] / 4.0)
            else:
                # Sliding state
                drop["y"] += drop["vy"] * dt
                drop["x"] += self.rng.uniform(-14, 14) * dt
                # Append to wet trail
                drop["trail"].append((drop["x"], drop["y"], 0.0))
                # Occasionally pinch off a tiny residual micro-bead along the trail
                if self.rng.random() < 0.14:
                    drop["residuals"].append((drop["x"], drop["y"], self.rng.uniform(1.0, 1.8), 0.0))
                drop["timer"] -= dt
                if drop["timer"] <= 0:
                    # Surface tension catches drop again
                    drop["state"] = "sticking"
                    drop["timer"] = self.rng.uniform(0.8, 3.2)

            # Age and evaporate trails and residuals
            drop["trail"] = [(tx, ty, age + dt) for tx, ty, age in drop["trail"] if age + dt < 3.8]
            drop["residuals"] = [(rx, ry, rr, age + dt) for rx, ry, rr, age in drop["residuals"] if age + dt < 4.5]

            # Respawn if reached bottom
            if drop["y"] > self.h + 15:
                drop.update(self._create_drop(anywhere=False))

        # 3. Update rain splashes & ripples
        # Trigger stochastic ripples on building rooftops and window sill
        if self.splash_surfaces and len(self.ripples) < 60:
            for _ in range(self.rng.randint(1, 3)):
                ledge = self.rng.choice(self.splash_surfaces)
                sx = self.rng.uniform(ledge[0], ledge[1])
                sy = ledge[2]
                self._spawn_splash(sx, sy)

        # Step active ripples
        alive_ripples = []
        for rip in self.ripples:
            rip["age"] += dt
            if rip["age"] < rip["duration"]:
                alive_ripples.append(rip)
        self.ripples = alive_ripples

        # Step active spray particles
        alive_particles = []
        for p in self.spray_particles:
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 220 * dt  # Gravity
            p["age"] += dt
            if p["age"] < p["duration"]:
                alive_particles.append(p)
        self.spray_particles = alive_particles

        # 4. Realistic multi-phase lightning system
        self.next_lightning -= dt
        if self.lightning_duration > 0:
            self.lightning_time += dt
            if self.lightning_time >= self.lightning_duration:
                # Lightning event ended
                self.lightning_duration = 0.0
                self.flash_intensity = 0.0
                self.bolt = None
                self.next_lightning = self.rng.uniform(8.0, 16.0)
            else:
                self.flash_intensity = self._compute_flash_intensity(self.lightning_time)
        elif self.next_lightning <= 0:
            # Trigger fresh procedural lightning strike
            self.lightning_duration = self.rng.uniform(0.70, 0.95)
            self.lightning_time = 0.0
            self.bolt = self._generate_fractal_bolt()
            self.flash_intensity = self._compute_flash_intensity(0.0)

    def _spawn_splash(self, x: float, y: float) -> None:
        """Spawns an expanding elliptical ripple ring and upward mist spray particles."""
        max_r = self.rng.uniform(3.5, 7.5)
        self.ripples.append(
            {
                "x": x,
                "y": y,
                "max_r": max_r,
                "age": 0.0,
                "duration": self.rng.uniform(0.24, 0.38),
            }
        )
        # 2-3 upward micro spray droplets
        for _ in range(self.rng.randint(2, 3)):
            self.spray_particles.append(
                {
                    "x": x + self.rng.uniform(-2, 2),
                    "y": y - 1,
                    "vx": self.rng.uniform(-24, 24),
                    "vy": self.rng.uniform(-36, -65),
                    "age": 0.0,
                    "duration": self.rng.uniform(0.18, 0.28),
                }
            )

    def _compute_flash_intensity(self, t: float) -> float:
        """Multi-phase lightning flash curve: pre-flash, blinding strike, flutter, restrike, decay."""
        if t < 0.05:
            # Phase 1: Pre-flash / stepped leader pulse
            return 0.30 * math.sin(t / 0.05 * math.pi)
        elif t < 0.15:
            # Phase 2: Main return stroke (pure blinding flash)
            progress = (t - 0.05) / 0.10
            return 1.0 - progress * 0.30
        elif t < 0.21:
            # Phase 3: Flutter / dip
            return 0.35 + self.rng.uniform(0.0, 0.08)
        elif t < 0.29:
            # Phase 4: Restrike!
            progress = (t - 0.21) / 0.08
            return 0.82 * (1.0 - progress * 0.25)
        else:
            # Phase 5: Smooth ambient decay lingering in clouds
            decay_t = t - 0.29
            return 0.60 * math.exp(-decay_t * 5.2)

    def _generate_fractal_bolt(self) -> dict:
        """Generates a procedural fractal branching lightning bolt across the sky."""
        start_x = self.rng.uniform(self.w * 0.15, self.w * 0.85)
        target_x = start_x + self.rng.uniform(-self.w * 0.18, self.w * 0.18)
        target_y = self.rng.uniform(self.h * 0.40, self.h * 0.72)

        trunk = self._subdivide_bolt_path((start_x, 0.0), (target_x, target_y), max_disp=22.0, steps=16)

        branches = []
        twigs = []
        # Fork secondary branches from trunk joints
        for i in range(2, len(trunk) - 2):
            if self.rng.random() < 0.38 and len(branches) < 6:
                pt = trunk[i]
                angle = self.rng.choice((-1, 1)) * self.rng.uniform(0.45, 0.95)
                b_len = self.rng.uniform(self.h * 0.12, self.h * 0.25)
                end_x = pt[0] + math.sin(angle) * b_len
                end_y = pt[1] + math.cos(angle) * b_len
                b_pts = self._subdivide_bolt_path(pt, (end_x, end_y), max_disp=10.0, steps=7)
                branches.append(b_pts)

                # Fork tertiary twigs from branches
                if self.rng.random() < 0.45 and len(b_pts) > 3:
                    t_pt = b_pts[len(b_pts) // 2]
                    t_angle = angle + self.rng.choice((-1, 1)) * 0.5
                    t_len = b_len * 0.4
                    t_end = (t_pt[0] + math.sin(t_angle) * t_len, t_pt[1] + math.cos(t_angle) * t_len)
                    twigs.append(self._subdivide_bolt_path(t_pt, t_end, max_disp=5.0, steps=4))

        return {
            "trunk": trunk,
            "branches": branches,
            "twigs": twigs,
            "origin": (start_x, 0.0),
        }

    def _subdivide_bolt_path(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        max_disp: float,
        steps: int,
    ) -> list[tuple[float, float]]:
        """Procedurally segments a lightning path with random lateral jitter."""
        pts = [p1, p2]
        for _ in range(int(math.log2(steps))):
            new_pts = [pts[0]]
            for j in range(len(pts) - 1):
                a, b = pts[j], pts[j + 1]
                mid_x = (a[0] + b[0]) / 2 + self.rng.uniform(-max_disp, max_disp)
                mid_y = (a[1] + b[1]) / 2 + self.rng.uniform(-max_disp * 0.3, max_disp * 0.3)
                new_pts.append((mid_x, mid_y))
                new_pts.append(b)
            pts = new_pts
            max_disp *= 0.55
        return pts

    def draw(self, surf: pygame.Surface) -> None:
        flash = self.flash_intensity

        # 1. Sky rendering: smooth transition from dark midnight storm to illuminated flash
        if self.sky_normal:
            surf.blit(self.sky_normal, (0, 0))
        if flash > 0.01 and self.sky_flash:
            self.sky_flash.set_alpha(int(255 * flash))
            surf.blit(self.sky_flash, (0, 0))

        # Radial lightning bloom around origin in upper sky
        if flash > 0.08 and self.bolt and self.lightning_bloom:
            bx, by = self.bolt["origin"]
            self.lightning_bloom.set_alpha(int(140 * flash))
            bw_half = self.lightning_bloom.get_width() // 2
            bh_half = self.lightning_bloom.get_height() // 2
            surf.blit(self.lightning_bloom, (int(bx - bw_half), int(by - bh_half)))

        # 2. Draw branching procedural fractal lightning bolt
        if flash > 0.12 and self.bolt:
            self._draw_lightning(surf, self.bolt, flash)

        # 3. Ambient city horizon glow at base of skyline
        if self.horizon_glow:
            glow_y = self.h - self.horizon_glow.get_height()
            # Dim the city ambient glow slightly when blinding lightning overwhelms it
            glow_alpha = int(255 * (1.0 - flash * 0.6))
            self.horizon_glow.set_alpha(glow_alpha)
            surf.blit(self.horizon_glow, (0, glow_y))

        # 4. Multi-tier parallax city skyline rendering
        # Subtle organic sway creates sensational 3D depth between layers
        sway = math.sin(self.t * 0.04)
        parallax_shifts = [sway * 1.5 - 20, sway * 4.0 - 20, sway * 8.0 - 20]

        for i, (norm_surf, rim_surf) in enumerate(self.cached_layers):
            sx = int(parallax_shifts[i])
            # Draw normal building layer with glowing windows
            surf.blit(norm_surf, (sx, 0))

            # During lightning flash, draw illuminated rim highlights on silhouettes
            if flash > 0.05:
                rim_surf.set_alpha(int(255 * flash))
                surf.blit(rim_surf, (sx, 0))

        # 5. Rooftop and spire hazard beacons
        self._draw_beacons(surf, parallax_shifts)

        # 6. Rain splashes and ripple rings on rooftops and ledges
        self._draw_splashes(surf)

        # 7. Multi-tier falling rain streaks
        self._draw_streaks(surf, flash)

        # 8. Wet glass window pane: condensation texture & sliding raindrops
        if self.glass_mist:
            surf.blit(self.glass_mist, (0, 0))
        self._draw_glass_droplets(surf, flash)

    def _draw_lightning(self, surf: pygame.Surface, bolt: dict, flash: float) -> None:
        """Renders multi-pass glowing lightning bolt: outer bloom, electric cyan mid, pure white core."""
        trunk = bolt["trunk"]
        branches = bolt["branches"]
        twigs = bolt["twigs"]

        # Outer lavender/cyan bloom
        bloom_alpha = int(180 * min(1.0, flash / 0.5))
        pygame.draw.lines(surf, (120, 145, 255), False, trunk, 10)
        for b in branches:
            pygame.draw.lines(surf, (120, 145, 255), False, b, 5)

        # Mid electric cyan glow
        pygame.draw.lines(surf, (185, 215, 255), False, trunk, 5)
        for b in branches:
            pygame.draw.lines(surf, (185, 215, 255), False, b, 3)

        # Blinding white hot core
        pygame.draw.lines(surf, (255, 255, 255), False, trunk, 2)
        for b in branches:
            pygame.draw.lines(surf, (255, 255, 255), False, b, 1)
        for tw in twigs:
            pygame.draw.lines(surf, (240, 245, 255), False, tw, 1)

    def _draw_beacons(self, surf: pygame.Surface, parallax_shifts: list[float]) -> None:
        """Renders pulsing red aviation hazard beacons and white strobe lights on spires."""
        for b in self.beacons:
            tier = b["tier"]
            shift = parallax_shifts[tier]
            bx = int(b["x"] + shift)
            by = int(b["y"])

            if b["is_strobe"]:
                # White strobe flash
                strobe_on = ((self.t + b["phase"]) % b["period"]) < 0.08
                if strobe_on:
                    pygame.draw.circle(surf, (255, 255, 255), (bx, by), 2)
                    if self.white_halo:
                        self.white_halo.set_alpha(190)
                        surf.blit(self.white_halo, (bx - 7, by - 7))
            else:
                # Pulsing red aviation light
                pulse = max(0.0, math.sin((self.t + b["phase"]) * (math.tau / b["period"]))) ** 6
                if pulse > 0.04:
                    pygame.draw.circle(surf, (255, 40, 40), (bx, by), 1)
                    if self.red_halo:
                        self.red_halo.set_alpha(int(200 * pulse))
                        surf.blit(self.red_halo, (bx - 6, by - 6))

    def _draw_splashes(self, surf: pygame.Surface) -> None:
        """Renders circular splash ripple rings and spray mist particles."""
        if not self.ripples and not self.spray_particles:
            return

        if self.splash_surface:
            self.splash_surface.fill((0, 0, 0, 0))
            # Elliptical ripple rings
            for rip in self.ripples:
                progress = rip["age"] / rip["duration"]
                rx = rip["max_r"] * progress
                ry = rx * 0.32  # Perspective squashed ellipse
                alpha = int(190 * (1.0 - progress))
                box = (rip["x"] - rx, rip["y"] - ry, rx * 2, ry * 2)
                if box[2] >= 2 and box[3] >= 1:
                    pygame.draw.ellipse(self.splash_surface, (205, 225, 250, alpha), box, 1)

            # Spray mist droplets
            for p in self.spray_particles:
                progress = p["age"] / p["duration"]
                alpha = int(210 * (1.0 - progress))
                pygame.draw.circle(
                    self.splash_surface,
                    (215, 235, 255, alpha),
                    (int(p["x"]), int(p["y"])),
                    1,
                )

            surf.blit(self.splash_surface, (0, 0))

    def _draw_streaks(self, surf: pygame.Surface, flash: float) -> None:
        """Renders multi-tier falling rain streaks with wind drift and flash illumination."""
        wind_dx = -3.5
        for x, y, depth in self.streaks:
            length = 12 + 26 * depth
            speed_tint = int(75 + 120 * depth)
            if flash > 0.1:
                # Rain catches lightning flash
                color = (min(255, speed_tint + 60), min(255, speed_tint + 60), 255)
            else:
                color = (speed_tint, speed_tint + 15, min(255, speed_tint + 35))

            width = 2 if depth > 0.8 else 1
            pygame.draw.line(surf, color, (x, y), (x + wind_dx, y + length), width)

    def _draw_glass_droplets(self, surf: pygame.Surface, flash: float) -> None:
        """Renders dynamic raindrops on the glass pane with wet trails, surface tension, and caustics."""
        if not self.glass_dynamic:
            return

        self.glass_dynamic.fill((0, 0, 0, 0))

        # 1. Render wet trails left by sliding raindrops
        for drop in self.drops:
            r = drop["r"]
            trail = drop["trail"]
            if len(trail) >= 2:
                for i in range(len(trail) - 1):
                    x1, y1, a1 = trail[i]
                    x2, y2, a2 = trail[i + 1]
                    fade = max(0.0, 1.0 - (a1 + a2) / 7.6)
                    alpha = int(50 * fade)
                    pygame.draw.line(
                        self.glass_dynamic,
                        (215, 230, 250, alpha),
                        (x1, y1),
                        (x2, y2),
                        max(1, int(r * 0.55)),
                    )

            # Stationary micro-droplets pinched off along the trail
            for rx, ry, rr, age in drop["residuals"]:
                fade = max(0.0, 1.0 - age / 4.5)
                alpha = int(70 * fade)
                pygame.draw.circle(
                    self.glass_dynamic,
                    (220, 235, 252, alpha),
                    (int(rx), int(ry)),
                    int(rr),
                )

        # 2. Render sliding raindrops
        for drop in self.drops:
            r = drop["r"]
            x = drop["x"]
            y = drop["y"]

            # Surface tension micro-vibration when clinging
            if drop["state"] == "sticking":
                x += math.sin(self.t * 10 + drop["wobble_seed"]) * 0.22

            ix, iy, ir = int(x), int(y), int(r)

            # Refraction shadow meniscus (dark rim)
            pygame.draw.circle(self.glass_dynamic, (14, 18, 28, 90), (ix, iy + 1), ir + 1)

            # Translucent fluid droplet body
            drop_body_alpha = min(255, 75 + int(60 * flash))
            pygame.draw.circle(self.glass_dynamic, (200, 222, 248, drop_body_alpha), (ix, iy), ir)

            # Trailing teardrop meniscus when sliding downward
            if drop["state"] == "sliding":
                tail_h = min(14, int(ir * 1.8))
                pygame.draw.line(
                    self.glass_dynamic,
                    (210, 230, 252, 90),
                    (ix, iy - tail_h),
                    (ix, iy),
                    max(1, ir - 1),
                )

            # Lower caustic ambient reflection
            pygame.draw.circle(
                self.glass_dynamic,
                (225, 240, 255, 120),
                (ix + max(1, ir // 3), iy + max(1, ir // 3)),
                max(1, ir // 3),
            )

            # Upper-left bright specular highlight (glistens brightly during lightning)
            glint_alpha = 255 if flash > 0.1 else 220
            pygame.draw.circle(
                self.glass_dynamic,
                (255, 255, 255, glint_alpha),
                (ix - max(1, ir // 3), iy - max(1, ir // 3)),
                max(1, ir // 3),
            )

        surf.blit(self.glass_dynamic, (0, 0))
