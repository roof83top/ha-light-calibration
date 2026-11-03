"""Whites by colour temperature: the routing rule, per-route profiles, the
mode switch, and the calibration session driving each route.

The session needs Home Assistant only for a handful of names, so when it is not
installed (the usual case here) a few stand-in modules are put in its place --
enough to load ``session.py`` and run ``_target_data`` against a fake ``hass``.
"""
from __future__ import annotations

import asyncio
import enum
import importlib
import sys
import types

import pytest

from light_calibration import color_math as cm
from light_calibration.calibration import (
    ROUTE_KELVIN,
    ROUTE_RGB,
    CalibrationPoint,
    CalibrationProfile,
    clamp_kelvin,
    white_command,
    white_route,
    whites_need_rerun,
    with_white_mode,
)
from light_calibration.const import (
    CONF_POINTS,
    CONF_REFERENCE,
    CONF_TARGET,
    CONF_WHITE_MODE,
    CONF_WHITES_MEASURED_MODE,
    WHITE_MODE_KELVIN,
    WHITE_MODE_KELVIN_RGB,
    WHITE_MODE_RGB,
)

STRIP = (2700, 6500)        # the LEDVANCE strip's phosphor whites


# --------------------------------------------------------------- white_route

@pytest.mark.parametrize(
    "mode,kelvin,ct_range,color,white_channel,route",
    [
        # Default mode: every white as RGB, inside the range or not.
        (WHITE_MODE_RGB, 4000, STRIP, True, True, ROUTE_RGB),
        (None, 4000, STRIP, True, True, ROUTE_RGB),           # option never set
        (WHITE_MODE_RGB, 4000, None, True, True, ROUTE_RGB),
        # Kelvin mode: the white LEDs inside the range, edges included...
        (WHITE_MODE_KELVIN, 4000, STRIP, True, True, ROUTE_KELVIN),
        (WHITE_MODE_KELVIN, 2700, STRIP, True, True, ROUTE_KELVIN),
        (WHITE_MODE_KELVIN, 6500, STRIP, True, True, ROUTE_KELVIN),
        # ...and outside it too: clamped there, never an RGB mix (the depth
        # presets ask for 2000K and 2400K).
        (WHITE_MODE_KELVIN, 2699, STRIP, True, True, ROUTE_KELVIN),
        (WHITE_MODE_KELVIN, 2000, STRIP, True, True, ROUTE_KELVIN),
        (WHITE_MODE_KELVIN, 6501, STRIP, True, True, ROUTE_KELVIN),
        # kelvin_rgb: the white LEDs inside the range, edges included...
        (WHITE_MODE_KELVIN_RGB, 4000, STRIP, True, True, ROUTE_KELVIN),
        (WHITE_MODE_KELVIN_RGB, 2700, STRIP, True, True, ROUTE_KELVIN),
        (WHITE_MODE_KELVIN_RGB, 6500, STRIP, True, True, ROUTE_KELVIN),
        # ...RGB outside it.
        (WHITE_MODE_KELVIN_RGB, 2699, STRIP, True, True, ROUTE_RGB),
        (WHITE_MODE_KELVIN_RGB, 2000, STRIP, True, True, ROUTE_RGB),
        (WHITE_MODE_KELVIN_RGB, 6501, STRIP, True, True, ROUTE_RGB),
        (WHITE_MODE_KELVIN_RGB, 2000, None, True, True, ROUTE_KELVIN),
        (WHITE_MODE_KELVIN_RGB, 4000, STRIP, True, False, ROUTE_RGB),
        # An unreported range: assume the fixture copes.
        (WHITE_MODE_KELVIN, 2000, None, True, True, ROUTE_KELVIN),
        # No white channel (RGB/HS/XY only): core would turn a kelvin back
        # into RGB and drop the correction, so RGB it stays.
        (WHITE_MODE_KELVIN, 4000, STRIP, True, False, ROUTE_RGB),
        # A tunable-white fixture only ever takes a kelvin, whatever the mode.
        (WHITE_MODE_RGB, 4000, STRIP, False, True, ROUTE_KELVIN),
        (WHITE_MODE_KELVIN, 2000, STRIP, False, True, ROUTE_KELVIN),
    ],
)
def test_white_route(mode, kelvin, ct_range, color, white_channel, route):
    assert white_route(mode, kelvin, ct_range, color, white_channel) == route


