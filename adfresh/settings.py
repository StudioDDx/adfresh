"""Saved screensaver settings and the hypridle hook they drive."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from adfresh.runtime import desktop_environment, log

HYPRIDLE = Path.home() / ".config" / "hypr" / "hypridle.conf"
QUICK_SETTINGS = Path.home() / ".config" / "hypr" / "scripts" / "Kool_Quick_Settings.sh"
BEGIN = "# BEGIN AD FRESH"
END = "# END AD FRESH"
MENU_BEGIN = "# BEGIN AD FRESH MENU"
MENU_END = "# END AD FRESH MENU"

IDLE_CHOICES = (
    (60, "1 minute"),
    (120, "2 minutes"),
    (180, "3 minutes"),
    (300, "5 minutes"),
    (480, "8 minutes"),
)
DWELL_CHOICES = (20, 30, 48, 90, 180)
SPEED_CHOICES = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
# GNOME's idle-delay is the monitor-off interval. 0 means Never.
MONITOR_OFF_CHOICES = (
    (60, "1 minute"),
    (120, "2 minutes"),
    (180, "3 minutes"),
    (300, "5 minutes"),
    (600, "10 minutes"),
    (900, "15 minutes"),
    (1800, "30 minutes"),
    (0, "Never"),
)
MONITOR_OFF_POSITIVE = tuple(choice for choice, _label in MONITOR_OFF_CHOICES if choice > 0)
GNOME_SESSION_SCHEMA = "org.gnome.desktop.session"
GNOME_IDLE_DELAY = "idle-delay"
SCREEN_SHIELD_NAME = "org.gnome.Shell.ScreenShield"
SHIELD_UNAVAILABLE_NOTE = (
    "GNOME cannot blank or lock this session (it was not started by GDM), "
    "so the monitor-off interval has no effect; AD Fresh keeps the saver on screen."
)

MENU_CASE = """  # BEGIN AD FRESH MENU
  "AD Fresh Screensaver")
    if [[ -x "$HOME/.local/bin/adfresh" ]]; then
      "$HOME/.local/bin/adfresh" --settings
    elif command -v adfresh >/dev/null 2>&1; then
      adfresh --settings
    else
      notify-send -i "$iDIR/error.png" "E-R-R-O-R" "AD Fresh is not installed"
    fi
    ;;
  # END AD FRESH MENU
