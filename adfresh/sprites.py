"""Sprites for the toasters and toast, faithfully reproducing the original 1990s After Dark screensaver.

The photographic body art is kept verbatim.  Instead of blitting the original
16-frame sheets (which bake both wings into the body and therefore render the far
wing as a detached sliver), the sprites are composed at runtime from reusable
raster layers shipped next to the original frames:

* ``assets/body_toaster.png`` / ``assets/body_toast_<kind>.png`` - wing-free body
  plates derived from the source frames by ``scripts/build_wing_assets.py``.
* ``assets/wing_master.png`` - one clean, transparent angel wing (with its
  shoulder ball) plus ``assets/wing_meta.json`` with the shoulder anchors.

Every frame is a three-layer composite: the far wing (the same wing raster
mirrored, smaller, dimmer and sitting *behind* the body), the body, and the near
wing (in front, casting a soft shadow on the body).  Wings rotate around their
shoulder pivots with a sinusoidal flap in mirror phase: the far wing's angle is
the mirror of the near wing's, so both tips rise and fall together, as a bird's
wings must.  Attachment points never move and the body cannot shimmer.  The
public ``toaster(frame, width, variant)`` / ``toast(kind, frame, width)`` API is
unchanged; if the derived layers are missing the module falls back to the legacy
sheets and then to procedural art.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pygame

from adfresh.drawutil import mix, rrect

WING_FRAMES = 16
FLAP_CYCLE = tuple(range(16))
CANVAS = (520, 360)
TOAST_CANVAS = (340, 380)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# --------------------------------------------------------------------------- #
# Layered composition parameters (fractions of the body plate size)
# --------------------------------------------------------------------------- #
TOASTER = {
    "wing_w": 0.500,          # near wing raster width / body width
    "near_anchor": (0.495, 0.470),   # near shoulder pivot, body fractions
    "near_base": 5.0,         # degrees; positive lifts the near wing tip
    "amp": 35.0,              # flap amplitude in degrees (clear up/down poses)
    "near_fore": 0.07,        # near-wing foreshortening (grows on the downstroke)
    "far_fore": 0.26,         # far-wing apparent span grows on the upstroke
    "far_tuck": (0.050, 0.080),  # downstroke: sink the far wing behind the body
    # The body plate is scaled down inside the sprite frame so both wings have
    # room to swing (the module compensates so the body is unchanged on
    # screen).  The frame margins are centred around the body content.
    "body_scale": 0.64,
    # The far wing sits on the hidden side: the mirrored wing (pointing away from
    # the body instead of across it), smaller, dimmer, drawn BEHIND the body so
    # only the part above the back edge is visible.  It flaps in mirror phase:
    # when the near tip rises the far tip rises too, like a bird's wings.
    "far_anchor": (0.390, 0.245),
    "far_base": -36.0,
    # The far wing sweeps a wider, asymmetric arc than the near wing: high over
    # the back on the upstroke, then folded down behind the body on the
    # downstroke where the body hides most of it.
    "far_amp_up": 40.0,
    "far_amp_down": 80.0,
    "far_flip": False,
    "far_scale": 0.82,
    "far_tint": 0.82,
    "far_desat": 0.18,
    "shadow_alpha": 78,
    "shadow_offset": (0.010, 0.016),  # fractions of body width, x/y
}

TOAST = {
    "wing_w": 0.88,           # near wing raster width / bread bbox width
    "near_base": -11.0,       # degrees relative to upright bread
    "far_base": 6.0,
    "tilt_follow": 0.45,      # how much of the bread tilt the wings follow
    "amp": 45.0,              # clear upstroke / downstroke poses
    "near_fore": 0.05,        # near-wing foreshortening
    "far_fore": 0.15,         # far-wing apparent span grows on the upstroke
    "far_tuck": (0.012, 0.020),  # downstroke: sink the far wing behind the toast
    "far_scale": 0.95,
    "far_tint": 0.96,
    "far_desat": 0.05,
    "shadow_alpha": 88,
    "shadow_offset": (0.012, 0.018),  # fractions of bread width
    "compose_size": (600, 500),       # shared canvas for every toast kind
    "compose_center": (300.0, 250.0),  # centred body leaves wing headroom
}

_toasters: dict[tuple[int, int], pygame.Surface] = {}
_toasts: dict[tuple[str, int, int], pygame.Surface] = {}
_raw_assets: dict[str, pygame.Surface | None] = {}
_toaster_parts: dict[int, tuple | None] = {}
_toast_parts: dict[tuple[str, int], tuple | None] = {}
_meta_cache: dict | None = None


# --------------------------------------------------------------------------- #
# Asset loading
# --------------------------------------------------------------------------- #
def _load_asset(name: str) -> pygame.Surface | None:
    if name in _raw_assets:
        return _raw_assets[name]
    path = ASSETS_DIR / f"{name}.png"
    if not path.is_file():
        return None
    try:
        surf = pygame.image.load(str(path))
        _raw_assets[name] = surf
        return surf
    except Exception:
        _raw_assets[name] = None
        return None


def _meta() -> dict:
    global _meta_cache
    if _meta_cache is None:
        path = ASSETS_DIR / "wing_meta.json"
        try:
            with open(path, encoding="utf-8") as handle:
                _meta_cache = json.load(handle)
        except Exception:
            _meta_cache = {}
    return _meta_cache


# --------------------------------------------------------------------------- #
# Raster helpers
# --------------------------------------------------------------------------- #
def _scale(surf: pygame.Surface, width: int, height: int | None = None) -> pygame.Surface:
    width = max(1, int(round(width)))
    if height is None:
        height = max(1, int(round(surf.get_height() * width / surf.get_width())))
    height = max(1, int(round(height)))
    if (width, height) == surf.get_size():
        return surf
    return pygame.transform.smoothscale(surf, (width, height))


def _tint(surf: pygame.Surface, mul: float, desat: float = 0.0) -> pygame.Surface:
    """Return a copy shaded by ``mul`` and partially desaturated toward grey."""
    out = surf.copy()
    pixels = pygame.surfarray.pixels3d(out).astype("float32")
    if desat > 0.0:
        grey = pixels.mean(axis=2, keepdims=True)
        pixels = pixels * (1.0 - desat) + grey * desat
    pixels *= mul
    view = pygame.surfarray.pixels3d(out)
    view[:, :, :] = pixels.clip(0, 255).astype(view.dtype)
    del view
    return out


def _rotate_about(
    surf: pygame.Surface, angle: float, pivot: tuple[float, float]
) -> tuple[pygame.Surface, tuple[float, float]]:
    """Rotate ``surf`` by ``angle`` degrees (CCW on screen) around ``pivot``.

    Returns the rotated surface and the pivot in the rotated surface's coordinates,
    so the caller can blit it wherever the pivot belongs.
    """
    rotated = pygame.transform.rotozoom(surf, angle, 1.0)
    cosine = math.cos(math.radians(angle))
    sine = math.sin(math.radians(angle))
    px = pivot[0] - surf.get_width() / 2.0
    py = pivot[1] - surf.get_height() / 2.0
    rx = px * cosine + py * sine
    ry = -px * sine + py * cosine
    return rotated, (rotated.get_width() / 2.0 + rx, rotated.get_height() / 2.0 + ry)


def _blit_at(
    canvas: pygame.Surface,
    image: pygame.Surface,
    image_pivot: tuple[float, float],
    target: tuple[float, float],
) -> None:
    canvas.blit(
        image,
        (
            int(round(target[0] - image_pivot[0])),
            int(round(target[1] - image_pivot[1])),
        ),
    )


def _shadow_layer(wing: pygame.Surface, alpha: int) -> pygame.Surface:
    """A soft, dark silhouette of ``wing`` used to ground it on the body."""
    width, height = wing.get_size()
    mask = pygame.mask.from_surface(wing)
    shadow = pygame.Surface((width, height), pygame.SRCALPHA)
    shadow.blit(mask.to_surface(setcolor=(0, 0, 0, alpha), unsetcolor=(0, 0, 0, 0)), (0, 0))
    soft = pygame.transform.smoothscale(
        shadow, (max(1, width // 3), max(1, height // 3))
    )
    return pygame.transform.smoothscale(soft, (width, height))


def _wing_layer(
    master: pygame.Surface,
    master_pivot: tuple[float, float],
    width: float,
    flip_h: bool,
    flip_v: bool = False,
    tint_mul: float = 1.0,
    desat: float = 0.0,
) -> tuple[pygame.Surface, tuple[float, float]]:
    """Scale/mirror/shade the master wing; returns the layer and its pivot."""
    width = max(6, int(round(width)))
    height = max(6, int(round(master.get_height() * width / master.get_width())))
    layer = _scale(master, width, height)
    if flip_h:
        layer = pygame.transform.flip(layer, True, False)
    if flip_v:
        layer = pygame.transform.flip(layer, False, True)
    pivot_x = master_pivot[0] * width / master.get_width()
    pivot_y = master_pivot[1] * height / master.get_height()
    if flip_h:
        pivot_x = width - pivot_x
    if flip_v:
        pivot_y = height - pivot_y
    if tint_mul != 1.0 or desat > 0.0:
        layer = _tint(layer, tint_mul, desat)
    return layer, (pivot_x, pivot_y)


def _scale_about_pivot(
    layer: pygame.Surface, pivot: tuple[float, float], factor: float
) -> tuple[pygame.Surface, tuple[float, float]]:
    """Scale a wing layer and its shoulder pivot by ``factor`` (foreshortening)."""
    if abs(factor - 1.0) < 0.005:
        return layer, pivot
    width = max(2, int(round(layer.get_width() * factor)))
    height = max(2, int(round(layer.get_height() * factor)))
    scaled = pygame.transform.smoothscale(layer, (width, height))
    return scaled, (
        pivot[0] * width / layer.get_width(),
        pivot[1] * height / layer.get_height(),
    )


# --------------------------------------------------------------------------- #
# Toaster layers
# --------------------------------------------------------------------------- #
def _toaster_layer_parts(width: int) -> tuple | None:
    if width in _toaster_parts:
        return _toaster_parts[width]
    body_src = _load_asset("body_toaster")
    wing_master = _load_asset("wing_master")
    pivot = _meta().get("wing", {}).get("pivot")
    if body_src is None or wing_master is None or not pivot:
        _toaster_parts[width] = None
        return None
    # The output frame keeps the body-plate aspect ratio, but the plate itself
    # is scaled by ``body_scale`` and centred so the wings have room to swing.
    source_w, source_h = body_src.get_size()
    canvas_h = max(1, int(round(width * source_h / source_w)))
    plate_w = max(1, int(round(width * TOASTER["body_scale"])))
    plate_h = max(1, int(round(plate_w * source_h / source_w)))
    body_plate = _scale(body_src, plate_w, plate_h)
    content = pygame.mask.from_surface(body_plate).get_bounding_rects()
    content_rect = max(content, key=lambda rect: rect.w * rect.h) if content else None
    if content_rect is not None:
        offset_x = int(round(width / 2 - (content_rect.x + content_rect.w / 2)))
        offset_y = int(round(canvas_h / 2 - (content_rect.y + content_rect.h / 2)))
    else:  # pragma: no cover - defensive
        offset_x = (width - plate_w) // 2
        offset_y = (canvas_h - plate_h) // 2
    body = pygame.Surface((width, canvas_h), pygame.SRCALPHA)
    body.blit(body_plate, (offset_x, offset_y))

    near, near_pivot = _wing_layer(
        wing_master, tuple(pivot), plate_w * TOASTER["wing_w"], flip_h=True
    )
    far, far_pivot = _wing_layer(
        wing_master,
        tuple(pivot),
        plate_w * TOASTER["wing_w"] * TOASTER["far_scale"],
        flip_h=TOASTER["far_flip"],
        tint_mul=TOASTER["far_tint"],
        desat=TOASTER["far_desat"],
    )
    shadow = _shadow_layer(near, TOASTER["shadow_alpha"])
    parts = (
        body,
        near,
        near_pivot,
        shadow,
        far,
        far_pivot,
        (
            TOASTER["near_anchor"][0] * plate_w + offset_x,
            TOASTER["near_anchor"][1] * plate_h + offset_y,
        ),
        (
            TOASTER["far_anchor"][0] * plate_w + offset_x,
            TOASTER["far_anchor"][1] * plate_h + offset_y,
        ),
    )
    _toaster_parts[width] = parts
    return parts


def _compose_toaster(parts: tuple, frame: int) -> pygame.Surface:
    body, near, near_pivot, shadow, far, far_pivot, near_anchor, far_anchor = parts
    width, height = body.get_size()
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    phase = math.sin(frame / WING_FRAMES * math.tau)  # +1 upstroke, -1 downstroke
    flap = TOASTER["amp"] * phase

    # A wingbeat is a rotation about the body's roll axis, so the apparent span
    # changes with the flap: the near wing foreshortens as it lifts away from
    # the viewer and grows as it comes down toward the viewer, while the far
    # wing is most exposed at the top of the upstroke and sinks behind the body
    # on the downstroke (tuck + smaller apparent span).
    near_img, near_piv = _scale_about_pivot(near, near_pivot, 1.0 - TOASTER["near_fore"] * phase)
    far_img, far_piv = _scale_about_pivot(far, far_pivot, 1.0 + TOASTER["far_fore"] * phase)
    plate_w = max(1, int(round(width * TOASTER["body_scale"])))
    plate_h = max(1, int(round(height * TOASTER["body_scale"])))
    tuck = max(0.0, -phase)
    far_target = (
        far_anchor[0] + TOASTER["far_tuck"][0] * plate_w * tuck,
        far_anchor[1] + TOASTER["far_tuck"][1] * plate_h * tuck,
    )

    far_amp = (
        TOASTER["far_amp_up"] if phase >= 0.0 else TOASTER["far_amp_down"]
    )
    far_angle = TOASTER["far_base"] - far_amp * phase
    far_rot, far_rot_pivot = _rotate_about(far_img, far_angle, far_piv)
    _blit_at(surface, far_rot, far_rot_pivot, far_target)
    surface.blit(body, (0, 0))

    offset_x = TOASTER["shadow_offset"][0] * plate_w
    offset_y = TOASTER["shadow_offset"][1] * plate_w
    shadow_rot, shadow_rot_pivot = _rotate_about(shadow, TOASTER["near_base"] + flap, near_piv)
    _blit_at(
        surface,
        shadow_rot,
        shadow_rot_pivot,
        (near_anchor[0] + offset_x, near_anchor[1] + offset_y),
    )
    near_rot, near_rot_pivot = _rotate_about(near_img, TOASTER["near_base"] + flap, near_piv)
    _blit_at(surface, near_rot, near_rot_pivot, near_anchor)
    return surface


# --------------------------------------------------------------------------- #
# Toast layers
# --------------------------------------------------------------------------- #
def _toast_geometry(kind: str) -> dict | None:
    info = _meta().get("toast", {}).get(kind)
    return info if isinstance(info, dict) else None


def _toast_layer_parts(kind: str, width: int) -> tuple | None:
    key = (kind, width)
    if key in _toast_parts:
        return _toast_parts[key]
    info = _toast_geometry(kind)
    wing_master = _load_asset("wing_master")
    pivot = _meta().get("wing", {}).get("pivot")
    body_src = _load_asset(info["body"]) if info else None
    if info is None or body_src is None or wing_master is None or not pivot:
        _toast_parts[key] = None
        return None

    compose_w, compose_h = TOAST["compose_size"]
    scale = width / compose_w
    compose_h = int(round(compose_h * scale))
    center_x, center_y = TOAST["compose_center"]
    bread_center = info["center"]
    offset_x = center_x * scale - bread_center[0] * scale
    offset_y = center_y * scale - bread_center[1] * scale

    body = _scale(body_src, max(1, int(round(body_src.get_width() * scale))))
    bread_w = info["bread_w"] * scale
    wing_w = bread_w * TOAST["wing_w"]
    tilt = float(info.get("tilt_deg", 0.0))

    near, near_pivot = _wing_layer(wing_master, tuple(pivot), wing_w, flip_h=False)
    far, far_pivot = _wing_layer(
        wing_master,
        tuple(pivot),
        wing_w * TOAST["far_scale"],
        flip_h=True,
        tint_mul=TOAST["far_tint"],
        desat=TOAST["far_desat"],
    )
    shadow = _shadow_layer(near, TOAST["shadow_alpha"])
    near_base = TOAST["near_base"] - TOAST["tilt_follow"] * tilt
    far_base = TOAST["far_base"] + TOAST["tilt_follow"] * tilt
    parts = (
        (width, compose_h),
        body,
        (offset_x, offset_y),
        near,
        near_pivot,
        shadow,
        far,
        far_pivot,
        (
            (info["near_anchor"][0] * scale + offset_x),
            (info["near_anchor"][1] * scale + offset_y),
        ),
        (
            (info["far_anchor"][0] * scale + offset_x),
            (info["far_anchor"][1] * scale + offset_y),
        ),
        near_base,
        far_base,
        bread_w,
    )
    _toast_parts[key] = parts
    return parts


def _compose_toast(parts: tuple, frame: int) -> pygame.Surface:
    (
        size,
        body,
        body_pos,
        near,
        near_pivot,
        shadow,
        far,
        far_pivot,
        near_anchor,
        far_anchor,
        near_base,
        far_base,
        bread_w,
    ) = parts
    surface = pygame.Surface(size, pygame.SRCALPHA)
    phase = math.sin(frame / WING_FRAMES * math.tau)  # +1 upstroke, -1 downstroke
    flap = TOAST["amp"] * phase

    near_img, near_piv = _scale_about_pivot(near, near_pivot, 1.0 - TOAST["near_fore"] * phase)
    far_img, far_piv = _scale_about_pivot(far, far_pivot, 1.0 + TOAST["far_fore"] * phase)
    tuck = max(0.0, -phase)
    far_target = (
        far_anchor[0] + TOAST["far_tuck"][0] * bread_w * tuck,
        far_anchor[1] + TOAST["far_tuck"][1] * bread_w * tuck,
    )

    far_rot, far_rot_pivot = _rotate_about(far_img, far_base + flap, far_piv)
    _blit_at(surface, far_rot, far_rot_pivot, far_target)
    surface.blit(body, (int(round(body_pos[0])), int(round(body_pos[1]))))

    offset_x = TOAST["shadow_offset"][0] * bread_w
    offset_y = TOAST["shadow_offset"][1] * bread_w
    shadow_rot, shadow_rot_pivot = _rotate_about(shadow, near_base - flap, near_piv)
    _blit_at(
        surface,
        shadow_rot,
        shadow_rot_pivot,
        (near_anchor[0] + offset_x, near_anchor[1] + offset_y),
    )
    near_rot, near_rot_pivot = _rotate_about(near_img, near_base - flap, near_piv)
    _blit_at(surface, near_rot, near_rot_pivot, near_anchor)
    return surface


# --------------------------------------------------------------------------- #
# Procedural fallbacks (only used when no raster assets exist at all)
# --------------------------------------------------------------------------- #
def _feather(
    surf: pygame.Surface,
    anchor: tuple[float, float],
    angle: float,
    length: float,
    width: float,
    color: tuple[int, int, int],
) -> None:
    ca, sa = math.cos(angle), math.sin(angle)
    px, py = -sa, ca
    tip = (anchor[0] + ca * length, anchor[1] + sa * length)
    mid = (anchor[0] + ca * length * 0.55, anchor[1] + sa * length * 0.55)
    pts = [
        (anchor[0] + px * width * 0.35, anchor[1] + py * width * 0.35),
        (mid[0] + px * width, mid[1] + py * width),
        tip,
        (mid[0] - px * width, mid[1] - py * width),
        (anchor[0] - px * width * 0.35, anchor[1] - py * width * 0.35),
    ]
    pygame.draw.polygon(surf, color, pts)
    rib = mix(color, (255, 255, 255), 0.35)
    pygame.draw.aaline(surf, rib, anchor, tip)


def _wings(
    surf: pygame.Surface, frame: int, anchor_l, anchor_r, length: float, width: float
) -> None:
    flap = math.sin(frame / WING_FRAMES * math.tau)
    cream = (248, 244, 234)
    shade = (214, 204, 184)
    edge = (92, 78, 64)
    specs = (
        (-0.22, 1.00, 1.00, cream),
        (0.00, 0.86, 0.82, shade),
        (0.20, 0.72, 0.70, cream),
    )
    for side, anchor, base in ((-1, anchor_l, math.pi), (1, anchor_r, 0.0)):
        for offset, len_k, wid_k, color in specs:
            angle = base + side * (-flap * 0.85 + offset)
            _feather(surf, anchor, angle, length * len_k * 1.05, width * wid_k * 1.25, edge)
            _feather(surf, anchor, angle, length * len_k, width * wid_k, color)


def _chrome_toaster(frame: int) -> pygame.Surface:
    surf = pygame.Surface(CANVAS, pygame.SRCALPHA)
    rrect(surf, (92, 98, 112), (348, 118, 52, 150), 14)
    rrect(surf, (70, 74, 86), (356, 128, 28, 44), 8)
    rrect(surf, (46, 48, 58), (176, 252, 46, 16), 7)
    rrect(surf, (46, 48, 58), (300, 252, 46, 16), 7)
    rrect(surf, (58, 62, 74), (138, 112, 236, 156), 22)
    rrect(surf, (168, 176, 190), (146, 120, 220, 140), 18)
    rrect(surf, (206, 214, 226), (158, 132, 196, 52), 14)
    rrect(surf, (118, 124, 138), (158, 196, 196, 48), 14)
    pygame.draw.line(surf, (236, 240, 246), (168, 148), (168, 230), 3)
    rrect(surf, (186, 194, 208), (156, 96, 214, 40), 14)
    rrect(surf, (28, 22, 20), (184, 106, 68, 18), 6)
    rrect(surf, (28, 22, 20), (270, 106, 68, 18), 6)
    rrect(surf, (78, 58, 42), (190, 116, 56, 4), 2)
    rrect(surf, (78, 58, 42), (276, 116, 56, 4), 2)
    rrect(surf, (42, 44, 52), (392, 156, 18, 62), 8)
    pygame.draw.circle(surf, (228, 176, 92), (401, 214), 8)
    pygame.draw.circle(surf, (255, 220, 150), (399, 212), 3)
    pygame.draw.circle(surf, (120, 64, 28), (188, 220), 7)
    pygame.draw.circle(surf, (255, 168, 72), (188, 220), 5)
    pygame.draw.circle(surf, (255, 228, 180), (186, 218), 2)
    _wings(surf, frame, (150, 176), (372, 176), 128, 18)
    return surf


def _procedural_toast(kind: str, frame: int) -> pygame.Surface:
    surf = pygame.Surface(TOAST_CANVAS, pygame.SRCALPHA)
    _wings(surf, frame, (78, 210), (262, 210), 86, 13)
    if kind == "dark":
        crust, crumb = (92, 56, 34), (62, 38, 26)
    else:
        crust, crumb = (186, 118, 58), (236, 198, 136)
    rrect(surf, mix(crust, (40, 24, 16), 0.35), (62, 78, 216, 230), 78)
    rrect(surf, crust, (70, 86, 200, 214), 72)
    rrect(surf, crumb, (88, 104, 164, 176), 58)
    rrect(surf, mix(crumb, (255, 255, 255), 0.28), (104, 118, 132, 46), 20)
    if kind == "butter":
        rrect(surf, (214, 168, 64), (118, 156, 104, 64), 10)
        rrect(surf, (252, 220, 120), (126, 164, 88, 40), 8)
        rrect(surf, (255, 244, 200), (134, 172, 72, 14), 6)
    elif kind == "jam":
        pygame.draw.ellipse(surf, (168, 36, 58), (124, 158, 96, 58))
        pygame.draw.ellipse(surf, (214, 80, 96), (140, 168, 48, 22))
        pygame.draw.circle(surf, (255, 220, 210), (156, 176), 4)
    elif kind == "plain":
        pygame.draw.line(surf, mix(crust, crumb, 0.4), (150, 150), (190, 210), 2)
    return surf


def _legacy_toaster(frame: int, width: int) -> pygame.Surface:
    raw = _load_asset(f"toaster_{frame}")
    if raw is None:
        raw = _chrome_toaster(frame)
    height = max(1, int(round(raw.get_height() * width / raw.get_width())))
    return _scale(raw, width, height)


def _legacy_toast(kind: str, frame: int, width: int) -> pygame.Surface:
    raw = _load_asset(f"toast_{kind}_{frame}")
    if raw is None:
        raw = _load_asset(f"toast_{kind}")
    if raw is None:
        raw = _procedural_toast(kind, frame)
    height = max(1, int(round(raw.get_height() * width / raw.get_width())))
    return _scale(raw, width, height)


# --------------------------------------------------------------------------- #
# Public sprite API
# --------------------------------------------------------------------------- #
def toaster(frame: int, width: int, variant: int | None = None) -> pygame.Surface:
    width = max(32, int(width) // 4 * 4)
    frame = int(frame) % WING_FRAMES
    flap_idx = FLAP_CYCLE[frame]
    key = (flap_idx, width)
    hit = _toasters.get(key)
    if hit is not None:
        return hit
    parts = _toaster_layer_parts(width)
    if parts is not None:
        image = _compose_toaster(parts, flap_idx)
    else:
        image = _legacy_toaster(flap_idx, width)
    # Cap cache size to avoid unbounded memory over long sessions.
    if len(_toasters) > 1200:
        _toasters.clear()
        _toaster_parts.clear()
    _toasters[key] = image
    return image


def toast(kind: str, frame: int, width: int) -> pygame.Surface:
    width = max(24, int(width) // 4 * 4)
    safe_kind = kind if kind in ("plain", "butter", "jam", "dark") else "plain"
    frame = int(frame) % WING_FRAMES
    key = (safe_kind, frame, width)
    hit = _toasts.get(key)
    if hit is not None:
        return hit
    parts = _toast_layer_parts(safe_kind, width)
    if parts is not None:
        image = _compose_toast(parts, frame)
    else:
        image = _legacy_toast(safe_kind, frame, width)
    if len(_toasts) > 1200:
        _toasts.clear()
        _toast_parts.clear()
    _toasts[key] = image
    return image


def icon_surface(size: int = 256) -> pygame.Surface:
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    surf.fill((16, 20, 28, 255))
    glow = pygame.Surface((size, size), pygame.SRCALPHA)
    radius = size // 2
    step = max(2, size // 32)
    for r in range(radius, 0, -step):
        alpha = int((1.0 - r / radius) * 45)
        pygame.draw.circle(glow, (210, 225, 255, alpha), (radius, radius), r)
    surf.blit(glow, (0, 0))
    # The reframed sprite has margin around the body, so ask for a slightly
    # larger frame and let the icon crop the wing margins.
    sprite = toaster(0, max(32, int(size * 1.25) // 4 * 4))
    surf.blit(
        sprite,
        ((size - sprite.get_width()) // 2, (size - sprite.get_height()) // 2),
    )
    return surf
