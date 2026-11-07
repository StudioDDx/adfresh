"""AD Fresh command line."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from adfresh.runtime import (
    ROOT,
    clear_pid,
    clear_quit,
    configure_sdl,
    desktop_environment,
    log,
    pid_alive,
    pid_path,
    quit_requested,
    read_pid,
    request_quit,
    stop_running,
    write_pid,
)

LAUNCHER = Path.home() / ".local" / "bin" / "adfresh"
SERVICE_NAME = "adfresh-idle.service"
BEGIN = "# BEGIN AD FRESH"
END = "# END AD FRESH"
WARN_OLD = 'notify-send -i $iDIR " You are idle!" # command to run when timeout has passed'
WARN_NEW = 'test -f "$XDG_RUNTIME_DIR/adfresh.pid" || notify-send -i $iDIR " You are idle!"'
LOCK_OLD = "loginctl lock-session # command to run when timeout has passed"
LOCK_NEW = "$HOME/.local/bin/adfresh --stop; loginctl lock-session"


@dataclass(frozen=True)
class InstallPaths:
    launcher: Path
    menu_entry: Path
    settings_entry: Path
    idle_launcher: Path
    service: Path
    hypridle: Path
    quick_settings: Path


def install_paths() -> InstallPaths:
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    binaries = home / ".local" / "bin"
    return InstallPaths(
        launcher=binaries / "adfresh",
        menu_entry=data / "applications" / "adfresh.desktop",
        settings_entry=data / "applications" / "adfresh-settings.desktop",
        idle_launcher=binaries / "adfresh-idle",
        service=config / "systemd" / "user" / SERVICE_NAME,
        hypridle=config / "hypr" / "hypridle.conf",
        quick_settings=config / "hypr" / "scripts" / "Kool_Quick_Settings.sh",
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="adfresh",
        description="AD Fresh — flying toasters and the rest of a night at the desk.",
    )
    parser.add_argument("--demo", action="store_true", help="windowed player; keys switch modules")
    parser.add_argument("--fullscreen", action="store_true", help="fullscreen the demo window")
    parser.add_argument("--background", action="store_true", help="detach, then cover every display")
    parser.add_argument("--display", type=int, default=None, help="one display index")
    parser.add_argument("--module", default=None, help="stay on a single module")
    parser.add_argument("--dwell", type=float, default=None, help="seconds on each module")
    parser.add_argument("--fade", type=float, default=None, help="crossfade seconds")
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--size", default="1280x720", help="demo window size")
    parser.add_argument("--preview", metavar="DIR", help="write one still per module and exit")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--settings", action="store_true", help="open the system settings menu")
    parser.add_argument("--install", action="store_true", help="launcher, menu entry, and hypridle hook")
    parser.add_argument("--uninstall", action="store_true", help="remove the hypridle hook and launcher")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--epoch", type=float, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--modules", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--spanning", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--virtual", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--offset", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def parse_virtual(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    try:
        width, height = raw.lower().split("x")
        return max(1, int(width)), max(1, int(height))
    except ValueError:
        raise SystemExit("--virtual expects WxH, for example 3840x1080")


def parse_offset(raw: str | None) -> tuple[int, int]:
    if not raw:
        return (0, 0)
    try:
        x, y = raw.split(",")
        return int(x), int(y)
    except ValueError:
        raise SystemExit("--offset expects X,Y, for example 1920,0")


def parse_size(raw: str) -> tuple[int, int]:
    try:
        w, h = raw.lower().split("x")
        return max(320, int(w)), max(240, int(h))
    except ValueError:
        raise SystemExit("--size expects WxH, for example 1280x720")


def hyprlock_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-x", "hyprlock"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def daemonize() -> None:
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)


def resolve_module(name: str | None) -> str | None:
    if not name:
        return None
    from adfresh.modules import resolve

    return resolve(name).id


def resolve_playback(args: argparse.Namespace) -> None:
    """Fill anything the command line left blank from the settings file."""
    from adfresh.modules import CATALOG
    from adfresh.settings import load_settings

    cfg = load_settings()
    if args.dwell is None:
        args.dwell = cfg.dwell
    if args.fade is None:
        args.fade = cfg.fade
    if args.speed is None:
        args.speed = cfg.speed
    known = [cls.id for cls in CATALOG]
    if args.modules:
        raw = {part.strip() for part in str(args.modules).split(",") if part.strip()}
        args.allowed = [name for name in known if name in raw] or known
    else:
        args.allowed = cfg.allowed_ids()
    log(
        "settings "
        f"dwell={args.dwell:g} speed={args.speed:g} "
        f"modules={','.join(args.allowed)}"
    )


def playlist_for(args: argparse.Namespace, epoch: float, only: str | None) -> list[str]:
    from adfresh.engine import build_playlist

    allowed = None
    if args.modules:
        allowed = [part.strip() for part in str(args.modules).split(",") if part.strip()]
    elif getattr(args, "allowed", None):
        allowed = list(args.allowed)
    return build_playlist(epoch, only, allowed)


def play(args: argparse.Namespace) -> None:
    from adfresh.engine import Player, Schedule, open_window, run_player

    display = 0 if args.display is None else args.display
    epoch = time.monotonic() if args.epoch is None else args.epoch
    only = resolve_module(args.module)
    schedule = Schedule(playlist_for(args, epoch, only), args.dwell, args.fade, epoch)
    saver = not args.demo
    fullscreen = bool(args.fullscreen or saver)
    virtual = parse_virtual(getattr(args, "virtual", None))
    offset = parse_offset(getattr(args, "offset", None))
    seed_arg = getattr(args, "seed", None)
    # Spanning only makes sense for the saver: demo keys and variable dt would
    # desynchronise the children.
    spanning = bool(getattr(args, "spanning", False)) and virtual is not None and saver
    if seed_arg is not None:
        seed = seed_arg
    elif spanning:
        # The supervisor passes the same --seed to every child; this default
        # keeps the two halves identical when run by hand.
        seed = 5000 + int(epoch)
    else:
        seed = 5000 + display * 997 + int(epoch)
    player = Player(
        display_index=display,
        seed=seed,
        schedule=schedule,
        saver=saver,
        speed=args.speed,
        virtual_size=virtual if spanning else None,
        offset=offset if spanning else (0, 0),
        fixed_step=spanning,
    )
    screen = open_window(display, fullscreen, parse_size(args.size))
    player.resize(screen.get_width(), screen.get_height())
    log(
        f"play display={display} fullscreen={fullscreen} saver={saver} "
        f"size={screen.get_size()} spanning={spanning} "
        f"virtual={virtual} offset={offset if spanning else (0, 0)}"
    )

    next_lock_check = 0.0
    locked = False

    def should_stop() -> bool:
        nonlocal next_lock_check, locked
        if not saver:
            return False
        if quit_requested():
            return True
        now = time.monotonic()
        if now >= next_lock_check:
            next_lock_check = now + 0.5
            locked = hyprlock_running()
        return locked

    try:
        run_player(
            player,
            screen,
            fullscreen=fullscreen,
            should_stop=should_stop,
            spanning=spanning,
            epoch=epoch,
        )
    finally:
        if saver:
            request_quit()
        import pygame

        pygame.quit()


def supervise(args: argparse.Namespace) -> None:
    from adfresh import layout

    import pygame

    pygame.display.init()
    count = max(1, pygame.display.get_num_displays())
    display_sizes = [tuple(size) for size in pygame.display.get_desktop_sizes()]
    # SDL knows the true rectangle of every display index even when Wayland
    # enumerates the monitors in a non-left-to-right order (or when xrandr is
    # unavailable).  Query it before the video subsystem is shut down.
    try:
        sdl_monitors = layout.sdl_display_bounds(count) if count > 1 else None
    except Exception:  # noqa: BLE001 - never break the saver over layout probing
        sdl_monitors = None
    pygame.display.quit()
    if args.child or args.display is not None:
        play(args)
        return

    epoch = time.monotonic()
    clear_quit()
    write_pid(os.getpid())

    # One virtual canvas when the desktop geometry can be trusted; otherwise
    # keep the old independent per-display behaviour.  ADFRESH_SPAN=0 is an
    # escape hatch back to independent per-display windows (e.g. very slow
    # software-composited sessions).
    span = None
    spanning_allowed = os.environ.get("ADFRESH_SPAN", "1").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }
    if count > 1 and spanning_allowed:
        span = None
        if sdl_monitors:
            try:
                span = layout.build_layout(sdl_monitors, display_sizes, source="sdl")
            except Exception:  # noqa: BLE001
                span = None
        if span is None:
            try:
                span = layout.virtual_layout(display_sizes)
            except Exception:  # noqa: BLE001 - a bad layout must never break the saver
                span = None
        if span is not None and len(span.monitors) != count:
            span = None
    log(
        f"supervise {count} displays epoch={epoch:.3f} "
        + (f"span {span.describe()}" if span is not None else "layout independent")
    )
    if count == 1:
        try:
            play(args)
        finally:
            clear_pid()
            clear_quit()
        return

    shared_seed = 5000 + int(epoch)

    def _stop(_signum, _frame):
        request_quit()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    procs = []
    for index in range(count):
        command = [
            sys.executable,
            "-m",
            "adfresh",
            "--child",
            "--display",
            str(index),
            "--epoch",
            str(epoch),
            "--dwell",
            str(args.dwell),
            "--fade",
            str(args.fade),
            "--speed",
            str(args.speed),
        ]
        if span is not None:
            monitor = span.monitor(index)
            command.extend(
                [
                    "--spanning",
                    "--virtual",
                    f"{span.width}x{span.height}",
                    "--offset",
                    f"{monitor.x},{monitor.y}",
                    "--seed",
                    str(shared_seed),
                ]
            )
        if args.module:
            command.extend(["--module", args.module])
        elif getattr(args, "allowed", None):
            command.extend(["--modules", ",".join(args.allowed)])
        if args.fullscreen:
            command.append("--fullscreen")
        procs.append(subprocess.Popen(command, env=env, cwd=str(ROOT)))
    try:
        while not quit_requested():
            if hyprlock_running() or any(proc.poll() is not None for proc in procs):
                break
            time.sleep(0.1)
    finally:
        request_quit()
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        deadline = time.time() + 1.5
        for proc in procs:
            remaining = max(0.0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()
        clear_pid()
        clear_quit()


def launcher_text() -> str:
    return f"""#!/bin/sh