def test_white_route_defaults_to_having_a_white_channel():
    assert white_route(WHITE_MODE_KELVIN, 3000, STRIP, True) == ROUTE_KELVIN


def test_the_route_follows_the_requested_kelvin_not_the_offset_one():
    """A -300K offset at 2800K lands below the floor; the route must not flip."""
    profile = CalibrationProfile([CalibrationPoint(2800, 40, kelvin_offset=-300,
                                                   route=ROUTE_KELVIN)])
    assert white_route(WHITE_MODE_KELVIN, 2800, STRIP, True) == ROUTE_KELVIN
    data = profile.command_for_white(2800, 40, ROUTE_KELVIN, STRIP)
    assert data["color_temp_kelvin"] == 2700        # clamped to the range


def test_clamp_kelvin():
    assert clamp_kelvin(2500, STRIP) == 2700
    assert clamp_kelvin(7000, STRIP) == 6500
    assert clamp_kelvin(3333.4, STRIP) == 3333
    assert clamp_kelvin(500) == cm.MIN_KELVIN
    assert clamp_kelvin(20000) == cm.MAX_KELVIN


def test_white_command_on_each_route():
    rgb = white_command(2700, 40, ROUTE_RGB, offset=-100, tint=20)
    assert rgb["rgb_color"] == list(cm.corrected_rgb(2700, -100, 20))
    assert rgb["brightness_pct"] == int(round(
        40 / cm.corrected_brightness_factor(2700, -100, 20)))
    assert "color_temp_kelvin" not in rgb

    ct = white_command(2700, 40, ROUTE_KELVIN, offset=-100, tint=20, ct_range=STRIP)
    assert ct == {"color_temp_kelvin": 2700, "brightness_pct": 40}   # no tint
    assert white_command(4000, 40, ROUTE_KELVIN, offset=150) == {
        "color_temp_kelvin": 4150, "brightness_pct": 40}


# ------------------------------------------------------ profile, per route

RGB_A = CalibrationPoint(2700, 40, kelvin_offset=-250, tint=20, brightness_actual=45)
RGB_B = CalibrationPoint(4000, 40, kelvin_offset=100, tint=-10, brightness_actual=30)
CT_A = CalibrationPoint(2700, 40, kelvin_offset=80, tint=0, brightness_actual=38,
                        route=ROUTE_KELVIN)
CT_B = CalibrationPoint(4000, 40, kelvin_offset=-60, tint=0, brightness_actual=44,
                        route=ROUTE_KELVIN)
HYBRID = CalibrationProfile([RGB_A, RGB_B, CT_A, CT_B])


def test_each_route_is_corrected_from_its_own_points_only():
    assert HYBRID.correction(2700, 40, ROUTE_RGB) == (-250.0, 20.0, 45 / 40)
    assert HYBRID.correction(4000, 40, ROUTE_RGB) == (100.0, -10.0, 30 / 40)
    assert HYBRID.correction(2700, 40, ROUTE_KELVIN) == (80.0, 0.0, 38 / 40)
    assert HYBRID.correction(4000, 40, ROUTE_KELVIN) == (-60.0, 0.0, 44 / 40)


def test_a_route_matches_a_profile_of_its_points_alone():
    rgb_only = CalibrationProfile([RGB_A, RGB_B])
    ct_only = CalibrationProfile([CT_A, CT_B])
    for kelvin in (2000, 2700, 3300, 4000, 5000):
        for brightness in (10, 40, 80):
            assert HYBRID.correction(kelvin, brightness, ROUTE_RGB) == pytest.approx(
                rgb_only.correction(kelvin, brightness))
            assert HYBRID.correction(kelvin, brightness, ROUTE_KELVIN) == pytest.approx(
                ct_only.correction(kelvin, brightness))


