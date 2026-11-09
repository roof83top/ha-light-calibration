/*
 * Light Calibration frontend.
 *
 * Three elements, all sharing one dialog:
 *   light-calibration-dialog  the modal itself; sliders drive the light live
 *   light-calibration-panel   the page the integration's Configure button opens
 *   light-calibration-card    optional dashboard card
 *
 * A config-flow form can only react when you press Submit, which makes matching
 * a colour by eye miserable -- hence a real dialog with continuous sliders.
 */

/* Ordered so the first entry is the right default for a light nobody has
   calibrated yet -- it is what a fresh dialog selects. Colours-only is a top-up
   for a light that already has whites, so it sits at the bottom rather than
   being the thing a first run falls into.

   Third field: needs a fixture that can show a colour. A tunable-white one is
   only offered the white-only depths. */
const DEPTHS = [
  ["standard", "Standard - 9 whites, ~8 min", false],
  ["quick", "Quick - 5 whites, ~3 min", false],
  ["standard_color", "Standard + colours - 9 whites, 6 hues, ~13 min", true],
  ["thorough", "Thorough - 15 whites, ~15 min", false],
  ["thorough_color", "Thorough + colours - 15 whites, 12 hues, ~25 min", true],
  ["colors", "Colours only - 6 hues, ~5 min", true],
];

/* Whites and colours need different adjustments: warm/cool and tint are
   meaningless on pure red, and a hue rotation is meaningless on a white. */
const WHITE_SLIDERS = [
  { key: "warm_cool", label: "Warm / cool", min: -1200, max: 1200, step: 25, unit: "K",
    hint: "orange ↔ blue" },
  { key: "green_magenta", label: "Magenta / green", min: -100, max: 400, step: 1, unit: "%",
    hint: "looks purple? push right" },
  { key: "brightness", label: "Brightness", min: 1, max: 100, step: 1, unit: "%",
    hint: "match the reference" },
];

const COLOR_SLIDERS = [
  { key: "hue_shift", label: "Hue", min: -60, max: 60, step: 1, unit: "°",
    hint: "rotate until it is the same colour" },
  { key: "saturation", label: "Saturation", min: 0, max: 100, step: 1, unit: "%",
    hint: "how pure the colour reads" },
  { key: "brightness", label: "Brightness", min: 1, max: 100, step: 1, unit: "%",
    hint: "match the reference" },
];

const ALL_SLIDERS = [...WHITE_SLIDERS, ...COLOR_SLIDERS.filter(
  (c) => !WHITE_SLIDERS.some((w) => w.key === c.key)
)];

const BUTTONS = `
  button.primary {
    background: var(--primary-color); color: var(--text-primary-color, #fff);
    border: none; border-radius: 8px; padding: 9px 16px; font-size: 0.95rem;
    cursor: pointer; font-family: inherit;
  }
  button.flat {
    background: none; border: none; color: var(--primary-color);
    padding: 9px 12px; font-size: 0.95rem; cursor: pointer; border-radius: 8px;
    font-family: inherit;
  }
  button.flat:hover:not(:disabled) { background: rgba(127,127,127,0.12); }
  /* Used constantly mid-step, so it needs to read as a control rather than as
     one more link in a row of links. */
  button.tonal {
    background: rgba(127,127,127,0.14); border: none; color: var(--primary-text-color);
    padding: 9px 14px; font-size: 0.95rem; cursor: pointer; border-radius: 8px;
    font-family: inherit;
  }
  button.tonal:hover:not(:disabled) { background: rgba(127,127,127,0.22); }
  button.quiet { color: var(--secondary-text-color); }
  button:disabled { opacity: 0.4; cursor: default; }
`;

const DIALOG_STYLE = `
  ${BUTTONS}
  :host { display: contents; }
  .scrim {
    position: fixed; inset: 0; background: rgba(0,0,0,0.5);
    display: none; align-items: center; justify-content: center; z-index: 9999;
  }
  .scrim.open { display: flex; }
  .dialog {
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color);
    border-radius: var(--ha-card-border-radius, 12px);
    width: min(560px, calc(100vw - 32px));
    max-height: calc(100vh - 64px); overflow: auto;
    box-shadow: 0 8px 32px rgba(0,0,0,0.35);
    padding: 24px;
    font-family: var(--paper-font-body1_-_font-family, inherit);
  }
  .titlebar { display: flex; align-items: center; gap: 12px; margin: 0 0 4px; }
  .dialog h2 { margin: 0; font-size: 1.35rem; font-weight: 400; flex: 1; }
  .sub { color: var(--secondary-text-color); font-size: 0.9rem; margin-bottom: 20px; }
  /* What the fixture is being driven with. Sat inline before the instructions it
     read as a bullet point; out here it reads as a sample. */
  .swatch {
    flex: 0 0 auto; width: 34px; height: 34px; border-radius: 8px;
    border: 1px solid rgba(127,127,127,0.35); box-shadow: inset 0 0 0 1px rgba(255,255,255,0.25);
  }
  .swatch[hidden] { display: none; }
  .field { margin: 18px 0; }
  .field[hidden] { display: none; }
  .field-head {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 0.9rem; margin-bottom: 2px;
  }
  .field-head .lbl { font-weight: 500; }
  .field-head .val { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .hint { color: var(--secondary-text-color); font-size: 0.78rem; margin-top: 2px; }
  input[type=range] { width: 100%; margin: 6px 0 0; accent-color: var(--primary-color); }
  select {
    width: 100%; padding: 10px; border-radius: 8px; font-size: 0.95rem;
    background: var(--secondary-background-color, #f0f0f0);
    color: var(--primary-text-color);
    border: 1px solid var(--divider-color, #ccc); font-family: inherit;
  }
  .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 24px;
             flex-wrap: wrap; align-items: center; }
  .actions .left { margin-right: auto; }
  /* Five controls in one row is snug on a phone; tighten before wrapping. */
  @media (max-width: 430px) {
    .actions { gap: 2px; }
    .actions button { padding: 9px 7px; font-size: 0.88rem; }
    .dialog { padding: 20px 16px; }
  }
  .progress {
    height: 4px; border-radius: 2px; background: var(--divider-color, #ddd);
    overflow: hidden; margin-bottom: 20px;
  }
  .progress > div { height: 100%; background: var(--primary-color); transition: width .2s; }
  .warn {
    margin: 0 0 16px; font-size: 0.85rem; color: var(--secondary-text-color);
    border-left: 3px solid var(--warning-color, #ffa726); padding-left: 12px;
  }
  .warn[hidden] { display: none; }
  button.compare[aria-pressed="true"] { opacity: 0.5; }
`;

/* ------------------------------------------------------------------ dialog */

class LightCalibrationDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._dragging = null;
    this._pending = null;
    this._lastSend = 0;
    this._local = {};
    this._build();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  get _attrs() {
    const st = this._hass && this.entityId ? this._hass.states[this.entityId] : null;
    return st ? st.attributes : {};
  }

  /* Entity ids are for automations, not for people. The displaced fixture keeps
     its name through the rename, so this reads back the same thing the user
     called the light before it was calibrated. */
  _name(entityId) {
    if (!entityId) return "";
    const st = this._hass && this._hass.states[entityId];
    if (st && st.attributes.friendly_name) return st.attributes.friendly_name;
    return entityId.replace(/^[^.]+\./, "").replace(/_raw$/, "").replace(/_/g, " ");
  }

  get _sliders() {
    const a = this._attrs;
    if (a.step_type === "color") return COLOR_SLIDERS;
    // Tint is a green/magenta shift off the blackbody curve, which a
    // tunable-white fixture cannot render at all, and neither can a colour
    // fixture's own white LEDs (white_tint false: the kelvin white mode).
    // Without white_tint (an older backend), supports_color decides as before.
    const tint = a.white_tint === true || a.white_tint === false
      ? a.white_tint : a.supports_color !== false;
    return tint ? WHITE_SLIDERS : WHITE_SLIDERS.filter((s) => s.key !== "green_magenta");
  }

  open(entityId) {
    this.entityId = entityId;
    this._done = false;
    this._wasActive = false;
    this.shadowRoot.querySelector(".scrim").classList.add("open");
    this._render();
  }

  close() {
    this.shadowRoot.querySelector(".scrim").classList.remove("open");
  }

  /* Every way out of the dialog has to go through here. An active session has
     both lights parked on the current step, and only cancel_calibration puts
     them back -- closing the dialog on its own would leave the reference stuck
     at whatever colour temperature it was last driven to. */
  _dismiss() {
    if (this._attrs.active) this._call("cancel_calibration");
    this.close();
  }

  connectedCallback() {
    window.addEventListener("keydown", this._onKey);
  }

  disconnectedCallback() {
    window.removeEventListener("keydown", this._onKey);
  }

  _build() {
    const style = document.createElement("style");
    style.textContent = DIALOG_STYLE;
    const scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.innerHTML = `
      <div class="dialog" role="dialog" aria-modal="true">
        <div class="progress"><div id="bar" style="width:0%"></div></div>
        <div class="titlebar">
          <h2 id="title"></h2>
          <div class="swatch" id="swatch" title="What the light is being sent" hidden></div>
        </div>
        <div class="sub" id="sub"></div>
        <div class="warn" id="skipped" hidden></div>
        <div id="setup">
          <div class="field">
            <div class="field-head"><span class="lbl">How thorough</span></div>
            <select id="depth">
              ${DEPTHS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}
            </select>
            <div class="hint">Each step is one colour and brightness to match.</div>
          </div>
        </div>
        <div id="sliders">
          ${ALL_SLIDERS.map(
            (s) => `
            <div class="field" id="field-${s.key}">
              <div class="field-head">
                <span class="lbl">${s.label}</span>
                <span class="val" id="val-${s.key}"></span>
              </div>
              <input type="range" id="in-${s.key}" min="${s.min}" max="${s.max}" step="${s.step}">
              <div class="hint">${s.hint}</div>
            </div>`
          ).join("")}
        </div>
        <div class="actions">
          <button class="flat quiet left" id="cancel">Cancel</button>
          <button class="flat quiet" id="finish">Finish now</button>
          <button class="flat" id="back">Back</button>
          <button class="tonal compare" id="compare" title="Flash the light back to no correction, then return">Compare</button>
          <button class="primary" id="next">Start calibration</button>
        </div>
      </div>`;
    this.shadowRoot.append(style, scrim);

    const q = (sel) => scrim.querySelector(sel);
    this._els = {
      scrim, title: q("#title"), sub: q("#sub"), bar: q("#bar"),
      setup: q("#setup"), sliders: q("#sliders"), depth: q("#depth"),
      cancel: q("#cancel"), back: q("#back"), next: q("#next"),
      finish: q("#finish"), compare: q("#compare"), skipped: q("#skipped"),
      swatch: q("#swatch"),
    };

    this._els.cancel.addEventListener("click", () => this._dismiss());
    this._els.back.addEventListener("click", () => this._call("previous_point"));
    this._els.compare.addEventListener("click", () => this._call("compare"));
    this._els.finish.addEventListener("click", () => this._call("finish_calibration"));
    this._els.next.addEventListener("click", () => {
      if (this._done) { this.close(); return; }
      if (this._attrs.active) this._call("save_point");
      else this._call("start_calibration", { depth: this._els.depth.value });
    });
    scrim.addEventListener("click", (e) => {
      if (e.target === scrim) this._dismiss();
    });
    // Added and removed in connected/disconnectedCallback, not here, so it does
    // not outlive the element.
    this._onKey = (e) => {
      if (e.key === "Escape" && scrim.classList.contains("open")) this._dismiss();
    };

    for (const s of ALL_SLIDERS) {
      const input = q(`#in-${s.key}`);
      input.addEventListener("input", () => {
        this._dragging = s.key;
        this._local[s.key] = Number(input.value);
        this._paint();
        this._send();
      });
      const done = () => { this._dragging = null; this._send(true); };
      input.addEventListener("change", done);
      input.addEventListener("pointerup", done);
    }
  }

  _render() {
    if (!this._hass || !this.entityId) return;
    const a = this._attrs;
    const active = !!a.active;
    const open = this._els.scrim.classList.contains("open");

    // Finishing the last step ends the session. Without this the dialog would
    // fall back to its idle state and invite you to calibrate all over again.
    if (open && this._wasActive && !active) this._done = true;
    this._wasActive = active;

    if (this._done) {
      // Everything that belongs to a running session has to be put away here,
      // or the saved screen keeps whichever bits were showing when it ended.
      this._els.setup.style.display = "none";
      this._els.sliders.style.display = "none";
      this._els.back.style.display = "none";
      this._els.cancel.style.display = "none";
      this._els.finish.style.display = "none";
      this._els.compare.style.display = "none";
      this._els.swatch.hidden = true;
      this._els.skipped.hidden = true;
      this._els.next.textContent = "Done";
      this._els.bar.style.width = "100%";
      this._els.title.textContent = `${this._name(a.calibrating)} is calibrated`;
      const whites = (a.stored_points || 0) - (a.stored_colors || 0);
      const colours = a.stored_colors ? ` and ${a.stored_colors} colours` : "";
      this._els.sub.innerHTML =
        `Stored ${whites} whites${colours}. Anything you did not revisit this ` +
        `time was kept, and both lights have been put back the way they were.` +
        `<br><br>Everything already pointing at this light is now getting ` +
        `corrected output. Turn the <b>Calibration</b> switch off to see what it ` +
        `looked like before.`;
      return;
    }

    // Only offer depths the fixture can actually be measured at.
    const allowColor = a.supports_color !== false;
    if (this._allowColor !== allowColor) {
      this._allowColor = allowColor;
      this._els.depth.innerHTML = DEPTHS.filter(([, , needsColor]) => allowColor || !needsColor)
        .map(([v, l]) => `<option value="${v}">${l}</option>`)
        .join("");
    }

    // The lights are parked on a step whenever a session is running, so the
    // compare flash is meaningful right through the check as well.
    const verifying = !!a.verifying;
    this._els.compare.style.display = active ? "" : "none";
    this._els.compare.setAttribute("aria-pressed", a.comparing ? "true" : "false");
    this._els.compare.disabled = !!a.comparing;

    const skipped = a.skipped || [];
    this._els.skipped.hidden = skipped.length === 0;
    if (skipped.length) {
      this._els.skipped.textContent =
        `Skipped ${skipped.join("; ")}. Those points are left as they were.`;
    }

    this._els.cancel.style.display = "";
    this._els.setup.style.display = active ? "none" : "block";
    // Nothing to adjust while checking: this is the finished profile, replayed.
    this._els.sliders.style.display = active && !verifying ? "block" : "none";
    this._els.back.style.display = active ? "" : "none";
    this._els.next.textContent = verifying
      ? "Looks right"
      : active ? "Save point and next" : "Start calibration";
    this._els.back.textContent = verifying ? "Fix that one" : "Back";
    this._els.back.disabled = !active || (!verifying && (a.step || 1) <= 1);
    this._els.finish.textContent = verifying ? "Save now" : "Finish now";
    // Only offer an early finish once something has actually been measured.
    this._els.finish.style.display =
      active && (verifying || (a.measured_this_run || 0) > 0) ? "" : "none";

    // Swap the slider set for colour steps. The fields are built once in a
    // fixed order, so they have to be re-sorted as well as shown and hidden --
    // otherwise a colour step leads with Brightness, which is the last thing you
    // should reach for and the opposite of what the instructions say.
    const shown = this._sliders;
    for (const s of ALL_SLIDERS) {
      this.shadowRoot.querySelector(`#field-${s.key}`).hidden =
        !shown.some((x) => x.key === s.key);
    }
    // Only when the set actually changes: appendChild moves live DOM nodes, and
    // moving a range input mid-drag drops the pointer capture, so re-sorting on
    // every state update would make the sliders impossible to drag.
    const order = shown.map((x) => x.key).join(",");
    if (this._sliderOrder !== order) {
      this._sliderOrder = order;
      for (const x of shown) {
        this._els.sliders.appendChild(this.shadowRoot.querySelector(`#field-${x.key}`));
      }
    }

    this._els.swatch.hidden = !(active && a.sending_rgb);
    if (active && a.sending_rgb) {
      this._els.swatch.style.background = `rgb(${a.sending_rgb.join(",")})`;
    }

    if (verifying) {
      this._els.title.textContent =
        `Check ${a.verify_step} of ${a.verify_total} - ${a.step_title || ""}`;
      this._els.sub.textContent = a.instructions || "";
      this._els.bar.style.width = "100%";
    } else if (active) {
      this._els.title.textContent = `Step ${a.step} of ${a.total} - ${a.step_title || ""}`;
      this._els.sub.textContent = a.instructions || "";
      this._els.bar.style.width = `${((a.step - 1) / a.total) * 100}%`;
    } else {
      const stored = (a.stored_points || 0) > 0;
      const light = this._name(a.calibrating);
      this._els.title.textContent = stored ? `Re-Calibrate ${light}` : `Calibrate ${light}`;
      this._els.sub.innerHTML = stored
        ? `Each step starts from what you measured last time, so this adjusts ` +
          `from where you left off rather than starting over. Anything you do ` +
          `not revisit is kept.<br><br>Both lights will change while you work -- ` +
          `pause anything that adapts them automatically first, or it will fight you.`
        : `Both lights will be driven to the same setting, one step at a time. ` +
          `Adjust until they look the same to you, then move on -- there is no ` +
          `right answer but your own eyes.<br><br>Matching against ` +
          `<b>${this._name(a.reference_light) || "the reference"}</b>. Pause ` +
          `anything that adapts these lights automatically first, or it will ` +
          `fight you.`;
      this._els.bar.style.width = "0%";
    }

    if (this._dragging === null) {
      for (const s of ALL_SLIDERS) {
        const v = a[s.key];
        if (v === undefined || v === null) continue;
        this._local[s.key] = Number(v);
        this.shadowRoot.querySelector(`#in-${s.key}`).value = v;
      }
      this._paint();
    }
  }

  _paint() {
    for (const s of ALL_SLIDERS) {
      const v = this._local[s.key];
      if (v === undefined) continue;
      const signed = s.key === "warm_cool" || s.key === "green_magenta" || s.key === "hue_shift";
      const sign = signed && v > 0 ? "+" : "";
      this.shadowRoot.querySelector(`#val-${s.key}`).textContent = `${sign}${v}${s.unit}`;
    }
  }

  _call(service, data = {}) {
    const entry_id = this._attrs.entry_id;
    if (!entry_id) return Promise.resolve();
    return this._hass.callService("light_calibration", service, { entry_id, ...data });
  }

  /* Throttled: a drag sends a steady stream rather than a flood. Zigbee bulbs
     choke well before a browser does. */
  _send(force = false) {
    const now = Date.now();
    const wait = 130;
    clearTimeout(this._pending);
    if (force || now - this._lastSend >= wait) {
      this._lastSend = now;
      const data = {};
      for (const s of this._sliders) data[s.key] = this._local[s.key];
      this._call("adjust", data);
    } else {
      this._pending = setTimeout(() => this._send(true), wait - (now - this._lastSend));
    }
  }
}

/* ------------------------------------------------------- shared discovery */

function calibrationSensors(hass) {
  return Object.keys(hass.states)
    .filter((e) => e.startsWith("sensor.") && hass.states[e].attributes.entry_id
                   && hass.states[e].attributes.calibrating)
    .sort();
}

/* ------------------------------------------------------------------- panel */

