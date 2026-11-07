"""Raytraced 3D luxury marbles with studio lighting and physics."""

from __future__ import annotations

import math
import random
import numpy as np
import pygame

from adfresh.modules.base import Module

# Presets representing distinct luxury materials:
# - Chrome mirror ball with studio softbox reflections
# - Deep gemstone marbles (ruby, emerald, sapphire, amethyst)
# - Cat's-Eye glass marbles with internal spiraling ribbons
# - Polished swirl marbles (classic agate swirled glass)
BALL_PRESETS = [
    ("chrome", "chrome", (220, 225, 235)),
    ("gemstone", "ruby", (195, 18, 48)),
    ("catseye", "fire", (255, 140, 20)),
    ("swirl", "cobalt", (24, 58, 195)),
    ("gemstone", "emerald", (14, 165, 85)),
    ("gemstone", "sapphire", (25, 75, 220)),
    ("swirl", "carnelian", (205, 45, 30)),
    ("catseye", "lime", (155, 250, 35)),
    ("gemstone", "amethyst", (142, 38, 205)),
    ("swirl", "jade", (18, 145, 85)),
    ("catseye", "ice", (45, 205, 255)),
]

NUM_ROTATION_FRAMES = 24
_SURF_CACHE: dict[tuple, pygame.Surface | list[pygame.Surface]] = {}
_SHADOW_CACHE: dict[int, pygame.Surface] = {}
_UNIT_CONTACT_SHADOW: pygame.Surface | None = None


def _get_unit_contact_shadow() -> pygame.Surface:
    """Pre-rendered soft elliptical contact shadow template for fast scaling."""
    global _UNIT_CONTACT_SHADOW
    if _UNIT_CONTACT_SHADOW is not None:
        return _UNIT_CONTACT_SHADOW
    s = 64
    y, x = np.ogrid[:s, :s]
    cx = cy = (s - 1) / 2.0
    r = (s - 1) / 2.0
    dist = np.hypot(x - cx, y - cy) / r
    falloff = np.clip(1.0 - dist, 0.0, 1.0) ** 1.5
    rgba = np.zeros((s, s, 4), dtype=np.uint8)
    rgba[:, :, 3] = (falloff * 255.0).astype(np.uint8)
    _UNIT_CONTACT_SHADOW = pygame.image.frombuffer(rgba.tobytes(), (s, s), "RGBA")
    return _UNIT_CONTACT_SHADOW


def _get_backplane_shadow(radius: int) -> pygame.Surface:
    """Soft ambient drop shadow cast on the backplane behind the marble."""
    r_key = max(4, int(radius))
    hit = _SHADOW_CACHE.get(r_key)
    if hit is not None:
        return hit
    sr = int(r_key * 1.15)
    size = sr * 2
    y, x = np.ogrid[:size, :size]
    cx = cy = (size - 1) / 2.0
    dist = np.hypot(x - cx, y - cy) / sr
    falloff = np.clip(1.0 - dist, 0.0, 1.0) ** 1.8
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[:, :, 3] = (falloff * 75.0).astype(np.uint8)
    surf = pygame.image.frombuffer(rgba.tobytes(), (size, size), "RGBA")
    _SHADOW_CACHE[r_key] = surf
    return surf


def _sphere_geometry(diameter: int):
    """Compute 3D spherical coordinate grid, normal vectors, and subpixel anti-aliased alpha."""
    n = max(8, int(diameter))
    x = np.linspace(-1.0, 1.0, n, dtype=np.float32)
    u, v = np.meshgrid(x, x)
    r2 = u**2 + v**2
    mask = r2 <= 1.0

    w = np.zeros_like(r2)
    w[mask] = np.sqrt(np.maximum(0.0, 1.0 - r2[mask]))

    # Subpixel anti-aliased edge alpha
    dist = 1.0 - np.sqrt(np.maximum(0.0, r2))
    edge_width = 1.4 / (n / 2.0)
    alpha = np.clip(dist / edge_width, 0.0, 1.0)

    return n, u, v, w, r2, mask, alpha