def test_tint_only_comes_from_rgb_points():
    # A kelvin point that somehow carries a tint still gives the kelvin route none.
    stray = CalibrationPoint(3000, 40, kelvin_offset=0, tint=50, route=ROUTE_KELVIN)
    profile = CalibrationProfile([RGB_A, stray])
    assert profile.correction(3000, 40, ROUTE_KELVIN)[1] == 0.0
    assert profile.correction(3000, 40, ROUTE_RGB)[1] == 20.0     # RGB_A's alone


def test_old_points_without_a_route_count_as_rgb():
    old = {"type": "white", "kelvin": 2700, "brightness": 40,
           "kelvin_offset": -250.0, "tint": 20.0, "brightness_actual": 45.0}
    profile = CalibrationProfile.from_list([old])
    assert profile.points[0].route == ROUTE_RGB
    assert profile.correction(2700, 40, ROUTE_RGB) == (-250.0, 20.0, 45 / 40)
    assert profile.correction(2700, 40, ROUTE_KELVIN) == (0.0, 0.0, 1.0)


def test_route_survives_a_round_trip():
    restored = CalibrationProfile.from_list(HYBRID.as_list())
    assert [p.route for p in restored.points] == ["rgb", "rgb", "kelvin", "kelvin"]
    assert restored.as_list() == HYBRID.as_list()


def test_no_points_on_a_route_means_no_correction_logged_once(caplog):
    profile = CalibrationProfile([RGB_A, RGB_B])
    with caplog.at_level("INFO"):
        for _ in range(3):
            assert profile.correction(3000, 40, ROUTE_KELVIN) == (0.0, 0.0, 1.0)
    assert sum("kelvin route" in r.message for r in caplog.records) == 1


def test_an_empty_profile_says_nothing(caplog):
    with caplog.at_level("INFO"):
        assert CalibrationProfile([]).correction(3000, 40, ROUTE_KELVIN) == (0.0, 0.0, 1.0)
    assert not caplog.records


def test_no_route_uses_every_point_as_before():
    """A tunable-white fixture: one route, and its old points carry none."""
    tw = CalibrationProfile([RGB_A, CT_B])
    assert tw.correction(2700, 40) == tw.correction(2700, 40, None)
    assert tw.kelvin_command_for_kelvin(2700, 40) == (2450, 45)
    assert tw.kelvin_command_for_kelvin(4000, 40) == (3940, 44)


def test_command_for_kelvin_and_rgb_use_rgb_points():
    rgb, out = HYBRID.command_for_kelvin(2700, 40)
    assert (rgb, out) == CalibrationProfile([RGB_A, RGB_B]).command_for_kelvin(2700, 40)
    near_white = cm.kelvin_to_rgb(2700)
    assert HYBRID.command_for_rgb(near_white, 40) == CalibrationProfile(
        [RGB_A, RGB_B]).command_for_rgb(near_white, 40)


def test_command_for_white():
    assert HYBRID.command_for_white(2700, 40, ROUTE_KELVIN, STRIP) == {
        "color_temp_kelvin": 2780, "brightness_pct": 38}
    rgb, out = HYBRID.command_for_kelvin(4000, 40)
    assert HYBRID.command_for_white(4000, 40, ROUTE_RGB, STRIP) == {
        "rgb_color": list(rgb), "brightness_pct": out}
    # A tunable white ignores the colour fixture's range and uses every point.
    assert HYBRID.command_for_white(4000, 40, ROUTE_KELVIN, STRIP, color_capable=False) == {
        "color_temp_kelvin": HYBRID.kelvin_command_for_kelvin(4000, 40)[0],
        "brightness_pct": HYBRID.kelvin_command_for_kelvin(4000, 40)[1]}


# ---------------------------------------------------- switching the mode

WHITES = [RGB_A.as_dict(), {"type": "color", "hue": 0, "brightness": 60}]


def test_a_profile_from_before_the_option_needs_nothing():
    assert not whites_need_rerun({CONF_POINTS: WHITES})


