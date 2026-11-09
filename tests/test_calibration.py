"""Tests for ``calibration`` -- the profile and the interpolation over it."""
from __future__ import annotations

import pytest

from light_calibration import color_math as cm
from light_calibration.const import TINT_MAX, TINT_MIN
from light_calibration.calibration import (
    COLOR_HUES,
    count_points,
    profile_summary,
    DEPTH_LABELS,
    DEPTH_POINTS,
    TYPE_COLOR,
    TYPE_WHITE,
    CalibrationPoint,
    CalibrationProfile,
    ColorPoint,
)


def counts(depth: str) -> tuple[int, int]:
    points = DEPTH_POINTS[depth]
    return (
        sum(1 for p in points if p["type"] == TYPE_WHITE),
        sum(1 for p in points if p["type"] == TYPE_COLOR),
    )


# ---------------------------------------------------------------- depth table

# The counts the README promises the user, and the times are quoted against.
@pytest.mark.parametrize(
    "depth,whites,colours",
    [
        ("colors", 0, 6),
        ("quick", 5, 0),
        ("standard", 9, 0),
        ("standard_color", 9, 6),
        ("thorough", 15, 0),
        ("thorough_color", 15, 12),
    ],
)
def test_depth_point_counts(depth, whites, colours):
    assert counts(depth) == (whites, colours)


def test_every_depth_has_a_label():
    assert set(DEPTH_LABELS) == set(DEPTH_POINTS)


def test_the_combined_depths_start_with_their_white_half():
    assert DEPTH_POINTS["standard_color"] == (
        DEPTH_POINTS["standard"] + DEPTH_POINTS["colors"]
    )
    assert (
        DEPTH_POINTS["thorough_color"][: len(DEPTH_POINTS["thorough"])]
        == DEPTH_POINTS["thorough"]
    )


def test_the_thorough_colour_depth_measures_two_levels_per_hue():
    """A fixture can be wrong about red at 20% and right about it at 80%."""
    colours = [p for p in DEPTH_POINTS["thorough_color"] if p["type"] == TYPE_COLOR]
    levels = {p["brightness"] for p in colours}
    assert len(levels) == 2
    for hue in COLOR_HUES:
        assert len([p for p in colours if p["hue"] == hue]) == 2


def test_the_colour_points_are_the_six_hue_anchors():
    assert [p["hue"] for p in DEPTH_POINTS["colors"]] == COLOR_HUES


# ------------------------------------------------------------ describing a profile


def test_profile_summary_counts_both_kinds():
    profile = CalibrationProfile(
        [CalibrationPoint(2700, b) for b in range(9)],
        [ColorPoint(h, 60) for h in COLOR_HUES],
    )
    assert count_points(profile.as_list()) == (9, 6)
    assert profile_summary(profile.as_list()) == "9 whites, 6 colours"


def test_profile_summary_omits_what_is_not_there():
    whites = CalibrationProfile([CalibrationPoint(2700, b) for b in (10, 40, 80)])
    colours = CalibrationProfile([], [ColorPoint(h, 60) for h in COLOR_HUES])
    assert profile_summary(whites.as_list()) == "3 whites"
    assert profile_summary(colours.as_list()) == "6 colours"


def test_profile_summary_is_singular_for_one():
    assert profile_summary([{"type": TYPE_WHITE, "kelvin": 2700, "brightness": 40}]) == (
        "1 white"
    )
    assert profile_summary([{"type": TYPE_COLOR, "hue": 0, "brightness": 60}]) == (
        "1 colour"
    )


def test_profile_summary_of_no_profile_is_empty():
    assert profile_summary([]) == ""
    assert profile_summary(None) == ""
    assert count_points(None) == (0, 0)


def test_counting_treats_untyped_entries_as_whites():
    """Same back-compat as loading: no type key means it predates colours."""
    assert count_points([{"kelvin": 2700, "brightness": 40}]) == (1, 0)


# --------------------------------------------------------------------- points