ROOT="{ROOT}"
export PYTHONPATH="$ROOT${{PYTHONPATH:+:$PYTHONPATH}}"
export PYGAME_HIDE_SUPPORT_PROMPT=1
export SDL_VIDEO_ALLOW_SCREENSAVER=1
export SDL_APP_NAME=adfresh
export SDL_VIDEO_X11_WMCLASS=adfresh
exec "$ROOT/.venv/bin/python" -m adfresh "$@"
"""


def idle_launcher_text() -> str:
    return f"""#!/bin/sh
ROOT="{ROOT}"
export PYTHONPATH="$ROOT${{PYTHONPATH:+:$PYTHONPATH}}"
export PYGAME_HIDE_SUPPORT_PROMPT=1
exec /usr/bin/python3 -m adfresh.gnome_idle "$@"
"""


def idle_service_text() -> str:
    return f"""[Unit]
Description=AD Fresh GNOME idle watcher
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/adfresh-idle
Environment=PYTHONUNBUFFERED=1
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""


def desktop_text(binary: Path | None = None) -> str:
    binary = binary or LAUNCHER
    icon = ROOT / "share" / "adfresh.png"
    return f"""[Desktop Entry]
Name=AD Fresh
GenericName=Screensaver
Comment=Flying toasters and the rest of a night at the desk
Exec={binary} --demo
Icon={icon}
Terminal=false
Type=Application
Categories=Screensaver;Utility;
StartupWMClass=adfresh
Keywords=screensaver;toasters;
Actions=Saver;Settings;

[Desktop Action Saver]
Name=Start screensaver
Exec={binary}

[Desktop Action Settings]
Name=Screensaver settings
Exec={binary} --settings
"""