def test_switching_keeps_the_points_and_flags_the_whites():
    data = {CONF_POINTS: WHITES, CONF_REFERENCE: "light.ref"}
    switched = with_white_mode(data, WHITE_MODE_KELVIN)
    assert switched[CONF_POINTS] is WHITES                   # nothing dropped
    assert switched[CONF_WHITE_MODE] == WHITE_MODE_KELVIN
    assert switched[CONF_WHITES_MEASURED_MODE] == WHITE_MODE_RGB
    assert whites_need_rerun(switched)
    # ...and switching back answers it without a run.
    assert not whites_need_rerun(with_white_mode(switched, WHITE_MODE_RGB))


def test_a_white_run_in_the_new_mode_clears_the_flag():
    switched = with_white_mode({CONF_POINTS: WHITES}, WHITE_MODE_KELVIN)
    # what the session writes when it saves whites
    rerun = {**switched, CONF_WHITES_MEASURED_MODE: WHITE_MODE_KELVIN}
    assert not whites_need_rerun(rerun)
    # A later switch pins nothing new: the record already says kelvin.
    back = with_white_mode(rerun, WHITE_MODE_RGB)
    assert back[CONF_WHITES_MEASURED_MODE] == WHITE_MODE_KELVIN
    assert whites_need_rerun(back)


def test_nothing_to_rerun_without_whites_or_on_a_tunable_white():
    colours_only = {CONF_POINTS: [{"type": "color", "hue": 0, "brightness": 60}]}
    assert not whites_need_rerun(with_white_mode(colours_only, WHITE_MODE_KELVIN))
    assert CONF_WHITES_MEASURED_MODE not in with_white_mode(colours_only, WHITE_MODE_KELVIN)
    assert not whites_need_rerun(with_white_mode({CONF_POINTS: []}, WHITE_MODE_KELVIN))
    tw = with_white_mode({CONF_POINTS: WHITES}, WHITE_MODE_KELVIN)
    assert not whites_need_rerun(tw, color_capable=False)


# ------------------------------------------------------------ the session

def _install_ha_stubs() -> None:
    """The few Home Assistant names session.py and capability.py import."""
    try:
        import homeassistant  # noqa: F401
        return
    except ImportError:
        pass

    class ColorMode(str, enum.Enum):
        ONOFF = "onoff"
        BRIGHTNESS = "brightness"
        COLOR_TEMP = "color_temp"
        HS = "hs"
        XY = "xy"
        RGB = "rgb"
        RGBW = "rgbw"
        RGBWW = "rgbww"

    def module(name: str, **attrs) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        sys.modules[name] = mod
        return mod

    notes = module(
        "homeassistant.components.persistent_notification",
        created=[], dismissed=[],
    )
    notes.async_create = lambda hass, message, title=None, notification_id=None: \
        notes.created.append(notification_id)
    notes.async_dismiss = lambda hass, notification_id: notes.dismissed.append(notification_id)
    light = module("homeassistant.components.light",
                   ATTR_SUPPORTED_COLOR_MODES="supported_color_modes", ColorMode=ColorMode)
    components = module("homeassistant.components",
                        persistent_notification=notes, light=light)
    components.__path__ = []
    root = module("homeassistant", components=components)
    root.__path__ = []
    module("homeassistant.config_entries", ConfigEntry=object)
    module("homeassistant.const", ATTR_ENTITY_ID="entity_id")
    module("homeassistant.core", HomeAssistant=object, callback=lambda f: f)


class _State:
    def __init__(self, attributes: dict) -> None:
        self.state = "on"
        self.attributes = attributes


class _Hass:
    def __init__(self, states: dict) -> None:
        self.states = types.SimpleNamespace(get=lambda e: states.get(e))
        self.calls: list[dict] = []
        hass = self

        async def async_call(domain, service, data, blocking=False):
            hass.calls.append(dict(data))

        def async_update_entry(entry, data):
            entry.data = data

        self.services = types.SimpleNamespace(async_call=async_call)
        self.config_entries = types.SimpleNamespace(async_update_entry=async_update_entry)


REFERENCE = "light.ref"
TARGET = "light.strip_raw"
RGBWW_STRIP = {"supported_color_modes": ["color_temp", "xy"],
               "min_color_temp_kelvin": 2700, "max_color_temp_kelvin": 6500}
