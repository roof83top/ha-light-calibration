"""The live calibration session.

Walks a list of steps. A step is either a **white** (a colour temperature at a
brightness) or a **colour** (a hue at a brightness), and each kind gets its own
set of adjustments -- warm/cool and tint make no sense on pure red, and a hue
rotation makes no sense on a white.

Moving a slider applies to the light immediately, so you adjust and watch rather
than adjust and submit.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from . import capability
from .calibration import (
    COLOR_NAMES,
    DEPTH_POINTS,
    ROUTE_KELVIN,
    ROUTE_RGB,
    TYPE_COLOR,
    TYPE_WHITE,
    CalibrationPoint,
    CalibrationProfile,
    ColorPoint,
    white_command,
    white_rerun_notification_id,
    white_route,
)
from .color_math import corrected_rgb, hs_to_rgb
from .const import (
    CONF_POINTS,
    CONF_REFERENCE,
    CONF_TARGET,
    CONF_WHITE_MODE,
    CONF_WHITES_MEASURED_MODE,
    DEFAULT_TRANSITION,
    WHITE_MODE_RGB,
)

_LOGGER = logging.getLogger(__name__)


class CalibrationSession:
    """Holds the in-progress calibration for one entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.reference: str = entry.data.get(CONF_REFERENCE, "")
        self.target: str = entry.data.get(CONF_TARGET, "")

        self.active = False
        self.depth = "standard"
        self.points: list[dict] = []
        self.results: list[Any] = []
        self.index = 0
        # Steps the reference light turned out not to be able to show, so the
        # dialog can say so rather than silently measuring fewer points.
        self.skipped: list[str] = []
        # The check at the end: a few of the measured points replayed with the
        # new profile applied, so a botched run is visible before it is saved.
        self.verifying = False
        self.verify_points: list[dict] = []
        self.verify_index = 0
        self._comparing = False

        # live values for a white step
        self.warm_cool = 0.0
        self.tint = 0.0
        # live values for a colour step
        self.hue_shift = 0.0
        self.saturation = 100.0
        # shared
        self.brightness = 40.0

        self._listeners: list[Callable[[], None]] = []
        self._snapshot: dict[str, dict] = {}
        # Whether the stored profile is applied. The switch flips this so the
        # before/after can be seen directly on the light.
        self.enabled = True

    # ------------------------------------------------------------- plumbing
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # ---------------------------------------------------------------- state
    @property
    def total(self) -> int:
        return len(self.points)

    @property
    def current(self) -> dict | None:
        if self.verifying:
            if self.verify_index >= len(self.verify_points):
                return None
            return self.verify_points[self.verify_index]
        if not self.active or self.index >= len(self.points):
            return None
        return self.points[self.index]

    @property
    def step_type(self) -> str | None:
        step = self.current
        return step["type"] if step else None

    @property
    def is_color_step(self) -> bool:
        return self.step_type == TYPE_COLOR

    @property
    def reference_kelvin_range(self) -> tuple[int, int] | None:
        """What colour temperatures the reference can actually show."""
        state = self.hass.states.get(self.reference)
        if state is None:
            return None
        low = state.attributes.get("min_color_temp_kelvin")
        high = state.attributes.get("max_color_temp_kelvin")
        if not low or not high:
            return None
        return int(low), int(high)

    def _usable(self, points: list[dict]) -> list[dict]:
        """Drop steps the reference cannot actually show, and say which.

        Every preset asks for 2000K somewhere and plenty of bulbs floor at 2200K
        or 2700K. Home Assistant clamps silently, so the reference sits at its
        floor while the profile records the answer against the number that was
        asked for -- the warm end of the profile ends up measuring a colour
        temperature the reference never produced.
        """
        self.skipped = []
        keep = list(points)

        if not capability.supports_color(self.hass, self.reference):
            dropped = [p for p in keep if p["type"] == TYPE_COLOR]
            if dropped:
                self.skipped.append(
                    f"{len(dropped)} colour steps: the reference light cannot show colours"
                )
            keep = [p for p in keep if p["type"] != TYPE_COLOR]

        if (span := self.reference_kelvin_range) is not None:
            low, high = span
            reachable = (
                lambda p: p["type"] != TYPE_WHITE or low <= p["kelvin"] <= high
            )
            dropped = [p for p in keep if not reachable(p)]
            if dropped:
                edges = sorted({p["kelvin"] for p in dropped})
                self.skipped.append(
                    f"{len(dropped)} steps at {', '.join(f'{k}K' for k in edges)}: "
                    f"the reference light only covers {low}-{high}K"
                )
            keep = [p for p in keep if reachable(p)]
        return keep

    @property
    def supports_color(self) -> bool:
        """Whether the fixture can be driven off the blackbody curve.

        A tunable-white one cannot, so it gets no hue steps and no tint axis --
        there is no way for it to render either.
        """
        return capability.supports_color(self.hass, self.target)

    @property
    def white_mode(self) -> str:
        return self.entry.data.get(CONF_WHITE_MODE, WHITE_MODE_RGB)

    def white_route(self, step: dict) -> str:
        """How the target is sent this white step: the light's own rule.

        Calibration has to measure exactly what the calibrated light will send
        later, so this is the same white_route call light.py makes.
        """
        return white_route(
            self.white_mode,
            step["kelvin"],
            capability.kelvin_range(self.hass, self.target),
            self.supports_color,
            capability.has_white_channel(self.hass, self.target),
        )

    def _white_ct_range(self, route: str) -> tuple[int, int] | None:
        """The range a kelvin-routed white is clamped to, None for the global limits.

        The fixture's reported range only bounds a colour fixture's white LEDs,
        as in the light; a tunable white is clamped as it always was.
        """
        if self.supports_color and route == ROUTE_KELVIN:
            return capability.kelvin_range(self.hass, self.target)
        return None

    @property
    def white_kelvin_range(self) -> list[int] | None:
        """The current white step's kelvin clamp, for auto mode's command model.

        Set only where _target_data clamps to the fixture's own range (a
        colour fixture's white LEDs, range reported); None otherwise.
        """
        step = self.current
        if not step or step["type"] != TYPE_WHITE:
            return None
        ct_range = self._white_ct_range(self.white_route(step))
        return list(ct_range) if ct_range else None

    def _profile_route(self, route: str) -> str | None:
        """Which stored points correct this route: None (all) on a tunable white."""
        return route if self.supports_color else None

    @property
    def white_tint(self) -> bool | None:
        """Whether the current white step has a green/magenta axis.

        Only an RGB-routed white on a colour fixture does. None on a colour
        step or with no step, so a reader falls back to supports_color.
        """
        step = self.current
        if not step or step["type"] != TYPE_WHITE:
            return None
        return self.supports_color and self.white_route(step) == ROUTE_RGB

    @property
    def step_label(self) -> str:
        if self.verifying:
            return f"{self.verify_index + 1}/{len(self.verify_points)}"
        return f"{self.index + 1}/{self.total}" if self.active else "idle"

    @property
    def step_title(self) -> str:
        step = self.current
        if not step:
            return ""
        if step["type"] == TYPE_COLOR:
            name = COLOR_NAMES.get(step["hue"], f"{step['hue']}°")
            return f"{name} at {step['brightness']}%"
        return f"{step['kelvin']}K at {step['brightness']}%"

    @property
    def instructions(self) -> str:
        step = self.current
        if not step:
            return "Press 'Start calibration' to begin."
        if self.verifying:
            return (
                "This is the finished calibration, replayed. Both lights should "
                "now look the same. If one of these is off, go back and redo it "
                "-- everything measured so far is kept either way."
            )
        if step["type"] == TYPE_COLOR:
            name = COLOR_NAMES.get(step["hue"], "this colour")
            return (
                f"The reference is showing {name}. Rotate the hue until the two "
                f"read as the same colour, then pull saturation and brightness to "
                f"match. Colours are harder to judge than whites -- step back and "
                f"compare, do not stare."
            )
        return (
            f"Reference is at {step['kelvin']}K, {step['brightness']}%. Move the "
            f"sliders until the light being calibrated looks the same. Purple or "
            f"pink means push Magenta/green towards green."
        )

    # --------------------------------------------------------------- actions
    def _take_snapshot(self) -> None:
        """Remember how the lights looked so calibrating can put them back."""
        self._snapshot = {}
        for entity in (self.reference, self.target):
            state = self.hass.states.get(entity)
            if state is None:
                continue
            a = state.attributes
            self._snapshot[entity] = {
                "on": state.state == "on",
                "brightness": a.get("brightness"),
                "color_temp_kelvin": a.get("color_temp_kelvin"),
                "rgb_color": a.get("rgb_color"),
            }

    async def _async_restore_snapshot(self) -> None:
        """Put the lights back the way they were before calibration started."""
        for entity, snap in self._snapshot.items():
            if not snap["on"]:
                await self.hass.services.async_call(
                    "light", "turn_off",
                    {ATTR_ENTITY_ID: entity, "transition": DEFAULT_TRANSITION},
                    blocking=False,
                )
                continue
            data: dict = {ATTR_ENTITY_ID: entity, "transition": DEFAULT_TRANSITION}
            if snap["brightness"] is not None:
                data["brightness"] = snap["brightness"]
            if snap["color_temp_kelvin"]:
                data["color_temp_kelvin"] = snap["color_temp_kelvin"]
            elif snap["rgb_color"]:
                data["rgb_color"] = list(snap["rgb_color"])
            await self.hass.services.async_call("light", "turn_on", data, blocking=False)
        self._snapshot = {}

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self._notify()

    def _seed_values_for_step(self) -> None:
        """Pre-load the sliders for the current step.

        With a stored profile this is what makes a re-run a *fine tune*: the
        light already sits where the last calibration put it, and only the
        difference needs correcting. Without one, corrections carry forward from
        the previous step, which is usually close.
        """
        step = self.current
        if not step:
            return
        self.brightness = float(step["brightness"])

        profile = self.profile
        if not profile.is_calibrated:
            if step["type"] == TYPE_COLOR and not self._came_from_color():
                self.hue_shift = 0.0
                self.saturation = 100.0
            return

        if step["type"] == TYPE_COLOR:
            shift, sat_scale, bright_scale = profile.color_correction(step["hue"])
            self.hue_shift = shift
            self.saturation = min(100.0, max(0.0, 100.0 * sat_scale))
            self.brightness = min(100.0, max(1.0, step["brightness"] * bright_scale))
        else:
            offset, tint, scale = profile.correction(
                step["kelvin"], step["brightness"],
                self._profile_route(self.white_route(step)),
            )
            self.warm_cool = offset
            self.tint = tint
            self.brightness = min(100.0, max(1.0, step["brightness"] * scale))

    def _came_from_color(self) -> bool:
        return self.index > 0 and self.points[self.index - 1]["type"] == TYPE_COLOR

    def _merged_points(self) -> list[dict]:
        """Fold this run's results into the stored profile.

        Points are keyed on what they measure, so re-doing a step replaces just
        that step and everything untouched survives. A colours-only run keeps the
        whites; a partial re-run keeps whatever it did not revisit.
        """
        def key(d: dict) -> tuple:
            if d.get("type") == TYPE_COLOR:
                return (TYPE_COLOR, d.get("hue"), d.get("brightness"))
            return ("white", d.get("kelvin"), d.get("brightness"))

        merged = {key(d): d for d in (self.entry.data.get(CONF_POINTS) or [])}
        for point in self.results:
            d = point.as_dict()
            merged[key(d)] = d
        return list(merged.values())

    async def async_start(self, depth: str | None = None) -> None:
        self.depth = depth or self.depth
        points = list(DEPTH_POINTS[self.depth])
        if not self.supports_color:
            points = [p for p in points if p["type"] != TYPE_COLOR]
        points = self._usable(points)
        if not points:
            _LOGGER.warning(
                "%s cannot show colours, so depth %s has nothing to measure",
                self.target, self.depth,
            )
            return
        self._take_snapshot()
        self.points = points
        self.results = []
        self.index = 0
        self.active = True
        self.verifying = False
        self.verify_points = []
        self.verify_index = 0
        self.warm_cool = 0.0
        self.tint = 0.0
        self.hue_shift = 0.0
        self.saturation = 100.0
        self._seed_values_for_step()
        _LOGGER.info(
            "Calibration started: %s against %s, %d steps",
            self.target, self.reference, len(self.points),
        )
        await self.async_apply()
        self._notify()

    async def async_cancel(self) -> None:
        self.active = False
        self.verifying = False
        self.points = []
        self.results = []
        self.verify_points = []
        self.index = 0
        await self._async_restore_snapshot()
        self._notify()

    async def async_next(self) -> None:
        """Record the current step and move on; check the result at the end."""
        if self.verifying:
            self.verify_index += 1
            if self.verify_index >= len(self.verify_points):
                await self._async_save()
                return
            await self.async_apply()
            self._notify()
            return

        step = self.current
        if not step:
            return

        if step["type"] == TYPE_COLOR:
            self.results.append(
                ColorPoint(
                    hue=step["hue"],
                    brightness=step["brightness"],
                    hue_shift=self.hue_shift,
                    saturation=self.saturation,
                    brightness_actual=self.brightness,
                )
            )
        else:
            route = self.white_route(step)
            self.results.append(
                CalibrationPoint(
                    kelvin=step["kelvin"],
                    brightness=step["brightness"],
                    kelvin_offset=self.warm_cool,
                    # Off the RGB route there is no tint axis; whatever the
                    # slider carried over from an RGB step was never sent.
                    tint=self.tint if route == ROUTE_RGB else 0.0,
                    brightness_actual=self.brightness,
                    route=route,
                )
            )
        self.index += 1

        if self.index >= len(self.points):
            await self._async_begin_verify()
            return

        self._seed_values_for_step()
        await self.async_apply()
        self._notify()

    async def async_back(self) -> None:
        """Step back to redo the previous step, or leave the check to fix one."""
        if self.verifying:
            if self.verify_index > 0:
                self.verify_index -= 1
                await self.async_apply()
                self._notify()
                return
            self.verifying = False
            self.index = len(self.points)   # rewound to the last step just below

        if not self.active or self.index == 0:
            return
        self.index -= 1
        if self.results:
            previous = self.results.pop()
            self.brightness = previous.brightness_actual
            if isinstance(previous, ColorPoint):
                self.hue_shift = previous.hue_shift
                self.saturation = previous.saturation
            else:
                self.warm_cool = previous.kelvin_offset
                self.tint = previous.tint
        await self.async_apply()
        self._notify()

    async def async_finish(self) -> None:
        """Save what has been measured so far and stop.

        For fine-tuning: fix the one point that drifted, then finish, instead of
        clicking through every remaining step.
        """
        if not (self.active or self.verifying):
            return
        await self._async_save()

    def _verify_sample(self) -> list[dict]:
        """A few of the points just measured, spread across the run.

        Enough to notice a calibration that came out wrong, few enough that
        nobody skips the check.
        """
        whites = [r for r in self.results if isinstance(r, CalibrationPoint)]
        colors = [r for r in self.results if isinstance(r, ColorPoint)]
        chosen: list[dict] = []
        for group, wanted in ((whites, 3), (colors, 2)):
            if not group:
                continue
            take = min(wanted, len(group))
            stride = (len(group) - 1) / (take - 1) if take > 1 else 0
            for i in range(take):
                point = group[int(round(i * stride))]
                if isinstance(point, ColorPoint):
                    chosen.append({"type": TYPE_COLOR, "hue": point.hue,
                                   "brightness": point.brightness})
                else:
                    chosen.append({"type": TYPE_WHITE, "kelvin": point.kelvin,
                                   "brightness": point.brightness})
        return chosen

    async def _async_begin_verify(self) -> None:
        """Replay a few measured points with the finished profile applied.

        Calibrating step by step gives no sense of the result as a whole, and a
        systematically bad run -- a reference that never reached the colour it
        was asked for, a slider left somewhere silly -- is invisible until weeks
        later. Thirty seconds of looking catches it while it is still fixable.
        """
        self.verify_points = self._verify_sample()
        if not self.verify_points:
            await self._async_save()
            return
        self.verifying = True
        self.verify_index = 0
        await self.async_apply()
        self._notify()

    async def _async_save(self) -> None:
        points = self._merged_points()
        self.active = False
        self.verifying = False
        _LOGGER.info(
            "Calibration finished for %s: %d measured this run, %d points stored",
            self.target, len(self.results), len(points),
        )
        data = {**self.entry.data, CONF_POINTS: points}
        if any(isinstance(r, CalibrationPoint) for r in self.results):
            # Whites measured in this mode: the "re-measure your whites" flag
            # that switching white_mode raises is answered.
            data[CONF_WHITES_MEASURED_MODE] = self.white_mode
            persistent_notification.async_dismiss(
                self.hass, white_rerun_notification_id(self.entry.entry_id)
            )
        await self._async_restore_snapshot()
        self._notify()
        self.hass.config_entries.async_update_entry(self.entry, data=data)

    # ----------------------------------------------------------------- apply
    def _reference_data(self, step: dict) -> dict:
        data = {
            ATTR_ENTITY_ID: self.reference,
            "brightness_pct": step["brightness"],
            "transition": DEFAULT_TRANSITION,
        }
        if step["type"] == TYPE_COLOR:
            data["rgb_color"] = list(hs_to_rgb(step["hue"], 100.0))
        else:
            data["color_temp_kelvin"] = step["kelvin"]
        return data

    def _target_data(self, step: dict, raw: bool = False) -> dict:
        """What to send the fixture for this step.

        ``raw`` is the same step with no correction at all -- what the fixture
        does left to itself, which is what the compare button flashes back to.
        While verifying, the correction comes from the finished profile rather
        than the sliders.
        """
        data: dict = {ATTR_ENTITY_ID: self.target, "transition": DEFAULT_TRANSITION}
        profile = (
            CalibrationProfile.from_list(self._merged_points())
            if self.verifying else None
        )

        if step["type"] == TYPE_COLOR:
            nominal = hs_to_rgb(step["hue"], 100.0)
            if raw:
                data["rgb_color"] = list(nominal)
                data["brightness_pct"] = step["brightness"]
            elif profile is not None:
                rgb, out = profile.command_for_rgb(nominal, float(step["brightness"]))
                data["rgb_color"] = list(rgb)
                data["brightness_pct"] = out
            else:
                data["rgb_color"] = list(
                    hs_to_rgb(step["hue"] + self.hue_shift, self.saturation)
                )
                data["brightness_pct"] = int(round(self.brightness))
            return data

        # The route the calibrated light will use for this white: RGB, or a
        # colour temperature (a tunable-white fixture, or a colour one's white
        # LEDs in the kelvin white mode). A kelvin is driven directly -- going
        # via RGB would be converted back by core, losing the offset we are
        # here to measure. white_command keeps the tint's own brightness out
        # of an RGB white, so the two sliders can be judged one at a time.
        kelvin = step["kelvin"]
        route = self.white_route(step)
        ct_range = self._white_ct_range(route)
        if raw:
            data.update(white_command(
                kelvin, float(step["brightness"]), route, ct_range=ct_range
            ))
        elif profile is not None:
            data.update(profile.command_for_white(
                kelvin, step["brightness"], route, ct_range, self.supports_color
            ))
        else:
            data.update(white_command(
                kelvin, self.brightness, route, self.warm_cool,
                self.tint if route == ROUTE_RGB else 0.0, ct_range,
            ))
        return data

    async def async_apply(self) -> None:
        """Push the current values to both lights right now."""
        step = self.current
        if not step:
            return
        await self.hass.services.async_call(
            "light", "turn_on", self._reference_data(step), blocking=False
        )
        await self.hass.services.async_call(
            "light", "turn_on", self._target_data(step), blocking=False
        )

    async def async_compare(self, seconds: float = 1.6) -> None:
        """Flash the fixture back to no correction at all, then return.

        The eye is far better at spotting a difference across a switch than
        across a gap: what is invisible while you stare at two lights is obvious
        the moment one of them changes. This is the quickest way to tell whether
        an adjustment is actually helping.
        """
        if self._comparing or not (self.active or self.verifying):
            return
        step = self.current
        if not step:
            return
        self._comparing = True
        self._notify()
        try:
            await self.hass.services.async_call(
                "light", "turn_on", self._target_data(step, raw=True), blocking=False
            )
            await asyncio.sleep(seconds)
        finally:
            self._comparing = False
            await self.async_apply()
            self._notify()

    async def async_set_values(
        self,
        warm_cool: float | None = None,
        tint: float | None = None,
        brightness: float | None = None,
        hue_shift: float | None = None,
        saturation: float | None = None,
    ) -> None:
        """Set any combination of the axes in one go, then apply once.

        The dialog sends the whole set while you drag, so this keeps it to a
        single light command per update instead of one per slider.
        """
        if warm_cool is not None:
            self.warm_cool = float(warm_cool)
        if tint is not None:
            self.tint = float(tint)
        if brightness is not None:
            self.brightness = float(brightness)
        if hue_shift is not None:
            self.hue_shift = float(hue_shift)
        if saturation is not None:
            self.saturation = float(saturation)
        if self.active:
            await self.async_apply()
        self._notify()

    # ------------------------------------------------------------- preview
    @property
    def profile(self) -> CalibrationProfile:
        return CalibrationProfile.from_list(self.entry.data.get(CONF_POINTS))

    def preview_rgb(self) -> tuple[int, int, int]:
        """The swatch shown in the dialog: what the fixture is being sent.

        Always an RGB, even for a fixture being driven by kelvin -- this is a
        picture of the colour, not the command.
        """
        step = self.current
        if not step:
            return (255, 167, 87)
        if step["type"] == TYPE_COLOR:
            return hs_to_rgb(step["hue"] + self.hue_shift, self.saturation)
        tint = self.tint if self.white_tint else 0.0
        return corrected_rgb(step["kelvin"], self.warm_cool, tint)

    def extra_attributes(self) -> dict[str, Any]:
        step = self.current
        return {
            "active": self.active or self.verifying,
            "depth": self.depth,
            "step": self.index + 1 if self.active else None,
            "total": self.total or None,
            "step_type": self.step_type,
            "step_title": self.step_title,
            "nominal_kelvin": step.get("kelvin") if step else None,
            "nominal_hue": step.get("hue") if step else None,
            "nominal_brightness": step.get("brightness") if step else None,
            "sending_rgb": list(self.preview_rgb()) if self.active else None,
            "instructions": self.instructions,
            "reference_light": self.reference,
            "calibrating": self.target,
            "warm_cool": self.warm_cool,
            "green_magenta": self.tint,
            "hue_shift": self.hue_shift,
            "saturation": self.saturation,
            "brightness": self.brightness,
            "entry_id": self.entry.entry_id,
            "calibration_enabled": self.enabled,
            "supports_color": self.supports_color,
            # Per white step: false when this white has no tint axis (a
            # tunable white, or the white LEDs in the kelvin white mode); None
            # on a colour step.
            "white_tint": self.white_tint,
            "white_route": (
                self.white_route(step) if step and step["type"] == TYPE_WHITE else None
            ),
            # Where that white's colour temperature is clamped (see above).
            "white_kelvin_range": self.white_kelvin_range,
            "verifying": self.verifying,
            "verify_step": self.verify_index + 1 if self.verifying else None,
            "verify_total": len(self.verify_points) if self.verifying else None,
            "comparing": self._comparing,
            "skipped": self.skipped,
            "measured_this_run": len(self.results),
        }