/* Inlined because ha-icon belongs to the Home Assistant bundle and a custom
   panel cannot import it. Paths are from @mdi/js 7.4.47 -- the exact version
   home-assistant/frontend pins -- so these are the same glyphs HA draws. */
const ICONS = {
  bulb: "M12,2A7,7 0 0,0 5,9C5,11.38 6.19,13.47 8,14.74V17A1,1 0 0,0 9,18H15A1," +
        "1 0 0,0 16,17V14.74C17.81,13.47 19,11.38 19,9A7,7 0 0,0 12,2M9,21A1,1 " +
        "0 0,0 10,22H14A1,1 0 0,0 15,21V20H9V21Z",
  bulbOff: "M12,2C9.76,2 7.78,3.05 6.5,4.68L16.31,14.5C17.94,13.21 19,11.24 19," +
           "9A7,7 0 0,0 12,2M3.28,4L2,5.27L5.04,8.3C5,8.53 5,8.76 5,9C5,11.38 " +
           "6.19,13.47 8,14.74V17A1,1 0 0,0 9,18H14.73L18.73,22L20,20.72L3.28," +
           "4M9,20V21A1,1 0 0,0 10,22H14A1,1 0 0,0 15,21V20H9Z",
  tune: "M3,17V19H9V17H3M3,5V7H13V5H3M13,21V19H21V17H13V15H11V21H13M7,9V11H3V13H7" +
        "V15H9V9H7M21,13V11H11V13H21M15,9H17V7H21V5H17V3H15V9Z",
  magnify: "M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71," +
           "14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11," +
           "16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5," +
           "9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z",
  close: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12," +
         "13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  // Material's own filter-chip checkmark, on an 18x18 viewBox rather than 24.
  plus: "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z",
  chevron: "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
  tick: "M6.75012 12.1274L3.62262 8.99988L2.55762 10.0574L6.75012 14.2499L15" +
        ".7501 5.24988L14.6926 4.19238L6.75012 12.1274Z",
  eyedropper: "M6.92,19L5,17.08L13.06,9L15,10.94M20.71,5.63L18.37,3.29C18,2.9 " +
              "17.35,2.9 16.96,3.29L13.84,6.41L11.91,4.5L10.5,5.91L11.92,7.33L3," +
              "16.25V21H7.75L16.67,12.08L18.09,13.5L19.5,12.09L17.58,10.17L20.7," +
              "7.05C21.1,6.65 21.1,6 20.71,5.63Z",
};

/* Mirrors capability.is_calibratable on the Python side: either a real colour
   mode, or colour temperature on its own. An on/off or brightness-only fixture
   has no colour behaviour to correct, so listing it only invites a rejection.

   A light reporting no modes at all is kept. That is what an unavailable entity
   looks like -- its attributes are stripped -- and hiding every light that
   happens to be offline would be worse than showing one that cannot be
   calibrated. */
const OFF_CURVE_MODES = new Set(["rgb", "rgbw", "rgbww", "hs", "xy"]);

function isCalibratable(light) {
  const modes = (light && light.attributes.supported_color_modes) || [];
  if (!modes.length) return true;
  return modes.some((m) => OFF_CURVE_MODES.has(m)) || modes.includes("color_temp");
}

/* Home Assistant's own conversions. The value channel is the raw maximum on a
   0..255 scale and is never normalised -- reimplementing this with a 0..1 value
   drives near-white lights to black, which is the easy way to get it wrong. */
function rgb2hsv([r, g, b]) {
  const v = Math.max(r, g, b);
  const c = v - Math.min(r, g, b);
  const h = c && (v === r ? (g - b) / c : v === g ? 2 + (b - r) / c : 4 + (r - g) / c);
  return [60 * (h < 0 ? h + 6 : h), v && c / v, v];
}

function hsv2rgb([h, s, v]) {
  const f = (n) => {
    const k = (n + h / 60) % 6;
    return v - v * s * Math.max(Math.min(k, 4 - k, 1), 0);
  };
  return [f(5), f(3), f(1)];
}

/* What colour a tile card gives a light's icon, ported from hui-tile-card's
   _computeStateColor. It floors *saturation*, not brightness: a light's
   rgb_color is its colour, not its level, so nothing needs lifting for being
   dim -- but a near-white one would be an invisible white icon on a white card,
   so it is either pushed to a minimum saturation or, if it is essentially pure
   white, dimmed instead. */
function lightColor(light) {
  const rgb = light.attributes.rgb_color;
  if (!rgb) return null;
  const hsv = rgb2hsv(rgb);
  if (hsv[1] < 0.4) {
    if (hsv[1] < 0.1) hsv[2] = 225;
    else hsv[1] = 0.4;
  }
  const [r, g, b] = hsv2rgb(hsv).map((c) => Math.round(c));
  return `rgb(${r}, ${g}, ${b})`;
}

/* One colour at two alphas -- the badge tint is the icon colour at 0.2, the way
   ha-tile-icon does it, rather than a separately chosen pale shade. */
function lightTint(light) {
  // The struck-through bulb belongs to "off" alone. Home Assistant's own
  // icons.json overrides light's icon for exactly one state -- off -- so an
  // unavailable or unknown light keeps the plain bulb and says so by being
  // greyed, not by looking switched off.
  if (!light || light.state === "unavailable") {
    return { color: "var(--state-unavailable-color, #bdbdbd)", icon: ICONS.bulb };
  }
  if (light.state === "off") {
    return { color: "var(--state-inactive-color, #9e9e9e)", icon: ICONS.bulbOff };
  }
  if (light.state !== "on") {
    return { color: "var(--state-inactive-color, #9e9e9e)", icon: ICONS.bulb };
  }
  return {
    color: lightColor(light) || "var(--state-light-active-color, #ffc107)",
    icon: ICONS.bulb,
  };
}

/* What the light is doing, in the words its own card would use. */
function describeLight(light) {
  const a = light.attributes;
  const pct = a.brightness != null
    ? `${Math.max(1, Math.round((a.brightness / 255) * 100))}%` : null;
  return ["On", pct].filter(Boolean).join(" \u00b7 ");
}

const SCOPE_KEY = "light_calibration.scope";

const HUE_NAMES = { 0: "red", 60: "yellow", 120: "green",
                    180: "cyan", 240: "blue", 300: "magenta" };

const signed = (n) => (n > 0 ? "+" : n < 0 ? "\u2212" : "") + Math.abs(Math.round(n));

/* What a profile actually measured. The stored numbers are corrections, not
   settings -- "asked for 2700K, this fixture needed -250K and a push towards
   green" -- so the table says which is which rather than listing raw fields. */
function renderPoints(points) {
  const whites = points.filter((p) => (p.type || "white") === "white")
    .sort((a, b) => a.brightness - b.brightness || a.kelvin - b.kelvin);
  const colours = points.filter((p) => p.type === "color")
    .sort((a, b) => a.brightness - b.brightness || a.hue - b.hue);
  let html = "";
  if (whites.length) {
    html += `<table><thead><tr><th>Asked for</th><th>Colour</th><th>Tint</th>
      <th>Brightness</th></tr></thead><tbody>` +
      whites.map((p) => `<tr>
        <td>${p.kelvin}K at ${p.brightness}%</td>
        <td>${signed(p.kelvin_offset || 0)}K</td>
        <td>${signed(p.tint || 0)}%</td>
        <td>${Math.round(p.brightness_actual ?? p.brightness)}%</td></tr>`).join("") +
      `</tbody></table>`;
  }
  if (colours.length) {
    html += `<table><thead><tr><th>Asked for</th><th>Hue</th><th>Saturation</th>
      <th>Brightness</th></tr></thead><tbody>` +
      colours.map((p) => `<tr>
        <td>${HUE_NAMES[p.hue] || p.hue + "\u00b0"} at ${p.brightness}%</td>
        <td>${signed(p.hue_shift || 0)}\u00b0</td>
        <td>${Math.round(p.saturation ?? 100)}%</td>
        <td>${Math.round(p.brightness_actual ?? p.brightness)}%</td></tr>`).join("") +
      `</tbody></table>`;
  }
  return html || "<p>Nothing measured yet.</p>";
}

