# AD Fresh

A modular night screensaver in the spirit of the classic After Dark suites. The
drawings are original: chrome toasters with cream wings, buttered and dark toast,
a 3D pipe maze, and nine other modules for the after-hours desk.

Modules: Flying Toasters, Starry Night, Aurora, Aquatic Realm, Hard Rain, Lava
Lamp, Pipes, Warp, Mystify, Marbles, Mountains, Lunatic Fringe, Clock,
Messages, Satori.

## Run

```bash
scripts/adfresh --demo          # window, arrow keys change modules
scripts/adfresh                 # cover every monitor; any input closes it
scripts/adfresh --module rain
scripts/adfresh --list
scripts/adfresh --preview build/preview
```

Demo keys: arrows cycle, `1`–`0` and `-` jump, space pauses, `f` fills the
screen, `r` returns to the automatic cycle, `=` speeds up, shift-minus slows
down, esc quits.

Dependencies live in `requirements.txt` (`pygame-ce`, `numpy`); the project
virtualenv at `.venv` already has them.

## Ubuntu desktop (GNOME)

This is the supported setup on Ubuntu 26.04 / GNOME 50 Wayland, including the
two-monitor desktop in this workspace.

```bash
scripts/adfresh --install
```

`--install` writes:

- `~/.local/bin/adfresh` (launcher)
- application menu entries for AD Fresh and AD Fresh Settings
- `~/.local/bin/adfresh-idle` and a systemd user unit
  `~/.config/systemd/user/adfresh-idle.service`

The idle watcher (`adfresh-idle`, plain system Python + Gio) follows Mutter's
idle monitor, holds off while an application inhibits idle (video, presentation),
stops for a locked session, and starts `adfresh` once the desk has been idle for
the saved delay. The saver covers **every monitor in true fullscreen** through
XWayland (SDL's native Wayland driver cannot place one window per monitor), so
the GNOME panel and dock are covered too. Any input dismisses it.

### One canvas across the monitors

The saver does not run two independent scenes. The supervisor first asks SDL
for the true rectangle of every display index (Wayland may enumerate display 0
as the right-hand monitor, and the idle service has no `DISPLAY` for xrandr),
then falls back to XRandR or Hyprland's monitor list. That defines **one virtual
canvas covering the whole layout**. Each monitor gets a fullscreen window showing its
crop of that single canvas, and every display process runs the same deterministic
fixed-timestep simulation from the same seed. Animation therefore continues
across the monitor boundary instead of restarting on each screen: a toaster, a
rain streak or a pipe can cross the seam, and the brand/title appear once on the
virtual canvas (far left / far right) rather than on every monitor. If the
geometry cannot be trusted (odd layouts, mixed sizes), the saver falls back to
independent per-display windows. Set `ADFRESH_SPAN=0` in the environment to force
that independent mode (slightly faster on very slow software-composited
sessions); it is on by default.

The GNOME session must be able to blank or lock for the screen to turn off at
the monitor-off interval. If GNOME cannot do that (for example this machine's
session is started by **SDDM**, which leaves GNOME without
`org.gnome.DisplayManager` and therefore without its screen shield), the
installer prints a note, the watcher logs it once, and AD Fresh keeps the saver
on screen instead of exposing the desktop. Logging in through GDM restores
GNOME's native blank + lock; `gdm3` is installed here but disabled. AD Fresh
does not change the display manager for you.

`adfresh --stop` closes a running saver. `adfresh --uninstall` disables and
removes the watcher, launcher, menu entries, and leaves the GNOME screen-blank
setting as it is.

## Hyprland

`adfresh --install` writes:

- `~/.local/bin/adfresh`
- application menu entries for AD Fresh and AD Fresh Settings
- a row in the system quick-settings menu
- a hypridle listener

The existing lock still runs at 10 minutes. The saver steps aside when hyprlock
starts. `adfresh --stop` closes it early. `adfresh --uninstall` removes the hook
and the settings row.

Idle tracking is left alone: the program asks SDL not to inhibit the
screensaver, so the lock still arrives.

## Settings

Open **AD Fresh Settings** in the application launcher, or run
`adfresh --settings`. On Hyprland the same menu is in the system quick settings
(**Super+Shift+E**). The menu uses rofi (falling back to zenity), and works on
GNOME Wayland by running rofi through XWayland.

The menu sets whether the saver is on, how long the desk sits idle before it
starts (1, 2, 3, 5, or 8 minutes), which modules play, how long each one stays
up, the speed, and — on GNOME — the **Monitor off** interval. Choices are stored
in `~/.config/adfresh/settings.json`; the next time the screensaver starts it
uses that file.

On GNOME, **Monitor off** is the same setting as Ubuntu's
*Settings → Power → Screen Blank* (`org.gnome.desktop.session idle-delay`), so
changing it in either place changes both. The saver always starts before the
screen turns off: raising the start delay past the monitor-off interval moves
the monitor-off interval later, and picking a monitor-off interval at or before
the start delay moves the start delay earlier. If GNOME's blank/lock is not
available (SDDM session), the picker says so and the saver stays on screen.
On Hyprland the menu keeps using the hypridle listener and the 10-minute lock.

## Pipes

The **Pipes** module is a modern take on the classic 3D pipe screensaver:
five independent pipe systems (chrome, teal, copper, blue steel, muted rose)
grow one grid cell at a time, turn at right angles, never cross each other, and
recycle when blocked. Joints are shaded spheres and elbow rings, tubes carry a
specular stripe, and a slowly drifting 3/4 camera plus night fog gives the
lattice depth. If several systems finish at once they fade out and a fresh maze
grows in.

## Aquatic Realm

The aquarium is drawn as a real tank, not an open-water backdrop:

- Metal rim with an inner black silicone lip and a glass top; an air gap and
  animated waterline/meniscus sit below the rim, and faint glass reflections
  and a vignette sit over the whole view.
- Layered depth: god rays, a smooth water column, distant boulder silhouettes,
  out-of-focus background plants, and a dark foreground layer that frames the
  view.
- Aquascape: gradient sand with gravel/pebbles and buried ripples, boulders with
  moss and speckle texture, a driftwood branch, a filter intake and glass
  heater, and static mushroom/brain/zoanthid corals.
- Plants: vallisneria ribbons, broad amazon swords (one bronze accent), java
  fern, stem plants, and a low carpet; all sway gently.
- Fish tails swish: each sprite is warped into an 8-frame tail cycle (head
  fixed, rear columns driven by a sine wave), mirrored for swimming direction.
  Bubbles, marine snow and caustics animate over the scene.
- Tap/click on the glass: a click is handed to the module (the engine only
  dismisses the saver on a key press, mouse movement, or an unconsumed click).
  Aquarium taps make expanding glass ripples and startle nearby fish away.
- Night mode: between 19:00 and 06:00 the tank uses a dark moonlight palette,
  dimmer/cooler rays and caustics, a stronger vignette and moon glow; fish swim
  slower. `ADFRESH_NIGHT=0`/`1` forces day/night for testing.

## Flying Toasters wings

Each flyer is composed from a single photographic body plate and one reusable
wing raster: the near wing sits in front of the body, the far wing is its
mirror image (smaller, dimmer) behind the far shoulder. Both wings rotate
around their own shoulder pivot, mirrored, so the two wing tips rise and fall
together like a bird's wings instead of one wing flapping up/down while the
other swings sideways.

The revised beat has three 3D cues:

- Foreshortening: each wing's apparent span changes with the flap (the near
  wing grows as it comes down toward the viewer; the far wing grows on the
  upstroke).