def _make_specular(u: np.ndarray, v: np.ndarray, w: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Multi-source studio specular highlights: Key softbox, secondary fill, and rim glint."""
    # Key light: upper-left-front
    l1 = np.array([-0.45, -0.60, 0.65], dtype=np.float32)
    l1 = l1 / np.linalg.norm(l1)

    # Fill light: right-front
    l2 = np.array([0.60, -0.25, 0.75], dtype=np.float32)
    l2 = l2 / np.linalg.norm(l2)

    view = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    h1 = (l1 + view) / np.linalg.norm(l1 + view)
    h2 = (l2 + view) / np.linalg.norm(l2 + view)

    n_dot_h1 = np.maximum(0.0, u * h1[0] + v * h1[1] + w * h1[2])
    n_dot_h2 = np.maximum(0.0, u * h2[0] + v * h2[1] + w * h2[2])

    spec1 = (n_dot_h1 ** 16) * 0.45 + (n_dot_h1 ** 48) * 0.95
    spec2 = (n_dot_h2 ** 36) * 0.65
    rim = ((1.0 - w) ** 3.5) * 0.45 * mask

    return np.clip(spec1 + spec2 + rim, 0.0, 1.0)


def _render_chrome(diameter: int) -> pygame.Surface:
    """Polished chrome mirror ball with environment reflections and crisp highlights."""
    n, u, v, w, r2, mask, alpha = _sphere_geometry(diameter)

    rx = 2.0 * w * u
    ry = 2.0 * w * v

    env_r = np.zeros_like(u)
    env_g = np.zeros_like(u)
    env_b = np.zeros_like(u)

    floor_mask = (ry >= 0.0) & mask
    ceil_mask = (ry < 0.0) & mask

    # Studio ceiling gradient
    env_r[ceil_mask] = 110.0 + (1.0 + ry[ceil_mask]) * 55.0
    env_g[ceil_mask] = 120.0 + (1.0 + ry[ceil_mask]) * 60.0
    env_b[ceil_mask] = 140.0 + (1.0 + ry[ceil_mask]) * 70.0

    # Horizon gleam
    horizon_band = np.exp(-((ry / 0.12) ** 2)) * 120.0
    env_r[mask] += horizon_band[mask] * 0.90
    env_g[mask] += horizon_band[mask] * 0.95
    env_b[mask] += horizon_band[mask] * 1.05

    # Studio floor gradient
    env_r[floor_mask] = 60.0 + (1.0 - ry[floor_mask]) * 50.0
    env_g[floor_mask] = 65.0 + (1.0 - ry[floor_mask]) * 55.0
    env_b[floor_mask] = 75.0 + (1.0 - ry[floor_mask]) * 60.0

    # Softbox 1: Key panel
    sb1_dx = np.maximum(0.0, np.abs(rx - (-0.35)) - 0.22)
    sb1_dy = np.maximum(0.0, np.abs(ry - (-0.42)) - 0.16)
    sb1_dist = (sb1_dx / 0.12)**2 + (sb1_dy / 0.12)**2
    sb1_light = np.exp(-sb1_dist * 1.6) * 255.0

    # Softbox 2: Fill panel
    sb2_dx = np.maximum(0.0, np.abs(rx - 0.42) - 0.14)
    sb2_dy = np.maximum(0.0, np.abs(ry - (-0.30)) - 0.14)
    sb2_dist = (sb2_dx / 0.10)**2 + (sb2_dy / 0.10)**2
    sb2_light = np.exp(-sb2_dist * 2.0) * 220.0

    # Side accent kicker
    sb3_dist = ((rx - (-0.65)) / 0.15)**2 + ((ry - 0.15) / 0.15)**2
    sb3_light = np.exp(-sb3_dist * 2.5) * 110.0

    env_r[mask] += sb1_light[mask] * 0.96 + sb2_light[mask] * 0.92 + sb3_light[mask] * 0.95
    env_g[mask] += sb1_light[mask] * 0.98 + sb2_light[mask] * 0.96 + sb3_light[mask] * 0.90
    env_b[mask] += sb1_light[mask] * 1.00 + sb2_light[mask] * 1.00 + sb3_light[mask] * 0.85

    # Fresnel metallic brightening & grazing ring
    fresnel = 0.82 + 0.18 * ((1.0 - w) ** 4)
    dark_ring = np.exp(-(((r2 - 0.92) / 0.07) ** 2)) * 0.35
    chrome_mult = np.clip(fresnel * (1.0 - dark_ring), 0.0, 1.25)
    edge_sheen = ((1.0 - w) ** 5) * 220.0

    final_r = np.clip(env_r * chrome_mult + edge_sheen, 0.0, 255.0)
    final_g = np.clip(env_g * chrome_mult + edge_sheen, 0.0, 255.0)
    final_b = np.clip(env_b * chrome_mult + edge_sheen, 0.0, 255.0)

    rgba = np.zeros((n, n, 4), dtype=np.uint8)
    rgba[:, :, 0] = final_r.astype(np.uint8)
    rgba[:, :, 1] = final_g.astype(np.uint8)
    rgba[:, :, 2] = final_b.astype(np.uint8)
    rgba[:, :, 3] = (alpha * 255.0).astype(np.uint8)

    return pygame.image.frombuffer(rgba.tobytes(), (n, n), "RGBA")


def _render_gemstone(diameter: int, gem_type: str) -> pygame.Surface:
    """Deep gemstone marbles (ruby, emerald, sapphire, amethyst) with rich Fresnel rim and subsurface depth."""
    gems = {
        "ruby": {
            "base": (195.0, 18.0, 48.0),
            "deep": (48.0, 3.0, 12.0),
            "caustic": (255.0, 70.0, 95.0),
            "rim": (255.0, 140.0, 160.0),
        },
        "emerald": {
            "base": (14.0, 165.0, 85.0),
            "deep": (3.0, 38.0, 18.0),
            "caustic": (45.0, 255.0, 145.0),
            "rim": (140.0, 255.0, 195.0),
        },
        "sapphire": {
            "base": (25.0, 75.0, 220.0),
            "deep": (4.0, 14.0, 56.0),
            "caustic": (65.0, 185.0, 255.0),
            "rim": (150.0, 210.0, 255.0),
        },
        "amethyst": {
            "base": (142.0, 38.0, 205.0),
            "deep": (28.0, 6.0, 45.0),
            "caustic": (235.0, 110.0, 255.0),
            "rim": (235.0, 165.0, 255.0),
        },
    }
    cfg = gems.get(gem_type, gems["ruby"])
    n, u, v, w, r2, mask, alpha = _sphere_geometry(diameter)

    depth = w
    l1 = np.array([-0.45, -0.60, 0.65], dtype=np.float32)
    l1 = l1 / np.linalg.norm(l1)
    diffuse = np.maximum(0.0, u * l1[0] + v * l1[1] + w * l1[2])
    lit = 0.22 + 0.78 * diffuse

    r = np.zeros_like(u)
    g = np.zeros_like(u)
    b = np.zeros_like(u)

    for c_idx, (b_c, d_c) in enumerate(zip(cfg["base"], cfg["deep"])):
        col = d_c + (b_c - d_c) * (lit * 0.65 + depth * 0.35)
        if c_idx == 0:
            r[mask] = col[mask]
        elif c_idx == 1:
            g[mask] = col[mask]
        else:
            b[mask] = col[mask]

    # Subsurface refractive caustic depth glow
    caustic_dist = (u - 0.36)**2 + (v - 0.42)**2
    caustic_glow = np.clip(np.exp(-caustic_dist * 3.8) * (depth ** 0.5) * 1.55, 0.0, 1.8)

    r[mask] += cfg["caustic"][0] * caustic_glow[mask]
    g[mask] += cfg["caustic"][1] * caustic_glow[mask]
    b[mask] += cfg["caustic"][2] * caustic_glow[mask]

    # Rich Fresnel rim glow
    fresnel = ((1.0 - w) ** 2.6) * 0.90
    r[mask] += cfg["rim"][0] * fresnel[mask]
    g[mask] += cfg["rim"][1] * fresnel[mask]
    b[mask] += cfg["rim"][2] * fresnel[mask]

    # Studio specular highlights
    spec = _make_specular(u, v, w, mask)
    r[mask] = np.clip(r[mask] * (1.0 - spec[mask] * 0.35) + 255.0 * spec[mask], 0.0, 255.0)
    g[mask] = np.clip(g[mask] * (1.0 - spec[mask] * 0.35) + 255.0 * spec[mask], 0.0, 255.0)
    b[mask] = np.clip(b[mask] * (1.0 - spec[mask] * 0.35) + 255.0 * spec[mask], 0.0, 255.0)

    rgba = np.zeros((n, n, 4), dtype=np.uint8)
    rgba[:, :, 0] = r.astype(np.uint8)
    rgba[:, :, 1] = g.astype(np.uint8)
    rgba[:, :, 2] = b.astype(np.uint8)
    rgba[:, :, 3] = (alpha * 255.0).astype(np.uint8)

    return pygame.image.frombuffer(rgba.tobytes(), (n, n), "RGBA")


def _render_catseye_frames(diameter: int, ribbon_type: str, num_frames: int = NUM_ROTATION_FRAMES) -> list[pygame.Surface]:
    """Cat's-Eye glass marbles with internal spiraling ribbons/cores."""
    ribbons = {
        "fire": {
            "vane1_core": (255.0, 245.0, 120.0),
            "vane1_body": (255.0, 115.0, 18.0),
            "vane2_core": (255.0, 180.0, 50.0),
            "vane2_body": (215.0, 30.0, 15.0),
        },
        "lime": {
            "vane1_core": (245.0, 255.0, 200.0),
            "vane1_body": (155.0, 250.0, 35.0),
            "vane2_core": (200.0, 255.0, 120.0),
            "vane2_body": (15.0, 185.0, 75.0),
        },
        "ice": {
            "vane1_core": (245.0, 252.0, 255.0),
            "vane1_body": (45.0, 205.0, 255.0),
            "vane2_core": (180.0, 235.0, 255.0),
            "vane2_body": (20.0, 85.0, 225.0),
        },
    }
    cfg = ribbons.get(ribbon_type, ribbons["fire"])
    n, u, v, w, r2, mask, alpha = _sphere_geometry(diameter)

    bg_r = 16.0 * (1.0 - w * 0.25)
    bg_g = 20.0 * (1.0 - w * 0.25)
    bg_b = 32.0 * (1.0 - w * 0.20)

    # Refractive lensing inside glass sphere
    refract = 1.0 / (1.0 + 0.22 * (1.0 - w))
    ur = u * refract
    vr = v * refract

    # Fixed studio specular & Fresnel rim (anchored in world space)
    spec = _make_specular(u, v, w, mask)
    fresnel = ((1.0 - w) ** 3.0) * 0.80

    frames: list[pygame.Surface] = []
    angles = np.linspace(0.0, 2.0 * np.pi, num_frames, endpoint=False)

    for ang in angles:
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)
        urot = ur * cos_a - vr * sin_a
        vrot = ur * sin_a + vr * cos_a

        # Dual twisting helical ribbons
        spine1_x = 0.36 * np.sin(2.6 * vrot + 0.3)
        dist1 = np.abs(urot - spine1_x)
        core1 = np.exp(-((dist1 / 0.06) ** 2)) * (w ** 0.8)
        body1 = np.exp(-((dist1 / 0.16) ** 2)) * (w ** 0.5)

        spine2_x = -0.32 * np.sin(2.4 * vrot - 1.2)
        dist2 = np.abs(urot - spine2_x)
        core2 = np.exp(-((dist2 / 0.05) ** 2)) * (w ** 0.8)
        body2 = np.exp(-((dist2 / 0.14) ** 2)) * (w ** 0.5)

        r = np.full_like(u, bg_r)
        g = np.full_like(u, bg_g)
        b = np.full_like(u, bg_b)

        r[mask] += cfg["vane1_body"][0] * body1[mask] + cfg["vane1_core"][0] * core1[mask]
        g[mask] += cfg["vane1_body"][1] * body1[mask] + cfg["vane1_core"][1] * core1[mask]
        b[mask] += cfg["vane1_body"][2] * body1[mask] + cfg["vane1_core"][2] * core1[mask]

        r[mask] += cfg["vane2_body"][0] * body2[mask] * 0.75 + cfg["vane2_core"][0] * core2[mask] * 0.8
        g[mask] += cfg["vane2_body"][1] * body2[mask] * 0.75 + cfg["vane2_core"][1] * core2[mask] * 0.8
        b[mask] += cfg["vane2_body"][2] * body2[mask] * 0.75 + cfg["vane2_core"][2] * core2[mask] * 0.8

        r[mask] += 190.0 * fresnel[mask]
        g[mask] += 220.0 * fresnel[mask]
        b[mask] += 250.0 * fresnel[mask]

        r[mask] = np.clip(r[mask] * (1.0 - spec[mask] * 0.25) + 255.0 * spec[mask], 0.0, 255.0)
        g[mask] = np.clip(g[mask] * (1.0 - spec[mask] * 0.25) + 255.0 * spec[mask], 0.0, 255.0)
        b[mask] = np.clip(b[mask] * (1.0 - spec[mask] * 0.25) + 255.0 * spec[mask], 0.0, 255.0)

        rgba = np.zeros((n, n, 4), dtype=np.uint8)
        rgba[:, :, 0] = r.astype(np.uint8)
        rgba[:, :, 1] = g.astype(np.uint8)
        rgba[:, :, 2] = b.astype(np.uint8)
        rgba[:, :, 3] = (alpha * 255.0).astype(np.uint8)

        frames.append(pygame.image.frombuffer(rgba.tobytes(), (n, n), "RGBA"))

    return frames


