"""Constants for the Light Calibration integration."""
from __future__ import annotations

DOMAIN = "light_calibration"

CONF_REFERENCE = "reference_entity"
CONF_TARGET = "target_entity"
CONF_NAME = "name"
CONF_DEPTH = "depth"
CONF_POINTS = "points"
CONF_TAKEOVER = "takeover_entity_id"
CONF_ORIGINAL_ID = "original_entity_id"
CONF_RENAMED_ID = "renamed_entity_id"

# Per-step form fields
FIELD_WARM_COOL = "warm_cool"
FIELD_TINT = "green_magenta"
FIELD_BRIGHTNESS = "brightness"
FIELD_NEXT = "matches"

# Slider bounds
WARM_COOL_MIN = -1200
WARM_COOL_MAX = 1200
WARM_COOL_STEP = 25
TINT_MIN = -60
TINT_MAX = 60
TINT_STEP = 2

DEFAULT_TRANSITION = 0.4

# How a colour-capable target is driven for a white (per entry, Options).
# "rgb": every white as an RGB colour, so green/magenta tint can be corrected.
# "kelvin": every white goes to its white LEDs as color_temp_kelvin, clamped
# to their range; only RGB requests are sent as RGB.
# "kelvin_rgb": the white LEDs inside their range, RGB beyond it -- for a
# light whose RGB whites are bright enough to fill the gap.
CONF_WHITE_MODE = "white_mode"
WHITE_MODE_RGB = "rgb"
WHITE_MODE_KELVIN = "kelvin"
WHITE_MODE_KELVIN_RGB = "kelvin_rgb"
WHITE_MODES = (WHITE_MODE_RGB, WHITE_MODE_KELVIN, WHITE_MODE_KELVIN_RGB)
# The white_mode the stored whites were last measured in. Absent means "rgb":
# every profile written before the option existed was measured that way.
CONF_WHITES_MEASURED_MODE = "whites_measured_mode"