const PANEL_STYLE = `
  ${BUTTONS}
  :host { display: block; background: var(--primary-background-color); min-height: 100vh; }
  .head {
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, #fff);
    padding: 0 8px; height: 56px; font-size: 1.25rem; font-weight: 400;
    display: flex; align-items: center; gap: 8px;
    position: sticky; top: 0; z-index: 2;
  }
  .head .back {
    background: none; border: none; cursor: pointer; color: inherit;
    width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center;
    flex: 0 0 auto;
  }
  .head .back:hover { background: rgba(255,255,255,0.12); }
  .head .back svg { width: 24px; height: 24px; fill: currentColor; }
  .head .grow { flex: 1; }
  /* Measured against home-assistant/frontend 20260826.6 -- the build core
     2026.9.1 pins. The search field is an outlined 1px-bordered box, not a
     shadowed card: ha-input-search, appearance="outlined", 40px tall with an
     8px radius. The 2026 --ha-* tokens carry a fallback each, since a var()
     that resolves to nothing takes the whole declaration with it. */
  /* Sticks under the 56px app header, the way Home Assistant's own list pages
     keep their search bar in reach. Needs the page background of its own: it is
     scrolling over cards, not with them. */
  .toolbar {
    position: sticky; top: 56px; z-index: 1;
    padding: 12px 16px;
    background: var(--primary-background-color);
    border-bottom: 1px solid var(--divider-color, rgba(127,127,127,0.2));
    display: flex; gap: 16px; align-items: center; flex-wrap: wrap;
  }
  .body { padding-top: 16px; }
  .search {
    flex: 1 1 220px; display: flex; align-items: center; height: 40px;
    padding: 0 var(--ha-space-2, 8px);
    border-radius: var(--ha-border-radius-md, 8px);
    background: var(--card-background-color, #fff);
    border: 1px solid
      var(--ha-color-border-neutral-quiet, var(--divider-color, #e6e6e6));
    transition: border-color 150ms ease-in-out;
  }
  .search:focus-within { border-color: var(--primary-color); }
  /* 18px, and in full primary text colour -- ha-input styles only the trailing
     slot as secondary, so the magnifier is not muted. */
  .search > svg {
    width: 18px; height: 18px; flex: 0 0 auto;
    fill: var(--primary-text-color);
    margin-inline-end: var(--ha-space-3, 12px);
  }
  .search input {
    flex: 1; min-width: 0; border: none; background: none; outline: none;
    font: inherit; font-size: 14px; color: var(--primary-text-color);
  }
  .search input::placeholder { color: var(--secondary-text-color, #989898); }
  .search input::-webkit-search-cancel-button { display: none; }
  .search .clearq {
    flex: 0 0 auto; width: 24px; height: 24px; border: none; background: none;
    margin-inline-start: var(--ha-space-3, 12px);
    border-radius: 50%; cursor: pointer; display: grid; place-items: center;
    color: var(--secondary-text-color);
  }
  .search .clearq:hover { background: rgba(127,127,127,0.16); }
  .search .clearq svg { width: 18px; height: 18px; fill: currentColor; }
  .search .clearq[hidden] { display: none; }
  /* ha-filter-chip geometry: 32px tall, 8px radius, a 1px outline that
     disappears when selected, and a tinted fill with the label in the accent
     colour rather than a solid block. HA's own list pages filter through a side
     pane instead -- but this is one binary choice, not a facet, and a pane for
     it would be absurd. */
  .chips { display: flex; gap: 8px; flex: 0 0 auto; }
  .chip {
    display: flex; align-items: center; gap: 8px; height: 32px;
    padding: 0 16px; border-radius: var(--ha-border-radius-md, 8px);
    border: 1px solid var(--outline-color, rgba(127,127,127,0.22));
    background: none; color: var(--primary-text-color);
    font: inherit; font-size: 14px; font-weight: 500; letter-spacing: 0.1px;
    cursor: pointer; transition: background 150ms, border-color 150ms, color 150ms;
  }
  .chip:hover { background: rgba(127,127,127,0.12); }
  .chip .tick { width: 18px; height: 18px; display: none; fill: currentColor; }
  .chip.on {
    border-color: transparent; color: var(--primary-color);
    background: var(--ha-color-fill-primary-normal-hover,
                    color-mix(in srgb, var(--primary-color) 16%, transparent));
    padding-inline-start: 8px;
  }
  .chip.on .tick { display: block; }
  /* Extended FAB, bottom right, the way every Home Assistant config page puts
     its primary action. Keeping it out of the toolbar also leaves exactly one
     filled accent control on the page. */
  .fab {
    position: fixed; right: 16px; z-index: 5;
    bottom: calc(16px + env(safe-area-inset-bottom, 0px));
    height: 56px; padding: 0 20px; border: none; border-radius: 28px;
    background: var(--primary-color); color: var(--text-primary-color, #fff);
    font: inherit; font-size: 0.95rem; font-weight: 500; cursor: pointer;
    display: flex; align-items: center; gap: 10px;
    box-shadow: 0 3px 5px -1px rgba(0,0,0,0.2), 0 6px 10px rgba(0,0,0,0.14),
                0 1px 18px rgba(0,0,0,0.12);
    transition: box-shadow 180ms ease-in-out;
  }
  .fab:hover {
    box-shadow: 0 5px 5px -3px rgba(0,0,0,0.2), 0 8px 10px 1px rgba(0,0,0,0.14),
                0 3px 14px 2px rgba(0,0,0,0.12);
  }
  .fab svg { width: 24px; height: 24px; fill: currentColor; }
  @media (max-width: 700px) {
    .search { flex-basis: 100%; }
    /* Collapses to a circle, as HA's does on narrow screens. */
    .fab span { display: none; }
    .fab { padding: 0; width: 56px; justify-content: center; }
  }
  /* The bottom padding clears the FAB, or the last row hides behind it. */
  .body { padding: 0 16px 88px; }

  .item {
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, none);
    border: 1px solid
      var(--ha-card-border-color, var(--divider-color, rgba(127,127,127,0.22)));
    color: var(--primary-text-color);
    display: flex; flex-direction: column;
    transition: border-color 180ms ease-in-out;
  }
  /* A calibrated light is the thing this page is about, so it gets picked out
     of the grid by its edge and a wash of the accent colour -- faint enough to
     read as a tint rather than as a state. */
  .item.calibrated {
    border-color: color-mix(in srgb, var(--primary-color) 45%, transparent);
    background: color-mix(in srgb, var(--primary-color) 5%,
      var(--ha-card-background, var(--card-background-color, #fff)));
  }
  /* Measured against home-assistant/frontend: ha-tile-icon, ha-tile-info and
     ha-control-switch. Laid out square rather than in a row, because these sit
     in a grid of their own rather than in a dashboard column. */
  /* Shaped like Home Assistant's integrations cards: a header row with the
     icon and name on one line, a divider, then a footer whose only colour is a
     text link -- their "21 services", here what this light has measured. */
  .grid {
    display: grid; gap: 14px;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  }
  .item { padding: 0; gap: 0; }
  .tile {
    display: flex; align-items: center; gap: 16px; width: 100%;
    padding: 18px; background: none; border: none; cursor: pointer;
    font: inherit; color: inherit; text-align: left;
  }
  .badge {
    flex: 0 0 auto; position: relative; width: 40px; height: 40px;
    border-radius: var(--ha-border-radius-pill, 9999px);
    display: grid; place-items: center; overflow: hidden;
    transition: color 180ms ease-in-out;
  }
  /* The tint is the icon's own colour at 0.2, not a separately picked shade. */
  .badge::before {
    content: ""; position: absolute; inset: 0; border-radius: inherit;
    background-color: currentColor; opacity: 0.2; transition: opacity 180ms;
  }
  .tile:hover .badge::before { opacity: 0.35; }
  .badge svg { width: 24px; height: 24px; fill: currentColor; position: relative; }
  .text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .name {
    font-size: 14px; font-weight: 500; line-height: 1.4; letter-spacing: 0.1px;
    color: var(--primary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .state {
    font-size: 12px; font-weight: 400; line-height: 1.3; letter-spacing: 0.4px;
    color: var(--primary-text-color); opacity: 0.75;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .state.warn { color: var(--warning-color, #ffa726); opacity: 1; }
  .chev {
    flex: 0 0 auto; width: 20px; height: 20px;
    fill: var(--secondary-text-color); opacity: 0.7;
  }
  .foot {
    display: flex; align-items: center; gap: 12px; min-height: 52px;
    padding: 8px 18px; box-sizing: border-box;
    border-top: 1px solid var(--divider-color, rgba(127,127,127,0.2));
  }
  .foot .grow { flex: 1; }
  .link {
    background: none; border: none; padding: 0; cursor: pointer; font: inherit;
    font-size: 0.9rem; color: var(--primary-color); text-align: left;
  }
  .link:hover { text-decoration: underline; }
  /* A plain switch, small enough to sit in a footer row beside a link. */
  .switch {
    position: relative; flex: 0 0 auto; width: 36px; height: 20px;
    border: none; background: none; padding: 0; cursor: pointer;
    color: var(--state-inactive-color, #9e9e9e);
    transition: color 180ms ease-in-out;
  }
  .switch.on { color: var(--primary-color); }
  .switch[hidden] { display: none; }
  .switch .track {
    position: absolute; inset: 0; border-radius: 10px;
    background: currentColor; opacity: 0.4; transition: opacity 180ms;
  }
  .switch:hover .track { opacity: 0.6; }
  .switch .knob {
    position: absolute; top: 2px; left: 2px; width: 16px; height: 16px;
    border-radius: 50%; background: var(--card-background-color, #fff);
    box-shadow: 0 1px 3px rgba(0,0,0,0.35);
    transition: transform 180ms ease-in-out, background 180ms ease-in-out;
  }
  .switch.on .knob { transform: translateX(16px); background: currentColor; }
  /* Shared by the card's copy control, the details dialog's reference picker
     and the add dialog's fallback. */
  label.tiny { display: block; font-size: 0.78rem; margin-bottom: 3px;
               color: var(--secondary-text-color); }
  ha-entity-picker { display: block; width: 100%; }
  select {
    width: 100%; padding: 8px; border-radius: 8px; font-size: 0.88rem;
    background: var(--secondary-background-color, #f0f0f0);
    color: var(--primary-text-color);
    border: 1px solid var(--divider-color, #ccc); font-family: inherit;
  }
  .empty { color: var(--secondary-text-color); line-height: 1.5; }
  .empty h3 { font-size: 1.1rem; margin: 0 0 6px; }
  /* details modal */
  .section { margin: 18px 0; }
  .section > label.tiny { margin-bottom: 5px; }
  /* A stated fact rather than a control -- see _renderDetails. */
  .dvalue { font-size: 0.95rem; color: var(--primary-text-color); }
  .state-row {
    display: flex; align-items: center; gap: 10px; padding: 10px 0;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .state-row .grow { flex: 1; }
  /* button.flat sets a colour, so this has to out-specify it. */
  button.flat.danger { color: var(--error-color, #db4437); }
  .measurements { margin-top: 14px; font-size: 0.85rem; overflow-x: auto; }
  .measurements[hidden] { display: none; }
  .measurements table { border-collapse: collapse; width: 100%; margin-bottom: 12px; }
  .measurements th, .measurements td {
    text-align: left; padding: 5px 10px 5px 0; white-space: nowrap;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .measurements th { color: var(--secondary-text-color); font-weight: 500; }
  .measurements td { font-variant-numeric: tabular-nums; }
  .scrim {
    position: fixed; inset: 0; background: rgba(0,0,0,0.5);
    display: none; align-items: center; justify-content: center; z-index: 9998;
  }
  .scrim.open { display: flex; }
  .scrim .dialog {
    background: var(--card-background-color, #fff); color: var(--primary-text-color);
    border-radius: var(--ha-card-border-radius, 12px); padding: 24px;
    width: min(520px, calc(100vw - 32px)); max-height: calc(100vh - 64px);
    overflow: auto; box-shadow: 0 8px 32px rgba(0,0,0,0.35);
  }
  .scrim h2 { margin: 0 0 4px; font-size: 1.35rem; font-weight: 400; }
  .scrim h2.ask { margin: 0 0 20px; }
  .scrim .field { margin: 16px 0 4px; }
  /* Wordless progress: the question is the only text on the step, and a
     "1 of 2" would be more prose to read past. */
  .scrim .dots { display: flex; gap: 6px; margin-bottom: 16px; }
  .scrim .dots span {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--divider-color, #ddd);
  }
  .scrim .dots span.on { background: var(--primary-color); }
  .scrim .choices { display: flex; flex-direction: column; gap: 10px; }
  .scrim .choices[hidden] { display: none; }
  .scrim .choice {
    display: flex; flex-direction: column; gap: 3px; text-align: left;
    padding: 14px 16px; border-radius: var(--ha-border-radius-lg, 12px);
    border: 1px solid var(--divider-color, rgba(127,127,127,0.22));
    background: none; color: inherit; font: inherit; cursor: pointer;
    transition: background 150ms, border-color 150ms;
  }
  .scrim .choice:hover {
    border-color: var(--primary-color);
    background: color-mix(in srgb, var(--primary-color) 8%, transparent);
  }
  .scrim .choice b { font-size: 0.95rem; font-weight: 500; }
  .scrim .choice span { font-size: 0.85rem; color: var(--secondary-text-color); }
  .scrim .err {
    color: var(--error-color, #db4437); font-size: 0.88rem; margin-top: 12px;
    border-left: 3px solid currentColor; padding-left: 12px;
  }
  .scrim .err[hidden] { display: none; }
  .scrim .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 24px; }
  .scrim .actions .left { margin-right: auto; }
  .add { display: flex; justify-content: center; margin: 4px 0 24px; }
  .add button { font-size: 0.95rem; }
  .add a {
    color: var(--primary-color); text-decoration: none; font-size: 0.95rem;
    padding: 9px 16px; border-radius: 8px;
  }
  .add a:hover { background: rgba(127,127,127,0.12); }
  .note {
    margin-top: 8px; font-size: 0.85rem; color: var(--secondary-text-color);
    border-left: 3px solid var(--warning-color, #ffa726); padding-left: 12px;
  }
`;

