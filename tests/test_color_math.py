"""Tests for ``color_math`` -- the pure colour maths.

The interesting cases here are all regressions. Every assertion that looks
oddly specific is pinning behaviour that was wrong at some point.
"""
from __future__ import annotations

import pytest

from light_calibration import color_math as cm


# --------------------------------------------------------------- kelvin -> rgb

# `kelvin_to_rgb` is a local reimplementation of Home Assistant's own
# `homeassistant.util.color.color_temperature_to_rgb` -- reimplemented, not
# imported, so this module stays dependency-free and testable offline. These
# anchors pin the two to the same answer. Anything else driving a light from a
# colour temperature goes through that core helper, so if this drifts, a
# calibrated light and an uncalibrated one asked for the same colour temperature
# stop agreeing, and the room goes mismatched again.
#
# The agreement is bounded: core clamps at 40000K, MAX_KELVIN here is 10000.
# Below that the two are identical at every kelvin.
CORE_CURVE_ANCHORS = [
    (1700, (255, 121, 0)),
    (2000, (255, 137, 14)),
    (2700, (255, 167, 87)),
    # Above 6600K red comes off its ceiling and the other branch of the
    # curve takes over, so the cool end needs anchoring separately.
    (8000, (221, 230, 255)),
    (10000, (202, 218, 255)),
]


@pytest.mark.parametrize("kelvin,expected", CORE_CURVE_ANCHORS)
def test_kelvin_to_rgb_matches_home_assistant_core(kelvin, expected):
    assert cm.kelvin_to_rgb(kelvin) == expected


def test_kelvin_to_rgb_clamps_to_the_supported_range():
    assert cm.kelvin_to_rgb(500) == cm.kelvin_to_rgb(cm.MIN_KELVIN)
    assert cm.kelvin_to_rgb(20000) == cm.kelvin_to_rgb(cm.MAX_KELVIN)


def test_kelvin_to_rgb_stays_in_gamut():
    for kelvin in range(cm.MIN_KELVIN, cm.MAX_KELVIN + 1, 100):
        assert all(0 <= c <= 255 for c in cm.kelvin_to_rgb(kelvin))


def test_kelvin_to_rgb_gets_bluer_as_it_gets_hotter():
    blues = [cm.kelvin_to_rgb(k)[2] for k in range(cm.MIN_KELVIN, cm.MAX_KELVIN + 1, 100)]
    assert blues == sorted(blues)
    assert blues[0] == 0        # deep warm has no blue at all
    assert blues[-1] == 255


# --------------------------------------------------------------- rgb -> kelvin


@pytest.mark.parametrize("kelvin", [1000, 1500, 2000, 2700, 3200, 4000])
def test_round_trip_is_exact_at_the_calibration_points(kelvin):
    assert cm.rgb_to_kelvin(cm.kelvin_to_rgb(kelvin)) == kelvin


def test_round_trip_is_tight_across_the_lamp_range():
    """1000-4000K is where domestic lamps live; error there stays small.

    Above about 9000K the curve flattens and runs into the MAX_KELVIN ceiling,
    so the round trip loosens considerably. That is accepted, not tested for.
    """
    worst = max(
        abs(cm.rgb_to_kelvin(cm.kelvin_to_rgb(k)) - k) for k in range(1000, 4001, 25)
    )
    assert worst <= 25


@pytest.mark.parametrize("kelvin", [1000, 1200, 1500, 1800])
def test_deep_warm_whites_are_not_dragged_to_the_floor(kelvin):
    """The reason ``rgb_to_kelvin`` is a nearest-match scan, not a ratio search.

    Below about 1900K the blue channel is zero at every temperature, so a search
    on the blue/red ratio cannot tell 1000K from 1900K and collapses all of them
    onto MIN_KELVIN. The scan compares all three channels, and green still
    separates them.
    """
    assert cm.rgb_to_kelvin(cm.kelvin_to_rgb(kelvin)) == kelvin


def test_deep_warm_whites_stay_distinct_from_each_other():
    warm = [cm.rgb_to_kelvin(cm.kelvin_to_rgb(k)) for k in (1000, 1200, 1500, 1800)]
    assert warm == sorted(warm)
    assert len(set(warm)) == 4


# ------------------------------------------------------------------- routing