def settings_desktop_text(binary: Path | None = None) -> str:
    binary = binary or LAUNCHER
    icon = ROOT / "share" / "adfresh.png"
    return f"""[Desktop Entry]
Name=AD Fresh Settings
GenericName=Screensaver settings
Comment=Idle delay, modules, and speed for the night screensaver
Exec={binary} --settings
Icon={icon}
Terminal=false
Type=Application
Categories=Settings;Screensaver;
StartupWMClass=adfresh
Keywords=screensaver;toasters;settings;
"""


def bake_icon() -> None:
    import pygame

    from adfresh.sprites import icon_surface

    pygame.display.init()
    pygame.font.init()
    pygame.display.set_mode((16, 16))
    share = ROOT / "share"
    share.mkdir(parents=True, exist_ok=True)
    pygame.image.save(icon_surface(256), share / "adfresh.png")
    pygame.display.quit()


def write_install_files(paths: InstallPaths, *, gnome: bool | None = None) -> None:
    """Launcher and desktop entries; on GNOME also the idle wrapper and user unit. Idempotent."""
    if gnome is None:
        gnome = desktop_environment() == "gnome"
    paths.launcher.parent.mkdir(parents=True, exist_ok=True)
    paths.launcher.write_text(launcher_text(), encoding="utf-8")
    paths.launcher.chmod(0o755)
    paths.menu_entry.parent.mkdir(parents=True, exist_ok=True)
    paths.menu_entry.write_text(desktop_text(paths.launcher), encoding="utf-8")
    paths.settings_entry.write_text(settings_desktop_text(paths.launcher), encoding="utf-8")
    if not gnome:
        return
    paths.idle_launcher.parent.mkdir(parents=True, exist_ok=True)
    paths.idle_launcher.write_text(idle_launcher_text(), encoding="utf-8")
    paths.idle_launcher.chmod(0o755)
    paths.service.parent.mkdir(parents=True, exist_ok=True)
    paths.service.write_text(idle_service_text(), encoding="utf-8")