def test_brightness_actual_defaults_to_the_requested_brightness():
    assert CalibrationPoint(2700, 40).brightness_actual == 40.0
    assert CalibrationPoint(2700, 40).brightness_scale == 1.0


def test_brightness_scale_is_actual_over_requested():
    assert CalibrationPoint(2700, 40, brightness_actual=45).brightness_scale == 1.125
    assert CalibrationPoint(2700, 40, brightness_actual=30).brightness_scale == 0.75


def test_zero_brightness_does_not_divide_by_zero():
    assert CalibrationPoint(2700, 0).brightness_scale == 0.0
    assert ColorPoint(0, 0).brightness_scale == 0.0


def test_colour_point_defaults_to_full_saturation():
    assert ColorPoint(0, 60).saturation == 100.0
    assert ColorPoint(0, 60).saturation_scale == 1.0
    assert ColorPoint(0, 60, saturation=80).saturation_scale == 0.8


# -------------------------------------------------------------------- storage


def test_profile_survives_a_storage_round_trip():
    profile = CalibrationProfile(
        [CalibrationPoint(2700, 40, kelvin_offset=-250, tint=20, brightness_actual=45)],
        [ColorPoint(0, 60, hue_shift=8, saturation=82, brightness_actual=55)],
    )
    restored = CalibrationProfile.from_list(profile.as_list())
    assert restored.as_list() == profile.as_list()
    assert len(restored.points) == 1
    assert len(restored.color_points) == 1


def test_a_profile_written_before_colours_existed_still_loads():
    """Entries with no ``type`` key predate colour calibration and are whites."""
    profile = CalibrationProfile.from_list(
        [{"kelvin": 2700, "brightness": 40, "kelvin_offset": -250}]
    )
    assert len(profile.points) == 1
    assert profile.points[0].kelvin_offset == -250
    assert profile.is_calibrated
    assert not profile.has_color


def test_an_empty_profile_is_not_calibrated():
    assert not CalibrationProfile.from_list(None).is_calibrated
    assert not CalibrationProfile.from_list([]).is_calibrated


def test_colour_only_profile_is_calibrated():
    profile = CalibrationProfile([], [ColorPoint(0, 60)])
    assert profile.is_calibrated
    assert profile.has_color


# --------------------------------------------------------- white interpolation


TWO_WHITES = CalibrationProfile(
    [
        CalibrationPoint(2700, 40, kelvin_offset=-250, tint=20, brightness_actual=45),
        CalibrationPoint(4000, 40, kelvin_offset=100, tint=-10, brightness_actual=30),
    ]
)


def test_no_points_means_no_correction():
    assert CalibrationProfile([]).correction(2700, 40) == (0.0, 0.0, 1.0)


def test_landing_exactly_on_a_point_returns_that_point():
    assert TWO_WHITES.correction(2700, 40) == (-250.0, 20.0, 1.125)
    assert TWO_WHITES.correction(4000, 40) == (100.0, -10.0, 0.75)


def test_between_two_points_blends_them():
    offset, tint, scale = TWO_WHITES.correction(3350, 40)
    assert -250 < offset < 100
    assert -10 < tint < 20
    assert 0.75 < scale < 1.125


def test_a_correction_never_leaves_the_measured_range():
    for kelvin in range(1000, 10001, 250):
        offset, tint, scale = TWO_WHITES.correction(kelvin, 40)
        assert -250 <= offset <= 100
        assert -10 <= tint <= 20
        assert 0.75 <= scale <= 1.125


def test_the_nearer_point_wins():
    near_warm = TWO_WHITES.correction(2800, 40)[0]
    near_cool = TWO_WHITES.correction(3900, 40)[0]
    assert near_warm < near_cool


def test_both_axes_contribute():
    """Without normalising, kelvin numbers dwarf brightness numbers and the
    brightness axis stops contributing at all."""
    profile = CalibrationProfile(
        [
            CalibrationPoint(1200, 40, kelvin_offset=100),
            CalibrationPoint(2700, 90, kelvin_offset=0),
        ]
    )
    blended = profile.correction(2700, 40)[0]
    assert 0 < blended < 100


