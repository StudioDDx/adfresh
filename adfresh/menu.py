"""Rofi settings menu, launched from the system quick-settings list or the app menu."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from adfresh.runtime import ROOT, desktop_environment
from adfresh.settings import (
    DWELL_CHOICES,
    IDLE_CHOICES,
    MONITOR_OFF_CHOICES,
    SPEED_CHOICES,
    Settings,
    apply_idle,
    dwell_label,
    effective_monitor_off,
    ensure_after_idle_change,
    gnome_screen_lock_available,
    idle_label,
    load_settings,
    lower_idle_for_monitor_off,
    monitor_off_label,
    monitor_off_note,
    save_settings,
    speed_label,
    summary_rows,
    sync_monitor_off_mirror,
    toggle_module,
)

THEME = Path.home() / ".config" / "hypr" / "rofi" / "config-edit.rasi"
ICON = ROOT / "share" / "adfresh.png"


def _rofi_env() -> dict[str, str]:
    """rofi 2.0 needs layer-shell on GNOME Wayland; the XWayland path works fine."""
    env = os.environ.copy()
    if desktop_environment() == "gnome":
        env.pop("WAYLAND_DISPLAY", None)
        env["GDK_BACKEND"] = "x11"
    return env


def _ask_rofi(prompt: str, rows: list[str], message: str, lines: int) -> tuple[bool, str | None]:
    """Return (rofi_ran, choice). rofi_ran is False when rofi could not show the list."""
    command = [
        "rofi",
        "-i",
        "-dmenu",
        "-p",
        prompt,
        "-mesg",
        message,
        "-theme-str",
        (
            "window { width: 34%; } "
            f"listview {{ columns: 1; lines: {lines}; }} "
            f'entry {{ placeholder: "{prompt}"; }}'
        ),
    ]
    if THEME.exists():
        command.extend(["-config", str(THEME)])
    try:
        result = subprocess.run(
            command,
            input="\n".join(rows) + "\n",
            text=True,
            capture_output=True,
            check=False,
            env=_rofi_env(),
        )
    except OSError:
        return False, None
    if result.returncode != 0:
        # Esc is a silent exit 1. Anything on stderr means rofi failed to start.
        return (not result.stderr.strip()), None
    choice = result.stdout.strip()
    return True, (choice or None)


def _ask_zenity(prompt: str, rows: list[str], message: str) -> str | None:
    """GTK list fallback for desktops where rofi cannot draw a window."""
    command = [
        "zenity",
        "--list",
        "--title=AD Fresh",
        f"--text={message}",
        "--column=Choice",
        "--hide-header",
        "--width=560",
        "--height=420",
        *rows,
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    choice = result.stdout.strip()
    return choice or None


def _ask(prompt: str, rows: list[str], message: str, *, lines: int = 8) -> str | None:
    if shutil.which("rofi") is not None:
        ran, choice = _ask_rofi(prompt, rows, message, lines)
        if ran:
            return choice
    if shutil.which("zenity") is not None:
        return _ask_zenity(prompt, rows, message)
    raise SystemExit("rofi and zenity are both missing, so the AD Fresh settings menu cannot open.")


def _notify(message: str) -> None:
    command = ["notify-send", "-a", "AD Fresh", "AD Fresh", message]
    if ICON.exists():
        command[1:1] = ["-i", str(ICON)]
    subprocess.run(command, check=False)


def _launch(extra: list[str], *, wait: bool) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    command = [sys.executable, "-m", "adfresh", *extra]
    if wait:
        subprocess.run(command, env=env, cwd=str(ROOT), check=False)
        return
    subprocess.Popen(command, env=env, cwd=str(ROOT), start_new_session=True)


def _mark(selected: bool, label: str) -> str:
    return f"{'●' if selected else '○'}  {label}"


def _marked_label(choice: str) -> str:
    if choice[:1] in {"●", "○"}:
        return choice.split("  ", 1)[-1]
    return choice


def _apply_idle_hook(cfg: Settings) -> None:
    """hypridle is Hyprland-only; on GNOME the idle watcher reads settings.json."""
    if desktop_environment() == "hyprland":
        apply_idle(cfg)


def _pick_idle(cfg: Settings) -> Settings:
    desktop = desktop_environment()
    rows = [_mark(cfg.idle_seconds == seconds, label) for seconds, label in IDLE_CHOICES]
    rows.append("Back")
    if desktop == "gnome":
        off = effective_monitor_off(cfg, gnome=True)
        message = f"GNOME turns the screen off after {monitor_off_label(off)}."
        if off > 0 and off <= cfg.idle_seconds:
            message = f"{monitor_off_label(off)} turns the screen off first; that moves later if needed."
    else:
        message = "The screen still locks at 10 minutes."
    choice = _ask("Starts after", rows, message, lines=len(rows))
    if choice is None or choice == "Back":
        return cfg
    picked = _marked_label(choice)
    for seconds, label in IDLE_CHOICES:
        if picked == label:
            cfg.idle_seconds = seconds
            cfg = save_settings(cfg)
            if desktop == "gnome":
                cfg, applied = ensure_after_idle_change(cfg)
                if applied is not None:
                    _notify(
                        f"Screen will turn off after {monitor_off_label(applied)} "
                        "so the saver can be seen."
                    )
                else:
                    _notify(f"AD Fresh starts after {idle_label(cfg.idle_seconds)}.")
            else:
                if cfg.enabled:
                    _apply_idle_hook(cfg)
                _notify(f"AD Fresh starts after {idle_label(cfg.idle_seconds)}.")
            return cfg
    return cfg


def _pick_monitor_off(cfg: Settings) -> Settings:
    current = effective_monitor_off(cfg, gnome=True)
    choices = list(MONITOR_OFF_CHOICES)
    if all(seconds != current for seconds, _label in choices):
        choices.insert(0, (current, monitor_off_label(current)))
    rows = [_mark(seconds == current, label) for seconds, label in choices]
    rows.append("Back")
    message = "How long GNOME waits before turning the monitors off (and locking)."
    note = monitor_off_note(gnome_screen_lock_available())
    if note:
        message = f"{message} {note}"
    choice = _ask("Monitor off", rows, message, lines=len(rows))
    if choice is None or choice == "Back":
        return cfg
    picked = _marked_label(choice)
    for seconds, label in choices:
        if picked != label:
            continue
        before = cfg.idle_seconds
        cfg, idle, ok = lower_idle_for_monitor_off(cfg, seconds)
        if not ok:
            _notify("Could not change the GNOME monitor-off interval.")
            return cfg
        if idle != before:
            _notify(
                f"Screensaver will start after {idle_label(idle)} "
                "so it is visible before the screen turns off."
            )
        elif seconds == 0:
            _notify("GNOME will keep the screen on.")
        else:
            _notify(f"Screen will turn off after {monitor_off_label(cfg.monitor_off_seconds)}.")
        return cfg
    return cfg


def _pick_dwell(cfg: Settings) -> Settings:
    choices = list(DWELL_CHOICES)
    if cfg.dwell not in choices:
        choices.insert(0, cfg.dwell)
    rows = [_mark(cfg.dwell == seconds, dwell_label(seconds)) for seconds in choices]
    rows.append("Back")
    choice = _ask("Time on each", rows, "How long one module stays up.", lines=len(rows))
    if choice is None or choice == "Back":
        return cfg
    picked = _marked_label(choice)
    for seconds in choices:
        if picked == dwell_label(seconds):
            cfg.dwell = float(seconds)
            cfg = save_settings(cfg)
            _notify(f"Each module stays up for {dwell_label(cfg.dwell)}.")
            return cfg
    return cfg


def _pick_speed(cfg: Settings) -> Settings:
    choices = list(SPEED_CHOICES)
    if cfg.speed not in choices:
        choices.append(cfg.speed)
        choices.sort()
    rows = [_mark(abs(cfg.speed - speed) < 0.001, speed_label(speed)) for speed in choices]
    rows.append("Back")
    choice = _ask("Speed", rows, "1× is the normal pace.", lines=len(rows))
    if choice is None or choice == "Back":
        return cfg
    picked = _marked_label(choice)
    for speed in choices:
        if picked == speed_label(speed):
            cfg.speed = float(speed)
            cfg = save_settings(cfg)
            _notify(f"Playback speed is {speed_label(cfg.speed)}.")
            return cfg
    return cfg


def _pick_modules(cfg: Settings) -> Settings:
    from adfresh.modules import CATALOG

    before = list(cfg.modules)
    while True:
        enabled = set(cfg.allowed_ids())
        rows = [
            "All modules",
            "Flying toasters only",
        ]
        rows.extend(_mark(cls.id in enabled, cls.title) for cls in CATALOG)
        rows.append("Back")
        choice = _ask("Modules", rows, "At least one module stays on.", lines=12)
        if choice is None or choice == "Back":
            break
        if choice == "All modules":
            cfg.modules = []
            continue
        if choice == "Flying toasters only":
            cfg.modules = ["toasters"]
            continue
        title = _marked_label(choice)
        match = next((cls for cls in CATALOG if cls.title == title), None)
        if match is None:
            continue
        cfg, kept = toggle_module(cfg, match.id)
        if not kept:
            _notify("At least one module stays on.")
    if cfg.modules != before:
        cfg = save_settings(cfg)
        from adfresh.settings import module_summary

        _notify(f"Modules: {module_summary(cfg)}.")
    return cfg


def _preview() -> None:
    from adfresh.modules import CATALOG

    rows = [cls.title for cls in CATALOG]
    rows.append("Back")
    choice = _ask("Preview", rows, "Opens a window. Esc closes it.", lines=12)
    if choice is None or choice == "Back":
        return
    match = next((cls for cls in CATALOG if cls.title == choice), None)
    if match is None:
        return
    _launch(["--demo", "--module", match.id], wait=True)


def run_menu() -> None:
    desktop = desktop_environment()
    cfg = sync_monitor_off_mirror(load_settings())
    if desktop == "gnome":
        message = "The GNOME idle watcher applies these."
    else:
        message = "Quick Settings keeps these for the idle screensaver."
    while True:
        choice = _ask("AD Fresh", summary_rows(cfg), message, lines=9)
        if choice is None or choice.startswith("Done"):
            return
        if choice.startswith("Screensaver"):
            cfg.enabled = not cfg.enabled
            cfg = save_settings(cfg)
            _apply_idle_hook(cfg)
            if cfg.enabled:
                _notify(f"AD Fresh starts after {idle_label(cfg.idle_seconds)}.")
            elif desktop == "gnome":
                _notify("AD Fresh is off. GNOME still turns the screen off on its own schedule.")
            else:
                _notify("AD Fresh is off. The screen still locks at 10 minutes.")
        elif choice.startswith("Starts after"):
            cfg = _pick_idle(cfg)
        elif choice.startswith("Modules"):
            cfg = _pick_modules(cfg)
        elif choice.startswith("Time on each"):
            cfg = _pick_dwell(cfg)
        elif choice.startswith("Speed"):
            cfg = _pick_speed(cfg)
        elif choice.startswith("Monitor off"):
            cfg = _pick_monitor_off(cfg)
        elif choice == "Preview a module":
            _preview()
        elif choice == "Start screensaver now":
            _launch(["--background"], wait=False)
            return
