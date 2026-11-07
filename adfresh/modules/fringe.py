"""Deep space arcade combat shooter faithful to After Dark's legendary Lunatic Fringe (1991).

Features:
- Multi-layer parallax starfield with celestial nebulae and twinkling stars.
- Sleek vector wedge starfighter with dual engine exhausts, particle wake, and deflector shields.
- Autonomous AI pilot (Screensaver Attract Mode) with predictive deflection shooting and missile dodging.
- Alien Armada: Fast Darting Scouts, Armored Cruisers with rotating deflector shields, and Pulsing Space Mines.
- Combat FX: Twin laser tracer trails, alien plasma fire, multi-stage particle explosions, and shockwave rings.
- Classic Lunatic Fringe Tactical CRT Radar HUD with rotating sweep beam, range rings, and target blips.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame

from adfresh.drawutil import font, mix, radial, rrect
from adfresh.modules.base import Module

# World Arena Dimensions (Toroidal space)
WORLD_W = 3800.0
WORLD_H = 2600.0
RADAR_RANGE = 1600.0

# Spectral star color temperatures
STAR_PALETTE = (
    (210, 230, 255),  # O/B: Sapphire blue-white
    (245, 250, 255),  # A: Crisp white
    (255, 245, 215),  # G: Solar amber-yellow
    (255, 210, 160),  # K: Warm orange
    (195, 210, 255),  # B: Cool cyan-blue
)


def wrap_coord(val: float, max_val: float) -> float:
    return val % max_val


def rel_coord(target: float, origin: float, max_val: float) -> float:
    """Toroidal shortest-distance offset from origin to target in [-max_val/2, max_val/2]."""
    return (target - origin + max_val * 0.5) % max_val - max_val * 0.5


def rotate_point(x: float, y: float, cos_a: float, sin_a: float) -> tuple[float, float]:
    return (cos_a * x - sin_a * y, sin_a * x + cos_a * y)


@dataclass
class Star:
    x: float
    y: float
    layer: int
    color: tuple[int, int, int]
    size: int
    twinkle_speed: float
    twinkle_phase: float


@dataclass
class Laser:
    x: float
    y: float
    vx: float
    vy: float
    angle: float
    is_player: bool
    kind: str  # "player_twin", "scout_laser", "cruiser_plasma"
    damage: float
    life: float
    max_life: float
    radius: float
    color: tuple[int, int, int]
    core_color: tuple[int, int, int]


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    color_start: tuple[int, int, int]
    color_end: tuple[int, int, int]
    kind: str  # "spark", "flame", "smoke", "debris"
    angle: float = 0.0
    rot_speed: float = 0.0


@dataclass
class Shockwave:
    x: float
    y: float
    radius: float
    max_radius: float
    speed: float
    color: tuple[int, int, int]
    width: int = 2


class Enemy:
    def __init__(self, kind: str, x: float, y: float, rng: random.Random):
        self.kind = kind
        self.x = x
        self.y = y
        self.vx = rng.uniform(-30, 30)
        self.vy = rng.uniform(-30, 30)
        self.angle = rng.uniform(0, math.tau)
        self.fire_timer = rng.uniform(0.5, 2.0)
        self.behavior_timer = rng.uniform(0.0, 3.0)
        self.alive = True
        self.shield_flash = 0.0
        self.rot_speed = rng.uniform(-0.8, 0.8)

        if kind == "scout":
            self.radius = 14.0
            self.hull = 30.0
            self.max_hull = 30.0
            self.shields = 0.0
            self.max_shields = 0.0
            self.color = (60, 255, 130)
            self.accent = (160, 255, 200)
            self.score = 150
            self.state = "intercept"
        elif kind == "cruiser":
            self.radius = 24.0
            self.hull = 80.0
            self.max_hull = 80.0
            self.shields = 50.0
            self.max_shields = 50.0
            self.color = (255, 55, 100)
            self.accent = (255, 160, 200)
            self.shield_rot = 0.0
            self.score = 400
            self.state = "patrol"
        elif kind == "mine":
            self.radius = 16.0
            self.hull = 25.0
            self.max_hull = 25.0
            self.shields = 0.0
            self.max_shields = 0.0
            self.color = (255, 180, 40)
            self.accent = (255, 60, 40)
            self.armed = False
            self.arm_timer = 0.0
            self.score = 250
            self.state = "drift"


class PlayerShip:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.angle = -math.pi / 2  # Facing up
        self.angular_vel = 0.0
        self.shields = 100.0
        self.max_shields = 100.0
        self.hull = 100.0
        self.max_hull = 100.0
        self.alive = True
        self.respawn_timer = 0.0
        self.invulnerable_timer = 2.0
        self.fire_cooldown = 0.0
        self.shield_flash = 0.0
        self.shield_recharge_wait = 0.0
        self.thrusting = False
        self.radius = 16.0
        self.ai_target: Enemy | None = None
        self.ai_status = "PATROL"


class Fringe(Module):
    id = "fringe"
    title = "Lunatic Fringe"

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.stars: list[Star] = []
        self.nebulae: list[tuple[pygame.Surface, float, float]] = []
        self.player = PlayerShip(WORLD_W * 0.5, WORLD_H * 0.5)
        self.enemies: list[Enemy] = []
        self.lasers: list[Laser] = []
        self.particles: list[Particle] = []
        self.shockwaves: list[Shockwave] = []
        self.score = 0
        self.wave = 1
        self.sweep_angle = 0.0
        self.sector_clear_timer = 0.0
        self.status_banner = "SECTOR 01: COMBAT PATROL"
        self.status_banner_timer = 3.0

        # Radar cache
        self.radar_surf: pygame.Surface | None = None
        self.radar_radius = 72
        self.radar_diam = 160

    def resize(self, w: int, h: int) -> None:
        super().resize(w, h)
        dim = min(w, h)
        self.radar_radius = max(54, int(dim * 0.095))
        self.radar_diam = self.radar_radius * 2 + 16

        # Pre-render CRT radar display bezel and range grid
        self._build_radar_base()

        # Pre-bake celestial nebulae with deep cosmic gas colors
        self._build_nebulae()

        # Initialize multi-layer stars
        self._build_stars()

        # If no enemies are present yet, spawn Wave 1
        if not self.enemies:
            self._spawn_wave(self.wave)

    def _build_radar_base(self) -> None:
        diam = self.radar_diam
        self.radar_surf = pygame.Surface((diam, diam), pygame.SRCALPHA)
        cx = cy = diam // 2
        r = self.radar_radius

        # Dark radar monitor glass
        pygame.draw.circle(self.radar_surf, (4, 18, 10, 210), (cx, cy), r)

        # Tactical range rings
        for frac in (0.33, 0.66, 1.0):
            ring_r = int(r * frac)
            pygame.draw.circle(self.radar_surf, (20, 80, 42, 160), (cx, cy), ring_r, 1)

        # Crosshairs with graduation marks
        pygame.draw.line(self.radar_surf, (20, 80, 42, 160), (cx - r, cy), (cx + r, cy), 1)
        pygame.draw.line(self.radar_surf, (20, 80, 42, 160), (cx, cy - r), (cx, cy + r), 1)

        for d in (int(r * 0.33), int(r * 0.66)):
            pygame.draw.line(self.radar_surf, (30, 110, 60, 200), (cx + d, cy - 3), (cx + d, cy + 3), 1)
            pygame.draw.line(self.radar_surf, (30, 110, 60, 200), (cx - d, cy - 3), (cx - d, cy + 3), 1)
            pygame.draw.line(self.radar_surf, (30, 110, 60, 200), (cx - 3, cy + d), (cx + 3, cy + d), 1)
            pygame.draw.line(self.radar_surf, (30, 110, 60, 200), (cx - 3, cy - d), (cx + 3, cy - d), 1)

        # Outer high-tech bezel ring
        pygame.draw.circle(self.radar_surf, (45, 75, 55, 240), (cx, cy), r + 2, 2)
        pygame.draw.circle(self.radar_surf, (25, 45, 35, 180), (cx, cy), r + 4, 1)

    def _build_nebulae(self) -> None:
        from adfresh.drawutil import additive_orb

        self.nebulae = []
        # Pre-render 5 distinct cosmic dust clouds (additive glowing RGB surfaces)
        cloud_specs = [
            (720, 520, (18, 32, 85), 0.15, 0.20),   # Sapphire indigo
            (850, 580, (38, 14, 60), 0.68, 0.30),   # Cosmic magenta / violet
            (680, 480, (12, 42, 58), 0.32, 0.72),   # Deep cyan / teal
            (780, 540, (30, 12, 48), 0.82, 0.78),   # Celestial purple
            (640, 460, (14, 25, 65), 0.50, 0.50),   # Midnight cobalt
        ]
        for w_sz, h_sz, color, rx, ry in cloud_specs:
            surf = pygame.Surface((w_sz, h_sz))
            surf.fill((0, 0, 0))
            cx, cy = w_sz // 2, h_sz // 2
            blobs = [
                (cx, cy, int(min(w_sz, h_sz) * 0.95), color),
                (cx - int(w_sz * 0.18), cy + int(h_sz * 0.12), int(min(w_sz, h_sz) * 0.70), (color[0] // 2, color[1], color[2])),
                (cx + int(w_sz * 0.20), cy - int(h_sz * 0.14), int(min(w_sz, h_sz) * 0.65), (color[0], color[1] // 2, color[2])),
                (cx + int(w_sz * 0.05), cy + int(h_sz * 0.18), int(min(w_sz, h_sz) * 0.50), (color[0] // 2, color[1] // 2, color[2])),
            ]
            for bx, by, diam, b_col in blobs:
                orb = additive_orb(diam, b_col)
                surf.blit(orb, (bx - diam // 2, by - diam // 2), special_flags=pygame.BLEND_ADD)
            self.nebulae.append((surf, rx * WORLD_W, ry * WORLD_H))

    def _build_stars(self) -> None:
        self.stars = []
        # Layer 0: Distant background (180 stars, 1px)
        for _ in range(180):
            self.stars.append(
                Star(
                    x=self.rng.uniform(0, WORLD_W),
                    y=self.rng.uniform(0, WORLD_H),
                    layer=0,
                    color=self.rng.choice(STAR_PALETTE),
                    size=1,
                    twinkle_speed=self.rng.uniform(1.2, 3.5),
                    twinkle_phase=self.rng.uniform(0, math.tau),
                )
            )
        # Layer 1: Mid distance (100 stars, 1-2px)
        for _ in range(100):
            self.stars.append(
                Star(
                    x=self.rng.uniform(0, WORLD_W),
                    y=self.rng.uniform(0, WORLD_H),
                    layer=1,
                    color=self.rng.choice(STAR_PALETTE),
                    size=2 if self.rng.random() < 0.4 else 1,
                    twinkle_speed=self.rng.uniform(2.0, 5.0),
                    twinkle_phase=self.rng.uniform(0, math.tau),
                )
            )
        # Layer 2: Nearby bright stars (40 stars, 2-3px)
        for _ in range(40):
            self.stars.append(
                Star(
                    x=self.rng.uniform(0, WORLD_W),
                    y=self.rng.uniform(0, WORLD_H),
                    layer=2,
                    color=self.rng.choice(STAR_PALETTE),
                    size=self.rng.choice((2, 3)),
                    twinkle_speed=self.rng.uniform(3.0, 6.5),
                    twinkle_phase=self.rng.uniform(0, math.tau),
                )
            )

    def _spawn_wave(self, wave: int) -> None:
        self.enemies.clear()
        num_scouts = 2 + min(wave * 2, 8)
        num_cruisers = 1 + min(wave, 4)
        num_mines = 2 + min(wave * 2, 7)

        px, py = self.player.x, self.player.y

        def spawn_point() -> tuple[float, float]:
            angle = self.rng.uniform(0, math.tau)
            dist = self.rng.uniform(600, 1300)
            return wrap_coord(px + math.cos(angle) * dist, WORLD_W), wrap_coord(py + math.sin(angle) * dist, WORLD_H)

        for _ in range(num_scouts):
            sx, sy = spawn_point()
            self.enemies.append(Enemy("scout", sx, sy, self.rng))

        for _ in range(num_cruisers):
            cx, cy = spawn_point()
            self.enemies.append(Enemy("cruiser", cx, cy, self.rng))

        for _ in range(num_mines):
            mx, my = spawn_point()
            self.enemies.append(Enemy("mine", mx, my, self.rng))

        self.status_banner = f"SECTOR {wave:02d}: INVASION ARMADA DETECTED"
        self.status_banner_timer = 3.5

    def step(self, dt: float) -> None:
        # Cap dt to prevent physics tunneling
        dt = min(dt, 0.05)

        # Radar sweep angle continuous rotation
        self.sweep_angle = (self.sweep_angle + 2.8 * dt) % math.tau

        if self.status_banner_timer > 0:
            self.status_banner_timer -= dt

        # Player Respawn & Invulnerability Management
        if not self.player.alive:
            self.player.respawn_timer -= dt
            if self.player.respawn_timer <= 0:
                self.player.alive = True
                self.player.x = WORLD_W * 0.5
                self.player.y = WORLD_H * 0.5
                self.player.vx = 0.0
                self.player.vy = 0.0
                self.player.hull = self.player.max_hull
                self.player.shields = self.player.max_shields
                self.player.invulnerable_timer = 2.5
                self._spawn_shockwave(self.player.x, self.player.y, 80.0, (0, 240, 255))
        else:
            if self.player.invulnerable_timer > 0:
                self.player.invulnerable_timer -= dt
            if self.player.shield_flash > 0:
                self.player.shield_flash -= dt
            if self.player.fire_cooldown > 0:
                self.player.fire_cooldown -= dt

            # Shield regeneration if not damaged recently
            if self.player.shield_recharge_wait > 0:
                self.player.shield_recharge_wait -= dt
            elif self.player.shields < self.player.max_shields:
                self.player.shields = min(self.player.max_shields, self.player.shields + 18.0 * dt)

            # Autonomous Attract Mode AI Pilot
            self._update_ai_pilot(dt)

            # Player inertial momentum and drag
            drag = 0.988 ** (dt * 60)
            self.player.vx *= drag
            self.player.vy *= drag
            speed = math.hypot(self.player.vx, self.player.vy)
            if speed > 440.0:
                scale = 440.0 / speed
                self.player.vx *= scale
                self.player.vy *= scale

            self.player.x = wrap_coord(self.player.x + self.player.vx * dt, WORLD_W)
            self.player.y = wrap_coord(self.player.y + self.player.vy * dt, WORLD_H)

            # Dual engine particle exhaust wake
            if self.player.thrusting:
                cos_p = math.cos(self.player.angle)
                sin_p = math.sin(self.player.angle)
                for noz in (-5.5, 5.5):
                    # Engine nozzle coordinates in world space
                    nx = self.player.x - cos_p * 15 - sin_p * noz
                    ny = self.player.y - sin_p * 15 + cos_p * noz
                    # Eject particle opposite to heading with random spray
                    spread = self.rng.uniform(-0.35, 0.35)
                    p_ang = self.player.angle + math.pi + spread
                    p_spd = self.rng.uniform(160, 280)
                    self.particles.append(
                        Particle(
                            x=wrap_coord(nx, WORLD_W),
                            y=wrap_coord(ny, WORLD_H),
                            vx=self.player.vx * 0.4 + math.cos(p_ang) * p_spd,
                            vy=self.player.vy * 0.4 + math.sin(p_ang) * p_spd,
                            life=self.rng.uniform(0.18, 0.32),
                            max_life=0.32,
                            size=self.rng.uniform(2.5, 4.0),
                            color_start=(255, 240, 160) if self.rng.random() < 0.4 else (0, 220, 255),
                            color_end=(30, 20, 60),
                            kind="flame",
                        )
                    )

        # Enemies update
        self._update_enemies(dt)

        # Lasers update & collision checks
        self._update_lasers(dt)

        # Particles & Shockwaves update
        self._update_particles(dt)

        # Sector wave advancement check
        if not self.enemies and self.sector_clear_timer <= 0:
            self.sector_clear_timer = 2.0
            self.score += self.wave * 1000
            self.status_banner = f"SECTOR {self.wave:02d} SECURED! HYPERJUMP ENGAGED"
            self.status_banner_timer = 2.5
        elif self.sector_clear_timer > 0:
            self.sector_clear_timer -= dt
            if self.sector_clear_timer <= 0:
                self.wave += 1
                self._spawn_wave(self.wave)

    def _update_ai_pilot(self, dt: float) -> None:
        """Autonomous AI combat ace: threat scanning, predictive deflection aim, dodging."""
        p = self.player
        p.thrusting = False

        if not self.enemies:
            p.ai_status = "PATROL: SECTOR ALL CLEAR"
            # Gentle cruise forward
            p.angular_vel += math.sin(self.t * 0.8) * 0.4 * dt
            p.angle += p.angular_vel * dt
            p.angular_vel *= 0.85 ** (dt * 60)
            p.vx += math.cos(p.angle) * 120 * dt
            p.vy += math.sin(p.angle) * 120 * dt
            p.thrusting = True
            return

        # 1. Target Evaluation & Selection
        best_target: Enemy | None = None
        best_threat = -999999.0

        for e in self.enemies:
            dx = rel_coord(e.x, p.x, WORLD_W)
            dy = rel_coord(e.y, p.y, WORLD_H)
            dist = math.hypot(dx, dy)

            # Dangerously close proximity mines take immediate priority
            if e.kind == "mine" and dist < 280:
                threat = 5000.0 - dist * 4
            elif e.kind == "scout":
                threat = 1800.0 - dist + (300.0 if dist < 450 else 0.0)
            elif e.kind == "cruiser":
                threat = 1400.0 - dist
            else:
                threat = 800.0 - dist

            if threat > best_threat:
                best_threat = threat
                best_target = e

        p.ai_target = best_target
        if not best_target:
            return

        tx, ty = best_target.x, best_target.y
        dx = rel_coord(tx, p.x, WORLD_W)
        dy = rel_coord(ty, p.y, WORLD_H)
        dist = math.hypot(dx, dy)

        # 2. Predictive Deflection Aim (first-order intercept)
        laser_speed = 880.0
        time_to_hit = dist / max(1.0, laser_speed)
        lead_x = dx + (best_target.vx - p.vx * 0.35) * time_to_hit
        lead_y = dy + (best_target.vy - p.vy * 0.35) * time_to_hit
        desired_angle = math.atan2(lead_y, lead_x)

        # 3. Smooth Starfighter Steering
        angle_diff = (desired_angle - p.angle + math.pi) % math.tau - math.pi
        p.angular_vel += math.copysign(min(14.0, abs(angle_diff) * 18.0), angle_diff) * dt
        p.angular_vel *= 0.82 ** (dt * 60)
        p.angle += p.angular_vel * dt

        # 4. Flight & Thrust Control
        ideal_dist = 360.0 if best_target.kind == "cruiser" else 280.0
        if abs(angle_diff) < 0.65:
            if dist > ideal_dist:
                # Thrust towards intercept range
                accel = 350.0
                p.vx += math.cos(p.angle) * accel * dt
                p.vy += math.sin(p.angle) * accel * dt
                p.thrusting = True
            elif dist < ideal_dist - 80:
                # Back-off / circle-strafe
                strafe_ang = p.angle + math.pi * 0.5
                p.vx += math.cos(strafe_ang) * 180.0 * dt
                p.vy += math.sin(strafe_ang) * 180.0 * dt

        # 5. Evasive Dodging: detect incoming hostile projectiles
        for las in self.lasers:
            if las.is_player:
                continue
            ldx = rel_coord(las.x, p.x, WORLD_W)
            ldy = rel_coord(las.y, p.y, WORLD_H)
            l_dist = math.hypot(ldx, ldy)
            if l_dist < 260.0:
                # If projectile velocity is directed toward player, perform evasive strafe
                dot = las.vx * (-ldx) + las.vy * (-ldy)
                if dot > 0:
                    perp_x = -las.vy / max(1.0, math.hypot(las.vx, las.vy))
                    perp_y = las.vx / max(1.0, math.hypot(las.vx, las.vy))
                    dodge_accel = 420.0
                    p.vx += perp_x * dodge_accel * dt
                    p.vy += perp_y * dodge_accel * dt
                    p.ai_status = "EVADING HOSTILE FIRE!"
                    break
        else:
            p.ai_status = f"ENGAGING {best_target.kind.upper()} [DIST {int(dist)}]"

        # 6. Weapon Firing Logic
        if abs(angle_diff) < 0.18 and dist < 720.0 and p.fire_cooldown <= 0:
            self._fire_player_lasers()
            p.fire_cooldown = 0.14

    def _fire_player_lasers(self) -> None:
        p = self.player
        cos_a = math.cos(p.angle)
        sin_a = math.sin(p.angle)
        laser_spd = 880.0

        for side in (-11.0, 11.0):
            # Wingtip cannon emitter coordinates
            wx = p.x + cos_a * 8 - sin_a * side
            wy = p.y + sin_a * 8 + cos_a * side
            self.lasers.append(
                Laser(
                    x=wrap_coord(wx, WORLD_W),
                    y=wrap_coord(wy, WORLD_H),
                    vx=cos_a * laser_spd + p.vx * 0.25,
                    vy=sin_a * laser_spd + p.vy * 0.25,
                    angle=p.angle,
                    is_player=True,
                    kind="player_twin",
                    damage=25.0,
                    life=0.9,
                    max_life=0.9,
                    radius=5.0,
                    color=(0, 230, 255),
                    core_color=(255, 255, 255),
                )
            )

        # Muzzle flash sparks
        for side in (-11.0, 11.0):
            wx = p.x + cos_a * 10 - sin_a * side
            wy = p.y + sin_a * 10 + cos_a * side
            for _ in range(2):
                sp_ang = p.angle + self.rng.uniform(-0.4, 0.4)
                sp_spd = self.rng.uniform(60, 140)
                self.particles.append(
                    Particle(
                        x=wrap_coord(wx, WORLD_W),
                        y=wrap_coord(wy, WORLD_H),
                        vx=p.vx + math.cos(sp_ang) * sp_spd,
                        vy=p.vy + math.sin(sp_ang) * sp_spd,
                        life=0.08,
                        max_life=0.08,
                        size=2.0,
                        color_start=(255, 255, 255),
                        color_end=(0, 200, 255),
                        kind="spark",
                    )
                )

    def _update_enemies(self, dt: float) -> None:
        px, py = self.player.x, self.player.y

        for e in self.enemies:
            if not e.alive:
                continue

            dx = rel_coord(px, e.x, WORLD_W)
            dy = rel_coord(py, e.y, WORLD_H)
            dist = math.hypot(dx, dy)
            ang_to_player = math.atan2(dy, dx)

            if e.shield_flash > 0:
                e.shield_flash -= dt

            if e.kind == "scout":
                # Fast agile swarmer: swoops in, fires burst, peels away in curve
                e.behavior_timer -= dt
                if e.behavior_timer <= 0:
                    e.behavior_timer = self.rng.uniform(2.0, 4.0)
                    e.state = "intercept" if dist > 380 else "peel"

                if e.state == "intercept":
                    target_ang = ang_to_player
                    speed = 280.0
                else:
                    target_ang = ang_to_player + math.pi * 0.75
                    speed = 310.0

                diff = (target_ang - e.angle + math.pi) % math.tau - math.pi
                e.angle += math.copysign(min(6.0 * dt, abs(diff)), diff)

                e.vx = math.cos(e.angle) * speed
                e.vy = math.sin(e.angle) * speed

                # Weapon firing
                e.fire_timer -= dt
                if e.fire_timer <= 0 and dist < 500:
                    e.fire_timer = self.rng.uniform(1.2, 2.2)
                    self._fire_enemy_laser(e, "scout_laser", e.angle, 540.0, 14.0, (60, 255, 120), (220, 255, 220))

            elif e.kind == "cruiser":
                # Heavy armored cruiser: steady drift, rotating deflector shield, heavy plasma
                e.shield_rot = (e.shield_rot + 2.2 * dt) % math.tau

                diff = (ang_to_player - e.angle + math.pi) % math.tau - math.pi
                e.angle += math.copysign(min(2.0 * dt, abs(diff)), diff)

                # Keep standoff distance
                if dist > 380:
                    e.vx += math.cos(e.angle) * 90.0 * dt
                    e.vy += math.sin(e.angle) * 90.0 * dt
                else:
                    e.vx *= 0.96 ** (dt * 60)
                    e.vy *= 0.96 ** (dt * 60)

                e.fire_timer -= dt
                if e.fire_timer <= 0 and dist < 650:
                    e.fire_timer = self.rng.uniform(1.6, 2.8)
                    self._fire_enemy_laser(e, "cruiser_plasma", e.angle, 420.0, 30.0, (255, 60, 110), (255, 230, 240))

            elif e.kind == "mine":
                # Space mine: rotates slowly, detects proximity, pulses core
                e.angle = (e.angle + e.rot_speed * dt) % math.tau

                if dist < 240:
                    e.armed = True
                    # Magnetic homing acceleration toward player
                    e.vx += math.cos(ang_to_player) * 110.0 * dt
                    e.vy += math.sin(ang_to_player) * 110.0 * dt
                    # If collides with player: detonate
                    if dist < (e.radius + self.player.radius) and self.player.alive:
                        self._detonate_mine(e)
                else:
                    e.armed = False
                    e.vx *= 0.99 ** (dt * 60)
                    e.vy *= 0.99 ** (dt * 60)

            # Move enemy
            e.x = wrap_coord(e.x + e.vx * dt, WORLD_W)
            e.y = wrap_coord(e.y + e.vy * dt, WORLD_H)

    def _fire_enemy_laser(
        self,
        enemy: Enemy,
        kind: str,
        angle: float,
        speed: float,
        damage: float,
        color: tuple[int, int, int],
        core: tuple[int, int, int],
    ) -> None:
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        self.lasers.append(
            Laser(
                x=wrap_coord(enemy.x + cos_a * (enemy.radius + 6), WORLD_W),
                y=wrap_coord(enemy.y + sin_a * (enemy.radius + 6), WORLD_H),
                vx=cos_a * speed + enemy.vx * 0.2,
                vy=sin_a * speed + enemy.vy * 0.2,
                angle=angle,
                is_player=False,
                kind=kind,
                damage=damage,
                life=1.4,
                max_life=1.4,
                radius=4.0 if kind == "scout_laser" else 7.0,
                color=color,
                core_color=core,
            )
        )

    def _detonate_mine(self, mine: Enemy) -> None:
        mine.alive = False
        self._spawn_shockwave(mine.x, mine.y, 140.0, (255, 140, 40))
        self._spawn_explosion(mine.x, mine.y, 50, (255, 120, 30), debris=True)

        # Proximity blast damage to player and nearby enemies (chain reaction!)
        if self.player.alive:
            p_dist = math.hypot(rel_coord(self.player.x, mine.x, WORLD_W), rel_coord(self.player.y, mine.y, WORLD_H))
            if p_dist < 140.0:
                self._damage_player(65.0)

        for other in self.enemies:
            if other != mine and other.alive:
                o_dist = math.hypot(rel_coord(other.x, mine.x, WORLD_W), rel_coord(other.y, mine.y, WORLD_H))
                if o_dist < 140.0:
                    other.hull -= 50.0
                    if other.hull <= 0:
                        self._kill_enemy(other)

    def _update_lasers(self, dt: float) -> None:
        for las in self.lasers:
            las.life -= dt
            las.x = wrap_coord(las.x + las.vx * dt, WORLD_W)
            las.y = wrap_coord(las.y + las.vy * dt, WORLD_H)

            if las.life <= 0:
                continue

            if las.is_player:
                # Check collision with enemies
                for e in self.enemies:
                    if not e.alive:
                        continue
                    dx = rel_coord(las.x, e.x, WORLD_W)
                    dy = rel_coord(las.y, e.y, WORLD_H)
                    if math.hypot(dx, dy) < (e.radius + las.radius):
                        las.life = 0.0
                        self._hit_enemy(e, las.damage, dx, dy)
                        break
            else:
                # Check collision with player
                if self.player.alive:
                    p = self.player
                    dx = rel_coord(las.x, p.x, WORLD_W)
                    dy = rel_coord(las.y, p.y, WORLD_H)
                    if math.hypot(dx, dy) < (p.radius + las.radius):
                        las.life = 0.0
                        self._damage_player(las.damage)

        self.lasers = [l for l in self.lasers if l.life > 0]

    def _hit_enemy(self, e: Enemy, damage: float, dx: float, dy: float) -> None:
        if e.shields > 0:
            e.shields -= damage
            e.shield_flash = 0.28
            # Deflector shield impact sparks
            for _ in range(6):
                sp_ang = math.atan2(dy, dx) + self.rng.uniform(-1.0, 1.0)
                sp_spd = self.rng.uniform(80, 200)
                self.particles.append(
                    Particle(
                        x=e.x,
                        y=e.y,
                        vx=math.cos(sp_ang) * sp_spd,
                        vy=math.sin(sp_ang) * sp_spd,
                        life=self.rng.uniform(0.12, 0.22),
                        max_life=0.22,
                        size=self.rng.uniform(2.0, 3.5),
                        color_start=(255, 120, 220),
                        color_end=(60, 20, 100),
                        kind="spark",
                    )
                )
            if e.shields < 0:
                e.hull += e.shields
                e.shields = 0.0
        else:
            e.hull -= damage
            for _ in range(5):
                sp_ang = self.rng.uniform(0, math.tau)
                sp_spd = self.rng.uniform(60, 180)
                self.particles.append(
                    Particle(
                        x=e.x,
                        y=e.y,
                        vx=math.cos(sp_ang) * sp_spd,
                        vy=math.sin(sp_ang) * sp_spd,
                        life=self.rng.uniform(0.1, 0.2),
                        max_life=0.2,
                        size=2.0,
                        color_start=(255, 240, 160),
                        color_end=(255, 60, 30),
                        kind="spark",
                    )
                )

        if e.hull <= 0:
            self._kill_enemy(e)

    def _kill_enemy(self, e: Enemy) -> None:
        e.alive = False
        self.score += e.score

        if e.kind == "mine":
            self._detonate_mine(e)
            return

        if e.kind == "cruiser":
            self._spawn_shockwave(e.x, e.y, 110.0, (255, 80, 120))
            self._spawn_explosion(e.x, e.y, 48, (255, 70, 90), debris=True)
        else:
            self._spawn_shockwave(e.x, e.y, 65.0, (80, 255, 140))
            self._spawn_explosion(e.x, e.y, 26, (80, 255, 140), debris=False)

    def _damage_player(self, damage: float) -> None:
        p = self.player
        if p.invulnerable_timer > 0:
            return

        p.shield_recharge_wait = 2.8

        if p.shields > 0:
            p.shields -= damage
            p.shield_flash = 0.35
            # Player deflector shield impact sparks
            for _ in range(8):
                sp_ang = self.rng.uniform(0, math.tau)
                sp_spd = self.rng.uniform(80, 220)
                self.particles.append(
                    Particle(
                        x=p.x,
                        y=p.y,
                        vx=math.cos(sp_ang) * sp_spd,
                        vy=math.sin(sp_ang) * sp_spd,
                        life=self.rng.uniform(0.15, 0.28),
                        max_life=0.28,
                        size=self.rng.uniform(2.0, 3.5),
                        color_start=(0, 240, 255),
                        color_end=(20, 40, 100),
                        kind="spark",
                    )
                )
            if p.shields < 0:
                p.hull += p.shields
                p.shields = 0.0
        else:
            p.hull -= damage
            for _ in range(8):
                sp_ang = self.rng.uniform(0, math.tau)
                sp_spd = self.rng.uniform(90, 240)
                self.particles.append(
                    Particle(
                        x=p.x,
                        y=p.y,
                        vx=math.cos(sp_ang) * sp_spd,
                        vy=math.sin(sp_ang) * sp_spd,
                        life=self.rng.uniform(0.18, 0.3),
                        max_life=0.3,
                        size=3.0,
                        color_start=(255, 200, 60),
                        color_end=(255, 40, 20),
                        kind="spark",
                    )
                )

        if p.hull <= 0:
            p.alive = False
            p.respawn_timer = 2.2
            self._spawn_shockwave(p.x, p.y, 130.0, (0, 240, 255))
            self._spawn_explosion(p.x, p.y, 60, (0, 220, 255), debris=True)

    def _spawn_explosion(
        self, x: float, y: float, count: int, color_base: tuple[int, int, int], debris: bool = False
    ) -> None:
        for _ in range(count):
            ang = self.rng.uniform(0, math.tau)
            spd = self.rng.uniform(60, 380)
            life = self.rng.uniform(0.3, 0.85)
            self.particles.append(
                Particle(
                    x=x,
                    y=y,
                    vx=math.cos(ang) * spd,
                    vy=math.sin(ang) * spd,
                    life=life,
                    max_life=life,
                    size=self.rng.uniform(2.5, 5.0),
                    color_start=(255, 255, 220) if self.rng.random() < 0.3 else color_base,
                    color_end=(40, 15, 25),
                    kind="spark",
                )
            )

        if debris:
            for _ in range(8):
                ang = self.rng.uniform(0, math.tau)
                spd = self.rng.uniform(40, 180)
                life = self.rng.uniform(0.6, 1.2)
                self.particles.append(
                    Particle(
                        x=x,
                        y=y,
                        vx=math.cos(ang) * spd,
                        vy=math.sin(ang) * spd,
                        life=life,
                        max_life=life,
                        size=self.rng.uniform(4.0, 7.0),
                        color_start=(160, 175, 195),
                        color_end=(50, 55, 65),
                        kind="debris",
                        angle=self.rng.uniform(0, math.tau),
                        rot_speed=self.rng.uniform(-8.0, 8.0),
                    )
                )

    def _spawn_shockwave(self, x: float, y: float, max_radius: float, color: tuple[int, int, int]) -> None:
        self.shockwaves.append(
            Shockwave(
                x=x,
                y=y,
                radius=4.0,
                max_radius=max_radius,
                speed=max_radius * 3.2,
                color=color,
                width=2,
            )
        )

    def _update_particles(self, dt: float) -> None:
        for p in self.particles:
            p.life -= dt
            p.x = wrap_coord(p.x + p.vx * dt, WORLD_W)
            p.y = wrap_coord(p.y + p.vy * dt, WORLD_H)
            p.vx *= 0.96 ** (dt * 60)
            p.vy *= 0.96 ** (dt * 60)
            p.angle += p.rot_speed * dt
        self.particles = [p for p in self.particles if p.life > 0]

        for s in self.shockwaves:
            s.radius += s.speed * dt
        self.shockwaves = [s for s in self.shockwaves if s.radius < s.max_radius]

        # Cull dead enemies
        self.enemies = [e for e in self.enemies if e.alive]

    def draw(self, surf: pygame.Surface) -> None:
        if self.radar_surf is None or surf.get_width() != self.w or surf.get_height() != self.h:
            self.resize(surf.get_width(), surf.get_height())

        # Deep space backdrop
        surf.fill((2, 4, 10))

        px, py = self.player.x, self.player.y

        # 1. Parallax Celestial Nebulae (Soft Additive Gas Clouds)
        for neb_surf, nwx, nwy in self.nebulae:
            ndx = rel_coord(nwx, px * 0.03, WORLD_W)
            ndy = rel_coord(nwy, py * 0.03, WORLD_H)
            sc_x = int(self.w * 0.5 + ndx - neb_surf.get_width() * 0.5)
            sc_y = int(self.h * 0.5 + ndy - neb_surf.get_height() * 0.5)
            surf.blit(neb_surf, (sc_x, sc_y), special_flags=pygame.BLEND_ADD)

        # 2. Multi-layer Starfield with Twinkle
        for star in self.stars:
            k = 0.05 if star.layer == 0 else (0.20 if star.layer == 1 else 0.55)
            sx = int((star.x - px * k) % self.w)
            sy = int((star.y - py * k) % self.h)

            twinkle = 0.72 + 0.28 * math.sin(self.t * star.twinkle_speed + star.twinkle_phase)
            r = min(255, int(star.color[0] * twinkle))
            g = min(255, int(star.color[1] * twinkle))
            b = min(255, int(star.color[2] * twinkle))
            col = (r, g, b)

            if star.size == 1:
                surf.set_at((sx, sy), col)
            elif star.size == 2:
                surf.fill(col, (sx, sy, 2, 2))
            else:
                surf.fill(col, (sx - 1, sy - 1, 3, 3))
                halo = (r // 3, g // 3, b // 3)
                surf.set_at((sx - 2, sy), halo)
                surf.set_at((sx + 2, sy), halo)
                surf.set_at((sx, sy - 2), halo)
                surf.set_at((sx, sy + 2), halo)

        # 3. Shockwave Rings
        for sw in self.shockwaves:
            dx = rel_coord(sw.x, px, WORLD_W)
            dy = rel_coord(sw.y, py, WORLD_H)
            sc_x = int(self.w * 0.5 + dx)
            sc_y = int(self.h * 0.5 + dy)
            progress = sw.radius / sw.max_radius
            if progress < 1.0 and -200 <= sc_x <= self.w + 200 and -200 <= sc_y <= self.h + 200:
                alpha = 1.0 - progress
                col = (int(sw.color[0] * alpha), int(sw.color[1] * alpha), int(sw.color[2] * alpha))
                pygame.draw.circle(surf, col, (sc_x, sc_y), int(sw.radius), sw.width)

        # 4. Particles (Sparks, Exhaust Flames, Debris)
        for p in self.particles:
            dx = rel_coord(p.x, px, WORLD_W)
            dy = rel_coord(p.y, py, WORLD_H)
            sc_x = int(self.w * 0.5 + dx)
            sc_y = int(self.h * 0.5 + dy)
            if 0 <= sc_x < self.w and 0 <= sc_y < self.h:
                t = max(0.0, min(1.0, 1.0 - p.life / p.max_life))
                col = mix(p.color_start, p.color_end, t)
                if p.kind == "debris":
                    # Spinning metal shard
                    sz = max(2, int(p.size * (1.0 - t * 0.3)))
                    cos_d = math.cos(p.angle) * sz
                    sin_d = math.sin(p.angle) * sz
                    pts = [
                        (sc_x + cos_d, sc_y + sin_d),
                        (sc_x - sin_d * 0.5, sc_y + cos_d * 0.5),
                        (sc_x - cos_d, sc_y - sin_d),
                        (sc_x + sin_d * 0.5, sc_y - cos_d * 0.5),
                    ]
                    pygame.draw.polygon(surf, col, pts)
                else:
                    sz = max(1, int(p.size * (1.0 - t * 0.5)))
                    if sz <= 1:
                        surf.set_at((sc_x, sc_y), col)
                    else:
                        pygame.draw.circle(surf, col, (sc_x, sc_y), sz)

        # 5. Projectiles (Lasers & Plasma Orbs)
        for las in self.lasers:
            dx = rel_coord(las.x, px, WORLD_W)
            dy = rel_coord(las.y, py, WORLD_H)
            sc_x = int(self.w * 0.5 + dx)
            sc_y = int(self.h * 0.5 + dy)
            if -50 <= sc_x <= self.w + 50 and -50 <= sc_y <= self.h + 50:
                if las.kind == "cruiser_plasma":
                    # Pulsing heavy plasma sphere with energy glow
                    pygame.draw.circle(surf, las.color, (sc_x, sc_y), int(las.radius + 3), 1)
                    pygame.draw.circle(surf, las.color, (sc_x, sc_y), int(las.radius))
                    pygame.draw.circle(surf, las.core_color, (sc_x, sc_y), int(las.radius * 0.55))
                else:
                    # High-velocity beam bolt with bright core and tracer line
                    cos_l = math.cos(las.angle)
                    sin_l = math.sin(las.angle)
                    tail_len = 18.0 if las.is_player else 14.0
                    tip = (sc_x + cos_l * 4, sc_y + sin_l * 4)
                    tail = (sc_x - cos_l * tail_len, sc_y - sin_l * tail_len)
                    pygame.draw.line(surf, las.color, tip, tail, 3)
                    pygame.draw.line(surf, las.core_color, tip, tail, 1)

        # 6. Alien Enemies
        for e in self.enemies:
            if not e.alive:
                continue
            dx = rel_coord(e.x, px, WORLD_W)
            dy = rel_coord(e.y, py, WORLD_H)
            sc_x = int(self.w * 0.5 + dx)
            sc_y = int(self.h * 0.5 + dy)
            if -60 <= sc_x <= self.w + 60 and -60 <= sc_y <= self.h + 60:
                self._draw_enemy(surf, e, sc_x, sc_y)

        # 7. Player Starfighter
        if self.player.alive:
            self._draw_player(surf, int(self.w * 0.5), int(self.h * 0.5))

        # 8. Classic Lunatic Fringe Tactical CRT Radar HUD
        self._draw_radar(surf)

        # 9. Cockpit HUD Overlay (Scores, Gauges, Status Ticker)
        self._draw_hud(surf)

    def _draw_player(self, surf: pygame.Surface, cx: int, cy: int) -> None:
        p = self.player
        cos_a = math.cos(p.angle)
        sin_a = math.sin(p.angle)

        # Dual Thruster Exhaust Flames
        if p.thrusting:
            fl_len = 18.0 + self.rng.uniform(0.0, 10.0)
            for side in (-7.0, 7.0):
                noz_x = cx - cos_a * 18 - sin_a * side
                noz_y = cy - sin_a * 18 + cos_a * side
                tip_x = cx - cos_a * (18 + fl_len) - sin_a * side
                tip_y = cy - sin_a * (18 + fl_len) + cos_a * side
                flame_pts = [
                    (noz_x - sin_a * 3.5, noz_y + cos_a * 3.5),
                    (tip_x, tip_y),
                    (noz_x + sin_a * 3.5, noz_y - cos_a * 3.5),
                ]
                pygame.draw.polygon(surf, (0, 180, 255), flame_pts)
                flame_core = [
                    (noz_x - sin_a * 1.8, noz_y + cos_a * 1.8),
                    (cx - cos_a * (18 + fl_len * 0.65) - sin_a * side, cy - sin_a * (18 + fl_len * 0.65) + cos_a * side),
                    (noz_x + sin_a * 1.8, noz_y - cos_a * 1.8),
                ]
                pygame.draw.polygon(surf, (255, 255, 230), flame_core)

        # Starfighter Vector Geometry Vertices
        hull_local = [
            (24.0, 0.0),      # Sleek needle nose
            (7.0, -11.0),     # Left intake facet
            (-16.0, -20.0),   # Left wingtip
            (-18.0, -20.0),   # Left cannon pylon
            (-18.0, -8.0),    # Left engine nozzle
            (-10.0, 0.0),     # Aft center keel
            (-18.0, 8.0),     # Right engine nozzle
            (-18.0, 20.0),    # Right cannon pylon
            (-16.0, 20.0),    # Right wingtip
            (7.0, 11.0),      # Right intake facet
        ]
        hull_pts = [(cx + cos_a * lx - sin_a * ly, cy + sin_a * lx + cos_a * ly) for lx, ly in hull_local]

        # Draw main starfighter hull
        pygame.draw.polygon(surf, (22, 32, 48), hull_pts)
        pygame.draw.lines(surf, (185, 215, 245), True, hull_pts, 2)

        # Cyber cyan wing trim lines
        left_trim = [
            (cx + cos_a * 3 - sin_a * (-10), cy + sin_a * 3 + cos_a * (-10)),
            (cx + cos_a * (-14) - sin_a * (-18), cy + sin_a * (-14) + cos_a * (-18)),
        ]
        right_trim = [
            (cx + cos_a * 3 - sin_a * 10, cy + sin_a * 3 + cos_a * 10),
            (cx + cos_a * (-14) - sin_a * 18, cy + sin_a * (-14) + cos_a * 18),
        ]
        pygame.draw.line(surf, (0, 240, 255), left_trim[0], left_trim[1], 2)
        pygame.draw.line(surf, (0, 240, 255), right_trim[0], right_trim[1], 2)

        # Cockpit canopy (glowing electric cyan with specular glint)
        canopy_local = [(14.0, 0.0), (2.0, -5.0), (-5.0, 0.0), (2.0, 5.0)]
        canopy_pts = [(cx + cos_a * lx - sin_a * ly, cy + sin_a * lx + cos_a * ly) for lx, ly in canopy_local]
        pygame.draw.polygon(surf, (50, 215, 255), canopy_pts)
        pygame.draw.lines(surf, (160, 245, 255), True, canopy_pts, 1)
        glint = (cx + cos_a * 5 - sin_a * (-1), cy + sin_a * 5 + cos_a * (-1))
        surf.set_at((int(glint[0]), int(glint[1])), (255, 255, 255))

        # Deflector Shield Impact / Invulnerability Bubble
        if p.invulnerable_timer > 0 or p.shield_flash > 0:
            pulse = math.sin(self.t * 14.0) * 0.12 + 0.88
            rad = int(30 * pulse)
            shield_col = (0, 230, 255)
            pygame.draw.circle(surf, shield_col, (cx, cy), rad, 1)
            # Hexagonal shield nodes
            for hx_ang in [i * math.pi / 3 + self.t * 2.2 for i in range(6)]:
                nx = cx + math.cos(hx_ang) * rad
                ny = cy + math.sin(hx_ang) * rad
                pygame.draw.circle(surf, (180, 245, 255), (int(nx), int(ny)), 2)

    def _draw_enemy(self, surf: pygame.Surface, e: Enemy, cx: int, cy: int) -> None:
        cos_a = math.cos(e.angle)
        sin_a = math.sin(e.angle)

        if e.kind == "scout":
            # Toxic Green Dart / Arrowhead
            scout_local = [
                (22.0, 0.0),
                (-12.0, -15.0),
                (-7.0, -5.0),
                (-10.0, 0.0),
                (-7.0, 5.0),
                (-12.0, 15.0),
            ]
            pts = [(cx + cos_a * lx - sin_a * ly, cy + sin_a * lx + cos_a * ly) for lx, ly in scout_local]
            pygame.draw.polygon(surf, (18, 48, 26), pts)
            pygame.draw.lines(surf, e.color, True, pts, 2)
            # Emerald engine flare
            noz_x = cx - cos_a * 11
            noz_y = cy - sin_a * 11
            pygame.draw.circle(surf, (120, 255, 160), (int(noz_x), int(noz_y)), 3)

        elif e.kind == "cruiser":
            # Armored Crimson Diamond Battleship
            cruiser_local = [
                (30.0, 0.0),
                (0.0, -25.0),
                (-18.0, -15.0),
                (-22.0, -8.0),
                (-17.0, 0.0),
                (-22.0, 8.0),
                (-18.0, 15.0),
                (0.0, 25.0),
            ]
            pts = [(cx + cos_a * lx - sin_a * ly, cy + sin_a * lx + cos_a * ly) for lx, ly in cruiser_local]
            pygame.draw.polygon(surf, (44, 18, 28), pts)
            pygame.draw.lines(surf, e.color, True, pts, 2)

            # Central menacing ruby sensor eye
            eye_x = cx + cos_a * 5
            eye_y = cy + sin_a * 5
            pygame.draw.circle(surf, (255, 40, 70), (int(eye_x), int(eye_y)), 5)
            pygame.draw.circle(surf, (255, 230, 240), (int(eye_x), int(eye_y)), 2)

            # Rotating Deflector Shield Nodes
            if e.shields > 0 or e.shield_flash > 0:
                rad = 35
                shield_color = (255, 80, 220) if e.shield_flash > 0 else (200, 50, 160)
                pygame.draw.circle(surf, shield_color, (cx, cy), rad, 1)
                for node_i in range(3):
                    n_ang = e.shield_rot + node_i * (math.tau / 3)
                    nx = cx + math.cos(n_ang) * rad
                    ny = cy + math.sin(n_ang) * rad
                    pygame.draw.circle(surf, (255, 140, 240), (int(nx), int(ny)), 3)

        elif e.kind == "mine":
            # Octagonal Spiked Space Mine
            pulse = math.sin(self.t * (16.0 if e.armed else 3.5)) * 0.5 + 0.5
            core_col = mix(e.accent, (255, 255, 180), pulse)

            # 8 Spikes radiating outward
            for i in range(8):
                spk_ang = e.angle + i * (math.tau / 8)
                tip_x = cx + math.cos(spk_ang) * 21
                tip_y = cy + math.sin(spk_ang) * 21
                pygame.draw.line(surf, (100, 110, 125), (cx, cy), (int(tip_x), int(tip_y)), 2)
                pygame.draw.circle(surf, (255, 60, 40), (int(tip_x), int(tip_y)), 2)

            # Center armored core
            pygame.draw.circle(surf, (36, 42, 50), (cx, cy), 11)
            pygame.draw.circle(surf, (140, 155, 175), (cx, cy), 11, 1)
            pygame.draw.circle(surf, core_col, (cx, cy), 5)

    def _draw_radar(self, surf: pygame.Surface) -> None:
        """Iconic circular CRT radar scanner in the corner with rotating sweep and phosphor blips."""
        assert self.radar_surf is not None
        rcx = self.w - self.radar_diam // 2 - 16
        rcy = self.h - self.radar_diam // 2 - 16
        r = self.radar_radius

        # Blit pre-baked radar base monitor
        surf.blit(self.radar_surf, (rcx - self.radar_diam // 2, rcy - self.radar_diam // 2))

        # Rotating CRT Phosphor Sweep Beam
        sweep_cos = math.cos(self.sweep_angle)
        sweep_sin = math.sin(self.sweep_angle)
        tip_x = rcx + sweep_cos * r
        tip_y = rcy + sweep_sin * r
        pygame.draw.line(surf, (80, 255, 140), (rcx, rcy), (int(tip_x), int(tip_y)), 2)

        # Fading phosphor wedge trailing the sweep line
        for step in (1, 2, 3):
            trail_ang = self.sweep_angle - step * 0.08
            tx = rcx + math.cos(trail_ang) * r
            ty = rcy + math.sin(trail_ang) * r
            alpha_col = (15, 65 // step, 28 // step)
            pygame.draw.line(surf, alpha_col, (rcx, rcy), (int(tx), int(ty)), 1)

        # Center Player Arrow Marker
        if self.player.alive:
            p_cos = math.cos(self.player.angle)
            p_sin = math.sin(self.player.angle)
            p_pts = [
                (rcx + p_cos * 6, rcy + p_sin * 6),
                (rcx - p_cos * 4 - p_sin * 4, rcy - p_sin * 4 + p_cos * 4),
                (rcx - p_cos * 2, rcy - p_sin * 2),
                (rcx - p_cos * 4 + p_sin * 4, rcy - p_sin * 4 - p_cos * 4),
            ]
            pygame.draw.polygon(surf, (100, 255, 160), p_pts)

        # Target Radar Blips
        px, py = self.player.x, self.player.y
        for e in self.enemies:
            if not e.alive:
                continue
            dx = rel_coord(e.x, px, WORLD_W)
            dy = rel_coord(e.y, py, WORLD_H)
            dist = math.hypot(dx, dy)
            if dist <= RADAR_RANGE:
                bx = rcx + int((dx / RADAR_RANGE) * r)
                by = rcy + int((dy / RADAR_RANGE) * r)

                # Check if sweep line has recently passed over this blip
                blip_ang = math.atan2(dy, dx) % math.tau
                ang_diff = (self.sweep_angle - blip_ang) % math.tau
                phosphor_boost = 1.0 if ang_diff < 0.35 else 0.45

                if e.kind == "scout":
                    col = (int(60 * phosphor_boost + 195 * (1 - phosphor_boost) * 0.2), int(255 * phosphor_boost), int(120 * phosphor_boost))
                    pygame.draw.circle(surf, col, (bx, by), 2)
                elif e.kind == "cruiser":
                    col = (int(255 * phosphor_boost), int(50 * phosphor_boost), int(80 * phosphor_boost))
                    pygame.draw.rect(surf, col, (bx - 2, by - 2, 4, 4))
                elif e.kind == "mine":
                    col = (int(255 * phosphor_boost), int(190 * phosphor_boost), int(30 * phosphor_boost))
                    surf.set_at((bx, by), col)
                    surf.set_at((bx - 1, by), col)
                    surf.set_at((bx + 1, by), col)
                    surf.set_at((bx, by - 1), col)
                    surf.set_at((bx, by + 1), col)

    def _draw_hud(self, surf: pygame.Surface) -> None:
        """Retro-futuristic tactical fighter cockpit HUD overlay."""
        f_title = font("mono", 14)
        f_body = font("mono", 12)
        f_small = font("mono", 10)

        # 1. Top-Left Tactical Readout
        surf.blit(f_title.render(f"LUNATIC FRINGE // SECTOR {self.wave:02d}", True, (0, 230, 255)), (24, 20))
        surf.blit(f_body.render(f"SCORE: {self.score:06d}", True, (240, 245, 255)), (24, 42))
        surf.blit(f_body.render(f"HOSTILES: {len(self.enemies):02d} DETECTED", True, (80, 255, 140)), (24, 62))

        # 2. Top-Right Defense Status Gauges
        gauge_w = 120
        gauge_h = 10
        rx = self.w - gauge_w - 180
        ry = 22

        # Shields Gauge
        s_pct = max(0.0, min(1.0, self.player.shields / self.player.max_shields))
        surf.blit(f_small.render("DEFLECTORS", True, (0, 220, 255)), (rx - 85, ry - 1))
        rrect(surf, (20, 35, 50), (rx, ry, gauge_w, gauge_h), 2)
        if s_pct > 0:
            s_col = (0, 240, 255) if s_pct > 0.3 else (255, 80, 80)
            rrect(surf, s_col, (rx, ry, int(gauge_w * s_pct), gauge_h), 2)
        surf.blit(f_small.render(f"{int(s_pct * 100)}%", True, (220, 240, 255)), (rx + gauge_w + 10, ry - 1))

        # Hull Gauge
        h_pct = max(0.0, min(1.0, self.player.hull / self.player.max_hull))
        surf.blit(f_small.render("HULL ARMOR", True, (100, 255, 160)), (rx - 85, ry + 18))
        rrect(surf, (20, 35, 50), (rx, ry + 19, gauge_w, gauge_h), 2)
        if h_pct > 0:
            h_col = (80, 255, 140) if h_pct > 0.3 else (255, 60, 40)
            rrect(surf, h_col, (rx, ry + 19, int(gauge_w * h_pct), gauge_h), 2)
        surf.blit(f_small.render(f"{int(h_pct * 100)}%", True, (220, 240, 255)), (rx + gauge_w + 10, ry + 18))

        # 3. Bottom Tactical Status Ticker
        status_text = f"AI TACTICAL PILOT: {self.player.ai_status}"
        surf.blit(f_body.render(status_text, True, (0, 220, 255)), (24, self.h - 32))

        # 4. Central Sector Banner Alert
        if self.status_banner_timer > 0:
            banner_surf = f_title.render(self.status_banner, True, (255, 240, 140))
            bx = (self.w - banner_surf.get_width()) // 2
            by = 70
            surf.blit(banner_surf, (bx, by))
