# Light Calibration

Two bulbs of the same model, sent the same settings, do not produce the same
light. Cheap fixtures are worse: one runs green, another runs magenta, a third
is a third dimmer than the rest at the same percentage. An automation or a
scene will happily send them identical commands, and the room still looks wrong.

This integration fixes that by **calibrating a light against one you trust**,
using nothing but your eyes. No colorimeter, no extra hardware, no external
software.

It creates a **virtual light entity that takes over the original's entity ID**,
so everything already pointing at that light — scenes, automations,
dashboards, voice — keeps working unchanged and starts getting corrected
output.

## How calibration works

Pick a reference light: one you consider correct. Then run the guided
calibration from the integration's settings page.

At each step the integration drives the reference to a chosen setting and the
target as close as it can compute, and shows you sliders. You adjust until the
two match by eye, then move on. Sliders are live — the light follows as you
drag, with no submit button.

**White steps** give you three controls: warm/cool (a Kelvin offset),
green/magenta (a tint), and brightness. **Colour steps** give you hue shift,
saturation, and brightness.

The tint runs from -100 (green removed entirely, full magenta) to +400 (five
times the green). It is lopsided on purpose: some RGB strips' whites come out
so purple that they need green several times over.

Moving the tint does not change how bright the light looks. Adding green
genuinely makes a colour brighter — green carries most of what the eye reads as
brightness — so that is taken back out of the brightness command automatically.
Otherwise the two sliders fight and you chase them round in circles.

**Compare** flashes the light back to no correction at all for a moment, then
returns. A difference that is invisible while you stare at two lights is obvious
the moment one of them changes, so this is the quickest way to tell whether an
adjustment is helping.

| Depth | Points | Roughly |
|---|---|---|
| Colours only | 6 hues | 5 min |
| Quick | 5 whites | 3 min |
| Standard | 9 whites | 8 min |
| Standard + colours | 9 whites, 6 hues | 13 min |
| Thorough | 15 whites | 15 min |
| Thorough + colours | 15 whites, 12 hues | 25 min |

Steps your reference light cannot show are skipped rather than measured
against whatever it clamps to — several presets ask for 2000 K and plenty of
bulbs stop at 2700 K. The dialog says which were dropped.

At the end a few of the measured points are replayed with the finished profile
applied, so you see the result as a whole before it is saved. If one is wrong,
go back and redo it; nothing measured is lost either way.

**Tunable-white lights** are calibrated too, on the axes they actually have:
colour temperature and brightness. Tint and the colour steps are not offered,
because a fixture with no colour control has no way to render either — so only
the white depths appear for one.

When you finish, the reference light is put back exactly as it was.

## What it does with the measurements

Corrections are interpolated, not looked up, so any request lands somewhere
sensible:

- **Whites** are fitted locally over the (Kelvin, brightness) plane: a plane
  through the nearby measurements, weighted by distance. That follows a trend
  instead of sagging between measurements, and averages out the scatter that
  matching by eye inevitably leaves.
- **Brightness distance is perceptual.** 10% to 20% is about three times the
  visible step of 70% to 80%, so measurements are not smeared together at the
  dim end — which is the end cheap fixtures get wrong.
- **Outside the measured points the correction holds** at the nearest edge
  rather than being extrapolated. A fitted trend runs away fast once it leaves
  the data, and nobody measured a correction out there anyway.
- **Colours** interpolate between the two measured hues either side, the short
  way around the wheel — so red blends magenta and yellow rather than being
  dragged by green on the far side — and between brightness levels within each
  hue, where more than one was measured.

An incoming request is routed by **how far it sits from the blackbody curve**. A
near-white RGB value is treated as a colour temperature and corrected along the
curve. A saturated colour is corrected from the hue points. This distinction
matters: projecting saturated colours onto the blackbody curve collapses them —
pure red and pure green both land on the low end and come out as the same
orange.

If a light has never had colour points measured, saturated colours pass through
with their hue untouched and only brightness is corrected.

