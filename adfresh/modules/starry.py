"""A quiet night sky: photorealistic moon, rich starfield, cosmic nebulae, and atmospheric shooting stars."""

from __future__ import annotations

import math
import random
import numpy as np
import pygame

from adfresh.drawutil import radial, vertical_gradient
from adfresh.modules.base import Module

# Spectral colors for astronomical star types
SPECTRAL_COLORS = [
    (205, 228, 255),  # O/B: Blue-white giant
    (248, 250, 255),  # A: Crisp white
    (255, 244, 200),  # G: Yellow sun-like
    (255, 196, 145),  # K: Orange dwarf
    (255, 148, 120),  # M: Reddish dwarf
]


def _build_lunar_surface(diameter: int, phase_angle: float = 0.92) -> pygame.Surface:
    """Generate a photorealistic shaded lunar sphere with maria, craters, rays, and phase."""
    diameter = max(32, int(diameter))
    radius = diameter / 2.0
    surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)

    y, x = np.ogrid[:diameter, :diameter]
    nx = (x - radius + 0.5) / radius
    ny = (y - radius + 0.5) / radius
    r2 = nx**2 + ny**2
    mask = r2 <= 1.0

    nz = np.zeros_like(r2)
    nz[mask] = np.sqrt(1.0 - r2[mask])

    # Sun direction vector
    # phase_angle ~ 0.92 gives a classic waxing gibbous (~75% illuminated)
    sun_x = math.sin(phase_angle)
    sun_y = -0.18
    sun_z = math.cos(phase_angle)
    s_norm = math.sqrt(sun_x**2 + sun_y**2 + sun_z**2)
    sun_x, sun_y, sun_z = sun_x / s_norm, sun_y / s_norm, sun_z / s_norm

    # Base lunar albedo
    albedo = np.full((diameter, diameter), 0.76, dtype=np.float32)

    # Procedural Maria (basaltic plains)
    maria_list = [
        (-0.35, -0.18, 0.38, 0.45, 0.42),  # Oceanus Procellarum
        (-0.16, -0.32, 0.22, 0.20, 0.45),  # Mare Imbrium
        (0.18, -0.24, 0.17, 0.16, 0.42),   # Mare Serenitatis
        (0.35, -0.08, 0.20, 0.18, 0.44),   # Mare Tranquillitatis
        (0.58, -0.16, 0.13, 0.11, 0.40),   # Mare Crisium
        (0.42, 0.14, 0.22, 0.19, 0.38),    # Mare Fecunditatis
        (0.28, 0.26, 0.14, 0.14, 0.36),    # Mare Nectaris
        (-0.20, 0.30, 0.20, 0.22, 0.38),   # Mare Nubium
        (-0.42, 0.32, 0.12, 0.12, 0.35),   # Mare Humorum
        (-0.05, -0.05, 0.15, 0.12, 0.34),  # Central sinus
    ]

    harmonics = (
        np.sin(nx * 14.0 + ny * 11.0) * 0.05 +
        np.sin(nx * 29.0 - ny * 23.0) * 0.03 +
        np.cos(nx * 57.0 + ny * 49.0) * 0.015 +
        np.sin(nx * 95.0 - ny * 83.0) * 0.008
    )

    for cx, cy, rx, ry, depth in maria_list:
        dist_m = ((nx - cx) / rx)**2 + ((ny - cy) / ry)**2 + harmonics * 1.5
        m_factor = np.clip(1.0 - dist_m, 0.0, 1.0)**1.8
        albedo -= m_factor * depth

    albedo += harmonics * 0.5
    height = harmonics * 0.3

    # Impact craters with rims, dark floors, and high-albedo rays
    craters = [
        (-0.11, 0.62, 0.055, 0.45, 0.35, 1.2, 0.40),  # Tycho (prominent ray system)
        (-0.28, -0.15, 0.060, 0.40, 0.30, 0.8, 0.32), # Copernicus
        (-0.52, -0.12, 0.040, 0.35, 0.25, 0.5, 0.28), # Kepler
        (-0.50, -0.36, 0.035, 0.50, 0.15, 0.4, 0.45), # Aristarchus
        (-0.18, 0.38, 0.045, 0.35, 0.25, 0.0, 0.0),   # Bullialdus
        (0.08, 0.18, 0.040, 0.35, 0.25, 0.0, 0.0),    # Theophilus
        (-0.14, -0.62, 0.055, 0.30, 0.45, 0.0, 0.0),  # Plato
        (-0.14, 0.76, 0.065, 0.35, 0.30, 0.0, 0.0),   # Clavius
    ]

    crater_rng = random.Random(1337)
    for _ in range(40):
        rcx = crater_rng.uniform(-0.85, 0.85)
        rcy = crater_rng.uniform(-0.85, 0.85)
        if rcx**2 + rcy**2 < 0.82:
            rr = crater_rng.uniform(0.016, 0.036)
            craters.append((rcx, rcy, rr, 0.25, 0.20, 0.0, 0.0))

    for cx, cy, cr, rim_h, floor_d, ray_len, ray_b in craters:
        d2 = ((nx - cx)**2 + (ny - cy)**2) / (cr**2)
        d = np.sqrt(d2 + 1e-6)
        rim = np.exp(-((d - 1.0) / 0.28)**2) * rim_h
        bowl = np.clip(1.0 - d, 0.0, 1.0)**2 * (-floor_d)
        height += rim + bowl
        albedo += rim * 0.35
        if ray_len > 0:
            angle = np.arctan2(ny - cy, nx - cx)
            spokes = (np.sin(angle * 11.0)**4 + np.sin(angle * 17.0 + 1.2)**4)
            dist_ray = np.sqrt((nx - cx)**2 + (ny - cy)**2) / ray_len
            ray_falloff = np.clip(1.0 - dist_ray, 0.0, 1.0)**2.5
            albedo += spokes * ray_falloff * ray_b

    albedo = np.clip(albedo, 0.22, 1.0)

    # Topographical normal perturbation
    dh_dx = np.zeros_like(height)
    dh_dy = np.zeros_like(height)
    dh_dx[:, 1:-1] = (height[:, 2:] - height[:, :-2]) * 0.5 * radius * 0.12
    dh_dy[1:-1, :] = (height[2:, :] - height[:-2, :]) * 0.5 * radius * 0.12

    norm_x = nx - dh_dx
    norm_y = ny - dh_dy
    norm_z = nz
    len_norm = np.sqrt(norm_x**2 + norm_y**2 + norm_z**2 + 1e-6)
    norm_x /= len_norm
    norm_y /= len_norm
    norm_z /= len_norm

    n_dot_l = norm_x * sun_x + norm_y * sun_y + norm_z * sun_z
    geom_ndotl = nx * sun_x + ny * sun_y + nz * sun_z

    mu0 = np.clip(n_dot_l, 0.0, 1.0)
    mu = np.clip(norm_z, 0.0, 1.0)
    lommel = mu0 / (mu0 + mu + 0.08)
    diffuse = 0.65 * mu0 + 0.35 * (2.0 * lommel)

    sun_lit = np.clip(geom_ndotl / 0.05 + 0.5, 0.0, 1.0)
    illumination = diffuse * sun_lit

    # Earthshine on the night side
    earth_ndotl = np.clip(-geom_ndotl, 0.0, 1.0)
    earthshine = 0.055 * earth_ndotl * nz

    base_lunar_rgb = np.array([245, 240, 230], dtype=np.float32)
    earthshine_rgb = np.array([32, 45, 68], dtype=np.float32)

    tone = albedo[:, :, None]
    sun_light_color = base_lunar_rgb * tone * illumination[:, :, None]
    night_color = earthshine_rgb * (0.8 + 0.4 * tone) * earthshine[:, :, None]

    final_rgb = np.clip(sun_light_color + night_color, 0, 255).astype(np.uint8)

    # Anti-aliased limb
    alpha = np.zeros((diameter, diameter), dtype=np.float32)
    edge_dist = 1.0 - np.sqrt(r2)
    alpha[mask] = np.clip(edge_dist[mask] * radius * 1.5, 0.0, 1.0)
    alpha_u8 = (alpha * 255).astype(np.uint8)

    rgba = np.dstack([final_rgb, alpha_u8])
    surf_array = pygame.image.frombuffer(rgba.tobytes(), (diameter, diameter), "RGBA")
    surf.blit(surf_array, (0, 0))
    return surf


