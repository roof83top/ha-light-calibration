"""Where the calibration has got to.

Also the data source for the dialog card, which reads this entity's attributes
for the current step, the live slider values and the entry_id.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .calibration import count_points, profile_summary, whites_need_rerun
from .const import CONF_POINTS, DOMAIN
from .entity import CalibrationControlEntity
from .session import CalibrationSession


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    session: CalibrationSession = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CalibrationStatus(entry, session)])


class CalibrationStatus(CalibrationControlEntity, SensorEntity):
    _attr_name = "Calibration"
    _attr_icon = "mdi:eyedropper-variant"

    def __init__(self, entry: ConfigEntry, session: CalibrationSession) -> None:
        super().__init__(entry, session, "status")

    @property
    def native_value(self) -> str:
        if self._session.active or self._session.verifying:
            # step_title formats whites and colours differently; never index the
            # step directly -- it is a dict, and a raised exception in a state
            # property fails the whole state write.
            title = self._session.step_title
            if not title:
                return "Saving"
            what = "Checking" if self._session.verifying else "Step"
            return f"{what} {self._session.step_label} - {title}"
        summary = profile_summary(self._entry.data.get(CONF_POINTS))
        return f"Calibrated ({summary})" if summary else "Not calibrated"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = self._session.extra_attributes()
        stored = self._entry.data.get(CONF_POINTS) or []
        whites, colors = count_points(stored)
        attrs["stored_points"] = len(stored)
        attrs["stored_colors"] = colors
        attrs["stored_whites"] = whites
        attrs["profile_summary"] = profile_summary(stored)
        attrs["white_mode"] = self._session.white_mode
        # Set when white_mode was switched after the whites were measured: the
        # whites sent the new way have no correction until they are re-run.
        attrs["white_rerun_needed"] = whites_need_rerun(
            self._entry.data, self._session.supports_color
        )
        return attrs
