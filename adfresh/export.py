"""Export the composed flying-toaster sprites as reusable sprite maps.

The screensaver composes each toaster (and toast) at runtime from a body plate
plus two wing layers.  This module flattens the composed frames into a texture
atlas so the art can be reused outside pygame: a transparent PNG sheet, a
labeled preview, and a JSON map with frame rectangles, shoulder anchors,
wing pivots and the per-frame flap parameters.

Toasters use one map (all 16 flap frames).  Toast has four toppings, so each
topping gets its own map; ``plain`` is exported by default, the others are
available with ``--toast-kind`` / ``--all-toasts`` on the export script.

Run ``scripts/export_sprites.py`` (or call :func:`export_all`) to regenerate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pygame

from adfresh import sprites

TOASTER_COLUMNS = 4
TOASTER_WIDTH = 600  # native body-plate width; module renders 72-245 px wide

TOAST_COLUMNS = 4
TOAST_WIDTH = 600  # native toast canvas is 600x500; module renders 56-198 px

TOAST_KINDS = ("plain", "butter", "jam", "dark")
DEFAULT_TOAST_KINDS = ("plain",)

PREVIEW_BG = (10, 12, 18)
PREVIEW_LABEL = (226, 226, 232)
PREVIEW_ACCENT = (255, 196, 110)
PREVIEW_MARGIN = 28
PREVIEW_HEADER = 64


def _pygame() -> None:
    if not pygame.display.get_init():
        pygame.display.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((1, 1))
    if not pygame.font.get_init():
        pygame.font.init()


def _label(text: str, size: int = 20) -> pygame.Surface:
    face = pygame.font.Font(
        "/usr/share/fonts/truetype/noto/NotoSans-Medium.ttf", size
    )
    return face.render(text, True, PREVIEW_LABEL)


def _title(text: str, size: int = 32) -> pygame.Surface:
    face = pygame.font.Font(
        "/usr/share/fonts/truetype/noto/NotoSans-Medium.ttf", size
    )
    return face.render(text, True, PREVIEW_ACCENT)


def _blit_label(
    surface: pygame.Surface, text: str, pos: tuple[int, int], size: int = 20
) -> None:
    surface.blit(_label(text, size), pos)


# --------------------------------------------------------------------------- #
# Frame metadata
# --------------------------------------------------------------------------- #
def _phase(frame: int) -> float:
    return math.sin(frame / sprites.WING_FRAMES * math.tau)


def _toaster_frame_meta(width: int, frame: int) -> dict:
    parts = sprites._toaster_layer_parts(width)
    if parts is None:  # pragma: no cover - asset-less fallback
        raise RuntimeError("toaster layer assets are missing")
    body, near, near_pivot, _shadow, far, far_pivot, near_anchor, far_anchor = parts
    body_w, body_h = body.get_size()
    source = sprites._load_asset("body_toaster")
    source_w, source_h = source.get_size()
    plate_w = max(1, int(round(width * sprites.TOASTER["body_scale"])))
    plate_h = max(1, int(round(plate_w * source_h / source_w)))
    phase = _phase(frame)
    flap = sprites.TOASTER["amp"] * phase
    near_scale = 1.0 - sprites.TOASTER["near_fore"] * phase
    far_scale = 1.0 + sprites.TOASTER["far_fore"] * phase
    tuck = max(0.0, -phase)
    far_target = (
        far_anchor[0] + sprites.TOASTER["far_tuck"][0] * plate_w * tuck,
        far_anchor[1] + sprites.TOASTER["far_tuck"][1] * plate_h * tuck,
    )
    return {
        "index": frame,
        "phase": round(phase, 6),
        "flap_deg": round(flap, 4),
        "near": {
            "angle_deg": round(sprites.TOASTER["near_base"] + flap, 4),
            "scale": round(near_scale, 6),
            "anchor": [round(v, 4) for v in near_anchor],
            "pivot": [
                round(near_pivot[0] * near_scale, 4),
                round(near_pivot[1] * near_scale, 4),
            ],
            "layer_size": [
                max(2, int(round(near.get_width() * near_scale))),
                max(2, int(round(near.get_height() * near_scale))),
            ],
        },
        "far": {
            "angle_deg": round(
                sprites.TOASTER["far_base"]
                - (
                    sprites.TOASTER["far_amp_up"]
                    if phase >= 0.0
                    else sprites.TOASTER["far_amp_down"]
                )
                * phase,
                4,
            ),
            "scale": round(far_scale, 6),
            "anchor": [round(v, 4) for v in far_target],
            "tuck": round(tuck, 6),
            "pivot": [
                round(far_pivot[0] * far_scale, 4),
                round(far_pivot[1] * far_scale, 4),
            ],
            "layer_size": [
                max(2, int(round(far.get_width() * far_scale))),
                max(2, int(round(far.get_height() * far_scale))),
            ],
        },
    }


def _toast_frame_meta(kind: str, width: int, frame: int) -> dict:
    parts = sprites._toast_layer_parts(kind, width)
    if parts is None:  # pragma: no cover - asset-less fallback
        raise RuntimeError("toast layer assets are missing")
    (
        _size,
        _body,
        _body_pos,
        near,
        near_pivot,
        _shadow,
        far,
        far_pivot,
        near_anchor,
        far_anchor,
        near_base,
        far_base,
        bread_w,
    ) = parts
    phase = _phase(frame)
    flap = sprites.TOAST["amp"] * phase
    near_scale = 1.0 - sprites.TOAST["near_fore"] * phase
    far_scale = 1.0 + sprites.TOAST["far_fore"] * phase
    tuck = max(0.0, -phase)
    far_target = (
        far_anchor[0] + sprites.TOAST["far_tuck"][0] * bread_w * tuck,
        far_anchor[1] + sprites.TOAST["far_tuck"][1] * bread_w * tuck,
    )
    return {
        "kind": kind,
        "index": frame,
        "phase": round(phase, 6),
        "flap_deg": round(flap, 4),
        "near": {
            "angle_deg": round(near_base - flap, 4),
            "scale": round(near_scale, 6),
            "anchor": [round(v, 4) for v in near_anchor],
            "pivot": [
                round(near_pivot[0] * near_scale, 4),
                round(near_pivot[1] * near_scale, 4),
            ],
            "layer_size": [
                max(2, int(round(near.get_width() * near_scale))),
                max(2, int(round(near.get_height() * near_scale))),
            ],
        },
        "far": {
            "angle_deg": round(far_base + flap, 4),
            "scale": round(far_scale, 6),
            "anchor": [round(v, 4) for v in far_target],
            "tuck": round(tuck, 6),
            "pivot": [
                round(far_pivot[0] * far_scale, 4),
                round(far_pivot[1] * far_scale, 4),
            ],
            "layer_size": [
                max(2, int(round(far.get_width() * far_scale))),
                max(2, int(round(far.get_height() * far_scale))),
            ],
        },
    }


# --------------------------------------------------------------------------- #
# Atlas helpers
# --------------------------------------------------------------------------- #
def _grid(
    frames: list[pygame.Surface], columns: int, rows: int
) -> tuple[pygame.Surface, list[tuple[int, int, int, int]]]:
    cell_w, cell_h = frames[0].get_size()
    atlas = pygame.Surface((columns * cell_w, rows * cell_h), pygame.SRCALPHA)
    rects: list[tuple[int, int, int, int]] = []
    for index, frame in enumerate(frames):
        column = index % columns
        row = index // columns
        rect = (column * cell_w, row * cell_h, cell_w, cell_h)
        atlas.blit(frame, (rect[0], rect[1]))
        rects.append(rect)
    return atlas, rects


def _atlas_preview(
    title: str,
    subtitle: str,
    frames: list[pygame.Surface],
    labels: list[str],
    columns: int,
) -> pygame.Surface:
    cell_w, cell_h = frames[0].get_size()
    rows = math.ceil(len(frames) / columns)
    width = columns * cell_w + 2 * PREVIEW_MARGIN
    height = rows * (cell_h + PREVIEW_MARGIN) + 2 * PREVIEW_MARGIN + PREVIEW_HEADER
    preview = pygame.Surface((width, height))
    preview.fill(PREVIEW_BG)
    preview.blit(_title(title), (PREVIEW_MARGIN, PREVIEW_MARGIN // 2))
    preview.blit(_label(subtitle, 18), (PREVIEW_MARGIN, PREVIEW_MARGIN // 2 + 38))
    for index, (frame, label) in enumerate(zip(frames, labels)):
        column = index % columns
        row = index // columns
        x = PREVIEW_MARGIN + column * cell_w
        y = PREVIEW_MARGIN + PREVIEW_HEADER + row * (cell_h + PREVIEW_MARGIN)
        pygame.draw.rect(
            preview, (22, 25, 34), (x - 6, y - 6, cell_w + 12, cell_h + 12), 1
        )
        preview.blit(frame, (x, y))
        _blit_label(preview, label, (x + 2, y + cell_h + 2), 19)
    return preview


def _pose_labels(frame_count: int) -> list[str]:
    labels = []
    for frame in range(frame_count):
        phase = _phase(frame)
        if frame == frame_count // 4:
            labels.append(f"f{frame:02d} upstroke peak")
        elif frame == 3 * frame_count // 4:
            labels.append(f"f{frame:02d} downstroke peak")
        elif abs(phase) < 0.01:
            labels.append(f"f{frame:02d} level")
        elif phase > 0:
            labels.append(f"f{frame:02d} upstroke")
        else:
            labels.append(f"f{frame:02d} downstroke")
    return labels


# --------------------------------------------------------------------------- #
# Public export API
# --------------------------------------------------------------------------- #
def export_toaster_atlas(
    directory: Path,
    *,
    width: int = TOASTER_WIDTH,
    columns: int = TOASTER_COLUMNS,
) -> dict:
    """Write the toaster atlas, preview and JSON map into ``directory``."""
    _pygame()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    frame_count = sprites.WING_FRAMES
    rows = math.ceil(frame_count / columns)
    frames = [sprites.toaster(frame, width) for frame in range(frame_count)]
    atlas, rects = _grid(frames, columns, rows)
    preview = _atlas_preview(
        "AD Fresh - Flying Toaster sprite map",
        f"{frame_count} flap frames, {columns} columns, row-major. "
        "Cells are transparent in the atlas.",
        frames,
        _pose_labels(frame_count),
        columns,
    )

    atlas_path = directory / "toaster-sprite-map.png"
    preview_path = directory / "toaster-sprite-map-preview.png"
    json_path = directory / "toaster-sprite-map.json"
    pygame.image.save(atlas, atlas_path)
    pygame.image.save(preview, preview_path)

    parts = sprites._toaster_layer_parts(width)
    body, _near, _near_pivot, _shadow, _far, _far_pivot, near_anchor, far_anchor = parts
    body_w, body_h = body.get_size()
    wing = sprites._meta()["wing"]
    wing_surface = sprites._load_asset("wing_master")
    metadata = {
        "name": "AD Fresh flying toaster sprite map",
        "version": 1,
        "generator": "adfresh.export.export_toaster_atlas",
        "source_project": "AD Fresh (original art)",
        "atlas": {
            "image": atlas_path.name,
            "preview": preview_path.name,
            "columns": columns,
            "rows": rows,
            "frame_count": frame_count,
            "frame_size": [body_w, body_h],
            "layout": "row-major, left-to-right, top-to-bottom",
            "transparent_background": True,
        },
        "animation": {
            "frames": frame_count,
            "flap_phase": "sin(2 * pi * frame / 16)",
            "upstroke_peak_frame": frame_count // 4,
            "downstroke_peak_frame": 3 * frame_count // 4,
            "level_frames": [0, frame_count // 2],
            "drawn_centered_on": "body center",
            "note": (
                "The screensaver plays these frames at 2.2-3.5 wingbeats per "
                "second depending on the flyer's depth plane."
            ),
        },
        "render_order": [
            "far wing (mirrored, scaled, tinted, behind body)",
            "body plate",
            "near-wing shadow",
            "near wing (in front)",
        ],
        "sources": {
            "body": "adfresh/assets/body_toaster.png",
            "wing": f"adfresh/assets/{wing['file']}.png",
            "wing_pivot": [round(v, 4) for v in wing["pivot"]],
            "wing_size": [wing_surface.get_width(), wing_surface.get_height()],
        },
        "anchors": {
            "near_shoulder": [round(v, 4) for v in near_anchor],
            "far_shoulder_base": [round(v, 4) for v in far_anchor],
            "note": (
                "Anchors are pixel positions in the frame; the far shoulder "
                "moves toward the body on the downstroke (see per-frame tuck)."
            ),
        },
        "parameters": {**sprites.TOASTER},
        "frames": [],
    }
    for frame, rect in enumerate(rects):
        info = _toaster_frame_meta(width, frame)
        info["rect"] = list(rect)
        metadata["frames"].append(info)
    json_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {
        "atlas": atlas_path,
        "preview": preview_path,
        "metadata": json_path,
        "frame_count": frame_count,
        "frame_size": [body_w, body_h],
    }


def export_toast_kind_atlas(
    directory: Path,
    kind: str,
    *,
    width: int = TOAST_WIDTH,
    columns: int = TOAST_COLUMNS,
) -> dict:
    """Write one toast topping's atlas, preview and JSON map."""
    if kind not in TOAST_KINDS:
        raise ValueError(f"unknown toast kind {kind!r}; expected one of {TOAST_KINDS}")
    _pygame()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    frame_count = sprites.WING_FRAMES
    rows = math.ceil(frame_count / columns)
    frames = [sprites.toast(kind, frame, width) for frame in range(frame_count)]
    atlas, rects = _grid(frames, columns, rows)
    preview = _atlas_preview(
        f"AD Fresh - {kind.capitalize()} flying toast sprite map",
        f"{frame_count} flap frames, {columns} columns, row-major. "
        "Cells are transparent in the atlas.",
        frames,
        _pose_labels(frame_count),
        columns,
    )

    stem = f"toast-{kind}-sprite-map"
    atlas_path = directory / f"{stem}.png"
    preview_path = directory / f"{stem}-preview.png"
    json_path = directory / f"{stem}.json"
    pygame.image.save(atlas, atlas_path)
    pygame.image.save(preview, preview_path)

    parts = sprites._toast_layer_parts(kind, width)
    if parts is None:  # pragma: no cover - asset-less fallback
        raise RuntimeError("toast layer assets are missing")
    (
        _size,
        _body,
        _body_pos,
        _near,
        _near_pivot,
        _shadow,
        _far,
        _far_pivot,
        near_anchor,
        far_anchor,
        near_base,
        far_base,
        bread_w,
    ) = parts
    cell_w, cell_h = frames[0].get_size()
    info = sprites._toast_geometry(kind) or {}
    wing = sprites._meta()["wing"]
    wing_surface = sprites._load_asset("wing_master")
    metadata = {
        "name": f"AD Fresh flying toast sprite map ({kind})",
        "version": 1,
        "generator": "adfresh.export.export_toast_kind_atlas",
        "source_project": "AD Fresh (original art)",
        "kind": kind,
        "atlas": {
            "image": atlas_path.name,
            "preview": preview_path.name,
            "columns": columns,
            "rows": rows,
            "frame_count": frame_count,
            "frame_size": [cell_w, cell_h],
            "layout": "row-major, left-to-right, top-to-bottom",
            "transparent_background": True,
        },
        "animation": {
            "frames": frame_count,
            "flap_phase": "sin(2 * pi * frame / 16)",
            "upstroke_peak_frame": frame_count // 4,
            "downstroke_peak_frame": 3 * frame_count // 4,
            "level_frames": [0, frame_count // 2],
            "drawn_centered_on": "compose center (300, 250) at 600x500 canvas scale",
            "note": (
                "The screensaver plays these frames at 2.2-3.5 wingbeats per "
                "second depending on the flyer's depth plane."
            ),
        },
        "render_order": [
            "far wing (mirrored, scaled, tinted, behind toast)",
            "toast plate",
            "near-wing shadow",
            "near wing (in front)",
        ],
        "sources": {
            "body": f"adfresh/assets/body_toast_{kind}.png",
            "wing": f"adfresh/assets/{wing['file']}.png",
            "wing_pivot": [round(v, 4) for v in wing["pivot"]],
            "wing_size": [wing_surface.get_width(), wing_surface.get_height()],
            "wing_meta": "adfresh/assets/wing_meta.json",
        },
        "kind_geometry": {
            "tilt_deg": info.get("tilt_deg"),
            "bread_width": info.get("bread_w"),
            "near_anchor": [round(v, 4) for v in near_anchor],
            "far_anchor_base": [round(v, 4) for v in far_anchor],
            "near_base_deg": round(near_base, 4),
            "far_base_deg": round(far_base, 4),
        },
        "parameters": {**sprites.TOAST},
        "frames": [],
    }
    for frame, rect in enumerate(rects):
        info = _toast_frame_meta(kind, width, frame)
        info["rect"] = list(rect)
        metadata["frames"].append(info)
    json_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {
        "atlas": atlas_path,
        "preview": preview_path,
        "metadata": json_path,
        "kind": kind,
        "frame_count": frame_count,
        "frame_size": [cell_w, cell_h],
    }


def export_all(
    directory: Path,
    *,
    toast_kinds: tuple[str, ...] | list[str] = DEFAULT_TOAST_KINDS,
) -> list[Path]:
    """Export the sprite maps into ``directory``; returns the written files.

    Toasters get one map. Toast gets one map per topping; ``plain`` is exported
    by default, pass more kinds (or all of :data:`TOAST_KINDS`) to add them.
    """
    _pygame()
    directory = Path(directory)
    kinds = []
    for kind in toast_kinds:
        if kind not in TOAST_KINDS:
            raise ValueError(f"unknown toast kind {kind!r}")
        if kind not in kinds:
            kinds.append(kind)
    toaster = export_toaster_atlas(directory)
    toasts = [export_toast_kind_atlas(directory, kind) for kind in kinds]
    readme = directory / "README.md"
    readme.write_text(_readme_text(toaster, toasts), encoding="utf-8")
    paths: list[Path] = [toaster["atlas"], toaster["preview"], toaster["metadata"]]
    for toast in toasts:
        paths.extend([toast["atlas"], toast["preview"], toast["metadata"]])
    paths.append(readme)
    return paths


def _readme_text(toaster: dict, toasts: list[dict]) -> str:
    tw, th = toaster["frame_size"]
    toast_lines = []
    for toast in toasts:
        kind = toast["kind"]
        cell_w, cell_h = toast["frame_size"]
        toast_lines.append(
            f"- `toast-{kind}-sprite-map.png` - transparent atlas, "
            f"{toast['frame_count']} flap frames, 4 columns x 4 rows, "
            f"{cell_w}x{cell_h} px cells, row-major."
        )
        toast_lines.append(
            f"- `toast-{kind}-sprite-map-preview.png` / "
            f"`toast-{kind}-sprite-map.json` - labeled preview and frame map."
        )
    missing = [kind for kind in TOAST_KINDS if kind not in {t["kind"] for t in toasts}]
    extra = ""
    if missing:
        extra = (
            "\nExport the remaining toast toppings with:\n\n"
            "```bash\n.venv/bin/python scripts/export_sprites.py --all-toasts\n"
            "```\n\nMissing right now: "
            + ", ".join(missing)
            + "\n"
        )
    return f"""# AD Fresh sprite maps

Generated by `scripts/export_sprites.py`; do not edit by hand.

## Flying Toasters (`toaster-sprite-map.*`)

- `toaster-sprite-map.png` - transparent atlas, {toaster['frame_count']} flap
  frames, 4 columns x 4 rows, each cell {tw}x{th} px, row-major.
- `toaster-sprite-map-preview.png` - the same frames on a dark background with
  frame numbers and pose labels.
- `toaster-sprite-map.json` - frame rectangles, near/far shoulder anchors, wing
  pivots, per-frame flap angles and foreshortening scales.

Each frame is the complete composed flyer (far wing behind the body, body, near
wing in front) centered on the body center. The screensaver blits it centered
on the flyer's screen position; the frames play in order at 2.2-3.5 beats per
second depending on depth.

## Flying Toast

One map per topping (16 frames each, 4 columns x 4 rows):

{chr(10).join(toast_lines) if toast_lines else '- none exported yet'}
{extra}
## Regenerate

```bash
.venv/bin/python scripts/export_sprites.py                    # toaster + plain toast
.venv/bin/python scripts/export_sprites.py --all-toasts       # every topping
.venv/bin/python scripts/export_sprites.py --toast-kind butter --toast-kind jam
.venv/bin/python scripts/export_sprites.py /tmp/maps          # custom directory
```
"""


if __name__ == "__main__":  # pragma: no cover
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build") / "sprites"
    for written in export_all(target):
        print(written)
