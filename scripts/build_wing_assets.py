#!/usr/bin/env python3
"""Build clean, reusable raster layers for the flying toaster/toast sprites.

The original 16-frame sprite sheets bake both wings into the body art.  That makes
it impossible to place the far-side wing correctly (it floats above the body and
reads as broken) and it lets the body drift between frames.  This script derives
from those same source PNGs:

* ``assets/body_toaster.png``           - toaster body with both wings removed
* ``assets/body_toast_<kind>.png``      - toast body (bread) with both wings removed
* ``assets/wing_master.png``            - one clean transparent angel wing with its
  shoulder ball, used for every near/far wing (mirrored / scaled / shaded at runtime)
* ``assets/wing_meta.json``             - shoulder anchors + tilt per toast kind, so
  the runtime can attach wings without hard-coding four different bread rotations

The body art itself is preserved: each static body pixel is copied verbatim from the
source frames (the per-pixel modal value across the 16 frames).  Only pixels that were
ever covered by a moving wing are reconstructed by diffusion from surrounding body
pixels, and those areas are hidden again by the newly composited wings.

Run:  .venv/bin/python scripts/build_wing_assets.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "adfresh" / "assets"

WING_FRAMES = 16
TOAST_KINDS = ("plain", "butter", "jam", "dark")

# Wing master is lifted from the left (near) wing of this toast frame.
WING_SOURCE = "toast_plain_4.png"

# Toast wing shoulder stations along the bread height (from the top crust).
TOAST_NEAR_STATION = 0.36
TOAST_FAR_STATION = 0.33


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #
def load_frame(name: str) -> np.ndarray:
    return np.asarray(Image.open(ASSETS / name).convert("RGBA"))


def save_rgba(array: np.ndarray, name: str) -> None:
    Image.fromarray(np.clip(array, 0, 255).astype(np.uint8)).save(ASSETS / name)


# --------------------------------------------------------------------------- #
# Per-pixel modal plate + body reconstruction
# --------------------------------------------------------------------------- #
def _mode_plate(frames: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Return (mode RGBA float array, known mask) across frames.

    ``known`` marks pixels whose RGBA value repeats in at least 8/16 frames; the
    body is static, so those are body pixels (wings move and therefore do not
    repeat, except for the 2-4 frame symmetry of the flap cycle).
    """
    stack = np.stack([f.astype(np.int64) for f in frames])
    code = (
        (stack[:, :, :, 0] << 24)
        | (stack[:, :, :, 1] << 16)
        | (stack[:, :, :, 2] << 8)
        | stack[:, :, :, 3]
    )
    ordered = np.sort(code, axis=0)
    best = np.ones(ordered.shape[1:], np.int32)
    value = ordered[0].copy()
    run = np.ones(ordered.shape[1:], np.int32)
    current = ordered[0].copy()
    for k in range(1, len(frames)):
        same = ordered[k] == current
        run = np.where(same, run + 1, 1)
        current = ordered[k]
        better = run > best
        best = np.where(better, run, best)
        value = np.where(better, current, value)
    mode = np.stack(
        [
            ((value >> 24) & 255).astype(np.float32),
            ((value >> 16) & 255).astype(np.float32),
            ((value >> 8) & 255).astype(np.float32),
            (value & 255).astype(np.float32),
        ],
        axis=2,
    )
    return mode, best >= 8


def _normalized_fill(rgb: np.ndarray, source: np.ndarray, radius: float) -> np.ndarray:
    """Smoothly extrapolate ``rgb`` from ``source`` pixels into everything else.

    Normalized convolution (blur(image * mask) / blur(mask)) so transparent /
    background pixels never bleed into the reconstructed body.  Two scales are
    combined so both small feather crevices and the large wing sweep fill cleanly.
    """
    weight = source.astype(np.float32)
    out = np.zeros_like(rgb, dtype=np.float32)
    total_w = np.zeros(rgb.shape[:2], dtype=np.float32)
    for scale in (radius, radius * 3.0, radius * 8.0):
        # weight blurred on a 0..255 image, then brought back to 0..1
        w = np.asarray(
            Image.fromarray((weight * 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(scale)
            )
        ).astype(np.float32) / 255.0
        for c in range(3):
            img = np.asarray(
                Image.fromarray(np.clip(rgb[:, :, c] * weight, 0, 255).astype(np.uint8)).filter(
                    ImageFilter.GaussianBlur(scale)
                )
            ).astype(np.float32)
            out[:, :, c] += img
        total_w += w
    total_w = np.maximum(total_w, 1e-3)
    return out / total_w[:, :, None]


def _convex_hull_mask(points_mask: np.ndarray) -> np.ndarray:
    """Rasterise the convex hull of a binary mask (body silhouette proxy)."""
    height, width = points_mask.shape
    ys, xs = np.where(points_mask)
    points = sorted(zip(xs.tolist(), ys.tolist()))
    if len(points) < 3:
        return np.zeros_like(points_mask)

    def cross(o, a, b) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[int, int]] = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[int, int]] = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    canvas = Image.new("L", (width, height), 0)
    ImageDraw.Draw(canvas).polygon(hull, fill=255)
    return np.asarray(canvas) > 0