def _fast_additive_orb(diameter: int, rgb: tuple[int, int, int]) -> pygame.Surface:
    """Vectorized fast additive orb for cosmic dust and nebulae."""
    diameter = max(4, int(diameter))
    y, x = np.ogrid[:diameter, :diameter]
    radius = (diameter - 1) / 2.0
    dist = np.hypot(x - radius, y - radius) / radius
    fall = np.clip(1.0 - dist, 0.0, 1.0)**2.2
    arr = (fall[:, :, None] * np.array(rgb, dtype=np.float32)).astype(np.uint8)
    return pygame.image.frombuffer(arr.tobytes(), (diameter, diameter), "RGB")


class Starry(Module):
    id = "starry"
    title = "Starry Night"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.stars: list[dict] = []
        self.shots: list[dict] = []
        self.trails: list[dict] = []
        self.until_shot = 2.5
        self.backdrop: pygame.Surface | None = None
        self.moon = (0, 0, 0)
        self.moon_surf: pygame.Surface | None = None
        self.moon_glow: pygame.Surface | None = None
        self.star_stamps: dict = {}

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        # Pre-bake deep space sky & cosmic nebula clouds
        sky = vertical_gradient(
            w,
            h,
            [
                (0.0, (2, 4, 12)),
                (0.35, (5, 7, 20)),
                (0.70, (8, 10, 24)),
                (1.0, (14, 12, 26)),
            ],
        )
        self.backdrop = sky.copy()

        # Additive cosmic nebula clouds (soft purples, deep cyans, cosmic dust)
        nebula_surf = pygame.Surface((w, h))
        nebula_surf.fill((0, 0, 0))
        nebula_nodes = [
            # Diagonal Milky Way & cosmic dust cloud structures
            (0.20, 0.42, 0.72, (38, 14, 52)),  # Soft purple
            (0.32, 0.34, 0.58, (12, 42, 58)),  # Deep cyan
            (0.45, 0.28, 0.62, (46, 18, 65)),  # Cosmic purple
            (0.58, 0.22, 0.52, (15, 50, 68)),  # Deep cyan
            (0.70, 0.16, 0.64, (36, 14, 48)),  # Soft purple
            (0.12, 0.58, 0.52, (10, 35, 48)),  # Deep teal
            (0.38, 0.46, 0.48, (42, 16, 32)),  # Cosmic dust (warm violet/amber)
            (0.52, 0.36, 0.50, (28, 14, 42)),  # Dust veil
            (0.82, 0.22, 0.55, (14, 40, 56)),  # Cyan dust
            (0.25, 0.24, 0.42, (18, 52, 72)),  # Cyan pocket
            (0.64, 0.12, 0.46, (48, 20, 62)),  # High purple cloud
        ]
        for xf, yf, df, rgb in nebula_nodes:
            diam = int(min(w, h) * df)
            orb = _fast_additive_orb(diam, rgb)
            nx = int(xf * w - orb.get_width() // 2)
            ny = int(yf * h - orb.get_height() // 2)
            nebula_surf.blit(orb, (nx, ny), special_flags=pygame.BLEND_RGB_ADD)

        self.backdrop.blit(nebula_surf, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

        # Photorealistic Moon
        mr = int(min(w, h) * 0.11)
        mx = int(w * 0.78)
        my = int(h * 0.22)
        self.moon = (mx, my, mr)
        self.moon_surf = _build_lunar_surface(mr * 2, phase_angle=0.92)

        # Soft lunar glow
        glow_diam = mr * 6
        self.moon_glow = radial(glow_diam, (185, 205, 235), 75)

        # Pre-render anti-aliased star stamps for magnitudes and spectral types
        self._init_star_stamps()

        # Rich multi-magnitude starfield
        self.stars = []
        num_stars = 380
        for _ in range(num_stars):
            x = self.rng.uniform(0, w)
            y = self.rng.uniform(0, h * 0.94)

            # Milky way band density clustering
            band = abs((x / w) * 0.8 + 0.05 - (y / h))
            if band < 0.20 and self.rng.random() < 0.50:
                y = (x / w) * h * 0.75 + self.rng.uniform(-h * 0.08, h * 0.08)

            # Spectral color variety
            spec_idx = self.rng.choices(
                [0, 1, 2, 3, 4],
                weights=[0.22, 0.35, 0.22, 0.14, 0.07],
            )[0]

            # Magnitude distribution: mostly faint stars, few brilliant giants
            mag = self.rng.choices(
                [1, 2, 3, 4, 5],
                weights=[0.03, 0.08, 0.20, 0.35, 0.34],
            )[0]

            # Twinkling parameters
            p1 = self.rng.uniform(0, math.tau)
            p2 = self.rng.uniform(0, math.tau)
            s1 = self.rng.uniform(0.8, 2.5)
            s2 = self.rng.uniform(1.8, 4.5)

            self.stars.append({
                "x": x,
                "y": y,
                "spec": spec_idx,
                "mag": mag,
                "p1": p1,
                "p2": p2,
                "s1": s1,
                "s2": s2,
            })

        self.shots = []
        self.trails = []
        self.until_shot = self.rng.uniform(2.0, 5.0)

    def _init_star_stamps(self) -> None:
        """Pre-bake anti-aliased star surfaces for each spectral color and magnitude."""
        self.star_stamps = {}
        for s_idx, color in enumerate(SPECTRAL_COLORS):
            # Mag 1: First-magnitude giants (diffraction spikes + soft glow)
            m1_surf = pygame.Surface((17, 17), pygame.SRCALPHA)
            cx, cy = 8, 8
            # Soft aura
            pygame.draw.circle(m1_surf, (*color, 70), (cx, cy), 6)
            pygame.draw.circle(m1_surf, (*color, 140), (cx, cy), 3)
            # Core
            pygame.draw.circle(m1_surf, (255, 255, 255, 255), (cx, cy), 1)
            # Subtle 4-point diffraction spike
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                for d in range(2, 8):
                    a = max(0, int(180 * (1.0 - d / 8.0)))
                    m1_surf.set_at((cx + dx * d, cy + dy * d), (*color, a))
            self.star_stamps[(s_idx, 1)] = m1_surf

            # Mag 2: Bright stars (soft halo + bright core)
            m2_surf = pygame.Surface((9, 9), pygame.SRCALPHA)
            cx, cy = 4, 4
            pygame.draw.circle(m2_surf, (*color, 80), (cx, cy), 3)
            pygame.draw.circle(m2_surf, (255, 255, 255, 220), (cx, cy), 1)
            self.star_stamps[(s_idx, 2)] = m2_surf

            # Mag 3: Medium stars (anti-aliased 5x5 disc)
            m3_surf = pygame.Surface((5, 5), pygame.SRCALPHA)
            cx, cy = 2, 2
            pygame.draw.circle(m3_surf, (*color, 180), (cx, cy), 1)
            m3_surf.set_at((cx, cy), (255, 255, 255, 240))
            self.star_stamps[(s_idx, 3)] = m3_surf

            # Mag 4: Faint stars (anti-aliased 3x3)
            m4_surf = pygame.Surface((3, 3), pygame.SRCALPHA)
            m4_surf.set_at((1, 1), (*color, 210))
            for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2)):
                m4_surf.set_at((dx, dy), (*color, 75))
            self.star_stamps[(s_idx, 4)] = m4_surf

    def step(self, dt: float) -> None:
        # Spawn occasional atmospheric shooting stars
        self.until_shot -= dt
        if self.until_shot <= 0:
            self.until_shot = self.rng.uniform(3.5, 7.5)
            x = self.rng.uniform(self.w * 0.08, self.w * 0.72)
            y = self.rng.uniform(self.h * 0.04, self.h * 0.38)
            speed = self.rng.uniform(850, 1300)
            angle = self.rng.uniform(0.22, 0.48)  # Natural entry trajectory
            vx = speed * math.cos(angle)
            vy = speed * math.sin(angle)
            max_life = self.rng.uniform(0.45, 0.75)
            self.shots.append({
                "x": x,
                "y": y,
                "vx": vx,
                "vy": vy,
                "age": 0.0,
                "max_life": max_life,
            })

        # Update active shooting stars and deposit ionization trails
        alive_shots = []
        for shot in self.shots:
            x1, y1 = shot["x"], shot["y"]
            shot["x"] += shot["vx"] * dt
            shot["y"] += shot["vy"] * dt
            shot["age"] += dt
            x2, y2 = shot["x"], shot["y"]

            # Deposit ionization trail segment
            self.trails.append({
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "age": 0.0,
                "life": 1.1,  # ionization persistent glow
            })

            if shot["age"] < shot["max_life"] and shot["x"] < self.w + 60 and shot["y"] < self.h + 60:
                alive_shots.append(shot)
        self.shots = alive_shots

        # Update fading ionization trails
        alive_trails = []
        for tr in self.trails:
            tr["age"] += dt
            if tr["age"] < tr["life"]:
                alive_trails.append(tr)
        self.trails = alive_trails

    def draw(self, surf: pygame.Surface) -> None:
        # 1. Deep space sky backdrop with pre-baked cosmic nebula clouds
        if self.backdrop:
            surf.blit(self.backdrop, (0, 0))

        # 2. Photorealistic Moon with soft lunar glow
        mx, my, mr = self.moon
        if self.moon_glow:
            surf.blit(self.moon_glow, (mx - self.moon_glow.get_width() // 2, my - self.moon_glow.get_height() // 2))
        if self.moon_surf:
            surf.blit(self.moon_surf, (mx - mr, my - mr))

        # 3. Rich starfield with spectral variety and realistic twinkling
        for s in self.stars:
            tw = 0.52 + 0.35 * math.sin(self.t * s["s1"] + s["p1"]) + 0.13 * math.sin(self.t * s["s2"] + s["p2"])
            mag = s["mag"]
            spec = s["spec"]

            if mag == 5:
                # Faint background micro-star
                base_c = SPECTRAL_COLORS[spec]
                v = int(140 * max(0.2, min(1.0, tw)))
                color = (min(255, int(base_c[0] * v / 255)),
                         min(255, int(base_c[1] * v / 255)),
                         min(255, int(base_c[2] * v / 255)))
                surf.set_at((int(s["x"]), int(s["y"])), color)
            else:
                stamp = self.star_stamps.get((spec, mag))
                if stamp:
                    alpha = int(255 * max(0.15, min(1.0, tw)))
                    stamp.set_alpha(alpha)
                    surf.blit(stamp, (int(s["x"] - stamp.get_width() // 2), int(s["y"] - stamp.get_height() // 2)))

        # 4. Atmospheric shooting stars: glowing meteor head and fading ionization trail
        # Draw ionization trails
        for tr in self.trails:
            age_frac = tr["age"] / tr["life"]
            if age_frac >= 1.0:
                continue
            alpha = max(0, min(255, int(255 * (1.0 - age_frac)**1.6)))

            # Ionization spectrum: starts intense white-emerald -> cyan -> warm amber/dust
            if age_frac < 0.22:
                t_col = age_frac / 0.22
                r = int(225 * (1 - t_col) + 130 * t_col)
                g = int(255 * (1 - t_col) + 235 * t_col)
                b = int(240 * (1 - t_col) + 210 * t_col)
            elif age_frac < 0.55:
                t_col = (age_frac - 0.22) / 0.33
                r = int(130 * (1 - t_col) + 240 * t_col)
                g = int(235 * (1 - t_col) + 165 * t_col)
                b = int(210 * (1 - t_col) + 85 * t_col)
            else:
                t_col = (age_frac - 0.55) / 0.45
                r = int(240 * (1 - t_col) + 150 * t_col)
                g = int(165 * (1 - t_col) + 75 * t_col)
                b = int(85 * (1 - t_col) + 65 * t_col)

            width = max(1, int(2.4 * (1.0 + age_frac * 1.2)))
            col_scaled = (int(r * alpha / 255), int(g * alpha / 255), int(b * alpha / 255))
            pygame.draw.line(surf, col_scaled, (tr["x1"], tr["y1"]), (tr["x2"], tr["y2"]), width)

        # Draw active meteor heads
        for shot in self.shots:
            x, y = int(shot["x"]), int(shot["y"])
            # Glowing plasma halo
            pygame.draw.circle(surf, (140, 225, 255), (x, y), 5)
            pygame.draw.circle(surf, (200, 245, 255), (x, y), 3)
            pygame.draw.circle(surf, (255, 255, 255), (x, y), 1)