def _render_swirl_frames(diameter: int, style: str, num_frames: int = NUM_ROTATION_FRAMES) -> list[pygame.Surface]:
    """Polished swirl marble (classic agate swirled glass) with dynamic 3D rotating pattern."""
    styles = {
        "cobalt": {
            "base": (24.0, 58.0, 195.0),
            "dark": (6.0, 16.0, 68.0),
            "swirl1": (252.0, 250.0, 242.0),
            "swirl2": (235.0, 170.0, 48.0),
        },
        "carnelian": {
            "base": (205.0, 45.0, 30.0),
            "dark": (58.0, 8.0, 6.0),
            "swirl1": (255.0, 248.0, 235.0),
            "swirl2": (248.0, 160.0, 38.0),
        },
        "jade": {
            "base": (18.0, 145.0, 85.0),
            "dark": (4.0, 38.0, 18.0),
            "swirl1": (246.0, 254.0, 250.0),
            "swirl2": (80.0, 225.0, 170.0),
        },
    }
    cfg = styles.get(style, styles["cobalt"])
    n, u, v, w, r2, mask, alpha = _sphere_geometry(diameter)

    # 3D Lambertian shading
    l1 = np.array([-0.45, -0.60, 0.65], dtype=np.float32)
    l1 = l1 / np.linalg.norm(l1)
    diffuse = np.maximum(0.0, u * l1[0] + v * l1[1] + w * l1[2])
    lit = 0.26 + 0.74 * diffuse

    # Fixed specular & clearcoat rim
    spec = _make_specular(u, v, w, mask)
    fresnel = ((1.0 - w) ** 3.2) * 0.65

    frames: list[pygame.Surface] = []
    angles = np.linspace(0.0, 2.0 * np.pi, num_frames, endpoint=False)

    for ang in angles:
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)
        urot = u * cos_a - v * sin_a
        vrot = u * sin_a + v * cos_a

        # 3D spherical agate swirl bands
        s = vrot + 0.38 * np.sin(3.0 * urot + 2.2 * w) + 0.22 * np.sin(4.2 * vrot - 2.5 * urot)
        band_val = np.sin(6.2 * s)

        t1 = np.clip((band_val - 0.15) / 0.30, 0.0, 1.0)
        t2 = np.clip((band_val - 0.70) / 0.20, 0.0, 1.0)

        r = np.zeros_like(u)
        g = np.zeros_like(u)
        b = np.zeros_like(u)

        for c_idx in range(3):
            base_c = cfg["dark"][c_idx] + (cfg["base"][c_idx] - cfg["dark"][c_idx]) * lit
            sw1_c = cfg["swirl1"][c_idx] * (0.42 + 0.58 * lit)
            sw2_c = cfg["swirl2"][c_idx] * (0.35 + 0.65 * lit)

            col = base_c * (1.0 - t1) + sw1_c * (t1 - t2) + sw2_c * t2
            if c_idx == 0:
                r[mask] = col[mask]
            elif c_idx == 1:
                g[mask] = col[mask]
            else:
                b[mask] = col[mask]

        r[mask] += 235.0 * fresnel[mask]
        g[mask] += 245.0 * fresnel[mask]
        b[mask] += 255.0 * fresnel[mask]

        r[mask] = np.clip(r[mask] * (1.0 - spec[mask] * 0.30) + 255.0 * spec[mask], 0.0, 255.0)
        g[mask] = np.clip(g[mask] * (1.0 - spec[mask] * 0.30) + 255.0 * spec[mask], 0.0, 255.0)
        b[mask] = np.clip(b[mask] * (1.0 - spec[mask] * 0.30) + 255.0 * spec[mask], 0.0, 255.0)

        rgba = np.zeros((n, n, 4), dtype=np.uint8)
        rgba[:, :, 0] = r.astype(np.uint8)
        rgba[:, :, 1] = g.astype(np.uint8)
        rgba[:, :, 2] = b.astype(np.uint8)
        rgba[:, :, 3] = (alpha * 255.0).astype(np.uint8)

        frames.append(pygame.image.frombuffer(rgba.tobytes(), (n, n), "RGBA"))

    return frames