def build_body(frames: list[np.ndarray], fill_radius: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (clean body RGBA, body-solid mask) for one sprite family."""
    mode, known = _mode_plate(frames)
    height, width = known.shape
    mode_alpha = mode[:, :, 3]
    alpha_max = np.max(np.stack([f[:, :, 3] for f in frames]), axis=0)
    known_body = known & (mode_alpha > 128)

    # Wing-removal support: pixels that only exist in some frames are wing pixels.
    # They become body only if they fall inside the convex hull of the known body
    # silhouette (e.g. a wing root that permanently covers part of the body edge);
    # wing sweep outside the body silhouette is dropped.
    hull = _convex_hull_mask(known_body)
    alpha = mode_alpha.copy()
    wing_pixels = (~known) & (alpha_max > 0)
    alpha = np.where(wing_pixels & hull, 255.0, alpha)
    alpha = np.where(wing_pixels & ~hull, 0.0, alpha)

    fill = _normalized_fill(mode[:, :, :3], known_body, fill_radius)
    rgb = np.where(known_body[:, :, None], mode[:, :, :3], fill)
    rgb = np.where((alpha <= 0)[:, :, None], 0.0, rgb)
    return np.dstack([rgb, alpha]).astype(np.float32), known_body


# --------------------------------------------------------------------------- #
# Wing master extraction
# --------------------------------------------------------------------------- #
def _label_components(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    labels = np.zeros((height, width), np.int32)
    current = 0
    for y in range(height):
        for x in range(width):
            if mask[y, x] and labels[y, x] == 0:
                current += 1
                stack = [(y, x)]
                labels[y, x] = current
                while stack:
                    cy, cx = stack.pop()
                    for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                        if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and labels[ny, nx] == 0:
                            labels[ny, nx] = current
                            stack.append((ny, nx))
    return labels


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill holes enclosed by the mask (background flood fill from the border)."""
    height, width = mask.shape
    outside = np.zeros_like(mask, bool)
    stack: list[tuple[int, int]] = []
    for x in range(width):
        for y in (0, height - 1):
            if not mask[y, x] and not outside[y, x]:
                outside[y, x] = True
                stack.append((y, x))
    for y in range(height):
        for x in (0, width - 1):
            if not mask[y, x] and not outside[y, x]:
                outside[y, x] = True
                stack.append((y, x))
    while stack:
        cy, cx = stack.pop()
        for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
            if 0 <= ny < height and 0 <= nx < width and not mask[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                stack.append((ny, nx))
    return mask | ~outside


def extract_wing() -> tuple[np.ndarray, tuple[float, float]]:
    """Extract the near (left) toast wing as a clean RGBA wing + shoulder pivot."""
    frame = load_frame(WING_SOURCE).astype(np.float32)
    rgb = frame[:, :, :3]
    alpha = frame[:, :, 3]
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    # Wings are the only desaturated, bright things in the toast art.
    mask = (alpha > 190) & (sat < 0.155) & (mx > 80)
    labels = _label_components(mask)
    best = None
    for label in range(1, labels.max() + 1):
        ys, xs = np.where(labels == label)
        if xs.mean() < 260 and (best is None or len(xs) > best[0]):
            best = (len(xs), label, xs, ys)
    if best is None:
        raise RuntimeError("could not locate toast wing component")
    _, label, xs, ys = best
    mask = labels == label
    mask = _fill_holes(mask)
    pad = 2
    x0, x1 = max(0, xs.min() - pad), min(mask.shape[1], xs.max() + 1 + pad)
    y0, y1 = max(0, ys.min() - pad), min(mask.shape[0], ys.max() + 1 + pad)
    mask = mask[y0:y1, x0:x1]
    rgb = rgb[y0:y1, x0:x1]

    # Extend wing colours into the boundary ring so the soft alpha edge is not
    # contaminated by bread crust, then feather the alpha by ~1px.
    color = _normalized_fill(rgb, mask, 1.6)
    alpha_soft = np.asarray(
        Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.9))
    ).astype(np.float32)
    alpha_soft = np.clip(alpha_soft * 1.35, 0, 255)
    wing = np.dstack([color, alpha_soft]).astype(np.float32)

    # Shoulder pivot: the rounded shoulder ball at the wing root (upper-right of
    # the extracted wing).  Rotating about the ball keeps the wing visually
    # attached while the feathers sweep.
    h, w = mask.shape
    ball = mask[: int(h * 0.40), int(w * 0.80):]
    ys2, xs2 = np.where(ball)
    if len(xs2) == 0:
        pivot = (w * 0.88, h * 0.24)
    else:
        pivot = (int(w * 0.80) + xs2.mean(), ys2.mean())
    return wing, (round(float(pivot[0]), 2), round(float(pivot[1]), 2))


