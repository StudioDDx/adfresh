"""GNOME idle watcher for AD Fresh.

This module runs on the *system* Python: only that interpreter has PyGObject
(Gio). AD Fresh itself stays on the project virtualenv. `adfresh --install` on
GNOME writes `~/.local/bin/adfresh-idle` and a systemd --user unit for it.

The watcher polls Mutter's idle time, GNOME's idle inhibitor flag, the logind
lock hint, and `org.gnome.desktop.session idle-delay` (the monitor-off
interval). When the desktop has been idle for the saved delay it starts
`~/.local/bin/adfresh --background`; on activity, lock, an idle inhibitor,
GNOME blanking the screen, or the saver being turned off it calls
`~/.local/bin/adfresh --stop`. When gnome-shell does not export
`org.gnome.Shell.ScreenShield` (e.g. this SDDM-started session), GNOME can
never blank or lock, so the monitor-off interval does not stop the saver: it
stays on screen until real activity, lock, or the saver being disabled.

Use `--once` to print the current inputs/decision and `--dry-run` to log
decisions without starting or stopping anything.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from adfresh.runtime import log, pid_alive, read_pid

POLL_SECONDS = 0.5
REFRESH_SECONDS = 2.0
ACTIVITY_SECONDS = 1.0
LAUNCH_COOLDOWN = 10.0

IDLE_INHIBIT_FLAG = 8

MUTTER_BUS = "org.gnome.Mutter.IdleMonitor"
MUTTER_PATH = "/org/gnome/Mutter/IdleMonitor/Core"
MUTTER_INTERFACE = "org.gnome.Mutter.IdleMonitor"

SESSION_BUS = "org.gnome.SessionManager"
SESSION_PATH = "/org/gnome/SessionManager"
SESSION_INTERFACE = "org.gnome.SessionManager"

SCREEN_SHIELD_NAME = "org.gnome.Shell.ScreenShield"
SHIELD_REFRESH_SECONDS = 10.0
SHIELD_UNAVAILABLE_NOTE = (
    "GNOME screen shield unavailable (session not started by GDM); "
    "the monitor-off interval cannot turn the display off — keeping the saver on screen"
)


def announce(message: str) -> None:
    """Write to the state log and to stdout, which systemd captures in the journal."""
    log(message)
    try:
        print(message, flush=True)
    except (OSError, ValueError):
        pass


def saver_launcher() -> Path:
    return Path.home() / ".local" / "bin" / "adfresh"


def saver_alive() -> bool:
    pid = read_pid()
    return bool(pid and pid_alive(pid))


def start_saver() -> bool:
    path = saver_launcher()
    if not path.exists():
        announce(f"gnome idle: launcher missing at {path}")
        return False
    announce("gnome idle: starting the screensaver")
    try:
        subprocess.Popen(
            [str(path), "--background"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        announce(f"gnome idle: could not start the screensaver: {exc}")
        return False
    return True


def stop_saver() -> bool:
    path = saver_launcher()
    if not path.exists():
        announce(f"gnome idle: launcher missing at {path}")
        return False
    announce("gnome idle: stopping the screensaver")
    try:
        subprocess.run(
            [str(path), "--stop"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        announce(f"gnome idle: could not stop the screensaver: {exc}")
        return False
    return True


def idle_decision(
    *,
    enabled: bool,
    locked: bool,
    inhibited: bool,
    idle_seconds: int,
    off_seconds: int,
    idle_ms: int,
    shield: bool = False,
) -> str:
    """Return "show", "stop", or "none" for the current desktop state.

    ``shield`` says whether GNOME will really blank/lock the screen. Only then
    does reaching the monitor-off interval stop the saver: without a screen
    shield the saver is the only thing protecting the display, so it stays up.
    """
    if not enabled or locked or inhibited:
        return "stop"
    seconds = max(0.0, int(idle_ms) / 1000.0)
    if seconds < ACTIVITY_SECONDS:
        return "stop"
    if shield and off_seconds > 0 and seconds >= off_seconds:
        return "stop"
    if seconds >= int(idle_seconds):
        return "show"
    return "none"


def _name_has_owner(name: str) -> bool:
    """Ask the session bus whether a well-known name is currently owned."""
    from gi.repository import GLib, Gio

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    result = bus.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameHasOwner",
        GLib.Variant("(s)", (name,)),
        GLib.VariantType.new("(b)"),
        Gio.DBusCallFlags.NONE,
        1000,
        None,
    )
    return bool(result.unpack()[0])


def parse_session_json(text: str, uid: int | None = None) -> str | None:
    """Pick the desktop session out of `loginctl list-sessions --json=short`."""
    try:
        entries = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(entries, list):
        return None
    wanted = os.getuid() if uid is None else int(uid)
    mine = [entry for entry in entries if isinstance(entry, dict) and entry.get("uid") == wanted]
    if not mine:
        return None
    graphical = [entry for entry in mine if entry.get("seat") == "seat0"]
    users = [entry for entry in graphical if entry.get("class") == "user"] or graphical
    chosen = (users or mine)[-1]
    session = chosen.get("session")
    return str(session) if session else None


def parse_session_table(text: str, uid: int | None = None) -> str | None:
    """Pick the desktop session out of the plain loginctl columns.

    Columns are ID UID USER SEAT LEADER CLASS TTY ... so the seat is field 3
    and the class is field 5 (both are absent on older logind versions).
    """
    wanted = str(os.getuid() if uid is None else int(uid))
    graphical: list[str] = []
    seated: list[str] = []
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[1] != wanted:
            continue
        seated.append(parts[0])
        if parts[3] == "seat0" and (len(parts) < 6 or parts[5] == "user"):
            graphical.append(parts[0])
    candidates = graphical or seated
    return candidates[-1] if candidates else None


def find_session_id(use_env: bool = True) -> str | None:
    """The logind session that belongs to this desktop (XDG_SESSION_ID is often empty or stale)."""
    if use_env:
        current = os.environ.get("XDG_SESSION_ID")
        if current and current != "auto":
            return current
    for command, parser in (
        (["loginctl", "list-sessions", "--no-legend", "--json=short"], parse_session_json),
        (["loginctl", "list-sessions", "--no-legend"], parse_session_table),
    ):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        session = parser(result.stdout)
        if session:
            return session
    return None


class GnomeProbe:
    """Read Mutter idle time, the idle inhibitor flag, and the logind lock hint."""

    def __init__(self) -> None:
        self._idle_proxy = None
        self._inhibit_proxy = None
        self._session_id: str | None = None
        self._use_env_session = True
        self._shield: bool | None = None
        self._shield_checked = float("-inf")
        self._warned = {"idle": False, "inhibit": False, "lock": False, "shield": False}

    @staticmethod
    def _ensure_bus_address() -> None:
        if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            return
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime:
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"

    def _proxy(self, bus_name: str, path: str, interface: str):
        from gi.repository import Gio

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            bus_name,
            path,
            interface,
            None,
        )

    def _warn(self, key: str, message: str) -> None:
        if not self._warned[key]:
            self._warned[key] = True
            announce(message)

    def idle_ms(self) -> int | None:
        """Milliseconds since the last input, from Mutter. None when unavailable."""
        try:
            from gi.repository import Gio

            self._ensure_bus_address()
            if self._idle_proxy is None:
                self._idle_proxy = self._proxy(MUTTER_BUS, MUTTER_PATH, MUTTER_INTERFACE)
            result = self._idle_proxy.call_sync(
                "GetIdletime",
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
            self._warned["idle"] = False
            return int(result.unpack()[0])
        except Exception as exc:  # gi missing, bus down, or Mutter not there
            self._idle_proxy = None
            self._warn("idle", f"gnome idle: Mutter idle monitor unavailable: {exc}")
            return None

    def idle_inhibited(self) -> bool | None:
        """True when an application holds an idle inhibitor (video, presentation)."""
        try:
            from gi.repository import GLib, Gio

            self._ensure_bus_address()
            if self._inhibit_proxy is None:
                self._inhibit_proxy = self._proxy(SESSION_BUS, SESSION_PATH, SESSION_INTERFACE)
            result = self._inhibit_proxy.call_sync(
                "IsInhibited",
                GLib.Variant("(u)", (IDLE_INHIBIT_FLAG,)),
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
            self._warned["inhibit"] = False
            return bool(result.unpack()[0])
        except Exception as exc:
            self._inhibit_proxy = None
            self._warn("inhibit", f"gnome idle: idle inhibitor check unavailable: {exc}")
            return None

    def screen_shield_available(self, now: float | None = None) -> bool:
        """True when gnome-shell exports org.gnome.Shell.ScreenShield.

        Only a GDM-started session provides it; under SDDM or a plain Wayland
        compositor GNOME never blanks or locks, so the daemon must keep the
        saver on screen instead of revealing the desktop at the blank interval.
        """
        now = time.monotonic() if now is None else float(now)
        if self._shield is True:
            return True
        if self._shield is False and now - self._shield_checked < SHIELD_REFRESH_SECONDS:
            return False
        try:
            self._ensure_bus_address()
            value = bool(_name_has_owner(SCREEN_SHIELD_NAME))
        except Exception as exc:
            value = False
            self._warn("shield", f"gnome idle: screen shield probe unavailable: {exc}")
        self._shield = value
        self._shield_checked = now
        return value

    def locked(self) -> bool | None:
        """loginctl LockedHint for the desktop session. None when unavailable."""
        if self._session_id is None:
            self._session_id = find_session_id(use_env=self._use_env_session)
            self._use_env_session = False
        if not self._session_id:
            self._warn("lock", "gnome idle: could not find the logind session")
            return None
        try:
            result = subprocess.run(
                ["loginctl", "show-session", self._session_id, "-p", "LockedHint"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._warn("lock", f"gnome idle: lock state unavailable: {exc}")
            return None
        text = result.stdout.strip()
        if result.returncode == 0 and "=yes" in text:
            self._warned["lock"] = False
            return True
        if result.returncode == 0 and "=no" in text:
            self._warned["lock"] = False
            return False
        # The cached session id may be stale after a re-login.
        self._session_id = None
        self._warn("lock", "gnome idle: could not read the logind lock state")
        return None


def read_saver_settings() -> tuple[bool, int, int] | None:
    """(enabled, saver idle seconds, cached monitor-off seconds) from settings.json."""
    from adfresh.settings import load_settings

    try:
        cfg = load_settings()
    except Exception as exc:
        announce(f"gnome idle: settings unavailable: {exc}")
        return None
    return bool(cfg.enabled), int(cfg.idle_seconds), max(0, int(cfg.monitor_off_seconds))


def read_monitor_off() -> int | None:
    from adfresh.settings import read_gnome_monitor_off

    try:
        return read_gnome_monitor_off()
    except Exception:
        return None


def run(
    *,
    probe: GnomeProbe | None = None,
    dry_run: bool = False,
    once: bool = False,
    settings_reader=None,
    off_reader=None,
    shield_reader=None,
    sleep=time.sleep,
    ticks: int | None = None,
) -> int:
    """Watch the right inputs and start/stop the saver. Returns the process exit code."""
    probe = probe or GnomeProbe()
    settings_reader = settings_reader or read_saver_settings
    off_reader = off_reader or read_monitor_off
    if shield_reader is None:
        shield_reader = getattr(probe, "screen_shield_available", None) or (lambda: False)

    stopping = {"value": False}

    def _stop(_signum, _frame) -> None:
        stopping["value"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    announce("gnome idle: watching Mutter idle time")
    state: dict = {}
    next_refresh = 0.0
    next_launch = 0.0
    last_action = "none"
    shield_note_logged = False
    remaining = ticks

    while not stopping["value"]:
        now = time.monotonic()
        if now >= next_refresh:
            next_refresh = now + REFRESH_SECONDS
            settings = settings_reader()
            if settings is not None:
                enabled, idle_seconds, cached_off = settings
                raw_off = off_reader()
                if raw_off is None:
                    raw_off = cached_off
                state.update(
                    {
                        "enabled": bool(enabled),
                        "idle_seconds": int(idle_seconds),
                        "off_seconds": max(0, int(raw_off or 0)),
                        "locked": bool(probe.locked()),
                        "inhibited": bool(probe.idle_inhibited()),
                        "shield": bool(shield_reader()),
                    }
                )

        idle = probe.idle_ms()
        if idle is None or not state:
            action = "none"
        else:
            action = idle_decision(
                enabled=state["enabled"],
                locked=state["locked"],
                inhibited=state["inhibited"],
                idle_seconds=state["idle_seconds"],
                off_seconds=state["off_seconds"],
                idle_ms=int(idle),
                shield=state.get("shield", False),
            )

        if once:
            print(
                "gnome-idle "
                f"idle_ms={idle if idle is not None else 'unknown'} "
                f"enabled={state.get('enabled')} "
                f"idle_seconds={state.get('idle_seconds')} "
                f"off_seconds={state.get('off_seconds')} "
                f"locked={state.get('locked')} "
                f"inhibited={state.get('inhibited')} "
                f"shield={state.get('shield')} "
                f"action={action} "
                f"saver={saver_alive()}"
            )
            return 0

        idle_seconds = int(idle) // 1000 if idle is not None else 0
        if (
            idle is not None
            and action == "show"
            and not state.get("shield", False)
            and state.get("off_seconds", 0) > 0
            and idle_seconds >= state["off_seconds"]
            and not shield_note_logged
        ):
            shield_note_logged = True
            announce(SHIELD_UNAVAILABLE_NOTE)

        if dry_run and action != last_action:
            announce(f"gnome idle: action={action} idle={idle_seconds}s")
        last_action = action

        if dry_run:
            pass
        elif action == "show":
            if not saver_alive() and now >= next_launch:
                next_launch = now + LAUNCH_COOLDOWN
                start_saver()
        elif action == "stop":
            if saver_alive():
                stop_saver()

        if remaining is not None:
            remaining -= 1
            if remaining <= 0:
                break
        sleep(POLL_SECONDS)

    if not dry_run and saver_alive():
        stop_saver()
    announce("gnome idle: stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="adfresh-idle",
        description="Start and stop AD Fresh around GNOME's idle and lock state.",
    )
    parser.add_argument("--once", action="store_true", help="print the current state and exit")
    parser.add_argument("--dry-run", action="store_true", help="log decisions without starting or stopping")
    args = parser.parse_args(argv)
    return run(dry_run=args.dry_run, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
