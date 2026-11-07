"""GNOME integration: desktop detection, SDL choice, monitor-off mirror, idle daemon, install."""

from __future__ import annotations

import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from adfresh import __main__ as cli  # noqa: E402
from adfresh import gnome_idle, menu as menu_mod  # noqa: E402
from adfresh.runtime import configure_sdl, desktop_environment  # noqa: E402
from adfresh.settings import (  # noqa: E402
    MONITOR_OFF_POSITIVE,
    Settings,
    clean_monitor_off,
    effective_monitor_off,
    ensure_after_idle_change,
    gnome_screen_lock_available,
    load_settings,
    lower_idle_below,
    lower_idle_for_monitor_off,
    monitor_off_label,
    monitor_off_note,
    next_monitor_off,
    parse_gsettings_uint32,
    read_gnome_monitor_off,
    save_settings,
    summary_rows,
    sync_monitor_off,
    sync_monitor_off_mirror,
    write_gnome_monitor_off,
)

MANAGED_ENV = {
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_DESKTOP",
    "HYPRLAND_INSTANCE_SIGNATURE",
    "WAYLAND_DISPLAY",
    "DISPLAY",
    "SDL_VIDEODRIVER",
    "SDL_AUDIODRIVER",
    "PYGAME_HIDE_SUPPORT_PROMPT",
}


def desktop_env(**values: str) -> mock._patch:
    """Patch os.environ with a clean desktop-detection environment."""
    base = {key: value for key, value in os.environ.items() if key not in MANAGED_ENV}
    base.update(values)
    return mock.patch.dict(os.environ, base, clear=True)


def completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


class TempHomeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self._env = mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / "config"),
                "XDG_DATA_HOME": str(self.home / "data"),
                "XDG_STATE_HOME": str(self.home / "state"),
                "XDG_RUNTIME_DIR": str(self.home / "run"),
                "XDG_SESSION_ID": "",
                "DBUS_SESSION_BUS_ADDRESS": "",
            },
            clear=False,
        )
        self._env.start()
        self.addCleanup(self._env.stop)


