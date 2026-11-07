#!/usr/bin/env python3
"""Export the flying-toaster and toast sprite maps.

Usage:
    .venv/bin/python scripts/export_sprites.py [OUTPUT_DIR]
        [--toast-kind KIND]... [--all-toasts]

The toaster map and the plain toast map are exported by default. Pass
``--toast-kind`` (repeatable) for other toppings, or ``--all-toasts`` for all
four. The default output directory is ``build/sprites/``.

Writes transparent atlas PNGs, labeled preview PNGs, JSON frame maps, and a
README.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The exporter renders offscreen only; no display or audio device needed.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from adfresh.export import (  # noqa: E402
    DEFAULT_TOAST_KINDS,
    TOAST_KINDS,
    export_all,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        default=str(ROOT / "build" / "sprites"),
        help="output directory (default: build/sprites)",
    )
    parser.add_argument(
        "--toast-kind",
        action="append",
        choices=TOAST_KINDS,
        help="also export this toast topping (repeatable)",
    )
    parser.add_argument(
        "--all-toasts",
        action="store_true",
        help="export every toast topping (plain, butter, jam, dark)",
    )
    args = parser.parse_args(argv[1:])

    if args.all_toasts:
        kinds = TOAST_KINDS
    elif args.toast_kind:
        kinds = tuple(args.toast_kind)
    else:
        kinds = DEFAULT_TOAST_KINDS

    for path in export_all(Path(args.output), toast_kinds=kinds):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