def test_brightness_is_interpolated_perceptually_not_linearly():
    """Halfway in percent is nowhere near halfway in appearance.

    10% to 20% is about three times the visible step of 70% to 80%, so a query
    at 45% sits well past the midpoint between measurements at 10% and 80%.
    """
    profile = CalibrationProfile(
        [
            CalibrationPoint(2700, 10, kelvin_offset=0),
            CalibrationPoint(2700, 80, kelvin_offset=700),
        ]
    )
    assert profile.correction(2700, 45)[0] > 450          # linear would give 350


# ------------------------------------------------------------ the interpolator


def linear_grid(slope=0.1):
    """The Standard 3x3 grid, with an offset that varies linearly with kelvin."""
    truth = lambda k: -400 + slope * (k - 2000)  # noqa: E731
    points = [
        CalibrationPoint(k, b, kelvin_offset=truth(k))
        for b in (40, 10, 80)
        for k in (2000, 2700, 4000)
    ]
    return CalibrationProfile(points), truth


def test_a_linear_response_is_reproduced_exactly():
    """Inverse-distance weighting was out by 23K in the middle of this grid."""
    profile, truth = linear_grid()
    worst = max(
        abs(profile.correction(k, 40)[0] - truth(k)) for k in range(2000, 4001, 50)
    )
    assert worst < 0.01


def test_there_are_no_flat_spots_at_the_measured_points():
    """Inverse-distance weighting has zero gradient at every sample, so the
    surface plateaus there and has to swing in between."""
    profile, _ = linear_grid()
    below = profile.correction(2690, 40)[0]
    at = profile.correction(2700, 40)[0]
    above = profile.correction(2710, 40)[0]
    assert below < at < above


def test_the_correction_is_held_at_the_edge_outside_the_measured_points():
    """Extrapolating the fit diverges -- 325K adrift at 6500K on a curved
    response -- so outside the measured box it holds the last thing seen."""
    profile, _ = linear_grid()
    edge = profile.correction(4000, 40)[0]
    for kelvin in (4500, 5500, 6500, 10000):
        assert profile.correction(kelvin, 40)[0] == pytest.approx(edge)
    for brightness in (90, 100):
        assert profile.correction(3000, brightness) == profile.correction(3000, 80)


def test_points_that_do_not_span_a_plane_still_interpolate():
    """Every measurement at one colour temperature cannot define a plane; the
    fit has to fall back rather than blow up."""
    profile = CalibrationProfile(
        [
            CalibrationPoint(2700, 10, tint=5),
            CalibrationPoint(2700, 50, tint=9),
            CalibrationPoint(2700, 90, tint=13),
        ]
    )
    assert 5 <= profile.correction(2700, 30)[1] <= 13


def test_a_measured_point_is_still_returned_exactly():
    profile, truth = linear_grid()
    for kelvin in (2000, 2700, 4000):
        assert profile.correction(kelvin, 40)[0] == pytest.approx(truth(kelvin))


# -------------------------------------------------------- colour interpolation


def test_no_colour_points_means_no_colour_correction():
    assert CalibrationProfile([]).color_correction(0) == (0.0, 1.0, 1.0)


def test_a_single_colour_point_applies_everywhere():
    profile = CalibrationProfile(
        [], [ColorPoint(120, 60, hue_shift=8, saturation=80, brightness_actual=30)]
    )
    assert profile.color_correction(0) == (8, 0.8, 0.5)
    assert profile.color_correction(300) == (8, 0.8, 0.5)


def test_landing_exactly_on_a_hue_returns_that_hue():
    profile = CalibrationProfile(
        [], [ColorPoint(h, 60, hue_shift=h / 10.0) for h in COLOR_HUES]
    )
    for hue in COLOR_HUES:
        assert profile.color_correction(hue)[0] == pytest.approx(hue / 10.0)