class DesktopDetectionTest(unittest.TestCase):
    def test_gnome_wayland_uses_xwayland(self) -> None:
        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME", WAYLAND_DISPLAY="wayland-0", DISPLAY=":1"):
            self.assertEqual(desktop_environment(), "gnome")
            configure_sdl(False)
            self.assertEqual(os.environ["SDL_VIDEODRIVER"], "x11")
            self.assertEqual(os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"], "1")

    def test_explicit_sdl_driver_is_respected(self) -> None:
        with desktop_env(
            XDG_CURRENT_DESKTOP="ubuntu:GNOME",
            WAYLAND_DISPLAY="wayland-0",
            DISPLAY=":1",
            SDL_VIDEODRIVER="wayland",
        ):
            configure_sdl(False)
            self.assertEqual(os.environ["SDL_VIDEODRIVER"], "wayland")

    def test_hyprland_keeps_the_wayland_driver(self) -> None:
        with desktop_env(XDG_CURRENT_DESKTOP="Hyprland", WAYLAND_DISPLAY="wayland-1"):
            self.assertEqual(desktop_environment(), "hyprland")
            configure_sdl(False)
            self.assertEqual(os.environ["SDL_VIDEODRIVER"], "wayland")

    def test_gnome_wayland_without_xwayland_falls_back_to_wayland(self) -> None:
        with desktop_env(XDG_CURRENT_DESKTOP="GNOME", WAYLAND_DISPLAY="wayland-0"):
            configure_sdl(False)
            self.assertEqual(os.environ["SDL_VIDEODRIVER"], "wayland")

    def test_preview_is_headless(self) -> None:
        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME", WAYLAND_DISPLAY="wayland-0", DISPLAY=":1"):
            configure_sdl(True)
            self.assertEqual(os.environ["SDL_VIDEODRIVER"], "dummy")
            self.assertEqual(os.environ["SDL_AUDIODRIVER"], "dummy")

    def test_detection_names(self) -> None:
        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME"):
            self.assertEqual(desktop_environment(), "gnome")
        with desktop_env(XDG_CURRENT_DESKTOP="Hyprland"):
            self.assertEqual(desktop_environment(), "hyprland")
        with desktop_env(HYPRLAND_INSTANCE_SIGNATURE="abc"):
            self.assertEqual(desktop_environment(), "hyprland")
        with desktop_env(XDG_CURRENT_DESKTOP="KDE"):
            self.assertEqual(desktop_environment(), "other")
        with desktop_env():
            self.assertEqual(desktop_environment(), "other")


class MonitorOffLogicTest(TempHomeTest):
    def test_parse_gsettings_uint32(self) -> None:
        self.assertEqual(parse_gsettings_uint32("uint32 300\n"), 300)
        self.assertEqual(parse_gsettings_uint32("uint32 0"), 0)
        self.assertEqual(parse_gsettings_uint32("600"), 600)
        self.assertIsNone(parse_gsettings_uint32(""))
        self.assertIsNone(parse_gsettings_uint32("garbage"))
        self.assertIsNone(parse_gsettings_uint32("uint32 nope"))

    def test_labels(self) -> None:
        self.assertEqual(monitor_off_label(0), "Never")
        self.assertEqual(monitor_off_label(300), "5 minutes")
        self.assertEqual(monitor_off_label(420), "7 minutes")
        self.assertEqual(monitor_off_label(90), "90 seconds")

    def test_clean_monitor_off(self) -> None:
        self.assertEqual(clean_monitor_off(0), 0)
        self.assertEqual(clean_monitor_off(-10), 0)
        self.assertEqual(clean_monitor_off(300), 300)
        self.assertEqual(clean_monitor_off(420), 300)
        self.assertEqual(clean_monitor_off(560), 600)

    def test_next_monitor_off_keeps_the_saver_visible(self) -> None:
        self.assertEqual(next_monitor_off(60), 120)
        self.assertEqual(next_monitor_off(300), 600)
        self.assertEqual(next_monitor_off(480), 600)
        self.assertEqual(next_monitor_off(1800), MONITOR_OFF_POSITIVE[-1])

    def test_lower_idle_below(self) -> None:
        self.assertEqual(lower_idle_below(120), 60)
        self.assertEqual(lower_idle_below(300), 180)
        self.assertEqual(lower_idle_below(60), 60)

    def test_read_uses_gsettings(self) -> None:
        with mock.patch("adfresh.settings.subprocess.run", return_value=completed(stdout="uint32 420\n")) as run:
            self.assertEqual(read_gnome_monitor_off(), 420)
        self.assertEqual(run.call_args.args[0][1:], ["get", "org.gnome.desktop.session", "idle-delay"])

    def test_read_failure_returns_none(self) -> None:
        with mock.patch("adfresh.settings.subprocess.run", return_value=completed(returncode=1)):
            self.assertIsNone(read_gnome_monitor_off())
        with mock.patch("adfresh.settings.subprocess.run", side_effect=OSError("no gsettings")):
            self.assertIsNone(read_gnome_monitor_off())

    def test_write_falls_back_to_uint32_literal(self) -> None:
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return completed(returncode=1 if len(calls) == 1 else 0)

        with mock.patch("adfresh.settings.subprocess.run", side_effect=fake_run):
            self.assertTrue(write_gnome_monitor_off(600))
        self.assertEqual(calls[0][-1], "600")
        self.assertEqual(calls[1][-1], "uint32 600")

    def test_effective_value_prefers_gsettings_on_gnome(self) -> None:
        cfg = Settings(monitor_off_seconds=900)
        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME"):
            with mock.patch("adfresh.settings.read_gnome_monitor_off", return_value=300):
                self.assertEqual(effective_monitor_off(cfg), 300)
        with desktop_env(XDG_CURRENT_DESKTOP="Hyprland"):
            self.assertEqual(effective_monitor_off(cfg), 900)

    def test_summary_row_only_on_gnome_and_warns_on_conflict(self) -> None:
        cfg = Settings(idle_seconds=300, monitor_off_seconds=600)
        with mock.patch("adfresh.settings.read_gnome_monitor_off", return_value=600):
            rows = summary_rows(cfg, gnome=True)
        self.assertTrue(any(row.startswith("Monitor off") and "10 minutes" in row for row in rows))
        self.assertFalse(any(row.startswith("Monitor off") for row in summary_rows(cfg, gnome=False)))
        with mock.patch("adfresh.settings.read_gnome_monitor_off", return_value=300):
            conflict = summary_rows(Settings(idle_seconds=300), gnome=True)
        self.assertTrue(any("before saver!" in row for row in conflict))

    def test_idle_change_raises_monitor_off(self) -> None:
        cfg = Settings(idle_seconds=480, monitor_off_seconds=300)
        written: list[int] = []
        cfg, applied = ensure_after_idle_change(
            cfg, read=lambda: 300, write=lambda value: written.append(value) or True
        )
        self.assertEqual(applied, 600)
        self.assertEqual(written, [600])
        self.assertEqual(cfg.monitor_off_seconds, 600)
        self.assertEqual(cfg.idle_seconds, 480)

    def test_idle_change_needs_no_move(self) -> None:
        cfg = Settings(idle_seconds=300, monitor_off_seconds=600)
        written: list[int] = []
        cfg, applied = ensure_after_idle_change(
            cfg, read=lambda: 900, write=lambda value: written.append(value) or True
        )
        self.assertIsNone(applied)
        self.assertEqual(written, [])
        self.assertEqual(cfg.monitor_off_seconds, 900)

    def test_idle_change_never_when_off_is_never(self) -> None:
        cfg = Settings(idle_seconds=480, monitor_off_seconds=0)
        written: list[int] = []
        _, applied = ensure_after_idle_change(
            cfg, read=lambda: 0, write=lambda value: written.append(value) or True
        )
        self.assertIsNone(applied)
        self.assertEqual(written, [])

    def test_monitor_off_pick_lowers_saver_idle(self) -> None:
        written: list[int] = []
        cfg, idle, ok = lower_idle_for_monitor_off(
            Settings(idle_seconds=300), 300, gnome=True, write=lambda value: written.append(value) or True
        )
        self.assertTrue(ok)
        self.assertEqual(written, [300])
        self.assertEqual(idle, 180)
        self.assertEqual(cfg.idle_seconds, 180)
        self.assertEqual(cfg.monitor_off_seconds, 300)

    def test_monitor_off_never_leaves_idle_alone(self) -> None:
        written: list[int] = []
        cfg, idle, ok = lower_idle_for_monitor_off(
            Settings(idle_seconds=300), 0, gnome=True, write=lambda value: written.append(value) or True
        )
        self.assertTrue(ok)
        self.assertEqual(written, [0])
        self.assertEqual(idle, 300)
        self.assertEqual(cfg.monitor_off_seconds, 0)

    def test_monitor_off_pick_below_smallest_choice_raises_the_blank(self) -> None:
        written: list[int] = []
        cfg, idle, ok = lower_idle_for_monitor_off(
            Settings(idle_seconds=300), 60, gnome=True, write=lambda value: written.append(value) or True
        )
        self.assertTrue(ok)
        self.assertEqual(written, [600])
        self.assertEqual(idle, 300)
        self.assertEqual(cfg.monitor_off_seconds, 600)

    def test_install_seed_raises_blank_to_ten_minutes(self) -> None:
        written: list[int] = []
        cfg, off, changed = sync_monitor_off(
            Settings(idle_seconds=300), read=lambda: 300, write=lambda value: written.append(value) or True
        )
        self.assertTrue(changed)
        self.assertEqual(written, [600])
        self.assertEqual(off, 600)
        self.assertEqual(cfg.monitor_off_seconds, 600)

        state = {"off": 600}
        written.clear()

        def write(value: int) -> bool:
            state["off"] = value
            written.append(value)
            return True

        cfg, off, changed = sync_monitor_off(
            Settings(idle_seconds=300, monitor_off_seconds=600), read=lambda: state["off"], write=write
        )
        self.assertFalse(changed)
        self.assertEqual(written, [])
        self.assertEqual(off, 600)

    def test_install_seed_keeps_never(self) -> None:
        written: list[int] = []
        cfg, off, changed = sync_monitor_off(
            Settings(idle_seconds=300), read=lambda: 0, write=lambda value: written.append(value) or True
        )
        self.assertFalse(changed)
        self.assertEqual(written, [])
        self.assertEqual(off, 0)

    def test_mirror_follows_gsettings(self) -> None:
        cfg = sync_monitor_off_mirror(Settings(monitor_off_seconds=0), gnome=True, read=lambda: 300)
        self.assertEqual(cfg.monitor_off_seconds, 300)
        self.assertEqual(load_settings().monitor_off_seconds, 300)

    def test_monitor_off_round_trips_through_settings_json(self) -> None:
        saved = save_settings(Settings(monitor_off_seconds=600))
        self.assertEqual(saved.monitor_off_seconds, 600)
        self.assertEqual(load_settings().monitor_off_seconds, 600)


class IdleDecisionTest(unittest.TestCase):
    def decide(self, **changes) -> str:
        values = {
            "enabled": True,
            "locked": False,
            "inhibited": False,
            "idle_seconds": 300,
            "off_seconds": 600,
            "idle_ms": 0,
            "shield": False,
        }
        values.update(changes)
        return gnome_idle.idle_decision(**values)

    def test_activity_stops(self) -> None:
        self.assertEqual(self.decide(idle_ms=200), "stop")

    def test_waiting_is_none(self) -> None:
        self.assertEqual(self.decide(idle_ms=120_000), "none")

    def test_idle_starts_the_saver(self) -> None:
        self.assertEqual(self.decide(idle_ms=300_000), "show")
        self.assertEqual(self.decide(idle_ms=300_000, idle_seconds=60), "show")

    def test_disabled_never_shows(self) -> None:
        self.assertEqual(self.decide(idle_ms=600_000, enabled=False), "stop")

    def test_lock_stops(self) -> None:
        self.assertEqual(self.decide(idle_ms=600_000, locked=True), "stop")

    def test_inhibitor_stops(self) -> None:
        self.assertEqual(self.decide(idle_ms=600_000, inhibited=True), "stop")

    def test_monitor_off_stops_only_with_a_screen_shield(self) -> None:
        self.assertEqual(self.decide(idle_ms=600_000, off_seconds=600, shield=True), "stop")
        self.assertEqual(self.decide(idle_ms=1_000_000, off_seconds=600, shield=True), "stop")
        self.assertEqual(self.decide(idle_ms=600_000, off_seconds=600, shield=False), "show")
        self.assertEqual(self.decide(idle_ms=1_000_000, off_seconds=600, shield=False), "show")

    def test_never_keeps_the_saver_up(self) -> None:
        self.assertEqual(self.decide(idle_ms=3_600_000, off_seconds=0), "show")


class SessionParseTest(unittest.TestCase):
    TABLE = """2 1000 rucaradio -     3136 manager -    no  -
5 1000 rucaradio seat0 5525 user    tty1 yes 3min 20s ago
"""

    JSON = (
        '[{"session":"2","uid":1000,"user":"rucaradio","seat":null,"leader":3136,'
        '"class":"manager","tty":null},'
        '{"session":"5","uid":1000,"user":"rucaradio","seat":"seat0","leader":5525,'
        '"class":"user","tty":"tty1"}]'
    )

    def test_json_finds_the_seated_session(self) -> None:
        self.assertEqual(gnome_idle.parse_session_json(self.JSON, uid=1000), "5")

    def test_table_finds_the_seated_session(self) -> None:
        self.assertEqual(gnome_idle.parse_session_table(self.TABLE, uid=1000), "5")

    def test_foreign_uid_is_ignored(self) -> None:
        self.assertIsNone(gnome_idle.parse_session_json(self.JSON, uid=1001))
        self.assertIsNone(gnome_idle.parse_session_table(self.TABLE, uid=1001))

    def test_garbage_is_ignored(self) -> None:
        self.assertIsNone(gnome_idle.parse_session_json("not json", uid=1000))
        self.assertIsNone(gnome_idle.parse_session_table("", uid=1000))


class DaemonTest(TempHomeTest):
    def test_saver_alive_reads_the_pid_file(self) -> None:
        pid_file = Path(os.environ["XDG_RUNTIME_DIR"]) / "adfresh.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.assertFalse(gnome_idle.saver_alive())
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        self.assertTrue(gnome_idle.saver_alive())
        pid_file.write_text("999999999", encoding="utf-8")
        self.assertFalse(gnome_idle.saver_alive())

    def test_missing_launcher_does_not_start(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertFalse(gnome_idle.start_saver())

    def test_starts_when_idle_and_stops_on_activity(self) -> None:
        running = {"saver": False, "starts": 0, "stops": 0}

        def alive() -> bool:
            return running["saver"]

        def start() -> bool:
            running["saver"] = True
            running["starts"] += 1
            return True

        def stop() -> bool:
            running["saver"] = False
            running["stops"] += 1
            return True

        probe = FakeProbe([350_000, 350_000, 200, 200])
        with mock.patch.object(gnome_idle, "saver_alive", alive), mock.patch.object(
            gnome_idle, "start_saver", start
        ), mock.patch.object(gnome_idle, "stop_saver", stop), redirect_stdout(io.StringIO()):
            code = gnome_idle.run(
                probe=probe,
                settings_reader=lambda: (True, 300, 600),
                off_reader=lambda: 600,
                sleep=lambda _seconds: None,
                ticks=4,
            )
        self.assertEqual(code, 0)
        self.assertEqual(running["starts"], 1)
        self.assertEqual(running["stops"], 1)

    def test_disabled_settings_stop_the_saver(self) -> None:
        running = {"saver": True, "starts": 0, "stops": 0}
        probe = FakeProbe([350_000, 350_000])
        with mock.patch.object(gnome_idle, "saver_alive", lambda: running["saver"]), mock.patch.object(
            gnome_idle, "start_saver", lambda: running.__setitem__("starts", running["starts"] + 1)
        ), mock.patch.object(
            gnome_idle,
            "stop_saver",
            lambda: (running.__setitem__("saver", False), running.__setitem__("stops", running["stops"] + 1))[0],
        ), redirect_stdout(
            io.StringIO()
        ):
            gnome_idle.run(
                probe=probe,
                settings_reader=lambda: (False, 300, 600),
                off_reader=lambda: 600,
                sleep=lambda _seconds: None,
                ticks=2,
            )
        self.assertEqual(running["starts"], 0)
        self.assertEqual(running["stops"], 1)

    def test_never_spin_spawns_a_missing_launcher(self) -> None:
        attempts: list[int] = []

        def start() -> bool:
            attempts.append(1)
            return False

        probe = FakeProbe([350_000])
        with mock.patch.object(gnome_idle, "saver_alive", lambda: False), mock.patch.object(
            gnome_idle, "start_saver", start
        ), mock.patch.object(gnome_idle, "stop_saver", lambda: True), redirect_stdout(io.StringIO()):
            gnome_idle.run(
                probe=probe,
                settings_reader=lambda: (True, 300, 600),
                off_reader=lambda: 600,
                sleep=lambda _seconds: None,
                ticks=5,
            )
        self.assertEqual(len(attempts), 1)

    def test_once_prints_state_and_returns(self) -> None:
        probe = FakeProbe([120_000])
        out = io.StringIO()
        with mock.patch.object(gnome_idle, "saver_alive", lambda: False), redirect_stdout(out):
            code = gnome_idle.run(
                probe=probe,
                once=True,
                settings_reader=lambda: (True, 300, 600),
                off_reader=lambda: 600,
                sleep=lambda _seconds: None,
            )
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("idle_ms=120000", text)
        self.assertIn("shield=False", text)
        self.assertIn("action=none", text)

    def test_output_texts(self) -> None:
        launcher = cli.idle_launcher_text()
        self.assertIn("exec /usr/bin/python3 -m adfresh.gnome_idle", launcher)
        self.assertIn('ROOT="', launcher)
        service = cli.idle_service_text()
        self.assertIn("After=graphical-session.target", service)
        self.assertIn("Restart=on-failure", service)
        self.assertIn("WantedBy=default.target", service)
        self.assertIn("ExecStart=%h/.local/bin/adfresh-idle", service)
        self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus", service)

    def test_desktop_entries_use_the_given_launcher(self) -> None:
        binary = Path("/tmp/somewhere/adfresh")
        self.assertIn(f"Exec={binary} --demo", cli.desktop_text(binary))
        self.assertIn(f"Exec={binary} --settings", cli.settings_desktop_text(binary))


class MenuAbstractionTest(unittest.TestCase):
    def _which(self, name: str) -> str | None:
        return {"rofi": "/usr/bin/rofi", "zenity": "/usr/bin/zenity"}.get(name)

    def test_gnome_rofi_runs_without_wayland_display(self) -> None:
        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME", WAYLAND_DISPLAY="wayland-0", DISPLAY=":1"):
            with mock.patch.object(menu_mod.shutil, "which", side_effect=self._which), mock.patch.object(
                menu_mod.subprocess, "run", return_value=completed(stdout="Speed\n")
            ) as run:
                choice = menu_mod._ask("Speed", ["Speed", "Back"], "message", lines=2)
        self.assertEqual(choice, "Speed")
        env = run.call_args.kwargs["env"]
        self.assertNotIn("WAYLAND_DISPLAY", env)
        self.assertEqual(env["GDK_BACKEND"], "x11")

    def test_hyprland_rofi_keeps_its_environment(self) -> None:
        with desktop_env(XDG_CURRENT_DESKTOP="Hyprland", WAYLAND_DISPLAY="wayland-1"):
            with mock.patch.object(menu_mod.shutil, "which", side_effect=self._which), mock.patch.object(
                menu_mod.subprocess, "run", return_value=completed(stdout="Back\n")
            ) as run:
                menu_mod._ask("Speed", ["Back"], "message", lines=1)
        self.assertEqual(run.call_args.kwargs["env"]["WAYLAND_DISPLAY"], "wayland-1")

    def test_rofi_crash_falls_back_to_zenity(self) -> None:
        results = [
            completed(returncode=1, stderr="Wayland-ERROR: Rofi on wayland requires layer shell\n"),
            completed(stdout="●  Speed\n"),
        ]
        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME", WAYLAND_DISPLAY="wayland-0", DISPLAY=":1"):
            with mock.patch.object(menu_mod.shutil, "which", side_effect=self._which), mock.patch.object(
                menu_mod.subprocess, "run", side_effect=results
            ) as run:
                choice = menu_mod._ask("Speed", ["●  Speed", "○  Back"], "message", lines=2)
        self.assertEqual(choice, "●  Speed")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0][0], "zenity")

    def test_rofi_escape_is_a_cancel_not_a_fallback(self) -> None:
        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME", WAYLAND_DISPLAY="wayland-0", DISPLAY=":1"):
            with mock.patch.object(menu_mod.shutil, "which", side_effect=self._which), mock.patch.object(
                menu_mod.subprocess, "run", return_value=completed(returncode=1)
            ) as run:
                self.assertIsNone(menu_mod._ask("Speed", ["Back"], "message", lines=1))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][0], "rofi")

    def test_monitor_off_picker_message_warns_without_a_screen_shield(self) -> None:
        captured: dict = {}

        def fake_ask(prompt, rows, message, *, lines=8):
            captured["message"] = message
            return None

        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME"), mock.patch.object(
            menu_mod, "_ask", side_effect=fake_ask
        ), mock.patch.object(menu_mod, "gnome_screen_lock_available", return_value=False):
            menu_mod._pick_monitor_off(Settings())
        self.assertIn("not started by GDM", captured["message"])

        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME"), mock.patch.object(
            menu_mod, "_ask", side_effect=fake_ask
        ), mock.patch.object(menu_mod, "gnome_screen_lock_available", return_value=True):
            menu_mod._pick_monitor_off(Settings())
        self.assertNotIn("not started by GDM", captured["message"])

    def test_idle_hook_only_touches_hypridle(self) -> None:
        cfg = Settings()
        with desktop_env(XDG_CURRENT_DESKTOP="ubuntu:GNOME"), mock.patch.object(menu_mod, "apply_idle") as apply:
            menu_mod._apply_idle_hook(cfg)
            apply.assert_not_called()
        with desktop_env(XDG_CURRENT_DESKTOP="Hyprland"), mock.patch.object(menu_mod, "apply_idle") as apply:
            menu_mod._apply_idle_hook(cfg)
            apply.assert_called_once_with(cfg)