/* Home Assistant does not load ha-entity-picker on every page. The reliable way
   to pull it in from a custom element is to ask the card helpers for an entities
   card editor, which imports it as a side effect. */
async function loadEntityPicker() {
  if (customElements.get("ha-entity-picker")) return true;
  try {
    const helpers = await window.loadCardHelpers();
    const card = await helpers.createCardElement({ type: "entities", entities: [] });
    await card.constructor.getConfigElement();
    await customElements.whenDefined("ha-entity-picker");
    return true;
  } catch (err) {
    console.warn("light-calibration: ha-entity-picker unavailable, using a plain select", err);
    return false;
  }
}

/* Only a colour light has two ways to show a white, and only a backend that
   reports white_mode offers the choice. */
function hasWhitesChoice(a) {
  return a.supports_color !== false && a.white_mode !== undefined;
}

class LightCalibrationPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._built = false;
    this._items = new Map();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._render();
    if (this._dialog) this._dialog.hass = hass;
  }

  set narrow(v) { this._narrow = v; }
  set route(v) {
    this._route = v;
    if (this._built && this._hass) this._render();
  }
  set panel(v) { this._panel = v; }

  /* Clicking Configure on one entry sends us here with ?config_entry=<id>.
     Scope the page to that light rather than listing every calibrated light. */
  _scopedEntryId() {
    try {
      const search = window.location.search || "";
      const id = new URLSearchParams(search).get("config_entry");
      return id || null;
    } catch (err) {
      return null;
    }
  }

  _build() {
    const style = document.createElement("style");
    style.textContent = PANEL_STYLE;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div class="head">
        <button class="back" title="Back" aria-label="Back">
          <svg viewBox="0 0 24 24"><path d="M20 11H7.8l5.6-5.6L12 4l-8 8 8 8 1.4-1.4L7.8 13H20v-2z"/></svg>
        </button>
        <span class="grow">Light Calibration</span>
      </div>
      <div class="toolbar">
        <div class="search">
          <svg viewBox="0 0 24 24"><path d="${ICONS.magnify}"/></svg>
          <input type="search" id="q" placeholder="Search lights"
                 autocomplete="off" spellcheck="false">
          <button class="clearq" hidden aria-label="Clear search">
            <svg viewBox="0 0 24 24"><path d="${ICONS.close}"/></svg>
          </button>
        </div>
        <div class="chips">
          <button class="chip" data-scope="calibrated">
            <svg class="tick" viewBox="0 0 18 18"><path d="${ICONS.tick}"/></svg>
            <span>Calibrated</span>
          </button>
          <button class="chip" data-scope="all">
            <svg class="tick" viewBox="0 0 18 18"><path d="${ICONS.tick}"/></svg>
            <span>All lights</span>
          </button>
        </div>
      </div>
      <div class="body" id="body"></div>
      <button class="fab" data-add>
        <svg viewBox="0 0 24 24"><path d="${ICONS.plus}"/></svg>
        <span>Calibrate a light</span>
      </button>`;
    const adder = document.createElement("div");
    adder.className = "scrim add-scrim";
    adder.innerHTML = `
      <div class="dialog" role="dialog" aria-modal="true">
        <div class="dots"></div>
        <h2 class="ask"></h2>
        <div class="field"><div class="pick"></div></div>
        <div class="choices" hidden>
          <button class="choice" data-method="new">
            <b>Measure it now</b>
            <span>Match it against the reference by eye, one setting at a time.</span>
          </button>
          <button class="choice" data-method="copy">
            <b>Copy another light's calibration</b>
            <span>For a second fixture of the same model, already measured.</span>
          </button>
        </div>
        <div class="err" hidden></div>
        <div class="actions">
          <button class="flat quiet left" data-act="cancel">Cancel</button>
          <button class="flat" data-act="back">Back</button>
          <button class="primary" data-act="go"></button>
        </div>
      </div>`;
    this._adder = adder;

    const details = document.createElement("div");
    details.className = "scrim details-scrim";
    details.innerHTML = `
      <div class="dialog" role="dialog" aria-modal="true">
        <h2 class="dname"></h2>
        <div class="sub"><code class="did"></code></div>
        <div class="state-row">
          <div class="grow">Correction<div class="meta dstate"></div></div>
          <button class="tonal dtoggle"></button>
        </div>
        <div class="section dref">
          <label class="tiny">Reference light</label>
          <div class="dvalue drefname"></div>
        </div>
        <div class="section dwhite" hidden>
          <label class="tiny" for="dwhitemode">Whites</label>
          <select id="dwhitemode" class="dwhitemode">
            <option value="rgb">Mixed from the colour LEDs (default, corrects tint)</option>
            <option value="kelvin">The light's own white LEDs (colour temperature)</option>
            <option value="kelvin_rgb">The light's own white LEDs, RGB beyond their range</option>
          </select>
          <div class="meta dwhitenote"></div>
        </div>
        <div class="section dcopy" hidden>
          <label class="tiny">Copy calibration from</label>
          <div class="dcopypick"></div>
        </div>
        <div class="section dmeasure">
          <button class="flat dshow">Show measurements</button>
          <div class="measurements" hidden></div>
        </div>
        <div class="actions">
          <button class="flat danger left dclear">Clear profile</button>
          <button class="flat dclose">Close</button>
          <button class="primary dcal"></button>
        </div>
      </div>`;
    this._details = details;
    details.addEventListener("click", (e) => {
      if (e.target === details) this._closeDetails();
    });
    details.querySelector(".dclose").addEventListener(
      "click", () => this._closeDetails());
    details.querySelector(".dcal").addEventListener("click", () => {
      const entity = this._detailsEntity;
      this._closeDetails();
      this._dialog.hass = this._hass;
      this._dialog.open(entity);
    });
    details.querySelector(".dtoggle").addEventListener("click", () => {
      const a = this._detailsAttrs();
      if (a) this._hass.callService("switch", "toggle",
        { entity_id: this._detailsEntity.replace(/^sensor\./, "switch.") });
    });
    details.querySelector(".dclear").addEventListener(
      "click", () => this._clearProfile(this._detailsEntity));
    details.querySelector(".dwhitemode").addEventListener(
      "change", (e) => this._setWhiteMode(this._detailsEntity, e.target));
    details.querySelector(".dshow").addEventListener(
      "click", () => this._toggleMeasurements(details));

    this._dialog = document.createElement("light-calibration-dialog");
    this.shadowRoot.append(style, wrap, adder, details, this._dialog);
    adder.addEventListener("click", (e) => {
      if (e.target === adder) this._closeAdd();
    });
    adder.querySelector('[data-act="cancel"]').addEventListener(
      "click", () => this._closeAdd());
    adder.querySelector('[data-act="back"]').addEventListener(
      "click", () => this._addBack());
    adder.querySelector('[data-act="go"]').addEventListener(
      "click", () => this._addNext());
    for (const choice of adder.querySelectorAll(".choice")) {
      choice.addEventListener("click", () => {
        this._addMethod = choice.dataset.method;
        if (this._addMethod === "copy") {
          this._addStep = 3;
          this._renderAddStep();
          return;
        }
        this._submitAdd();
      });
    }
    this._body = wrap.querySelector("#body");
    // Remembered per browser: which scope you left it on is a preference, not
    // something to rediscover on every visit. Every read and write is guarded
    // -- localStorage throws outright in some privacy settings.
    this._scope = this._storedScope() || "all";
    this._query = "";
    const q = wrap.querySelector("#q");
    this._search = q;
    const clearq = wrap.querySelector(".clearq");
    q.addEventListener("input", () => {
      this._query = q.value.trim().toLowerCase();
      clearq.hidden = !q.value;
      this._render();
    });
    clearq.addEventListener("click", () => {
      q.value = ""; this._query = ""; clearq.hidden = true; q.focus(); this._render();
    });
    for (const chip of wrap.querySelectorAll(".chip")) {
      // Whichever scope was remembered starts selected.
      chip.classList.toggle("on", chip.dataset.scope === this._scope);
      chip.addEventListener("click", () => {
        this._scope = chip.dataset.scope;
        this._storeScope(this._scope);
        for (const other of wrap.querySelectorAll(".chip")) {
          other.classList.toggle("on", other === chip);
        }
        this._render();
      });
    }
    wrap.querySelector(".back").addEventListener("click", () => this._goBack());
    this._pickerReady = loadEntityPicker();
    // The add buttons are written into .body as markup whenever the list is
    // rebuilt, so the click is caught here rather than re-bound each time.
    this.shadowRoot.addEventListener("click", (e) => {
      if (e.target.closest("[data-add]")) this._openAdd();
    });
    this._built = true;
  }

  /* A custom panel gets no toolbar of its own, so it needs to provide the way
     out. Prefer real history; fall back to the integration page for a deep link
     or a fresh tab. */
  _goBack() {
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    const path = "/config/integrations/integration/light_calibration";
    window.history.pushState(null, "", path);
    this.dispatchEvent(
      new CustomEvent("location-changed", { bubbles: true, composed: true })
    );
  }

  /* One row per light shown on the page. The default scope is the lights this
     integration already stands in front of; "All lights" widens it to every
     light in Home Assistant, so calibrating a new one is a matter of finding it
     here rather than adding it somewhere else first. */
  _rows() {
    const byLight = new Map();
    const displaced = new Set();
    for (const sensor of calibrationSensors(this._hass)) {
      const behind = this._hass.states[sensor].attributes.calibrating || "";
      displaced.add(behind);
      byLight.set(behind.replace(/_raw$/, ""), sensor);
    }

    let ids = [...byLight.keys()];
    if (this._scope === "all") {
      // Every light except the displaced fixtures, which are the uncorrected
      // half of a light already on the page.
      ids = Object.keys(this._hass.states).filter(
        (e) => e.startsWith("light.") && !displaced.has(e) &&
               isCalibratable(this._hass.states[e]));
    }

    // Arrived from an entry's Configure button: show just that light.
    const scoped = this._scopedEntryId();
    if (scoped) {
      const only = ids.filter((id) => {
        const sensor = byLight.get(id);
        return sensor && this._hass.states[sensor].attributes.entry_id === scoped;
      });
      if (only.length) ids = only;
    }

    const total = ids.length;
    if (this._query) {
      ids = ids.filter(
        (id) => `${this._name(id)} ${id}`.toLowerCase().includes(this._query));
    }

    const rows = ids
      .map((light) => ({ light, sensor: byLight.get(light) || null }))
      .sort((x, y) => this._name(x.light).localeCompare(this._name(y.light)));
    // `total` is the scope before the search narrows it -- what the placeholder
    // is offering to search through, which is not the same as what is on screen.
    return { rows, total };
  }

  _emptyMarkup() {
    if (this._query) {
      return `<div class="item empty">
                <h3>Nothing matches "${this._query.replace(/[<&]/g, "")}"</h3>
                <p>${this._scope === "calibrated"
                  ? "Only calibrated lights are being shown. Switch to " +
                    "<b>All lights</b> to search everything."
                  : "No light in Home Assistant has that name."}</p>
              </div>`;
    }
    if (this._scope === "calibrated") {
      return `<div class="item empty">
                <h3>No lights calibrated yet</h3>
                <p>Switch to <b>All lights</b> and pick one that doesn't look
                right, or press <b>Calibrate a light</b>.</p>
              </div>`;
    }
    return `<div class="item empty"><h3>No lights</h3>
            <p>Home Assistant has no light entities.</p></div>`;
  }

  _render() {
    const { rows, total } = this._rows();
    this._search.placeholder =
      `Search ${total} light${total === 1 ? "" : "s"}`;
    // The sensor is part of the key: a light gaining or losing a calibration
    // entry changes what its card is, not just what it says.
    const key = this._scope + "|" +
      rows.map((r) => `${r.light}:${r.sensor || ""}`).join(",");
    if (key !== this._key) {
      this._key = key;
      this._items.clear();
      this._body.innerHTML = "";
      if (!rows.length) {
        this._body.innerHTML = this._emptyMarkup();
      } else {
        const grid = document.createElement("div");
        grid.className = "grid";
        for (const row of rows) {
          const item = this._buildItem(row);
          this._items.set(row.light, item);
          grid.appendChild(item.el);
        }
        this._body.appendChild(grid);
      }
    }
    for (const [, item] of this._items) this._updateItem(item);
    if (this._details.classList.contains("open")) this._renderDetails();

    // A light that has just been added has no profile yet -- drop straight into
    // calibration rather than making them find the button.
    if (!this._autoOpened) {
      const fresh = rows.find((r) => {
        if (!r.sensor) return false;
        const a = this._hass.states[r.sensor].attributes;
        return !a.active && a.stored_points === 0;
      });
      if (fresh) {
        this._autoOpened = true;
        this._dialog.hass = this._hass;
        this._dialog.open(fresh.sensor);
      }
    }
  }

  /* Home Assistant's config flow is drivable over its own HTTP API, and this
     integration owns both ends of it: the form is always the same two lights.
     So the panel asks for them here and submits, instead of sending people out
     to Settings, through a flow dialog, and back again to start calibrating. */
  async _openAdd(preTarget) {
    // Started from a light's own card, the first question is already answered.
    this._addPicked = [preTarget || "", ""];
    this._addMethod = null;
    this._addSource = "";
    this._addStep = preTarget ? 1 : 0;
    this._setAddError("");
    this._adder.classList.add("open");
    await this._renderAddStep();
  }

  /* Every calibrated light is a profile this one could take instead of
     measuring its own. No such light, no choice to offer. */
  _addSources() {
    return calibrationSensors(this._hass).filter(
      (e) => this._hass.states[e].attributes.stored_points > 0);
  }

  /* One question per step. Two always -- which light, and what it should match.
     A third when there is a calibration worth copying, and a fourth to say
     which, so the shortest path stays two steps. */
  async _renderAddStep() {
    const step = this._addStep;
    const d = this._adder;
    const sources = this._addSources();
    const total = !sources.length ? 2 : this._addMethod === "copy" ? 4 : 3;

    d.querySelector(".ask").textContent = [
      "Which light looks wrong?",
      "Which light should it match?",
      "How should it be calibrated?",
      "Copy which light's calibration?",
    ][step];

    d.querySelector(".dots").innerHTML = Array.from(
      { length: total }, (_, i) => `<span class="${i <= step ? "on" : ""}"></span>`
    ).join("");

    const choosing = step === 2;
    d.querySelector(".choices").hidden = !choosing;
    d.querySelector(".field").hidden = choosing;
    d.querySelector('[data-act="back"]').style.display = step === 0 ? "none" : "";
    const go = d.querySelector('[data-act="go"]');
    go.hidden = choosing;
    go.disabled = false;
    go.textContent = step === 3 ? "Copy calibration"
      : step === 1 && !sources.length ? "Start calibrating"
      : "Next";
    this._setAddError("");
    if (choosing) return;

    if (step === 3) {
      await this._mountAddPicker(
        new Set(), this._addSource, [...this._calibratedLights().keys()]);
      return;
    }

    // The displaced fixtures are never an answer to either question: they are
    // the uncorrected output of a light already calibrated, so matching against
    // one throws away the correction, and calibrating one again is nonsense.
    const raw = new Set();
    const calibrated = new Set();
    for (const e of calibrationSensors(this._hass)) {
      const behind = this._hass.states[e].attributes.calibrating || "";
      raw.add(behind);
      calibrated.add(behind.replace(/_raw$/, ""));
    }
    // Step one also hides lights already calibrated; step two hides the light
    // being calibrated, so the two can never be the same. A calibrated light is
    // a fine reference, though -- often the best one.
    const skip = step === 0
      ? new Set([...raw, ...calibrated])
      : new Set([...raw, this._addPicked[0]]);
    await this._mountAddPicker(skip, this._addPicked[step]);
  }

  /* Every "which light?" question in the panel gets this one control: the add
     flow's steps and the details dialog's copy control. ``only`` narrows it to
     an explicit list instead of hiding a few. Rebuilt on each mount, so it
     never hands back an answer to a different question and its exclusions are
     never stale. */
  async _mountPicker(holder, { value, skip, only, onChange } = {}) {
    const native = await this._pickerReady;
    holder.replaceChildren();
    let control;
    if (native) {
      control = document.createElement("ha-entity-picker");
      control.hass = this._hass;
      control.includeDomains = ["light"];
      control.allowCustomEntity = false;
      if (only) control.includeEntities = only;
      else control.excludeEntities = [...(skip || [])].filter(Boolean);
      control.value = value || "";
      if (onChange) control.addEventListener(
        "value-changed", (e) => onChange(e.detail.value, control));
    } else {
      const ids = only
        ? only.slice()
        : Object.keys(this._hass.states)
            .filter((e) => e.startsWith("light.") && !(skip && skip.has(e)));
      control = document.createElement("select");
      control.innerHTML =
        `<option value="">Choose a light...</option>` +
        ids.sort()
          .map((e) => `<option value="${e}"${e === value ? " selected" : ""}>` +
                      `${this._name(e)}</option>`)
          .join("");
      if (onChange) control.addEventListener(
        "change", (e) => onChange(e.target.value, control));
    }
    holder.appendChild(control);
    return control;
  }

  _mountAddPicker(skip, value, only) {
    return this._mountPicker(
      this._adder.querySelector(".pick"), { skip, value, only });
  }

  /* The calibrated lights, keyed by the light itself rather than by the sensor
     that describes it -- the picker deals in lights. */
  _calibratedLights() {
    const map = new Map();
    for (const sensor of this._addSources()) {
      const behind = this._hass.states[sensor].attributes.calibrating || "";
      map.set(behind.replace(/_raw$/, ""), sensor);
    }
    return map;
  }

  async _addBack() {
    this._addStep = this._addStep === 3 ? 2 : this._addStep - 1;
    if (this._addStep < 0) this._addStep = 0;
    if (this._addStep < 2) this._addMethod = null;
    await this._renderAddStep();
  }

  async _addNext() {
    const holder = this._adder.querySelector(".pick").firstChild;
    const value = (holder && holder.value) || "";
    if (this._addStep === 3) {
      if (!value) { this._setAddError("Pick a light to copy from."); return; }
      this._addSource = value;
      await this._submitAdd();
      return;
    }
    if (!value) {
      this._setAddError("Pick a light.");
      return;
    }
    this._addPicked[this._addStep] = value;
    if (this._addStep === 0) {
      this._addStep = 1;
      await this._renderAddStep();
      return;
    }
    if (this._addSources().length) {
      this._addStep = 2;
      await this._renderAddStep();
      return;
    }
    await this._submitAdd();
  }

  _storedScope() {
    try {
      const stored = window.localStorage.getItem(SCOPE_KEY);
      return stored === "calibrated" || stored === "all" ? stored : null;
    } catch (err) {
      return null;
    }
  }

  _storeScope(scope) {
    try {
      window.localStorage.setItem(SCOPE_KEY, scope);
    } catch (err) { /* nothing worth doing about it */ }
  }

  _closeAdd() {
    this._adder.classList.remove("open");
  }

  _setAddError(text) {
    const box = this._adder.querySelector(".err");
    box.textContent = text;
    box.hidden = !text;
  }

  /* The flow answers with error keys, which are the same ones the translations
     already carry -- so the message is whatever the setup form would have said. */
  _addErrorText(code) {
    const key = `component.light_calibration.config.error.${code}`;
    const localized = this._hass.localize && this._hass.localize(key);
    return localized && localized !== key
      ? localized : `That light cannot be calibrated (${code}).`;
  }

  async _submitAdd() {
    const [target, reference] = this._addPicked;
    const go = this._adder.querySelector('[data-act="go"]');
    go.disabled = true;
    this._setAddError("");
    let flow = null;
    try {
      flow = await this._hass.callApi("POST", "config/config_entries/flow", {
        handler: "light_calibration", show_advanced_options: false,
      });
      const result = await this._hass.callApi(
        "POST", `config/config_entries/flow/${flow.flow_id}`,
        { reference_entity: reference, target_entity: target },
      );
      if (result.type === "create_entry") {
        this._closeAdd();
        const entryId = result.result.entry_id;
        if (this._addSource) {
          await this._copyWhenReady(entryId, this._addSource);
        } else {
          await this._openWhenReady(entryId);
        }
        return;
      }
      // Came back with the form: say why, and drop the half-finished flow so it
      // does not sit in Settings as something in progress.
      this._setAddError(this._addErrorText(
        (result.errors && result.errors.base) || result.reason || "unknown"));
    } catch (err) {
      this._setAddError(
        (err && (err.message || (err.body && err.body.message))) || String(err));
    }
    if (flow) {
      try {
        await this._hass.callApi(
          "DELETE", `config/config_entries/flow/${flow.flow_id}`);
      } catch (err) { /* already gone */ }
    }
    go.disabled = false;
  }

  /* Chose to copy rather than measure: hand the profile over as soon as the
     new entry has entities, and do not drop into calibration -- the whole point
     of copying is not having to. */
  async _copyWhenReady(entryId, sourceLight) {
    this._autoOpened = true;   // suppress the open-on-empty-profile behaviour
    const sourceSensor = this._calibratedLights().get(sourceLight);
    const sensor = await this._sensorFor(entryId);
    if (!sensor || !sourceSensor) return;
    this._hass.callService("light_calibration", "copy_profile", {
      entry_id: this._hass.states[sensor].attributes.entry_id,
      source_entry_id: this._hass.states[sourceSensor].attributes.entry_id,
    });
  }

  async _sensorFor(entryId) {
    for (let i = 0; i < 40; i++) {
      const found = calibrationSensors(this._hass).find(
        (e) => this._hass.states[e].attributes.entry_id === entryId);
      if (found) return found;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    return null;
  }

  /* The entry exists before its entities do. Wait for the sensor, then drop
     straight into calibration -- which is the whole point of adding one. */
  async _openWhenReady(entryId) {
    for (let i = 0; i < 40; i++) {
      const found = calibrationSensors(this._hass).find(
        (e) => this._hass.states[e].attributes.entry_id === entryId);
      if (found) {
        this._autoOpened = true;   // this is the auto-open; do not also fire it
        this._dialog.hass = this._hass;
        this._dialog.open(found);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }

  /* The calibrated light itself -- the entity that took over the original id.
     The card shows its real state, so this is what everything visual keys off. */
  _lightOf(sensorEntity) {
    const a = this._hass.states[sensorEntity];
    if (!a) return null;
    const id = (a.attributes.calibrating || "").replace(/_raw$/, "");
    return id ? this._hass.states[id] : null;
  }

  /* Entity ids are for automations, not for people. */
  _name(entityId) {
    if (!entityId) return "";
    const st = this._hass && this._hass.states[entityId];
    if (st && st.attributes.friendly_name) return st.attributes.friendly_name;
    return entityId.replace(/^[^.]+\./, "").replace(/_raw$/, "").replace(/_/g, " ");
  }

  /* Shaped like a Home Assistant tile card, because that is what the interface
     a user came from looks like. A row is a light, which may or may not have a
     calibration entry behind it -- an uncalibrated one is offered the way to
     get one, and nothing else. */
  _buildItem(row) {
    const el = document.createElement("div");
    el.className = "item";
    el.innerHTML = `
      <button class="tile" type="button">
        <span class="badge"><svg viewBox="0 0 24 24"><path/></svg></span>
        <span class="text">
          <span class="name"></span>
          <span class="state"></span>
        </span>
        <svg class="chev" viewBox="0 0 24 24"><path d="${ICONS.chevron}"/></svg>
      </button>
      <div class="foot">
        <button class="link act"></button>
        <span class="grow"></span>
        <button class="switch" role="switch" aria-label="Calibration">
          <span class="track"></span>
          <span class="knob"></span>
        </button>
      </div>`;

    // A tile that looks like Home Assistant's should do what one does: open the
    // light's own more-info dialog. Calibration has its own controls below.
    el.querySelector(".tile").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("hass-more-info", {
        detail: { entityId: row.light },
        bubbles: true, composed: true,
      }));
    });
    // The footer link is this card's one action, the way an integrations card
    // puts "21 services" there: a calibrated light opens its details, one with
    // nothing measured starts measuring -- unless how it shows whites is still
    // to be chosen, which has to happen before the whites are measured.
    el.querySelector(".act").addEventListener("click", () => {
      if (item.row.sensor && this._opensDetails(
            this._hass.states[item.row.sensor].attributes)) {
        this._openDetails(item.row.sensor);
        return;
      }
      if (item.row.sensor) {
        this._dialog.hass = this._hass;
        this._dialog.open(item.row.sensor);
        return;
      }
      // No entry yet: the light is already chosen, so the add flow only has to
      // ask what it should match.
      this._openAdd(row.light);
    });

    el.querySelector(".switch").addEventListener("click", () => {
      if (!item.row.sensor) return;
      this._hass.callService("switch", "toggle",
        { entity_id: item.row.sensor.replace(/^sensor\./, "switch.") });
    });
    const item = {
      el,
      row,
      icon: el.querySelector(".badge path"),
      badge: el.querySelector(".badge"),
      name: el.querySelector(".name"),
      state: el.querySelector(".state"),
      act: el.querySelector(".act"),
      sw: el.querySelector(".switch"),
      foot: el.querySelector(".foot"),
    };
    return item;
  }

  /* Only offered on a light with nothing to lose. Once one is calibrated,
     replacing its measurements is a thing you go looking for, not something
     sitting next to the button you press every day. */
  _copyLights(entity) {
    const map = this._calibratedLights();
    const a = this._hass.states[entity] && this._hass.states[entity].attributes;
    if (a) map.delete((a.calibrating || "").replace(/_raw$/, ""));
    return map;
  }

  _copyFrom(entity, other) {
    if (!other) return;
    const to = this._hass.states[entity].attributes;
    const from = this._hass.states[other].attributes;
    const losing = to.stored_points > 0
      ? `\n\n${this._name(to.calibrating)}'s own measurements ` +
        `(${to.profile_summary}) are discarded.`
      : "";
    if (!window.confirm(
      `Give ${this._name(to.calibrating)} the calibration measured for ` +
      `${this._name(from.calibrating)} ` +
      `(${from.profile_summary || from.stored_points + " points"})?\n\n` +
      `Only worth it if they are the same model -- a profile describes one ` +
      `fixture's particular errors.${losing}`)) return;
    this._hass.callService("light_calibration", "copy_profile", {
      entry_id: to.entry_id, source_entry_id: from.entry_id,
    });
  }

  /* The white_mode option (the backend's set_white_mode service; the options
     form has the same switch). Whites already measured stay stored, but the
     ones the new mode sends differently need measuring again -- the note
     under the control says so until they are. */
  _setWhiteMode(entity, control) {
    const a = this._hass.states[entity].attributes;
    if (control.value === (a.white_mode || "rgb")) return;
    if (a.stored_whites > 0 && !window.confirm(
      `Switch how ${this._name(a.calibrating)} shows whites?

` +
      `The whites measured so far were measured the other way, so whites ` +
      `sent the new way are not corrected until you run a white calibration ` +
      `again. Colours are not affected.`)) {
      control.value = a.white_mode || "rgb";
      return;
    }
    this._hass.callService("light_calibration", "set_white_mode",
      { entry_id: a.entry_id, white_mode: control.value });
  }

  _clearProfile(entity) {
    const a = this._hass.states[entity].attributes;
    if (!window.confirm(
      `Discard the calibration for ${this._name(a.calibrating)}?\n\n` +
      `It goes back to uncorrected output, and measuring it again means ` +
      `another pass with the sliders.`)) return;
    this._hass.callService("light_calibration", "clear_profile",
      { entry_id: a.entry_id });
  }

  async _toggleMeasurements(root) {
    const box = root.querySelector(".measurements");
    const button = root.querySelector(".dshow");
    if (!box.hidden) {
      box.hidden = true;
      button.textContent = "Show measurements";
      return;
    }
    button.disabled = true;
    try {
      const result = await this._hass.callWS({
        type: "light_calibration/profile",
        entry_id: this._detailsAttrs().entry_id,
      });
      box.innerHTML = renderPoints(result.points || []);
      button.textContent = "Hide measurements";
    } catch (err) {
      box.textContent = `Could not read the profile: ${(err && err.message) || err}`;
    }
    box.hidden = false;
    button.disabled = false;
  }

  // ------------------------------------------------------------------ details
  _detailsAttrs() {
    const st = this._detailsEntity && this._hass.states[this._detailsEntity];
    return st ? st.attributes : null;
  }

  _openDetails(entity) {
    this._detailsEntity = entity;
    const box = this._details.querySelector(".measurements");
    box.hidden = true;
    this._details.querySelector(".dshow").textContent = "Show measurements";
    this._copyKey = null;
    this._details.classList.add("open");
    this._renderDetails();
  }

  /* Whether the footer action opens Details rather than starting to measure. */
  _opensDetails(a) {
    return a.stored_points > 0 || hasWhitesChoice(a);
  }

  _closeDetails() {
    this._details.classList.remove("open");
    this._detailsEntity = null;
  }

  _renderDetails() {
    const a = this._detailsAttrs();
    if (!a) {
      this._closeDetails();
      return;
    }
    const d = this._details;
    const calibrated = a.stored_points > 0;
    d.querySelector(".dname").textContent = this._name(a.calibrating);
    d.querySelector(".did").textContent =
      (a.calibrating || "").replace(/_raw$/, "");

    const sw = this._hass.states[this._detailsEntity.replace(/^sensor\./, "switch.")];
    const on = sw && sw.state === "on";
    const toggle = d.querySelector(".dtoggle");
    toggle.hidden = !calibrated;
    toggle.textContent = on ? "Disable Calibration" : "Enable Calibration";
    d.querySelector(".dstate").textContent = !calibrated
      ? "Nothing measured yet"
      : on ? "Applied" : "Off -- the light is running uncorrected";

    // A record of what this light was measured against, not a live setting:
    // swapping it would leave measurements describing a reference that is no
    // longer there. Re-calibrating is how you change it.
    d.querySelector(".drefname").textContent =
      this._name(a.reference_light) || "None set";

    // Hidden on the card once a light is calibrated, but still reachable here.
    // Rebuilt only when the set of sources actually changes: this runs on every
    // state update, and re-mounting would shut a menu the pointer is in.
    const sources = this._copyLights(this._detailsEntity);
    d.querySelector(".dcopy").hidden = sources.size === 0;
    const key = [...sources.keys()].sort().join(",");
    if (sources.size && key !== this._copyKey) {
      this._copyKey = key;
      this._mountPicker(d.querySelector(".dcopypick"), {
        only: [...sources.keys()],
        onChange: (value, control) => {
          control.value = "";
          if (sources.has(value)) {
            this._copyFrom(this._detailsEntity, sources.get(value));
          }
        },
      });
    }

    // Only a colour light has two ways to show a white. Hidden when the
    // backend does not report the option at all.
    const whites = d.querySelector(".dwhite");
    whites.hidden = !hasWhitesChoice(a);
    const mode = d.querySelector(".dwhitemode");
    if (!mode.matches(":focus")) {   // not under an open menu
      mode.value = a.white_mode || "rgb";
    }
    d.querySelector(".dwhitenote").textContent = a.white_rerun_needed
      ? "The stored whites were measured the other way: run a white calibration again."
      : a.white_mode === "kelvin"
        ? "Brighter whites with better colour rendering, but no green/magenta " +
          "correction. A white beyond their range is shown as their nearest one."
        : a.white_mode === "kelvin_rgb"
          ? "Brighter whites with better colour rendering, but no green/magenta " +
            "correction. A white beyond their range is mixed from the colour LEDs."
          : "";

    d.querySelector(".dmeasure").hidden = !calibrated;
    d.querySelector(".dclear").hidden = !calibrated;
    d.querySelector(".dcal").textContent = calibrated ? "Re-Calibrate" : "Calibrate";
  }

  _updateItem(item) {
    const { light: lightId, sensor } = item.row;
    const light = this._hass.states[lightId];
    const a = sensor ? this._hass.states[sensor].attributes : null;
    const calibrated = !!(a && a.stored_points > 0);
    const sw = sensor
      ? this._hass.states[sensor.replace(/^sensor\./, "switch.")] : null;
    const on = sw && sw.state === "on";

    item.name.textContent = this._name(lightId);

    const tint = lightTint(light);
    item.badge.style.color = tint.color;
    item.icon.setAttribute("d", tint.icon);

    // A tile card's second line is the light's state, and that is what this
    // shows. The calibration only gets a word when something is worth saying.
    const lightState = !light || light.state === "unavailable"
      ? "Unavailable"
      : light.state === "on" ? describeLight(light) : "Off";
    const note = a && a.active ? this._hass.states[sensor].state
      : !sensor ? null
      : !calibrated ? "not calibrated"
      : !on ? "correction off"
      : null;
    item.state.textContent = note ? `${lightState} \u00b7 ${note}` : lightState;
    item.state.classList.toggle("warn", calibrated && !on && !(a && a.active));

    item.el.classList.toggle("calibrated", calibrated);
    item.act.textContent = a && this._opensDetails(a) ? "Details" : "Calibrate";
    item.sw.hidden = !calibrated;
    item.sw.setAttribute("aria-checked", on ? "true" : "false");
    item.sw.title = on ? "Correction on" : "Correction off";
    item.sw.classList.toggle("on", !!on);

  }

}