- A wider, asymmetric far-wing arc: the far wing sweeps high over the back on
  the upstroke, then folds well down behind the body on the downstroke, where
  the body hides it. This is what the flat, mirrored swivel was missing.
- Framing: the body plate is scaled down and centred inside the sprite frame so
  both wings have room to swing without clipping; the module compensates the
  draw size, so the on-screen body is the same size as before.

The body is one static plate and cannot shimmer between frames. This models
the wingbeat kinematics only; whether the toaster would actually generate lift
depends on mass, wing area and flap rate, which are unknown.

The flying toast uses the same two-layer rig, but both wings stay visible at
the bread's left and right edges (the far wing sits behind the bread, the near
wing in front). The revised toast beat raises both wings higher on the
upstroke and opens them wider on the downstroke; the far wing is now close to
the near wing in size and brightness instead of a dim, tucked sliver. The
toast canvas is taller (600×500, body centred) to give the wider wing arc room
without clipping.

## Sprite maps

The composed flyers can be exported as reusable sprite sheets (atlas PNGs plus
JSON frame maps with wing pivots and per-frame flap parameters):

```bash
.venv/bin/python scripts/export_sprites.py                 # toaster + plain toast
.venv/bin/python scripts/export_sprites.py --all-toasts    # every toast topping
.venv/bin/python scripts/export_sprites.py --toast-kind butter
# writes to build/sprites/ ; optional first argument overrides the directory
```

Outputs:

- `toaster-sprite-map.png` — transparent atlas of the 16 toaster flap frames
  (4×4, 600×668 px cells, row-major).
- `toaster-sprite-map-preview.png` — labeled preview of the same frames.
- `toaster-sprite-map.json` — frame rectangles, shoulder anchors, wing pivots,
  flap angles, foreshortening scales, and the composition parameters.
- `toast-<kind>-sprite-map.*` — the same for one flying-toast topping. The
  plain toast map is exported by default; butter, jam and dark are one flag
  away (`--all-toasts` or repeated `--toast-kind`). Each kind has its own
  16-frame atlas (4×4, 600×500 px cells) because each topping is a different
  bread plate.

The export is deterministic and generated from the live sprite composer, so it
always matches what the screensaver draws.
