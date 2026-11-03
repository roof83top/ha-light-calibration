"""The calibrated (virtual) light entity."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import capability
from .calibration import ROUTE_RGB, CalibrationProfile, white_route
from .color_math import rgb_to_kelvin, split_level
from .session import CalibrationSession
from .const import (
    CONF_ORIGINAL_ID,
    CONF_POINTS,
    CONF_REFERENCE,
    CONF_TARGET,
    CONF_WHITE_MODE,
    DEFAULT_TRANSITION,
    DOMAIN,
    WHITE_MODE_RGB,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_MIN_KELVIN = 2000
DEFAULT_MAX_KELVIN = 6500


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([CalibratedLight(hass, entry)])


class CalibratedLight(LightEntity):
    """Presents a corrected view of a miscalibrated light.

    Asked for 2700K at 40%, it works out what THIS fixture needs to be sent to
    actually look like 2700K at 40%, and sends that instead.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_supported_features = LightEntityFeature.TRANSITION

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._target: str = entry.data[CONF_TARGET]
        self._reference: str = entry.data.get(CONF_REFERENCE, "")
        self._white_mode: str = entry.data.get(CONF_WHITE_MODE, WHITE_MODE_RGB)
        self._profile = CalibrationProfile.from_list(entry.data.get(CONF_POINTS))
        _LOGGER.debug("%s: loaded %d calibration points", entry.title, len(self._profile.points))

        self._attr_name = entry.title
        self._attr_unique_id = f"{entry.entry_id}_calibrated"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Light Calibration",
            model="Calibrated light",
        )

        # Claim the entity_id the real light used to have. __init__.py has
        # already moved the real one out of the way.
        original = entry.data.get(CONF_ORIGINAL_ID)
        if original:
            self.entity_id = original

        self._attr_color_mode = ColorMode.COLOR_TEMP
        self._attr_brightness: int | None = None
        self._attr_color_temp_kelvin: int | None = None
        self._attr_rgb_color: tuple[int, int, int] | None = None
        self._attr_is_on = False

        self._session: CalibrationSession | None = hass.data.get(DOMAIN, {}).get(
            entry.entry_id
        )
        self._enabled = self._session.enabled if self._session else True
        self._empty = CalibrationProfile([])

    # ------------------------------------------------------------------ setup
    async def async_added_to_hass(self) -> None:
        self._sync_from_target()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._target], self._handle_target_change
            )
        )
        if self._session:
            self.async_on_remove(self._session.add_listener(self._handle_session))

    @callback
    def _handle_session(self) -> None:
        """React to the calibration switch being flipped.

        Re-send the last request through the new path so the fixture visibly
        jumps between raw and corrected -- that is the whole point of the switch.
        """
        if not self._session or self._session.enabled == self._enabled:
            return
        self._enabled = self._session.enabled
        self.async_write_ha_state()
        if self._attr_is_on:
            self.hass.async_create_task(self._async_reapply())

    async def _async_reapply(self) -> None:
        kwargs: dict[str, Any] = {}
        if self._attr_brightness is not None:
            kwargs[ATTR_BRIGHTNESS] = self._attr_brightness
        if self._attr_rgb_color:
            kwargs[ATTR_RGB_COLOR] = self._attr_rgb_color
        elif self._attr_color_temp_kelvin:
            kwargs[ATTR_COLOR_TEMP_KELVIN] = self._attr_color_temp_kelvin
        await self.async_turn_on(**kwargs)

    @property
    def _active_profile(self) -> CalibrationProfile:
        """The stored profile, or a pass-through one when calibration is off."""
        if self._session and not self._session.enabled:
            return self._empty
        return self._profile

    @callback
    def _handle_target_change(self, event: Event) -> None:
        self._sync_from_target()
        self.async_write_ha_state()

    @callback
    def _sync_from_target(self) -> None:
        """Follow the real light's on/off and capabilities.

        Colour and brightness keep whatever was last *requested* of us -- that
        is the whole point: the numbers you asked for are the numbers you see,
        even though the fixture is being driven with different ones.
        """
        state = self.hass.states.get(self._target)
        if state is None:
            self._attr_is_on = False
            return
        self._attr_is_on = state.state == STATE_ON
        if not self._attr_is_on:
            return
        if self._attr_brightness is None:
            self._attr_brightness = state.attributes.get(ATTR_BRIGHTNESS)
        if self._attr_color_temp_kelvin is None:
            self._attr_color_temp_kelvin = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Advertise only what the fixture behind us can actually do.

        A tunable-white fixture gets colour temperature alone -- claiming RGB
        would put a colour wheel on a light that cannot show a colour.
        """
        if capability.supports_color(self.hass, self._target):
            return {ColorMode.COLOR_TEMP, ColorMode.RGB}
        return {ColorMode.COLOR_TEMP}

    @property
    def available(self) -> bool:
        """Follow the real fixture.

        This entity has taken over the original entity_id, so it is the only
        thing anything points at. If the fixture drops off the network that has
        to surface here -- reporting "off" instead tells every automation and
        dashboard the light is fine when it is not there at all.
        """
        state = self.hass.states.get(self._target)
        return state is not None and state.state != STATE_UNAVAILABLE

    @property
    def min_color_temp_kelvin(self) -> int:
        """Advertise the reference light's range, not the target's.

        The point of calibration is that the fixture's own limits stop mattering
        -- driven in RGB it can render below its native colour-temp floor.
        """
        state = self.hass.states.get(self._reference) if self._reference else None
        if state:
            return state.attributes.get("min_color_temp_kelvin") or DEFAULT_MIN_KELVIN
        return DEFAULT_MIN_KELVIN

    @property
    def max_color_temp_kelvin(self) -> int:
        state = self.hass.states.get(self._reference) if self._reference else None
        if state:
            return state.attributes.get("max_color_temp_kelvin") or DEFAULT_MAX_KELVIN
        return DEFAULT_MAX_KELVIN

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "calibrated_target": self._target,
            "reference_light": self._reference,
            "calibration_points": len(self._profile.points),
            "calibrated": self._profile.is_calibrated,
            "calibration_applied": bool(self._session.enabled) if self._session else True,
            "white_mode": self._white_mode,
        }

    # ------------------------------------------------------------------ action
    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness or 255)
        profile = self._active_profile
        color_capable = capability.supports_color(self.hass, self._target)

        # A colour and a level are separate things, so a request carrying both
        # is split before either is used -- see split_level.
        requested_rgb = None
        if ATTR_RGB_COLOR in kwargs:
            requested_rgb, level = split_level(tuple(kwargs[ATTR_RGB_COLOR]))
            brightness *= level

        brightness_pct = max(1.0, min(100.0, brightness / 255.0 * 100.0))
        data: dict[str, Any] = {ATTR_ENTITY_ID: self._target}

        if requested_rgb is not None and color_capable:
            rgb, out_pct = profile.command_for_rgb(requested_rgb, brightness_pct)
            data[ATTR_RGB_COLOR] = list(rgb)
            self._attr_color_mode = ColorMode.RGB
            self._attr_rgb_color = requested_rgb
            self._attr_color_temp_kelvin = None
        else:
            # A tunable-white fixture cannot show a colour, so a colour request
            # is resolved to the nearest colour temperature here rather than
            # being left to core's rgb-to-kelvin fallback, which would drop the
            # correction and shift the result by hundreds of kelvin.
            if requested_rgb is not None:
                kelvin = rgb_to_kelvin(requested_rgb)
            else:
                kelvin = kwargs.get(
                    ATTR_COLOR_TEMP_KELVIN, self._attr_color_temp_kelvin or 2700
                )
            # The same rule calibration measured with: RGB, or -- in the kelvin
            # white mode, inside the fixture's own range -- its white LEDs.
            ct_range = capability.kelvin_range(self.hass, self._target)
            route = white_route(
                self._white_mode, kelvin, ct_range, color_capable,
                capability.has_white_channel(self.hass, self._target),
            )
            command = profile.command_for_white(
                kelvin, brightness_pct, route, ct_range, color_capable
            )
            out_pct = command.pop("brightness_pct")
            if route == ROUTE_RGB:
                data[ATTR_RGB_COLOR] = command["rgb_color"]
            else:
                data[ATTR_COLOR_TEMP_KELVIN] = command["color_temp_kelvin"]
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_color_temp_kelvin = int(kelvin)
            self._attr_rgb_color = None

        self._attr_brightness = int(round(brightness))
        self._attr_is_on = True
        data["brightness_pct"] = out_pct
        transition = kwargs.get(ATTR_TRANSITION, DEFAULT_TRANSITION)
        if transition:
            data[ATTR_TRANSITION] = transition

        _LOGGER.debug(
            "%s: asked for %s -> driving %s with %s",
            self.entity_id,
            kwargs,
            self._target,
            {k: v for k, v in data.items() if k != ATTR_ENTITY_ID},
        )
        await self.hass.services.async_call(
            "light", "turn_on", data, blocking=False, context=self._context
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        data: dict[str, Any] = {ATTR_ENTITY_ID: self._target}
        if ATTR_TRANSITION in kwargs:
            data[ATTR_TRANSITION] = kwargs[ATTR_TRANSITION]
        self._attr_is_on = False
        await self.hass.services.async_call(
            "light", "turn_off", data, blocking=False, context=self._context
        )
        self.async_write_ha_state()