def test_between_two_hues_blends_them():
    profile = CalibrationProfile(
        [], [ColorPoint(h, 60, hue_shift=h / 10.0) for h in COLOR_HUES]
    )
    assert profile.color_correction(90)[0] == pytest.approx(9.0)   # 60 and 120
    assert profile.color_correction(30)[0] == pytest.approx(3.0)   # 0 and 60


# Red sits between magenta (300) and yellow (60) the short way round. Green at
# 120 is on the far side and must never be consulted -- so it is given an
# absurd shift that would be obvious in the result if it leaked in.
POISONED_GREEN = CalibrationProfile(
    [],
    [
        ColorPoint(300, 60, hue_shift=30),
        ColorPoint(60, 60, hue_shift=-30),
        ColorPoint(120, 60, hue_shift=999),
    ],
)


@pytest.mark.parametrize(
    "hue,shift",
    [
        (0, 0.0),      # exactly between magenta and yellow
        (10, -5.0),    # a sixth of the way towards yellow
        (350, 5.0),    # below zero: wraps back towards magenta
        (30, -15.0),   # three quarters of the way to yellow
    ],
)
def test_hues_near_red_blend_magenta_and_yellow_not_green(hue, shift):
    assert POISONED_GREEN.color_correction(hue)[0] == pytest.approx(shift)


def test_wrapping_never_reaches_the_far_side_of_the_wheel():
    for hue in list(range(300, 360)) + list(range(0, 61)):
        assert POISONED_GREEN.color_correction(hue)[0] <= 30


# ------------------------------------------------------------------- commands


def test_command_for_kelvin_applies_the_correction():
    rgb, brightness = TWO_WHITES.command_for_kelvin(2700, 40)
    assert rgb == cm.corrected_rgb(2700, -250, 20)
    # 40 x 1.125 brightness scale, then divided by the tint's own brightness
    assert brightness == 41


# -------------------------------------------- commands for a tunable-white fixture


def test_kelvin_command_applies_the_offset_and_the_brightness():
    assert TWO_WHITES.kelvin_command_for_kelvin(2700, 40) == (2450, 45)
    assert TWO_WHITES.kelvin_command_for_kelvin(4000, 40) == (4100, 30)


def test_kelvin_command_ignores_tint():
    """A tunable-white fixture cannot render off the blackbody curve.

    The tint measured on it would be meaningless, so it must not leak into the
    colour temperature -- which is exactly what happens if the correction is
    sent as RGB and left to core to convert back.
    """
    tinted = CalibrationProfile([CalibrationPoint(2700, 40, kelvin_offset=-250, tint=40)])
    plain = CalibrationProfile([CalibrationPoint(2700, 40, kelvin_offset=-250, tint=0)])
    assert tinted.kelvin_command_for_kelvin(2700, 40) == plain.kelvin_command_for_kelvin(
        2700, 40
    )


def test_kelvin_command_with_no_profile_passes_through():
    assert CalibrationProfile([]).kelvin_command_for_kelvin(2700, 40) == (2700, 40)


def test_kelvin_command_stays_in_the_supported_range():
    freezing = CalibrationProfile([CalibrationPoint(1000, 40, kelvin_offset=-5000)])
    boiling = CalibrationProfile([CalibrationPoint(9000, 40, kelvin_offset=5000)])
    assert freezing.kelvin_command_for_kelvin(1000, 40)[0] == cm.MIN_KELVIN
    assert boiling.kelvin_command_for_kelvin(9000, 40)[0] == cm.MAX_KELVIN


def test_both_command_kinds_agree_when_there_is_no_tint():
    """With no tint the two drive paths differ only in the colour they send."""
    profile = CalibrationProfile(
        [CalibrationPoint(2700, 40, kelvin_offset=-250, brightness_actual=45)]
    )
    for brightness in (10, 40, 80):
        assert (
            profile.kelvin_command_for_kelvin(2700, brightness)[1]
            == profile.command_for_kelvin(2700, brightness)[1]
        )