### Whites from the light's own white LEDs (optional)

By default a colour light gets every white as an RGB mix of its colour LEDs.
That is what lets a white be corrected for green/magenta tint, but an RGBWW
fixture's phosphor white LEDs are never used: its whites come out dimmer and
with poorer colour rendering than it can do.

**Details → Whites → The light's own white LEDs** (or `white_mode: kelvin` in
the entry's options, or the `set_white_mode` service) sends whites as a colour
temperature instead, corrected for warm/cool and brightness. The trade-off:
whites can no longer be corrected for green/magenta tint, so the dialog drops
that axis on those steps. Every white goes to the white LEDs, even
one outside their colour-temperature range: 2000 K on a strip whose whites stop
at 2700 K comes out as its warmest white, corrected for brightness. An RGB mix
could get warmer, but a light that shows either its colour or its white LEDs,
never both, makes a much dimmer and poorer white that way. Only RGB requests
are sent as RGB. Each white point records which way it was measured, and a
white is only corrected from points measured the same way. Colours are not
affected.

For a light whose RGB whites are good enough, **The light's own white LEDs, RGB
beyond their range** (`white_mode: kelvin_rgb`) sends whites outside the white
LEDs' range as RGB instead, with tint, so they reach the colour temperature
asked for.

**After switching, run a white calibration again** (Quick is enough to start).
The stored points are kept, but whites now sent the other way have nothing
measured for them and go uncorrected until they are. A notification says so,
the Details dialog shows it, and the status sensor's `white_rerun_needed`
attribute is true until whites have been measured in the new mode. Switching
back clears it.

Only colour lights with a white channel (a `color_temp` or `rgbww` mode) are
affected; a tunable-white light is always driven by colour temperature, and an
RGB-only one always by RGB.

## Entities

Per calibrated light:

- `light.<original_id>` — the virtual light. It claims the original entity ID,
  and inherits the area the original was in. The real light is renamed to
  `<id>_raw`, hidden, and driven behind the scenes; it still works and is still
  reachable, it just stops being offered in pickers and dashboards.
- `switch.<name>_calibration` — turn the correction off to A/B it against raw
  output. Flipping it re-applies immediately, so you can see the difference on
  a live light.
- `sensor.<name>_calibration` — status, e.g. "Calibrated (9 whites, 6 colours)".

Removing a config entry gives the original light its entity ID back, and
unhides it.

## Identical fixtures

Two units of the same model are usually wrong in the same way, so there is no
need to measure both. Calibrate one, then copy its profile to the other — the
difference between eight minutes and none.

When you add a light and something has already been calibrated, the flow asks
how to calibrate it: measure it now, or copy another light's calibration. Copy,
and it asks which — and the new light is set up already matching, with no pass
through the sliders at all.

An existing light can take another's calibration from **Details**. It replaces
rather than merges, and asks first: only worth doing between
fixtures of the same model, since a profile describes one particular fixture's
errors.

There is a `copy_profile` service for doing it from a script.

## Seeing what was measured

**Details → Show measurements** lists every point in the profile: what was
asked for, and what the fixture had to be sent to produce it. That is the only
view of a calibration as a whole — the numbers live in the config entry, not in
any entity.

For the raw data, the entry's ⋮ → **Download diagnostics** gives the stored
points as JSON, along with the corrections the profile produces at a spread of
colour temperatures and brightnesses. Worth keeping a copy before doing
anything irreversible to a profile.

## Re-running

Running calibration again — **Re-Calibrate** in Details — **fine-tunes rather
than resets**. Each step is seeded
with the stored value, so you are adjusting from where you left off. "Finish
now" saves what you have measured this pass and merges it into the stored
profile — anything you did not revisit is kept. So a Quick pass can touch up
five whites without disturbing a Thorough profile.

## Installing

HACS → ⋮ → Custom repositories → this repo URL, category **Integration**.
Download and restart Home Assistant.