def _systemctl(*args: str) -> int:
    try:
        return subprocess.run(["systemctl", "--user", *args], check=False).returncode
    except OSError:
        return 127


def enable_gnome_service() -> bool:
    _systemctl("daemon-reload")
    enabled = _systemctl("enable", "--now", SERVICE_NAME) == 0
    restarted = _systemctl("restart", SERVICE_NAME) == 0
    log(f"gnome idle service enable={enabled} restart={restarted}")
    return enabled and restarted


def disable_gnome_service() -> None:
    _systemctl("disable", "--now", SERVICE_NAME)
    _systemctl("daemon-reload")


def install_hypridle_hook(paths: InstallPaths) -> None:
    from adfresh.settings import ensure_quick_settings, listener_block, load_settings, splice_block

    if paths.hypridle.exists():
        original = paths.hypridle.read_text(encoding="utf-8")
        backup = paths.hypridle.with_suffix(".conf.bak-adfresh")
        if not backup.exists():
            backup.write_text(original, encoding="utf-8")
        text = original.replace(WARN_OLD, WARN_NEW).replace(LOCK_OLD, LOCK_NEW)
        text = splice_block(text, listener_block(load_settings()))
        if text != original:
            paths.hypridle.write_text(text, encoding="utf-8")
            restarted = subprocess.run(
                ["systemctl", "--user", "restart", "hypridle"],
                check=False,
            )
            log(f"hypridle restart exit {restarted.returncode}")
    ensure_quick_settings(paths.quick_settings)