/* -------------------------------------------------------------------- card */

const CARD_STYLE = `
  ${BUTTONS}
  :host { display: block; }
  ha-card { padding: 16px; }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .name { font-size: 1.1rem; font-weight: 500; color: var(--primary-text-color); }
  .status { color: var(--secondary-text-color); font-size: 0.9rem; margin-top: 4px; }
`;

class LightCalibrationCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._built = false;
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Set 'entity' to a Light Calibration status sensor");
    }
    this._config = config;
  }

  static getStubConfig(hass) {
    return { entity: calibrationSensors(hass)[0] || "" };
  }

  getCardSize() { return 2; }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    const st = hass.states[this._config.entity];
    if (!st) return;
    this._name.textContent = st.attributes.friendly_name || this._config.entity;
    this._status.textContent = st.state;
    this._dialog.hass = hass;
  }

  _build() {
    const style = document.createElement("style");
    style.textContent = CARD_STYLE;
    const card = document.createElement("ha-card");
    card.innerHTML = `
      <div class="row">
        <div><div class="name"></div><div class="status"></div></div>
        <button class="primary" id="open">Calibrate</button>
      </div>`;
    this._dialog = document.createElement("light-calibration-dialog");
    this.shadowRoot.append(style, card, this._dialog);
    this._name = card.querySelector(".name");
    this._status = card.querySelector(".status");
    card.querySelector("#open").addEventListener("click", () => {
      this._dialog.hass = this._hass;
      this._dialog.open(this._config.entity);
    });
    this._built = true;
  }
}

/* Loaded on every HA page, so never throw if it somehow runs twice. */
if (customElements.get("light-calibration-dialog")) {
  /* A different build already claimed these names in this page, and a custom
     element name cannot be redefined -- so everything above is inert and the
     page will keep rendering whichever build got here first.

     Content-addressing the module URL stops a stale file being *fetched*; it
     cannot help once a page has registered an older one, and Home Assistant's
     frontend is a single page app that survives a restart. Updating without
     reloading the tab therefore leaves the old interface in place, looking
     exactly like an update that did not work. Say so instead of going quiet. */
  console.warn(
    "%c LIGHT-CALIBRATION ", "background:#e65100;color:#fff",
    "another build of this panel is already loaded in this page, so this one " +
    "is doing nothing. Reload the page to pick up the new version."
  );
} else {
  customElements.define("light-calibration-dialog", LightCalibrationDialog);
  customElements.define("light-calibration-panel", LightCalibrationPanel);
  customElements.define("light-calibration-card", LightCalibrationCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "light-calibration-card",
    name: "Light Calibration",
    description: "Guided, live colour matching for a miscalibrated light.",
  });

  console.info("%c LIGHT-CALIBRATION ", "background:#03a9f4;color:#fff", "loaded");
}