class ShieldAwarenessTest(TempHomeTest):
    def test_screen_lock_helper_reads_name_has_owner(self) -> None:
        with mock.patch(
            "adfresh.settings.subprocess.run", return_value=completed(stdout="(true,)\n")
        ) as run:
            self.assertTrue(gnome_screen_lock_available())
        self.assertIn("org.freedesktop.DBus.NameHasOwner", run.call_args.args[0])
        with mock.patch("adfresh.settings.subprocess.run", return_value=completed(stdout="(false,)")):
            self.assertFalse(gnome_screen_lock_available())
        with mock.patch("adfresh.settings.subprocess.run", return_value=completed(returncode=1)):
            self.assertFalse(gnome_screen_lock_available())
        with mock.patch("adfresh.settings.subprocess.run", side_effect=OSError("no gdbus")):
            self.assertFalse(gnome_screen_lock_available())

    def test_monitor_off_note(self) -> None:
        self.assertEqual(monitor_off_note(True), "")
        note = monitor_off_note(False)
        self.assertIn("not started by GDM", note)
        self.assertIn("keeps the saver on screen", note)

    def test_screen_shield_probe_caches_true(self) -> None:
        probe = gnome_idle.GnomeProbe()
        with mock.patch.object(gnome_idle, "_name_has_owner", return_value=True) as owner:
            self.assertTrue(probe.screen_shield_available(now=100.0))
            self.assertTrue(probe.screen_shield_available(now=101.0))
        self.assertEqual(owner.call_count, 1)

    def test_screen_shield_probe_rechecks_false(self) -> None:
        probe = gnome_idle.GnomeProbe()
        with mock.patch.object(gnome_idle, "_name_has_owner", return_value=False) as owner:
            self.assertFalse(probe.screen_shield_available(now=100.0))
            self.assertFalse(probe.screen_shield_available(now=105.0))
            self.assertEqual(owner.call_count, 1)
            self.assertFalse(probe.screen_shield_available(now=111.0))
            self.assertEqual(owner.call_count, 2)

    def test_screen_shield_probe_failure_is_false(self) -> None:
        probe = gnome_idle.GnomeProbe()
        with mock.patch.object(gnome_idle, "_name_has_owner", side_effect=RuntimeError("no bus")):
            with redirect_stdout(io.StringIO()):
                self.assertFalse(probe.screen_shield_available(now=100.0))

    def test_off_interval_keeps_the_saver_when_shield_is_missing(self) -> None:
        running = {"saver": True, "starts": 0, "stops": 0}
        slept = {"count": 0}

        def sleeper(_seconds: float) -> None:
            slept["count"] += 1
            if slept["count"] >= 3:
                raise KeyboardInterrupt

        probe = FakeProbe([700_000], shield=False)
        with mock.patch.object(gnome_idle, "saver_alive", lambda: running["saver"]), mock.patch.object(
            gnome_idle, "start_saver", lambda: running.__setitem__("starts", running["starts"] + 1)
        ), mock.patch.object(
            gnome_idle,
            "stop_saver",
            lambda: (running.__setitem__("saver", False), running.__setitem__("stops", running["stops"] + 1))[0],
        ), redirect_stdout(
            io.StringIO()
        ), self.assertRaises(
            KeyboardInterrupt
        ):
            gnome_idle.run(
                probe=probe,
                settings_reader=lambda: (True, 300, 600),
                off_reader=lambda: 600,
                sleep=sleeper,
            )
        self.assertEqual(running["starts"], 0)
        self.assertEqual(running["stops"], 0)

    def test_off_interval_stops_the_saver_with_a_shield(self) -> None:
        running = {"saver": True, "starts": 0, "stops": 0}
        slept = {"count": 0}

        def sleeper(_seconds: float) -> None:
            slept["count"] += 1
            if slept["count"] >= 3:
                raise KeyboardInterrupt

        probe = FakeProbe([700_000], shield=True)
        with mock.patch.object(gnome_idle, "saver_alive", lambda: running["saver"]), mock.patch.object(
            gnome_idle, "start_saver", lambda: running.__setitem__("starts", running["starts"] + 1)
        ), mock.patch.object(
            gnome_idle,
            "stop_saver",
            lambda: (running.__setitem__("saver", False), running.__setitem__("stops", running["stops"] + 1))[0],
        ), redirect_stdout(
            io.StringIO()
        ), self.assertRaises(
            KeyboardInterrupt
        ):
            gnome_idle.run(
                probe=probe,
                settings_reader=lambda: (True, 300, 600),
                off_reader=lambda: 600,
                sleep=sleeper,
            )
        self.assertEqual(running["starts"], 0)
        self.assertEqual(running["stops"], 1)

    def test_shield_note_is_logged_once(self) -> None:
        probe = FakeProbe([700_000], shield=False)
        out = io.StringIO()
        with mock.patch.object(gnome_idle, "saver_alive", lambda: False), mock.patch.object(
            gnome_idle, "start_saver", lambda: True
        ), redirect_stdout(out):
            gnome_idle.run(
                probe=probe,
                settings_reader=lambda: (True, 300, 600),
                off_reader=lambda: 600,
                sleep=lambda _seconds: None,
                ticks=4,
            )
        self.assertEqual(out.getvalue().count("GNOME screen shield unavailable"), 1)
        self.assertIn("keeping the saver on screen", out.getvalue())

    def test_once_reports_shield(self) -> None:
        probe = FakeProbe([700_000], shield=False)
        out = io.StringIO()
        with mock.patch.object(gnome_idle, "saver_alive", lambda: False), redirect_stdout(out):
            gnome_idle.run(
                probe=probe,
                once=True,
                settings_reader=lambda: (True, 300, 600),
                off_reader=lambda: 600,
                sleep=lambda _seconds: None,
            )
        text = out.getvalue()
        self.assertIn("shield=False", text)
        self.assertIn("action=show", text)


