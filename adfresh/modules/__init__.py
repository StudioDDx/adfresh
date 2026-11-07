"""Module catalog. Order is the manual cycle order."""

from __future__ import annotations

from adfresh.modules.aquatic import Aquatic
from adfresh.modules.clock import Clock
from adfresh.modules.fringe import Fringe
from adfresh.modules.marbles import Marbles
from adfresh.modules.messages import Messages
from adfresh.modules.mountains import Mountains
from adfresh.modules.pipes import Pipes
from adfresh.modules.rain import Rain
from adfresh.modules.satori import Satori
from adfresh.modules.starry import Starry
from adfresh.modules.toasters import Toasters
from adfresh.modules.warp import Warp

CATALOG = [
    Toasters,
    Starry,
    Aquatic,
    Rain,
    Pipes,
    Warp,
    Marbles,
    Mountains,
    Fringe,
    Clock,
    Messages,
    Satori,
]

BY_ID = {cls.id: cls for cls in CATALOG}


def resolve(name: str):
    key = name.lower().strip()
    if key in BY_ID:
        return BY_ID[key]
    for cls in CATALOG:
        if cls.title.lower() == key or cls.id.startswith(key) or cls.title.lower().startswith(key):
            return cls
    known = ", ".join(cls.id for cls in CATALOG)
    raise SystemExit(f"unknown module {name!r}. Modules: {known}")