**Light Calibration** then appears in the sidebar, with a search box and a
**Calibrated / All lights** switch across the top and **Calibrate a light** in
the bottom corner.

It opens on every light that *could* be calibrated — anything with colour or a
tunable white — or on just the calibrated ones, whichever you last had it set
to. Switch to **All lights** and every candidate appears — anything with colour or a
tunable white; a plain on/off or brightness-only fixture has no colour
behaviour to correct and is left out. Press **Calibrate** on any of them and it
goes straight to asking what it should match, since you have already said which
light. No trip through Settings, and nothing to add first.

Each light gets a card shaped like the ones on Home Assistant's integrations
page: the icon carries the light's current colour and state, and the row opens
that light's ordinary more-info dialog.

Under the divider, a calibrated light offers **Details** — what it was matched
against, the measurements, re-calibrating and clearing the profile — next to a
switch for the correction itself, so you can flip between corrected and raw
output without opening anything. Calibrated cards carry a tinted border, so the
lights this integration is actually correcting stand out in the grid. A light
with nothing measured shows **Calibrate**.

Adding one through **Settings → Devices & Services → Add integration** still
works and does the same thing. The entry's **Configure** button reopens the
panel scoped to that one light.

**Light Calibration** appears in the sidebar, listing every calibrated light.
The entry's **Configure** button opens the same page scoped to that one light.

The frontend module is served by the integration itself and registered
automatically. There is no Lovelace resource to add and no card to place on a
dashboard.

## Services

All take an `entry_id`.

| Service | |
|---|---|
| `start_calibration` | Begin a session, optional `depth` |
| `adjust` | Set live values for the current point |
| `save_point` | Record and advance |
| `previous_point` | Step back |
| `finish_calibration` | Save what has been measured and stop |
| `compare` | Flash the light to uncorrected output and back |
| `cancel_calibration` | Abandon; the stored profile is untouched |
| `set_reference` | Change the reference light |
| `clear_profile` | Discard the profile, leaving the light uncorrected |
| `copy_profile` | Replace one light's calibration with another's |
| `set_white_mode` | `rgb` (default) or `kelvin`: how a colour light is sent whites |

## Developing

`dev/harness.html` renders the frontend against a mock Home Assistant in an
ordinary browser, so the dialog can be worked on without a deploy. See
[`dev/README.md`](dev/README.md). Nothing outside `custom_components/` is
installed by HACS.

Tests for the colour maths and the interpolation run offline, with no Home
Assistant checkout:

```bash
uv run --with pytest pytest tests/
```

## Notes

- The correction is applied to what the light is *sent*. It cannot make a
  fixture exceed its own limits — asking for 1800 K from a bulb whose floor is
  2000 K still gives 2000 K.
- A light with no colour control at all — on/off, or brightness only — cannot
  be calibrated, and is rejected when you try to add it.
- A colour and a level are kept separate, as everywhere else in Home Assistant:
  asking for a dim `rgb_color` sets the colour at full and puts the level into
  brightness, so the light reports what it is actually showing.
- Calibration is only as good as the reference. It matches lights to each
  other, not to a colorimetric standard.
- The frontend URL contains a hash of the file's contents. Home Assistant is
  often behind a CDN that caches `.js` for hours, and a stale module shows up as
  a blank panel. A content-addressed URL cannot go stale.
- **Reload the page after updating.** Home Assistant's frontend is a single page
  app, so restarting it does not reload your browser tab, and a custom element
  name cannot be redefined once a page has claimed it. A tab left open across an
  update keeps rendering the old interface — which looks exactly like an update
  that did nothing. The console says so if it happens.
- **A frontend-only update does not need a Home Assistant restart.** Settings →
  Devices & services → Light Calibration → ⋮ → **Reload** re-serves the module
  at its new address and re-registers the panel; reload the browser tab after.
  A change to the Python does need a restart, because Python will not re-read a
  module it has already imported — no custom integration escapes that.