class FakeProbe:
    def __init__(
        self,
        idle_values: list[int],
        locked: bool = False,
        inhibited: bool = False,
        shield: bool = False,
    ) -> None:
        self.idles = list(idle_values)
        self.index = 0
        self.locked_value = locked
        self.inhibited_value = inhibited
        self.shield_value = shield

    def idle_ms(self) -> int | None:
        value = self.idles[min(self.index, len(self.idles) - 1)]
        self.index += 1
        return value

    def locked(self) -> bool:
        return self.locked_value

    def idle_inhibited(self) -> bool:
        return self.inhibited_value

    def screen_shield_available(self) -> bool:
        return self.shield_value


class InstallTest(TempHomeTest):
    def test_write_install_files_is_idempotent(self) -> None:
        paths = cli.install_paths()
        cli.write_install_files(paths, gnome=True)
        first = {
            path: path.read_bytes()
            for path in (
                paths.launcher,
                paths.menu_entry,
                paths.settings_entry,
                paths.idle_launcher,
                paths.service,
            )
        }
        cli.write_install_files(paths, gnome=True)
        second = {path: path.read_bytes() for path in first}
        self.assertEqual(first, second)
        self.assertEqual(stat.S_IMODE(paths.launcher.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(paths.idle_launcher.stat().st_mode), 0o755)
        self.assertTrue(paths.service.read_text(encoding="utf-8").startswith("[Unit]"))

    def test_gnome_install_seeds_and_is_idempotent(self) -> None:
        paths = cli.install_paths()
        state = {"off": 300}
        written: list[int] = []

        def fake_read() -> int:
            return state["off"]

        def fake_write(value: int) -> bool:
            state["off"] = value
            written.append(value)
            return True

        out = io.StringIO()
        with mock.patch.object(cli, "desktop_environment", return_value="gnome"), mock.patch.object(
            cli, "bake_icon"
        ), mock.patch.object(cli, "enable_gnome_service", return_value=True), mock.patch(
            "adfresh.settings.read_gnome_monitor_off", side_effect=fake_read
        ), mock.patch(
            "adfresh.settings.write_gnome_monitor_off", side_effect=fake_write
        ), mock.patch(
            "adfresh.settings.gnome_screen_lock_available", return_value=True
        ), redirect_stdout(
            out
        ):
            cli.install(paths)
            first = {
                path: path.read_bytes()
                for path in (paths.launcher, paths.menu_entry, paths.settings_entry, paths.idle_launcher, paths.service)
            }
            cli.install(paths)
            second = {path: path.read_bytes() for path in first}
        self.assertEqual(first, second)
        self.assertEqual(written, [600])
        self.assertEqual(load_settings().monitor_off_seconds, 600)
        text = out.getvalue()
        self.assertIn("raised GNOME screen-off to 10 minutes", text)
        self.assertIn("AD Fresh starts after 5 minutes", text)
        self.assertTrue(paths.idle_launcher.exists())
        self.assertTrue(paths.service.exists())

    def test_gnome_install_warns_when_service_cannot_start(self) -> None:
        paths = cli.install_paths()
        out = io.StringIO()
        with mock.patch.object(cli, "desktop_environment", return_value="gnome"), mock.patch.object(
            cli, "bake_icon"
        ), mock.patch.object(cli, "enable_gnome_service", return_value=False), mock.patch(
            "adfresh.settings.read_gnome_monitor_off", return_value=0
        ), mock.patch(
            "adfresh.settings.gnome_screen_lock_available", return_value=True
        ), redirect_stdout(
            out
        ):
            cli.install(paths)
        self.assertIn("could not start adfresh-idle.service", out.getvalue())
        self.assertIn("monitor   GNOME turns the screen off after Never", out.getvalue())

    def test_hyprland_install_leaves_gnome_alone(self) -> None:
        paths = cli.install_paths()
        paths.hypridle.parent.mkdir(parents=True, exist_ok=True)
        paths.hypridle.write_text("# Warn\nlistener {\n    timeout = 540\n}\n", encoding="utf-8")
        with mock.patch.object(cli, "desktop_environment", return_value="hyprland"), mock.patch.object(
            cli, "bake_icon"
        ), mock.patch.object(cli, "enable_gnome_service") as service, mock.patch(
            "adfresh.__main__.subprocess.run", return_value=completed()
        ), redirect_stdout(
            io.StringIO()
        ), mock.patch(
            "adfresh.settings.ensure_quick_settings"
        ):
            cli.install(paths)
        service.assert_not_called()
        conf = paths.hypridle.read_text(encoding="utf-8")
        self.assertIn("# BEGIN AD FRESH", conf)
        self.assertIn("on-timeout = $HOME/.local/bin/adfresh --background", conf)

    def test_gnome_install_notes_when_screen_shield_is_missing(self) -> None:
        paths = cli.install_paths()
        out = io.StringIO()
        with mock.patch.object(cli, "desktop_environment", return_value="gnome"), mock.patch.object(
            cli, "bake_icon"
        ), mock.patch.object(cli, "enable_gnome_service", return_value=True), mock.patch(
            "adfresh.settings.read_gnome_monitor_off", return_value=600
        ), mock.patch(
            "adfresh.settings.gnome_screen_lock_available", return_value=False
        ), redirect_stdout(
            out
        ):
            cli.install(paths)
        text = out.getvalue()
        self.assertIn("GNOME's screen blank/lock is unavailable in this SDDM session", text)
        self.assertIn("The monitor-off interval will not turn the display off", text)
        self.assertIn("Log in through GDM (gdm3 is installed, disabled)", text)

    def test_gnome_uninstall_removes_files_and_is_idempotent(self) -> None:
        paths = cli.install_paths()
        cli.write_install_files(paths, gnome=True)
        with mock.patch.object(cli, "desktop_environment", return_value="gnome"), mock.patch.object(
            cli, "_systemctl", return_value=0
        ), mock.patch.object(cli, "stop_running") as stop, redirect_stdout(io.StringIO()) as out:
            cli.uninstall(paths)
            cli.uninstall(paths)
        self.assertTrue(stop.called)
        for path in (
            paths.launcher,
            paths.menu_entry,
            paths.settings_entry,
            paths.idle_launcher,
            paths.service,
        ):
            self.assertFalse(path.exists())
        self.assertIn("GNOME screen blank and lock settings were left as they are", out.getvalue())


if __name__ == "__main__":
    unittest.main()