REFERENCE_BULB = {"supported_color_modes": ["color_temp", "xy"],
                  "min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6535}


@pytest.fixture(scope="module")
def session_module():
    _install_ha_stubs()
    return importlib.import_module("light_calibration.session")


def make_session(session_module, mode=None, target=RGBWW_STRIP, points=None):
    data = {CONF_REFERENCE: REFERENCE, CONF_TARGET: TARGET, CONF_POINTS: points or []}
    if mode:
        data[CONF_WHITE_MODE] = mode
    entry = types.SimpleNamespace(data=data, entry_id="E1", title="Strip")
    hass = _Hass({REFERENCE: _State(REFERENCE_BULB), TARGET: _State(target)})
    return session_module.CalibrationSession(hass, entry), hass


def white(kelvin, brightness=40):
    return {"type": "white", "kelvin": kelvin, "brightness": brightness}


def test_session_default_mode_sends_every_white_as_rgb(session_module):
    s, _ = make_session(session_module)
    s.warm_cool, s.tint, s.brightness = -100.0, 20.0, 40.0
    for kelvin in (2000, 2700, 4000):
        data = s._target_data(white(kelvin))
        assert data["rgb_color"] == list(cm.corrected_rgb(kelvin, -100, 20))
        assert "color_temp_kelvin" not in data


def test_session_kelvin_mode_uses_the_white_leds_for_every_white(session_module):
    s, _ = make_session(session_module, WHITE_MODE_KELVIN)
    s.warm_cool, s.tint, s.brightness = -100.0, 20.0, 40.0
    assert s._target_data(white(4000)) == {
        "entity_id": TARGET, "transition": 0.4,
        "color_temp_kelvin": 3900, "brightness_pct": 40}
    # At the floor, an offset below it is held at the floor.
    assert s._target_data(white(2700))["color_temp_kelvin"] == 2700
    # Below the range: still the white LEDs, at their warmest, never RGB.
    assert s._target_data(white(2000)) == {
        "entity_id": TARGET, "transition": 0.4,
        "color_temp_kelvin": 2700, "brightness_pct": 40}
    # Compare flashes the raw fixture on the same route.
    assert s._target_data(white(4000), raw=True)["color_temp_kelvin"] == 4000
    assert s._target_data(white(2000), raw=True)["color_temp_kelvin"] == 2700


def test_session_kelvin_rgb_mode_sends_rgb_beyond_the_range(session_module):
    s, _ = make_session(session_module, WHITE_MODE_KELVIN_RGB)
    s.warm_cool, s.tint, s.brightness = -100.0, 20.0, 40.0
    assert s._target_data(white(4000))["color_temp_kelvin"] == 3900
    below = s._target_data(white(2000))
    assert below["rgb_color"] == list(cm.corrected_rgb(2000, -100, 20))
    assert "color_temp_kelvin" not in below


def test_session_kelvin_mode_on_an_rgb_only_fixture_stays_rgb(session_module):
    s, _ = make_session(session_module, WHITE_MODE_KELVIN,
                        target={"supported_color_modes": ["rgb"]})
    assert "rgb_color" in s._target_data(white(4000))


def test_session_tunable_white_is_unchanged(session_module):
    s, _ = make_session(session_module, WHITE_MODE_RGB, target={
        "supported_color_modes": ["color_temp"],
        "min_color_temp_kelvin": 2700, "max_color_temp_kelvin": 6500})
    s.warm_cool, s.brightness = -800.0, 40.0
    # Clamped only to the global limits, as before -- the fixture clamps itself.
    assert s._target_data(white(2700))["color_temp_kelvin"] == 1900
    _run(s, "quick")
    assert s.extra_attributes()["white_kelvin_range"] is None


def _run(session, depth):
    asyncio.run(session.async_start(depth))


def test_session_records_the_route_and_exposes_white_tint(session_module):
    s, hass = make_session(session_module, WHITE_MODE_KELVIN)
    _run(s, "quick")          # 2700@40, 2000@40, 4000@40, 2700@10, 2700@80
    attrs = s.extra_attributes()
    assert attrs["white_tint"] is False and attrs["white_route"] == ROUTE_KELVIN
    assert attrs["supports_color"] is True
    # The clamp _target_data applies to this white, for auto mode's command model.
    assert attrs["white_kelvin_range"] == [2700, 6500]
    s.tint = 30.0                                  # never sent on this step
    asyncio.run(s.async_next())
    attrs = s.extra_attributes()
    assert s.current["kelvin"] == 2000             # below the range: same route
    assert attrs["white_tint"] is False and attrs["white_route"] == ROUTE_KELVIN
    assert attrs["white_kelvin_range"] == [2700, 6500]
    asyncio.run(s.async_next())
    first, second = s.results
    assert (first.route, first.tint) == (ROUTE_KELVIN, 0.0)
    assert (second.route, second.tint) == (ROUTE_KELVIN, 0.0)


def test_session_white_tint_is_none_off_a_white_step(session_module):
    s, _ = make_session(session_module, WHITE_MODE_KELVIN)
    assert s.extra_attributes()["white_tint"] is None
    assert s.extra_attributes()["white_kelvin_range"] is None
    _run(s, "colors")
    assert s.extra_attributes()["white_tint"] is None
    assert s.extra_attributes()["white_kelvin_range"] is None


def test_session_default_mode_keeps_white_tint_true(session_module):
    s, _ = make_session(session_module)
    _run(s, "quick")
    assert s.extra_attributes()["white_tint"] is True


def test_session_seeds_each_step_from_its_own_route(session_module):
    s, _ = make_session(session_module, WHITE_MODE_KELVIN, points=HYBRID.as_list())
    _run(s, "quick")                         # 2700@40, kelvin route
    assert (s.warm_cool, s.tint) == (80.0, 0.0)
    asyncio.run(s.async_next())              # 2000@40, kelvin route too
    assert s.warm_cool == pytest.approx(HYBRID.correction(2000, 40, ROUTE_KELVIN)[0])
    assert s.tint == 0.0


def test_session_verify_replays_each_route(session_module):
    s, _ = make_session(session_module, WHITE_MODE_KELVIN, points=HYBRID.as_list())
    s.verifying = True
    s.results = []
    assert s._target_data(white(4000)) == {
        "entity_id": TARGET, "transition": 0.4,
        "color_temp_kelvin": 3940, "brightness_pct": 44}
    assert s._target_data(white(2000)) == {
        "entity_id": TARGET, "transition": 0.4,
        "color_temp_kelvin": 2700, "brightness_pct": 38}


def test_session_save_records_the_mode_and_dismisses_the_notice(session_module):
    switched = with_white_mode({CONF_POINTS: WHITES}, WHITE_MODE_KELVIN)
    s, _ = make_session(session_module, WHITE_MODE_KELVIN, points=switched[CONF_POINTS])
    s.entry.data = {**s.entry.data, **switched}
    assert whites_need_rerun(s.entry.data)
    _run(s, "quick")
    asyncio.run(s.async_next())
    asyncio.run(s.async_finish())
    assert s.entry.data[CONF_WHITES_MEASURED_MODE] == WHITE_MODE_KELVIN
    assert not whites_need_rerun(s.entry.data)
    stored = [p for p in s.entry.data[CONF_POINTS] if p.get("kelvin") == 2700
              and p.get("brightness") == 40]
    assert stored and stored[0]["route"] == ROUTE_KELVIN   # replaced the RGB one
    notes = sys.modules["homeassistant.components.persistent_notification"]
    if hasattr(notes, "dismissed"):
        assert "light_calibration_E1_white_rerun" in notes.dismissed


def test_session_colour_only_run_leaves_the_flag(session_module):
    switched = with_white_mode({CONF_POINTS: WHITES}, WHITE_MODE_KELVIN)
    s, _ = make_session(session_module, WHITE_MODE_KELVIN)
    s.entry.data = {**s.entry.data, **switched}
    _run(s, "colors")
    asyncio.run(s.async_next())
    asyncio.run(s.async_finish())
    assert whites_need_rerun(s.entry.data)