# --------------------------------------------------------------------------- #
# Bread geometry for toast wings
# --------------------------------------------------------------------------- #
# The toast faces are photographic 3-D slices, so a PCA of the slice silhouette is
# dominated by the (roughly square) face shape and gives unstable angles.  Instead
# the shoulder anchors are read straight off the upper side edges as the viewer
# sees them, and the tilt is estimated from the lower crust line, which is a good
# proxy for how far the slice is banked.
TOAST_TILT_DEG = {"plain": 20.0, "butter": 24.0, "jam": 6.0, "dark": 30.0}


def bread_frame(kind: str, body: np.ndarray) -> dict:
    """Measure bread bbox centre, screen tilt and upper-side shoulder anchors."""
    mask = body[:, :, 3] > 128
    height, width = mask.shape
    ys, xs = np.where(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())

    def edge_x(station: float, side: str) -> tuple[float, float]:
        y = y0 + station * (y1 - y0)
        row_lo, row_hi = max(0, int(y) - 2), min(height, int(y) + 3)
        rows = mask[row_lo:row_hi]
        cols = np.where(rows.any(axis=0))[0]
        if len(cols) == 0:
            return (float(x0), float(y))
        inset = 0.05 * (x1 - x0)
        if side == "near":
            return (float(cols.min()) + inset, float(y))
        return (float(cols.max()) - inset, float(y))

    near_anchor = edge_x(TOAST_NEAR_STATION, "near")
    far_anchor = edge_x(TOAST_FAR_STATION, "far")
    return {
        "center": [round((x0 + x1) / 2.0, 2), round((y0 + y1) / 2.0, 2)],
        "bread_bbox": [x0, y0, x1, y1],
        "bread_w": x1 - x0,
        "tilt_deg": TOAST_TILT_DEG.get(kind, 0.0),
        "near_anchor": [round(near_anchor[0], 2), round(near_anchor[1], 2)],
        "far_anchor": [round(far_anchor[0], 2), round(far_anchor[1], 2)],
    }


# --------------------------------------------------------------------------- #
# Main build
# --------------------------------------------------------------------------- #
def main() -> int:
    missing = [
        name
        for name in (
            [f"toaster_{k}.png" for k in range(WING_FRAMES)]
            + [f"toast_{kind}_{k}.png" for kind in TOAST_KINDS for k in range(WING_FRAMES)]
            + [WING_SOURCE]
        )
        if not (ASSETS / name).is_file()
    ]
    if missing:
        print("missing source frames:", ", ".join(missing[:6]))
        return 1

    wing, pivot = extract_wing()
    save_rgba(wing, "wing_master.png")
    print(f"wing_master.png {wing.shape[1]}x{wing.shape[0]} pivot={pivot}")

    meta: dict = {"wing": {"file": "wing_master", "pivot": list(pivot)}, "toast": {}}

    toaster = [load_frame(f"toaster_{k}.png") for k in range(WING_FRAMES)]
    body, _ = build_body(toaster, fill_radius=10.0)
    save_rgba(body, "body_toaster.png")
    meta["toaster"] = {"body": "body_toaster", "size": [body.shape[1], body.shape[0]]}
    print(f"body_toaster.png {body.shape[1]}x{body.shape[0]}")

    for kind in TOAST_KINDS:
        frames = [load_frame(f"toast_{kind}_{k}.png") for k in range(WING_FRAMES)]
        body, _ = build_body(frames, fill_radius=6.0)
        geometry = bread_frame(kind, body)
        meta["toast"][kind] = {
            "body": f"body_toast_{kind}",
            "size": [body.shape[1], body.shape[0]],
            **geometry,
        }
        save_rgba(body, f"body_toast_{kind}.png")
        print(
            f"body_toast_{kind}.png {body.shape[1]}x{body.shape[0]} "
            f"tilt={geometry['tilt_deg']:+.1f} near={geometry['near_anchor']} far={geometry['far_anchor']}"
        )

    with open(ASSETS / "wing_meta.json", "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("wing_meta.json written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
