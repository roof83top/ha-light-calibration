"""Setup flow.

Calibration itself is not done here -- a config-flow form can only react when
you press Submit, which makes eyeballing a colour match miserable. The sliders
live on the device page instead and apply the moment you move them. This flow
just wires the two lights together.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from .capability import color_modes, is_calibratable

from .const import (
    CONF_NAME,
    CONF_ORIGINAL_ID,
    CONF_POINTS,
    CONF_REFERENCE,
    CONF_RENAMED_ID,
    CONF_TARGET,
    CONF_WHITE_MODE,
    DOMAIN,
    WHITE_MODE_RGB,
    WHITE_MODES,
)
from .white_mode import async_update_with_white_mode

_LOGGER = logging.getLogger(__name__)

RAW_SUFFIX = "_raw"


def _light_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="light", multiple=False)
    )


class LightCalibrationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair a light that looks wrong with one that looks right."""

    VERSION = 1
    MINOR_VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            reference = user_input[CONF_REFERENCE]
            target = user_input[CONF_TARGET]
            if reference == target:
                errors["base"] = "same_light"
            elif problem := self._problem_with(target):
                errors["base"] = problem
            else:
                await self.async_set_unique_id(f"{DOMAIN}_{target}")
                self._abort_if_unique_id_configured()
                domain, object_id = target.split(".", 1)
                renamed = f"{domain}.{object_id}{RAW_SUFFIX}"
                name = user_input.get(CONF_NAME) or self._default_name(target)
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_NAME: name,
                        CONF_REFERENCE: reference,
                        CONF_TARGET: renamed,        # __init__ moves the real light here
                        CONF_ORIGINAL_ID: target,    # ...the virtual light takes this
                        CONF_RENAMED_ID: renamed,
                        CONF_POINTS: [],
                    },
                )

        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REFERENCE): _light_selector(),
                    vol.Required(CONF_TARGET): _light_selector(),
                    vol.Optional(CONF_NAME): selector.TextSelector(),
                }
            ),
        )

    def _problem_with(self, target: str) -> str | None:
        """Why this light cannot be calibrated, if it cannot.

        Caught here rather than at setup because every one of these fails in a
        way that is hard to see from the outside: a light that cannot be
        renamed leaves two entities fighting over one entity_id, and one with no
        colour behaviour at all just quietly does nothing.
        """
        if er.async_get(self.hass).async_get(target) is None:
            # The virtual light claims this entity_id, so the real one has to be
            # renamed out of the way first. A YAML light or a light group has no
            # registry entry to rename.
            return "not_registered"

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_RENAMED_ID) == target:
                return "raw_light"
            if entry.data.get(CONF_ORIGINAL_ID) == target:
                return "already_calibrated"

        modes = color_modes(self.hass, target)
        if modes and not is_calibratable(modes):
            return "no_color_control"
        return None

    def _default_name(self, target: str) -> str:
        state = self.hass.states.get(target)
        friendly = state.attributes.get("friendly_name") if state else None
        return friendly or target.split(".", 1)[-1].replace("_", " ").title()

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return LightCalibrationOptionsFlow()


class LightCalibrationOptionsFlow(OptionsFlow):
    """Change the reference light, how whites are driven, or clear the profile."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            data = {**entry.data, CONF_REFERENCE: user_input[CONF_REFERENCE]}
            if user_input.get("clear_profile"):
                data[CONF_POINTS] = []
            async_update_with_white_mode(
                self.hass, entry, data,
                user_input.get(CONF_WHITE_MODE, WHITE_MODE_RGB),
            )
            return self.async_create_entry(title="", data={})

        stored = len(entry.data.get(CONF_POINTS) or [])
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REFERENCE, default=entry.data.get(CONF_REFERENCE)
                    ): _light_selector(),
                    vol.Required(
                        CONF_WHITE_MODE,
                        default=entry.data.get(CONF_WHITE_MODE, WHITE_MODE_RGB),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(WHITE_MODES),
                            mode=selector.SelectSelectorMode.LIST,
                            translation_key=CONF_WHITE_MODE,
                        )
                    ),
                    vol.Required("clear_profile", default=False): selector.BooleanSelector(),
                }
            ),
            description_placeholders={
                "target": entry.data.get(CONF_ORIGINAL_ID, ""),
                "points": str(stored),
            },
        )