def test_every_colour_temperature_reads_as_white():
    """A blackbody colour is by definition zero distance from the curve."""
    worst = max(
        cm.blackbody_distance(cm.kelvin_to_rgb(k))
        for k in range(cm.MIN_KELVIN, cm.MAX_KELVIN + 1, 50)
    )
    assert worst <= cm.WHITE_TOLERANCE


def test_a_slightly_off_white_still_reads_as_white():
    assert cm.blackbody_distance((255, 200, 150)) <= cm.WHITE_TOLERANCE


@pytest.mark.parametrize(
    "name,rgb",
    [
        ("red", (255, 0, 0)),
        ("yellow", (255, 255, 0)),
        ("green", (0, 255, 0)),
        ("cyan", (0, 255, 255)),
        ("blue", (0, 0, 255)),
        ("magenta", (255, 0, 255)),
    ],
)
def test_saturated_colours_read_as_colour(name, rgb):
    """The six calibration hues must all route down the colour path.

    Routing is by distance from the blackbody curve, not by whether the request
    named a colour temperature. Get this wrong and saturated colours are
    projected onto the curve, where red and green both land on the warm floor
    and come out as the same orange.
    """
    assert cm.blackbody_distance(rgb) > cm.WHITE_TOLERANCE


def test_red_and_green_are_nowhere_near_each_other_on_the_curve():
    assert cm.blackbody_distance((255, 0, 0)) != cm.blackbody_distance((0, 255, 0))


# ---------------------------------------------------------------------- tint


def test_zero_tint_changes_nothing():
    rgb = cm.kelvin_to_rgb(2700)
    assert cm.apply_tint(rgb, 0) == rgb


def test_positive_tint_adds_green_and_negative_removes_it():
    rgb = cm.kelvin_to_rgb(2700)
    greener = cm.apply_tint(rgb, 20)
    pinker = cm.apply_tint(rgb, -20)
    assert greener[1] > rgb[1] > pinker[1]


def test_tint_moves_one_axis_only():
    """Red against blue is untouched -- this is green/magenta, not a colour shift."""
    for kelvin in (2000, 2700, 4000):
        rgb = cm.kelvin_to_rgb(kelvin)
        for tint in (-40, -20, 20, 40):
            out = cm.apply_tint(rgb, tint)
            assert out[0] / out[2] == pytest.approx(rgb[0] / rgb[2], rel=0.02)


def test_the_brightness_factor_cancels_the_tint_brightness():
    """The point of the factor: tint and brightness stay independent axes.

    Green carries 71% of luminance and the peak channel is pinned to the drive
    level, so no chromaticity is both greener and equally bright. The tint's own
    brightness has to come out of the brightness command instead.
    """
    for kelvin in (2000, 2700, 4000, 6000):
        base = cm.relative_luminance(cm.kelvin_to_rgb(kelvin))
        for tint in (-40, -20, 20, 40):
            tinted = cm.relative_luminance(cm.apply_tint(cm.kelvin_to_rgb(kelvin), tint))
            factor = cm.corrected_brightness_factor(kelvin, 0, tint)
            assert tinted / factor == pytest.approx(base, rel=1e-6)


def test_the_brightness_factor_is_one_when_there_is_no_tint():
    assert cm.corrected_brightness_factor(2700, -250, 0) == 1.0


@pytest.mark.parametrize("tint", [-1000, -100, 0, 100, 1000])
def test_tint_stays_in_gamut(tint):
    assert all(0 <= c <= 255 for c in cm.apply_tint(cm.kelvin_to_rgb(2700), tint))


# ------------------------------------------------------------------ hue / sat


@pytest.mark.parametrize(
    "rgb,hue,saturation",
    [
        ((255, 0, 0), 0.0, 100.0),
        ((255, 255, 0), 60.0, 100.0),
        ((0, 255, 0), 120.0, 100.0),
        ((0, 0, 255), 240.0, 100.0),
        ((255, 255, 255), 0.0, 0.0),
    ],
)
def test_rgb_to_hs(rgb, hue, saturation):
    assert cm.rgb_to_hs(rgb) == pytest.approx((hue, saturation))


@pytest.mark.parametrize("hue", [0, 60, 120, 180, 240, 300])
def test_hs_round_trip(hue):
    assert cm.rgb_to_hs(cm.hs_to_rgb(hue, 100))[0] == pytest.approx(hue)


