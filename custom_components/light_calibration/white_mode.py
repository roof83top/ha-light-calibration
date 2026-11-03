"""Switching how whites are driven (the ``white_mode`` option).

Shared by the options flow and the ``set_white_mode`` service, which is what
the panel calls: the integration's Configure button opens the panel, not the
options form, so the panel needs a way in of its own.
"""
from __future__ import annotations

import logging

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .calibration import (
    white_rerun_notification_id,
    whites_need_rerun,
    with_white_mode,
)
from .capability import supports_color
from .const import CONF_TARGET, CONF_WHITE_MODE, WHITE_MODE_KELVIN_RGB, WHITE_MODE_RGB

_LOGGER = logging.getLogger(__name__)


@callback
def async_update_with_white_mode(
    hass: HomeAssistant, entry: ConfigEntry, data: dict, mode: str
) -> None:
    """Write ``data`` with ``white_mode`` set, and flag the whites if needed.

    The stored points are kept: colours are unaffected, and each route still
    uses the whites measured on it. But a white the new mode sends the other
    way has no correction until it is measured again, so the user is told.
    """
    changed = mode != entry.data.get(CONF_WHITE_MODE, WHITE_MODE_RGB)
    data = with_white_mode(data, mode)
    hass.config_entries.async_update_entry(entry, data=data)
    _async_announce(hass, entry, data, changed)


@callback
def _async_announce(
    hass: HomeAssistant, entry: ConfigEntry, data: dict, changed: bool
) -> None:
    """Tell the user, once and visibly, that the whites need measuring again.

    A persistent notification rather than only a log line: the switch is made
    in a dialog, and whites that quietly lose their correction look like a
    calibration that stopped working. The sensor carries the same flag
    (``white_rerun_needed``) for the panel and dashboards. Measuring whites in
    the new mode dismisses it, and so does switching back.
    """
    notification_id = white_rerun_notification_id(entry.entry_id)
    if not whites_need_rerun(data, supports_color(hass, data.get(CONF_TARGET, ""))):
        persistent_notification.async_dismiss(hass, notification_id)
        return
    if not changed:
        return
    mode = data.get(CONF_WHITE_MODE, WHITE_MODE_RGB)
    how = {
        WHITE_MODE_RGB: "RGB colour mixing",
        WHITE_MODE_KELVIN_RGB: "its own white LEDs (colour temperature), and "
        "RGB beyond their range",
    }.get(mode, "its own white LEDs (colour temperature)")
    _LOGGER.warning(
        "%s: whites are now driven as %s; the stored whites were measured the "
        "other way and need a re-run", entry.title, mode,
    )
    persistent_notification.async_create(
        hass,
        f"**{entry.title}** now drives its whites with {how}. The stored whites "
        "were measured the other way, so whites sent the new way are not "
        "corrected until they are measured again. Run a white calibration "
        "(Quick is enough) from the Light Calibration panel. Colours are not "
        "affected, and the old white points are kept.",
        title="Light Calibration: re-measure the whites",
        notification_id=notification_id,
    )