def get_marble_surface(material: str, subtype: str, diameter: int) -> pygame.Surface | list[pygame.Surface]:
    """Retrieve cached raytraced 3D marble surface or animation frame list."""
    diameter = max(12, int(diameter))
    key = (material, subtype, diameter)
    hit = _SURF_CACHE.get(key)
    if hit is not None:
        return hit

    if material == "chrome":
        surf = _render_chrome(diameter)
    elif material == "gemstone":
        surf = _render_gemstone(diameter, subtype)
    elif material == "catseye":
        surf = _render_catseye_frames(diameter, subtype)
    elif material == "swirl":
        surf = _render_swirl_frames(diameter, subtype)
    else:
        surf = _render_chrome(diameter)

    _SURF_CACHE[key] = surf
    return surf


class Marbles(Module):
    id = "marbles"
    title = "Marbles"

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        self.balls: list[dict] = []
        n = max(7, min(14, int(w * h / 160000)))
        for i in range(n):
            radius = self.rng.uniform(min(w, h) * 0.035, min(w, h) * 0.075)
            preset = BALL_PRESETS[i % len(BALL_PRESETS)]
            self.balls.append(self._spawn(radius, preset))
        self._separate()

    def _spawn(self, radius: float, preset: tuple) -> dict:
        speed = self.rng.uniform(80, 180)
        angle = self.rng.uniform(0, math.tau)
        spin_vel = self.rng.uniform(-3.5, 3.5)
        d = max(12, int(round(radius * 2)))
        material, subtype, rep_color = preset
        sprite_or_frames = get_marble_surface(material, subtype, d)

        return {
            "x": self.rng.uniform(radius, self.w - radius),
            "y": self.rng.uniform(radius, self.h - radius),
            "vx": math.cos(angle) * speed,
            "vy": math.sin(angle) * speed,
            "r": radius,
            "m": radius * radius,
            "color": rep_color,
            "material": material,
            "subtype": subtype,
            "diameter": d,
            "sprites": sprite_or_frames,
            "angle": self.rng.uniform(0.0, math.tau),
            "spin": spin_vel,
        }

    def _separate(self) -> None:
        for _ in range(16):
            for i, a in enumerate(self.balls):
                for b in self.balls[i + 1 :]:
                    dx = b["x"] - a["x"]
                    dy = b["y"] - a["y"]
                    dist = math.hypot(dx, dy) or 0.001
                    need = a["r"] + b["r"]
                    if dist < need:
                        push = (need - dist) / 2
                        nx, ny = dx / dist, dy / dist
                        a["x"] -= nx * push
                        a["y"] -= ny * push
                        b["x"] += nx * push
                        b["y"] += ny * push

        # Keep strictly inside bounds
        for ball in self.balls:
            r = ball["r"]
            ball["x"] = max(r, min(self.w - r, ball["x"]))
            ball["y"] = max(r, min(self.h - r, ball["y"]))

    def step(self, dt: float) -> None:
        restitution = 0.99

        # 1. Update ball positions & rolling rotation
        for ball in self.balls:
            ball["x"] += ball["vx"] * dt
            ball["y"] += ball["vy"] * dt
            ball["angle"] = (ball["angle"] + ball["spin"] * dt) % math.tau

            # 2. Wall bounces with elastic restitution & spin transfer
            r = ball["r"]
            if ball["x"] < r:
                ball["x"] = r
                ball["vx"] = abs(ball["vx"]) * restitution
                ball["spin"] += (-ball["vy"] / r) * 0.15
            elif ball["x"] > self.w - r:
                ball["x"] = self.w - r
                ball["vx"] = -abs(ball["vx"]) * restitution
                ball["spin"] += (ball["vy"] / r) * 0.15

            if ball["y"] < r:
                ball["y"] = r
                ball["vy"] = abs(ball["vy"]) * restitution
                ball["spin"] += (ball["vx"] / r) * 0.15
            elif ball["y"] > self.h - r:
                ball["y"] = self.h - r
                ball["vy"] = -abs(ball["vy"]) * restitution
                ball["spin"] += (-ball["vx"] / r) * 0.15

        # 3. Ball-to-ball realistic elastic collisions with mass
        balls = self.balls
        for i, a in enumerate(balls):
            for b in balls[i + 1 :]:
                dx = b["x"] - a["x"]
                dy = b["y"] - a["y"]
                dist = math.hypot(dx, dy)
                need = a["r"] + b["r"]
                if dist >= need or dist <= 1e-6:
                    continue

                nx, ny = dx / dist, dy / dist
                overlap = need - dist
                ma, mb = a["m"], b["m"]
                total_m = ma + mb

                # Positional separation weighted by inverse mass
                a["x"] -= nx * overlap * (mb / total_m)
                a["y"] -= ny * overlap * (mb / total_m)
                b["x"] += nx * overlap * (ma / total_m)
                b["y"] += ny * overlap * (ma / total_m)

                # Relative velocity along collision normal
                rvx = b["vx"] - a["vx"]
                rvy = b["vy"] - a["vy"]
                vn = rvx * nx + rvy * ny

                if vn < 0:
                    # Elastic collision impulse
                    j = -(1.0 + restitution) * vn / (1.0 / ma + 1.0 / mb)
                    a["vx"] -= (j / ma) * nx
                    a["vy"] -= (j / ma) * ny
                    b["vx"] += (j / mb) * nx
                    b["vy"] += (j / mb) * ny

                    # Tangential spin exchange from surface friction
                    tx, ty = -ny, nx
                    vt = rvx * tx + rvy * ty + a["spin"] * a["r"] + b["spin"] * b["r"]
                    spin_impulse = np.clip(vt / (a["r"] + b["r"]) * 0.20, -4.0, 4.0)
                    a["spin"] -= spin_impulse
                    b["spin"] += spin_impulse

        # 4. Momentum preservation & angular drag
        for ball in self.balls:
            ball["spin"] *= math.exp(-0.08 * dt)
            spd = math.hypot(ball["vx"], ball["vy"])
            if spd < 65.0:
                scale = 75.0 / max(1.0, spd)
                ball["vx"] *= scale
                ball["vy"] *= scale
            elif spd > 260.0:
                scale = 250.0 / spd
                ball["vx"] *= scale
                ball["vy"] *= scale

        # 5. STRICT clamp to guarantee contained() is always True
        for ball in self.balls:
            r = ball["r"]
            if ball["x"] < r:
                ball["x"] = r
                if ball["vx"] < 0:
                    ball["vx"] = -ball["vx"]
            elif ball["x"] > self.w - r:
                ball["x"] = self.w - r
                if ball["vx"] > 0:
                    ball["vx"] = -ball["vx"]
            if ball["y"] < r:
                ball["y"] = r
                if ball["vy"] < 0:
                    ball["vy"] = -ball["vy"]
            elif ball["y"] > self.h - r:
                ball["y"] = self.h - r
                if ball["vy"] > 0:
                    ball["vy"] = -ball["vy"]

    def draw(self, surf: pygame.Surface) -> None:
        # Rich 64-bit style luxury studio environment
        w, h = self.w, self.h
        floor_start = int(h * 0.72)

        # Upper back wall: deep obsidian gradient
        # Studio floor: dark slate reflection plane
        for y in range(0, h, 2):
            if y < floor_start:
                t = y / floor_start
                r = int(10 + 6 * t)
                g = int(12 + 8 * t)
                b = int(18 + 12 * t)
            else:
                t = (y - floor_start) / max(1, h - floor_start)
                r = int(22 - 6 * t)
                g = int(26 - 7 * t)
                b = int(36 - 10 * t)
            surf.fill((r, g, b), (0, y, w, 2))

        # Soft horizon line
        horizon_y = floor_start
        pygame.draw.line(surf, (32, 40, 56), (0, horizon_y), (w, horizon_y), 1)

        # 1. Backplane ambient drop shadows
        for ball in self.balls:
            r = ball["r"]
            shadow = _get_backplane_shadow(int(r))
            sx = int(ball["x"] + r * 0.20 - shadow.get_width() / 2)
            sy = int(ball["y"] + r * 0.25 - shadow.get_height() / 2)
            surf.blit(shadow, (sx, sy))

        # 2. Dynamic soft contact drop shadows underneath marbles near the box edges/floor
        unit_shadow = _get_unit_contact_shadow()
        floor_y = h
        for ball in self.balls:
            r = ball["r"]
            x = ball["x"]
            y = ball["y"]

            # Floor contact shadow
            dist_to_floor = floor_y - (y + r)
            if dist_to_floor < 2.5 * r:
                proximity = max(0.0, 1.0 - dist_to_floor / (2.5 * r))
                sw = max(4, int(r * (1.15 - 0.20 * (1.0 - proximity))))
                sh = max(2, int(r * (0.32 * (1.0 - proximity * 0.4))))
                alpha = int(240.0 * (proximity ** 1.4))

                if sw > 2 and sh > 1 and alpha > 0:
                    scaled = pygame.transform.scale(unit_shadow, (sw * 2, sh * 2))
                    if alpha < 255:
                        scaled.set_alpha(alpha)
                    surf.blit(scaled, (int(x - sw), int(floor_y - sh * 1.5)))

            # Left wall contact shadow
            dist_left = x - r
            if dist_left < 2.0 * r:
                proximity = max(0.0, 1.0 - dist_left / (2.0 * r))
                sh = max(4, int(r * (1.15 - 0.20 * (1.0 - proximity))))
                sw = max(2, int(r * (0.30 * (1.0 - proximity * 0.4))))
                alpha = int(200.0 * (proximity ** 1.5))
                if sw > 1 and sh > 2 and alpha > 0:
                    scaled = pygame.transform.scale(unit_shadow, (sw * 2, sh * 2))
                    scaled.set_alpha(alpha)
                    surf.blit(scaled, (0, int(y - sh)))

            # Right wall contact shadow
            dist_right = w - (x + r)
            if dist_right < 2.0 * r:
                proximity = max(0.0, 1.0 - dist_right / (2.0 * r))
                sh = max(4, int(r * (1.15 - 0.20 * (1.0 - proximity))))
                sw = max(2, int(r * (0.30 * (1.0 - proximity * 0.4))))
                alpha = int(200.0 * (proximity ** 1.5))
                if sw > 1 and sh > 2 and alpha > 0:
                    scaled = pygame.transform.scale(unit_shadow, (sw * 2, sh * 2))
                    scaled.set_alpha(alpha)
                    surf.blit(scaled, (w - sw * 2, int(y - sh)))

        # 3. Draw raytraced marbles with smooth anti-aliased discs and spin/rotation
        for ball in self.balls:
            sprites = ball["sprites"]
            if isinstance(sprites, list):
                # Rotating marble (cat's-eye ribbon or swirl bands)
                frame_idx = int((ball["angle"] / math.tau) * len(sprites)) % len(sprites)
                sprite = sprites[frame_idx]
            else:
                sprite = sprites

            x = int(ball["x"] - sprite.get_width() / 2)
            y = int(ball["y"] - sprite.get_height() / 2)
            surf.blit(sprite, (x, y))

    def contained(self) -> bool:
        for ball in self.balls:
            r = ball["r"] - 0.5
            if not (r <= ball["x"] <= self.w - r and r <= ball["y"] <= self.h - r):
                return False
        return True