def test_hs_to_rgb_wraps_past_a_full_turn():
    assert cm.hs_to_rgb(360, 100) == cm.hs_to_rgb(0, 100)
    assert cm.hs_to_rgb(-60, 100) == cm.hs_to_rgb(300, 100)


def test_hs_to_rgb_is_always_full_level():
    """Home Assistant carries brightness separately, so the colour channel
    describes hue and saturation only."""
    for hue in range(0, 360, 30):
        assert max(cm.hs_to_rgb(hue, 100)) == 255


def test_hs_to_rgb_clamps_saturation():
    assert cm.hs_to_rgb(0, 500) == cm.hs_to_rgb(0, 100)
    assert cm.hs_to_rgb(0, -50) == cm.hs_to_rgb(0, 0)


# ----------------------------------------------------------- colour versus level


def test_split_level_separates_a_dim_colour_from_a_dark_one():
    """(80,0,0) is red at a third of the level, not a dark shade of red."""
    colour, level = cm.split_level((80, 0, 0))
    assert colour == (255, 0, 0)
    assert level == pytest.approx(80 / 255)


def test_split_level_leaves_a_full_colour_alone():
    for rgb in [(255, 0, 0), (255, 167, 87), (0, 255, 0), (12, 255, 200)]:
        colour, level = cm.split_level(rgb)
        assert colour == rgb
        assert level == 1.0


def test_split_level_preserves_the_colour():
    """Only the level comes out -- the hue and saturation are untouched."""
    for rgb in [(80, 0, 0), (40, 26, 13), (100, 100, 50), (9, 3, 6)]:
        colour, _ = cm.split_level(rgb)
        assert cm.rgb_to_hs(colour) == pytest.approx(cm.rgb_to_hs(rgb), abs=1.0)


def test_split_level_of_black():
    assert cm.split_level((0, 0, 0)) == ((0, 0, 0), 0.0)


def test_a_dim_colour_no_longer_reads_as_a_dark_one():
    """The reason this exists: a dashboard icon tinted from the reported colour
    was coming out very nearly black for a dim request."""
    dim, _ = cm.split_level((80, 0, 0))
    assert max(dim) == 255


# ----------------------------------------------------------------- composition


def test_corrected_rgb_is_the_offset_kelvin_then_the_tint():
    assert cm.corrected_rgb(2700, -250, 20) == cm.apply_tint(cm.kelvin_to_rgb(2450), 20)


def test_corrected_rgb_with_no_correction_is_just_the_kelvin():
    assert cm.corrected_rgb(2700, 0, 0) == cm.kelvin_to_rgb(2700)


# The slider runs -100..+400. Both ends are real settings, not just limits.

@pytest.mark.parametrize("kelvin", [2000, 2700, 4000, 6500])
def test_full_magenta_removes_green_and_nothing_else(kelvin):
    rgb = cm.kelvin_to_rgb(kelvin)
    out = cm.apply_tint(rgb, -100)
    assert out[1] == 0
    assert out[0] / out[2] == pytest.approx(rgb[0] / rgb[2], rel=0.02)


@pytest.mark.parametrize("kelvin", [2000, 2700, 4000, 6500])
def test_full_green_quintuples_green_in_linear_light(kelvin):
    rgb = cm.kelvin_to_rgb(kelvin)
    out = cm.apply_tint(rgb, 400)
    green = lambda c: cm._to_linear(c[1]) / cm._to_linear(c[0])
    assert all(0 <= c <= 255 for c in out)
    if out[0] >= 8:          # red not rounded away, so the ratio means something
        assert green(out) == pytest.approx(5 * green(rgb), rel=0.05)


@pytest.mark.parametrize("kelvin", [2000, 2700, 4000, 6500])
@pytest.mark.parametrize("tint", [-100, 400])
def test_the_brightness_factor_holds_at_the_ends_of_the_slider(kelvin, tint):
    """Positive and finite even with green gone: the command divides by it."""
    base = cm.relative_luminance(cm.kelvin_to_rgb(kelvin))
    tinted = cm.relative_luminance(cm.apply_tint(cm.kelvin_to_rgb(kelvin), tint))
    factor = cm.corrected_brightness_factor(kelvin, 0, tint)
    assert 0 < factor < 10
    assert tinted / factor == pytest.approx(base, rel=1e-6)
