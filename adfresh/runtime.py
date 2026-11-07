"""Process paths, logging, and SDL setup. No pygame import."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    path = Path(base) if base else Path(f"/tmp/adfresh-{os.getuid()}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def pid_path() -> Path:
    return runtime_dir() / "adfresh.pid"


def quit_path() -> Path:
    return runtime_dir() / "adfresh.quit"


def log_path() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "adfresh"
    state.mkdir(parents=True, exist_ok=True)
    return state / "adfresh.log"


def log(message: str) -> None:
    try:
        with log_path().open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        return


def desktop_environment() -> str:
    """Which desktop owns this process: "hyprland", "gnome", or "other"."""
    raw = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("XDG_SESSION_DESKTOP", "")
    names = [part.strip().lower() for part in raw.replace(";", ":").split(":") if part.strip()]
    if "hyprland" in names or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if "gnome" in names or "ubuntu" in names:
        return "gnome"
    return "other"


def configure_sdl(preview: bool) -> None:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    os.environ.setdefault("SDL_VIDEO_ALLOW_SCREENSAVER", "1")
    os.environ.setdefault("SDL_APP_NAME", "adfresh")
    os.environ.setdefault("SDL_VIDEO_X11_WMCLASS", "adfresh")
    if preview:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        return
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    if "SDL_VIDEODRIVER" in os.environ:
        return
    if os.environ.get("WAYLAND_DISPLAY"):
        if desktop_environment() == "gnome" and os.environ.get("DISPLAY"):
            # GNOME's native Wayland driver cannot put one window on each monitor.
            # XWayland gives real per-display fullscreen windows (top bar included).
            os.environ["SDL_VIDEODRIVER"] = "x11"
        else:
            os.environ["SDL_VIDEODRIVER"] = "wayland"


def read_pid() -> int | None:
    try:
        raw = pid_path().read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def write_pid(pid: int) -> None:
    pid_path().write_text(str(pid), encoding="utf-8")


def clear_pid() -> None:
    try:
        pid_path().unlink()
    except OSError:
        return


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def request_quit() -> None:
    try:
        quit_path().write_text("1", encoding="utf-8")
    except OSError:
        return


def quit_requested() -> bool:
    return quit_path().exists()


def clear_quit() -> None:
    try:
        quit_path().unlink()
    except OSError:
        return


def stop_running() -> None:
    pid = read_pid()
    request_quit()
    if pid and pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(30):
            if not pid_alive(pid):
                break
            time.sleep(0.05)
    if not pid or not pid_alive(pid):
        clear_pid()
