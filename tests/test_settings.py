"""Settings file, idle-hook text, and the quick-settings row."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from adfresh.settings import (  # noqa: E402
    Settings,
    apply_idle,
    clean_idle,
    ensure_quick_settings,
    listener_block,
    listener_body,
    load_settings,
    remove_quick_settings,
    save_settings,
    splice_block,
    summary_rows,
    toggle_module,
)

SAMPLE_IDLE = """# BEGIN AD FRESH
# Flying toasters and the other night modules. The lock at 10 minutes takes over.
listener {
    timeout = 300
    on-timeout = $HOME/.local/bin/adfresh --background
    on-resume = $HOME/.local/bin/adfresh --stop
}
# END AD FRESH

# Warn
listener {
    timeout = 540
}
"""

QUICK = """  "Search for Keybinds") "$scriptsDir/KeyBinds.sh" ;;
  "Rainbow Borders Mode") rainbow_borders_menu ;;
  *) return ;;

  "[[ Misc ]]")
    options=$(
      cat <<EOF
Change Starship Prompt
Rainbow Borders Mode
EOF
    )
    ;;

  printf '%b\\n' "[[ Misc ]]\\x00meta\\x1fChange Starship Prompt Rainbow Borders Mode"
  printf '%s\\n' "[ Quick Links]"
  printf '%s\\n' "Manage User Defaults"
"""


class SettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_config = os.environ.get("XDG_CONFIG_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        if self._old_config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_config
        self._tmp.cleanup()

    def test_missing_file_uses_defaults(self) -> None:
        cfg = load_settings()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.idle_seconds, 300)
        self.assertEqual(cfg.dwell, 48)
        self.assertEqual(cfg.speed, 1)
        self.assertEqual(cfg.modules, [])
        self.assertIn("toasters", cfg.allowed_ids())
        rows = summary_rows(cfg)
        self.assertIn("5 minutes", rows[1])
        self.assertIn("All", rows[2])

    def test_round_trip_and_idle_snap(self) -> None:
        cfg = Settings(enabled=False, idle_seconds=400, dwell=90, speed=1.5, modules=["rain", "nope"])
        saved = save_settings(cfg)
        self.assertFalse(saved.enabled)
        self.assertEqual(saved.idle_seconds, clean_idle(400))
        self.assertEqual(saved.idle_seconds, 480)
        self.assertEqual(saved.modules, ["rain"])
        loaded = load_settings()
        self.assertEqual(loaded, saved)
        self.assertEqual(loaded.allowed_ids(), ["rain"])

    def test_default_listener_matches_the_installed_block(self) -> None:
        block = listener_block(Settings())
        self.assertTrue(SAMPLE_IDLE.startswith(block + "\n# Warn\n") or SAMPLE_IDLE.startswith(block))
        rewritten = splice_block(SAMPLE_IDLE, block)
        self.assertEqual(rewritten, SAMPLE_IDLE)
        self.assertIn("timeout = 300", listener_body(rewritten) or "")

    def test_disable_removes_the_listener_and_keeps_the_markers(self) -> None:
        path = Path(self._tmp.name) / "hypridle.conf"
        path.write_text(SAMPLE_IDLE, encoding="utf-8")
        cfg = Settings(enabled=False, idle_seconds=180)
        restarted = apply_idle(cfg, path=path, restart=False)
        text = path.read_text(encoding="utf-8")
        self.assertFalse(restarted)
        self.assertIn("# BEGIN AD FRESH", text)
        self.assertIn("# END AD FRESH", text)
        self.assertEqual(listener_body(text), "")
        self.assertIn("# Warn", text)
        again = apply_idle(cfg, path=path, restart=False)
        self.assertFalse(again)
        cfg.enabled = True
        cfg.idle_seconds = 120
        apply_idle(cfg, path=path, restart=False)
        text = path.read_text(encoding="utf-8")
        self.assertIn("timeout = 120", text)
        self.assertIn("on-timeout = $HOME/.local/bin/adfresh --background", text)
        self.assertEqual(text.count("# BEGIN AD FRESH"), 1)

    def test_last_module_stays_on(self) -> None:
        cfg = Settings(modules=["clock"])
        updated, kept = toggle_module(cfg, "clock")
        self.assertFalse(kept)
        self.assertEqual(updated.modules, ["clock"])
        updated, kept = toggle_module(cfg, "rain")
        self.assertTrue(kept)
        self.assertEqual(updated.allowed_ids(), ["rain", "clock"])

    def test_playback_reads_the_saved_file(self) -> None:
        import argparse

        from adfresh.__main__ import playlist_for, resolve_playback

        save_settings(Settings(dwell=20, speed=2, modules=["warp", "rain"]))
        args = argparse.Namespace(
            dwell=None, fade=None, speed=None, modules=None, module=None
        )
        resolve_playback(args)
        self.assertEqual(args.dwell, 20)
        self.assertEqual(args.fade, 1.35)
        self.assertEqual(args.speed, 2)
        self.assertEqual(args.allowed, ["rain", "warp"])
        self.assertEqual(set(playlist_for(args, 5.0, None)), {"rain", "warp"})
        args.dwell = 99
        args.modules = "toasters"
        resolve_playback(args)
        self.assertEqual(args.dwell, 99)
        self.assertEqual(args.allowed, ["toasters"])

    def test_quick_settings_row_is_idempotent(self) -> None:
        path = Path(self._tmp.name) / "Kool_Quick_Settings.sh"
        path.write_text(QUICK, encoding="utf-8")
        self.assertTrue(ensure_quick_settings(path))
        once = path.read_text(encoding="utf-8")
        self.assertIn("# BEGIN AD FRESH MENU", once)
        self.assertIn('"$HOME/.local/bin/adfresh" --settings', once)
        self.assertIn("AD Fresh Screensaver\nChange Starship Prompt", once)
        self.assertIn('printf \'%s\\n\' "AD Fresh Screensaver"', once)
        self.assertIn("AD Fresh Screensaver Rainbow Borders Mode", once)
        self.assertFalse(ensure_quick_settings(path))
        self.assertEqual(path.read_text(encoding="utf-8"), once)
        self.assertTrue(remove_quick_settings(path))
        self.assertEqual(path.read_text(encoding="utf-8"), QUICK)
        self.assertFalse(remove_quick_settings(path))


if __name__ == "__main__":
    unittest.main()