def install(paths: InstallPaths | None = None) -> None:
    target = paths or install_paths()
    desktop = desktop_environment()
    bake_icon()
    write_install_files(target, gnome=desktop == "gnome")
    print(f"launcher  {target.launcher}")
    print(f"menu      {target.menu_entry}")
    print(f"settings  {target.settings_entry}")
    if desktop == "gnome":
        from adfresh.settings import (
            gnome_screen_lock_available,
            idle_label,
            load_settings,
            monitor_off_label,
            sync_monitor_off,
        )

        cfg, off, changed = sync_monitor_off(load_settings())
        running = enable_gnome_service()
        print(f"idle      {target.idle_launcher} + {target.service}")
        print("idle      adfresh-idle follows Mutter idle time, lock, inhibitors, and screen blank")
        if changed:
            print(
                f"monitor   raised GNOME screen-off to {monitor_off_label(off)} "
                "so the saver is visible first"
            )
        else:
            print(f"monitor   GNOME turns the screen off after {monitor_off_label(off)}")
        if not gnome_screen_lock_available():
            print("note      GNOME's screen blank/lock is unavailable in this SDDM session (no org.gnome.DisplayManager).")
            print("note      The monitor-off interval will not turn the display off; AD Fresh keeps the saver on screen.")
            print("note      Log in through GDM (gdm3 is installed, disabled) to enable GNOME blank+lock.")
        print(f"saver     AD Fresh starts after {idle_label(cfg.idle_seconds)}")
        print("settings  GNOME Settings -> Power -> Screen Blank, or AD Fresh Settings -> Monitor off")
        if not running:
            print("warning   could not start adfresh-idle.service; check: systemctl --user status adfresh-idle")
        return
    if desktop == "hyprland":
        install_hypridle_hook(target)
        print("idle      hypridle shows AD Fresh after the saved delay, then locks at 10 minutes")
        print("menu      Super+Shift+E, then AD Fresh Screensaver")
        return
    print("idle      no GNOME or Hyprland session detected; the launcher and menus are installed")


def remove_hypridle_hook(paths: InstallPaths) -> None:
    from adfresh.settings import remove_quick_settings

    if paths.hypridle.exists():
        text = paths.hypridle.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            pre, rest = text.split(BEGIN, 1)
            _, post = rest.split(END, 1)
            text = pre + post.lstrip("\n")
        text = text.replace(WARN_NEW, WARN_OLD)
        text = text.replace(LOCK_NEW, LOCK_OLD)
        paths.hypridle.write_text(text, encoding="utf-8")
        subprocess.run(["systemctl", "--user", "restart", "hypridle"], check=False)
    remove_quick_settings(paths.quick_settings)


def uninstall(paths: InstallPaths | None = None) -> None:
    target = paths or install_paths()
    desktop = desktop_environment()
    if desktop == "gnome" or target.service.exists():
        disable_gnome_service()
        stop_running()
    if desktop == "hyprland":
        remove_hypridle_hook(target)
    elif desktop != "gnome" and target.hypridle.exists():
        remove_hypridle_hook(target)
    for path in (
        target.launcher,
        target.menu_entry,
        target.settings_entry,
        target.idle_launcher,
        target.service,
    ):
        try:
            path.unlink()
        except OSError:
            pass
    if desktop == "gnome":
        print("removed the AD Fresh launcher, menus, and GNOME idle watcher")
        print("GNOME screen blank and lock settings were left as they are")
    else:
        print("removed the AD Fresh launcher, settings menu, and idle hook")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.stop:
        stop_running()
        return
    if args.uninstall:
        uninstall()
        return
    if args.settings:
        from adfresh.menu import run_menu

        run_menu()
        return
    if args.list:
        configure_sdl(False)
        from adfresh.modules import CATALOG

        for cls in CATALOG:
            print(f"{cls.id:12} {cls.title}")
        return
    configure_sdl(bool(args.preview or args.install))
    if args.install:
        install()
        return
    if args.preview:
        from adfresh.engine import render_previews

        render_previews(args.preview, parse_size(args.size))
        print(args.preview)
        return
    if args.background:
        pid = read_pid()
        if pid and pid_alive(pid):
            return
        daemonize()
        clear_quit()
    resolve_playback(args)
    try:
        if args.demo or args.child or args.display is not None:
            play(args)
        else:
            supervise(args)
    except Exception:
        import traceback

        log(traceback.format_exc())
        raise
    finally:
        if not args.demo and not args.child and os.getpid() == (read_pid() or os.getpid()):
            # The supervisor clears its own pid. A demo must not.
            if not args.demo and args.display is None and not args.child:
                clear_pid()


if __name__ == "__main__":
    main()