def test_a_tinted_white_is_delivered_at_the_brightness_asked_for():
    """The rgb path takes the tint's own brightness back out of the command.

    The kelvin path has no tint to compensate for, so it does not move.
    """
    tinted = CalibrationProfile([CalibrationPoint(2700, 40, tint=40)])
    plain = CalibrationProfile([CalibrationPoint(2700, 40, tint=0)])
    assert (
        tinted.command_for_kelvin(2700, 40)[1] < plain.command_for_kelvin(2700, 40)[1]
    )
    assert (
        tinted.kelvin_command_for_kelvin(2700, 40)[1]
        == plain.kelvin_command_for_kelvin(2700, 40)[1]
    )


def test_kelvin_command_brightness_is_clamped():
    dim = CalibrationProfile([CalibrationPoint(2700, 40, brightness_actual=4)])
    bright = CalibrationProfile([CalibrationPoint(2700, 40, brightness_actual=80)])
    assert dim.kelvin_command_for_kelvin(2700, 5)[1] == 1
    assert bright.kelvin_command_for_kelvin(2700, 90)[1] == 100


def test_command_brightness_is_clamped_to_a_usable_range():
    dim = CalibrationProfile([CalibrationPoint(2700, 40, brightness_actual=4)])
    bright = CalibrationProfile([CalibrationPoint(2700, 40, brightness_actual=80)])
    assert dim.command_for_kelvin(2700, 5)[1] == 1
    assert bright.command_for_kelvin(2700, 90)[1] == 100


def test_a_near_white_rgb_request_goes_down_the_blackbody_path():
    profile = CalibrationProfile([CalibrationPoint(2700, 40, tint=20)])
    white = cm.kelvin_to_rgb(2700)
    assert profile.command_for_rgb(white, 40) == profile.command_for_kelvin(2700, 40)


def test_a_saturated_request_goes_down_the_hue_path():
    profile = CalibrationProfile(
        [CalibrationPoint(2700, 40, kelvin_offset=-250, tint=20)],
        [ColorPoint(0, 60, hue_shift=10, saturation=80, brightness_actual=30)],
    )
    rgb, brightness = profile.command_for_rgb((255, 0, 0), 50)
    assert rgb == cm.hs_to_rgb(10, 80)
    assert brightness == 25


def test_saturated_colours_pass_through_when_no_hues_were_measured():
    """Documented behaviour: hue untouched, only brightness corrected."""
    profile = CalibrationProfile([CalibrationPoint(2700, 40, brightness_actual=20)])
    for rgb in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]:
        assert profile.command_for_rgb(rgb, 50)[0] == rgb


def test_red_and_green_do_not_collapse_into_the_same_orange():
    """The regression that motivated routing by blackbody distance.

    An earlier version projected every request onto the blackbody curve. Pure
    red and pure green both landed on the warm floor and were both sent as
    (243, 81, 0) -- the light could not show green at all.
    """
    uncalibrated = CalibrationProfile([CalibrationPoint(2700, 40)])
    measured = CalibrationProfile(
        [CalibrationPoint(2700, 40)],
        [ColorPoint(h, 60, hue_shift=5) for h in COLOR_HUES],
    )
    for profile in (uncalibrated, measured):
        red = profile.command_for_rgb((255, 0, 0), 50)[0]
        green = profile.command_for_rgb((0, 255, 0), 50)[0]
        assert red != green
        assert cm.rgb_to_hs(green)[0] > 90     # still recognisably green


@pytest.mark.parametrize("tint", [TINT_MIN, TINT_MAX])
def test_command_for_kelvin_at_the_ends_of_the_tint_slider(tint):
    """The brightness compensation can ask for more than 100% at either end --
    it has to stop at 100, not wrap or go out of range."""
    for kelvin in (2700, 6500):
        profile = CalibrationProfile([CalibrationPoint(kelvin, 80, tint=tint)])
        rgb, brightness = profile.command_for_kelvin(kelvin, 80)
        assert rgb == cm.corrected_rgb(kelvin, 0, tint)
        assert 1 <= brightness <= 100