"""


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "adfresh" / "settings.json"


def _as_bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def clean_idle(seconds: int) -> int:
    allowed = [choice for choice, _label in IDLE_CHOICES]
    if seconds in allowed:
        return seconds
    return min(allowed, key=lambda choice: abs(choice - seconds))


def idle_label(seconds: int) -> str:
    for choice, label in IDLE_CHOICES:
        if choice == seconds:
            return label
    return f"{seconds} seconds"


def dwell_label(seconds: float) -> str:
    if seconds >= 60 and abs(seconds - round(seconds / 60) * 60) < 0.01:
        minutes = int(round(seconds / 60))
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit}"
    if float(seconds).is_integer():
        return f"{int(seconds)} seconds"
    return f"{seconds:g} seconds"


def speed_label(speed: float) -> str:
    text = f"{speed:g}"
    return f"{text}×"


def monitor_off_label(seconds: int) -> str:
    """Human label for a GNOME monitor-off (idle-delay) value."""
    seconds = int(seconds)
    if seconds <= 0:
        return "Never"
    for choice, label in MONITOR_OFF_CHOICES:
        if choice == seconds:
            return label
    if seconds % 60 == 0:
        minutes = seconds // 60
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit}"
    return f"{seconds} seconds"


def clean_monitor_off(seconds: int) -> int:
    """Snap a monitor-off value to the picker choices. 0 stays Never."""
    seconds = int(seconds)
    if seconds <= 0:
        return 0
    if seconds in MONITOR_OFF_POSITIVE:
        return seconds
    return min(MONITOR_OFF_POSITIVE, key=lambda choice: abs(choice - seconds))


def parse_gsettings_uint32(text: str) -> int | None:
    """Parse `gsettings get` output such as 'uint32 300'."""
    parts = str(text or "").split()
    if not parts:
        return None
    try:
        return max(0, int(parts[-1]))
    except ValueError:
        return None


def _monitor_off_value(value: object) -> int:
    try:
        return max(0, min(86400, int(value)))
    except (TypeError, ValueError):
        return 0


def gsettings_command() -> str:
    return shutil.which("gsettings") or "gsettings"


def read_gnome_monitor_off() -> int | None:
    """Read GNOME's monitor-off interval in seconds. None when unavailable."""
    try:
        result = subprocess.run(
            [gsettings_command(), "get", GNOME_SESSION_SCHEMA, GNOME_IDLE_DELAY],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_gsettings_uint32(result.stdout)


def write_gnome_monitor_off(seconds: int) -> bool:
    """Apply the monitor-off interval through gsettings. gsettings is the source of truth."""
    value = max(0, int(seconds))
    command = gsettings_command()
    for raw in (str(value), f"uint32 {value}"):
        try:
            result = subprocess.run(
                [command, "set", GNOME_SESSION_SCHEMA, GNOME_IDLE_DELAY, raw],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode == 0:
            log(f"gnome idle-delay set to {value}")
            return True
    log(f"could not set gnome idle-delay to {value}")
    return False


def gdbus_command() -> str:
    return shutil.which("gdbus") or "gdbus"


def gnome_screen_lock_available() -> bool:
    """True when gnome-shell exports org.gnome.Shell.ScreenShield.

    GNOME only blanks and locks in sessions started by GDM. This Ubuntu session
    is started by SDDM, so the ScreenShield name is absent and the monitor-off
    interval is inert. Default to False: without a shield the saver stays up.
    """
    try:
        result = subprocess.run(
            [
                gdbus_command(),
                "call",
                "--session",
                "--dest",
                "org.freedesktop.DBus",
                "--object-path",
                "/org/freedesktop/DBus",
                "--method",
                "org.freedesktop.DBus.NameHasOwner",
                SCREEN_SHIELD_NAME,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    return result.stdout.strip().lower().startswith("(true")


def monitor_off_note(available: bool) -> str:
    """A warning sentence for the monitor-off UI when GNOME cannot blank the screen."""
    return "" if available else SHIELD_UNAVAILABLE_NOTE


def effective_monitor_off(cfg: Settings, *, gnome: bool | None = None) -> int:
    """Current monitor-off interval. On GNOME gsettings wins over settings.json."""
    if gnome is None:
        gnome = desktop_environment() == "gnome"
    if not gnome:
        return cfg.monitor_off_seconds
    value = read_gnome_monitor_off()
    return cfg.monitor_off_seconds if value is None else value


def next_monitor_off(idle_seconds: int) -> int:
    """First monitor-off choice that leaves the saved saver delay visible."""
    for choice in MONITOR_OFF_POSITIVE:
        if choice > int(idle_seconds):
            return choice
    return MONITOR_OFF_POSITIVE[-1]


def lower_idle_below(off_seconds: int) -> int:
    """Largest saver delay choice strictly below the monitor-off interval."""
    below = [choice for choice, _label in IDLE_CHOICES if choice < int(off_seconds)]
    return max(below) if below else IDLE_CHOICES[0][0]


def lower_idle_for_monitor_off(
    cfg: Settings,
    seconds: int,
    *,
    gnome: bool | None = None,
    write=None,
) -> tuple[Settings, int, bool]:
    """Apply a picked monitor-off value; if it is at or below the saver delay, move the saver earlier."""
    if gnome is None:
        gnome = desktop_environment() == "gnome"
    off = max(0, int(seconds))
    idle = cfg.idle_seconds
    if off > 0 and off <= idle:
        idle = lower_idle_below(off)
        if idle >= off:
            # No saver delay fits below this blank interval: keep the saver and blank later instead.
            off = next_monitor_off(cfg.idle_seconds)
            idle = cfg.idle_seconds
    writer = write or write_gnome_monitor_off
    ok = writer(off) if gnome else True
    if not ok:
        return cfg, cfg.idle_seconds, False
    cfg.monitor_off_seconds = off
    cfg.idle_seconds = idle
    return save_settings(cfg), cfg.idle_seconds, True


def ensure_after_idle_change(
    cfg: Settings,
    *,
    read=None,
    write=None,
) -> tuple[Settings, int | None]:
    """After the saver delay changed, raise GNOME's monitor-off above it when needed."""
    reader = read or read_gnome_monitor_off
    writer = write or write_gnome_monitor_off
    off = reader()
    if off is None or off == 0:
        return cfg, None
    if off > cfg.idle_seconds:
        if cfg.monitor_off_seconds != off:
            cfg.monitor_off_seconds = off
            cfg = save_settings(cfg)
        return cfg, None
    applied = next_monitor_off(cfg.idle_seconds)
    if not writer(applied):
        return cfg, None
    cfg.monitor_off_seconds = applied
    return save_settings(cfg), applied


def sync_monitor_off(
    cfg: Settings,
    *,
    read=None,
    write=None,
) -> tuple[Settings, int, bool]:
    """Install-time seed from gsettings. Returns (cfg, off, changed) where changed means gsettings was raised."""
    reader = read or read_gnome_monitor_off
    writer = write or write_gnome_monitor_off
    off = reader()
    if off is None:
        return cfg, cfg.monitor_off_seconds, False
    applied = off
    changed = False
    if off > 0 and off <= cfg.idle_seconds:
        applied = next_monitor_off(cfg.idle_seconds)
        if writer(applied):
            changed = True
        else:
            applied = off
    if cfg.monitor_off_seconds != applied:
        cfg.monitor_off_seconds = applied
        cfg = save_settings(cfg)
    return cfg, applied, changed


def sync_monitor_off_mirror(cfg: Settings, *, gnome: bool | None = None, read=None) -> Settings:
    """Keep settings.json's cached monitor-off in step with gsettings when the menu opens."""
    if gnome is None:
        gnome = desktop_environment() == "gnome"
    if not gnome:
        return cfg
    reader = read or read_gnome_monitor_off
    off = reader()
    if off is None or off == cfg.monitor_off_seconds:
        return cfg
    cfg.monitor_off_seconds = off
    return save_settings(cfg)


@dataclass
class Settings:
    enabled: bool = True
    idle_seconds: int = 300
    dwell: float = 48.0
    fade: float = 1.35
    speed: float = 1.0
    modules: list[str] = field(default_factory=list)
    monitor_off_seconds: int = 0

    def allowed_ids(self) -> list[str]:
        from adfresh.modules import CATALOG

        known = [cls.id for cls in CATALOG]
        if not self.modules:
            return known
        chosen = [name for name in known if name in set(self.modules)]
        return chosen or known


def load_settings() -> Settings:
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    modules = data.get("modules") or []
    if not isinstance(modules, list):
        modules = []
    try:
        idle = clean_idle(int(data.get("idle_seconds", 300)))
        dwell = _clamp(float(data.get("dwell", 48)), 10, 600)
        fade = _clamp(float(data.get("fade", 1.35)), 0, 5)
        speed = _clamp(float(data.get("speed", 1)), 0.25, 4)
        monitor_off = _monitor_off_value(data.get("monitor_off_seconds", 0))
    except (TypeError, ValueError):
        return Settings()
    return Settings(
        enabled=_as_bool(data.get("enabled", True)),
        idle_seconds=idle,
        dwell=dwell,
        fade=fade,
        speed=speed,
        modules=[str(item) for item in modules],
        monitor_off_seconds=monitor_off,
    )


def save_settings(cfg: Settings) -> Settings:
    from adfresh.modules import CATALOG

    known = [cls.id for cls in CATALOG]
    chosen = [name for name in known if name in set(cfg.modules)]
    stored = [] if not chosen or set(chosen) == set(known) else chosen
    clean = Settings(
        enabled=_as_bool(cfg.enabled),
        idle_seconds=clean_idle(int(cfg.idle_seconds)),
        dwell=_clamp(cfg.dwell, 10, 600),
        fade=_clamp(cfg.fade, 0, 5),
        speed=_clamp(cfg.speed, 0.25, 4),
        modules=stored,
        monitor_off_seconds=_monitor_off_value(cfg.monitor_off_seconds),
    )
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": clean.enabled,
        "idle_seconds": clean.idle_seconds,
        "dwell": clean.dwell,
        "fade": clean.fade,
        "speed": clean.speed,
        "modules": clean.modules,
        "monitor_off_seconds": clean.monitor_off_seconds,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return clean


def module_summary(cfg: Settings) -> str:
    from adfresh.modules import BY_ID, CATALOG

    ids = cfg.allowed_ids()
    known = [cls.id for cls in CATALOG]
    if ids == known:
        return f"All {len(known)}"
    if len(ids) == 1:
        return BY_ID[ids[0]].title
    return f"{len(ids)} of {len(known)}"


def summary_rows(cfg: Settings, *, gnome: bool | None = None) -> list[str]:
    state = "On" if cfg.enabled else "Off"
    rows = [
        f"{'Screensaver':<16}{state}",
        f"{'Starts after':<16}{idle_label(cfg.idle_seconds)}",
        f"{'Modules':<16}{module_summary(cfg)}",
        f"{'Time on each':<16}{dwell_label(cfg.dwell)}",
        f"{'Speed':<16}{speed_label(cfg.speed)}",
    ]
    if gnome is None:
        gnome = desktop_environment() == "gnome"
    if gnome:
        off = effective_monitor_off(cfg, gnome=True)
        label = monitor_off_label(off)
        if off > 0 and off <= cfg.idle_seconds:
            label = f"{label} (before saver!)"
        rows.append(f"{'Monitor off':<16}{label}")
    rows.extend(["Preview a module", "Start screensaver now", "Done"])
    return rows


def listener_block(cfg: Settings) -> str:
    if not cfg.enabled:
        body = (
            "# Screensaver is off. Turn it on from Quick Settings, AD Fresh Screensaver.\n"
            f"# Saved delay is {idle_label(cfg.idle_seconds)}. The lock at 10 minutes still runs.\n"
        )
    else:
        note = "The lock at 10 minutes takes over."
        if cfg.idle_seconds != 300:
            note = f"Starts after {idle_label(cfg.idle_seconds)}. The lock at 10 minutes takes over."
        body = (
            f"# Flying toasters and the other night modules. {note}\n"
            "listener {\n"
            f"    timeout = {int(cfg.idle_seconds)}\n"
            "    on-timeout = $HOME/.local/bin/adfresh --background\n"
            "    on-resume = $HOME/.local/bin/adfresh --stop\n"
            "}\n"
        )
    return f"{BEGIN}\n{body}{END}\n"


def splice_block(text: str, block: str) -> str:
    if not block.endswith("\n"):
        block += "\n"
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        _old, post = rest.split(END, 1)
        if post.startswith("\n"):
            post = post[1:]
        return pre + block + post
    marker = "# Warn\n"
    if marker not in text:
        raise SystemExit("could not find the Warn listener in hypridle.conf")
    return text.replace(marker, block + "\n" + marker, 1)


def listener_body(text: str) -> str | None:
    if BEGIN not in text or END not in text:
        return None
    block = text.split(BEGIN, 1)[1].split(END, 1)[0]
    start = block.find("listener")
    if start < 0:
        return ""
    end = block.find("}", start)
    if end < 0:
        return block[start:]
    return block[start : end + 1]


def restart_hypridle() -> int:
    result = subprocess.run(["systemctl", "--user", "restart", "hypridle"], check=False)
    log(f"hypridle restart exit {result.returncode}")
    return result.returncode


def apply_idle(cfg: Settings, *, path: Path | None = None, restart: bool = True) -> bool:
    """Write the idle listener. Restart hypridle when the listener itself changed."""
    target = path or HYPRIDLE
    if not target.exists():
        return False
    original = target.read_text(encoding="utf-8")
    updated = splice_block(original, listener_block(cfg))
    listener_changed = listener_body(original) != listener_body(updated)
    if updated != original:
        target.write_text(updated, encoding="utf-8")
        log(f"hypridle listener updated enabled={cfg.enabled} timeout={cfg.idle_seconds}")
    if listener_changed and restart:
        restart_hypridle()
        return True
    return False


def toggle_module(cfg: Settings, module_id: str) -> tuple[Settings, bool]:
    """Return the updated settings and whether the toggle was kept."""
    from adfresh.modules import CATALOG

    known = [cls.id for cls in CATALOG]
    current = set(cfg.allowed_ids())
    if module_id in current:
        if len(current) == 1:
            return cfg, False
        current.remove(module_id)
    else:
        current.add(module_id)
    cfg.modules = [] if current == set(known) else [name for name in known if name in current]
    return cfg, True


def ensure_quick_settings(path: Path | None = None) -> bool:
    """Add the AD Fresh row to the KooL quick-settings menu. Idempotent."""
    target = path or QUICK_SETTINGS
    if not target.exists():
        return False
    text = target.read_text(encoding="utf-8")
    original = text
    anchor = '  "Rainbow Borders Mode") rainbow_borders_menu ;;\n'
    if MENU_BEGIN not in text and anchor in text:
        text = text.replace(anchor, MENU_CASE + anchor, 1)
    if not re.search(r"(?m)^AD Fresh Screensaver$", text):
        text = text.replace(
            "Change Starship Prompt\n",
            "AD Fresh Screensaver\nChange Starship Prompt\n",
            1,
        )
    quick = "  printf '%s\\n' \"[ Quick Links]\"\n"
    entry = "  printf '%s\\n' \"AD Fresh Screensaver\"\n"
    if entry not in text and quick in text:
        text = text.replace(quick, quick + entry, 1)
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if "[[ Misc ]]" in line and "meta" in line and "AD Fresh Screensaver" not in line:
            lines[index] = line.replace(
                "Rainbow Borders Mode",
                "AD Fresh Screensaver Rainbow Borders Mode",
                1,
            )
            break
    text = "".join(lines)
    if text == original:
        return False
    target.write_text(text, encoding="utf-8")
    return True


def remove_quick_settings(path: Path | None = None) -> bool:
    target = path or QUICK_SETTINGS
    if not target.exists():
        return False
    text = target.read_text(encoding="utf-8")
    original = text
    text = re.sub(
        r"  # BEGIN AD FRESH MENU\n.*?# END AD FRESH MENU\n",
        "",
        text,
        count=1,
        flags=re.S,
    )
    text = text.replace("AD Fresh Screensaver\nChange Starship Prompt\n", "Change Starship Prompt\n")
    text = text.replace("  printf '%s\\n' \"AD Fresh Screensaver\"\n", "")
    text = text.replace("AD Fresh Screensaver Rainbow Borders Mode", "Rainbow Borders Mode")
    if text == original:
        return False
    target.write_text(text, encoding="utf-8")
    return True
