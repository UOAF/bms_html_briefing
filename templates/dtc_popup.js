function getSelectedPopupMode() {
  if (selectedHasVip()) return "vip";
  if (selectedHasVrp()) return "vrp";
  return "";
}

function renderPopupReferenceMode() {
  const button = document.getElementById("dtc-popup-ref-mode");
  if (!button) return;
  const mode = getSelectedPopupMode();
  const label = mode ? mode.toUpperCase() : "NONE";
  button.textContent = label;
  button.title = mode
    ? "Selected steerpoint is set as " + label + "."
    : "Set the selected steerpoint as VIP or VRP in the offset panel first.";
}

function getPopupNumber(fieldName) {
  const input = document.querySelector("[data-popup-field='" + fieldName + "']");
  if (input?.classList.contains("dtc-popup-slider")) {
    const readout = document.querySelector("[data-slider-value-for='" + fieldName + "']");
    if (readout && document.activeElement === readout) {
      const readoutValue = normalizePopupSliderValue(input, readout.value);
      return Number.isFinite(readoutValue) ? readoutValue : NaN;
    }
  }
  const value = Number.parseFloat(input?.value || "");
  return Number.isFinite(value) ? value : NaN;
}

function getPopupValue(fieldName) {
  const control = document.querySelector("[data-popup-field='" + fieldName + "']");
  return cleanOffsetValue(control?.dataset?.popupValue ?? control?.value);
}

function renderPopupClicker(button) {
  const fieldName = button?.dataset?.popupField;
  const options = DTC_POPUP_CLICKER_OPTIONS[fieldName] || [];
  renderCycleButton(button, options, "popupValue", button?.dataset?.popupValue);
}

function cyclePopupClicker(button) {
  const fieldName = button?.dataset?.popupField;
  const options = DTC_POPUP_CLICKER_OPTIONS[fieldName] || [];
  cycleButton(button, options, "popupValue");
}

function renderPopupClickers() {
  renderPopupReferenceMode();
  document.querySelectorAll(".dtc-popup-clicker[data-popup-field]").forEach(renderPopupClicker);
}

function formatSliderValue(input) {
  const value = Number.parseFloat(input.value || "");
  if (!Number.isFinite(value)) return "";
  const step = Number.parseFloat(input.step || "1");
  const decimals = Number.isFinite(step) && step > 0 && !Number.isInteger(step) ? String(step).split(".")[1].length : 0;
  return decimals > 0 ? value.toFixed(decimals) : String(Math.round(value));
}

function getPopupSliderStepDecimals(slider) {
  const stepText = String(slider?.step || "1");
  if (stepText.toLowerCase() === "any") return 0;
  const step = Number.parseFloat(stepText);
  if (!Number.isFinite(step) || step <= 0 || Number.isInteger(step)) return 0;
  return (stepText.split(".")[1] || "").length;
}

function normalizePopupSliderValue(slider, rawValue, options = {}) {
  let value = Number.parseFloat(String(rawValue ?? "").trim());
  if (!Number.isFinite(value)) return NaN;
  const min = Number.parseFloat(slider.min || "");
  const max = Number.parseFloat(slider.max || "");
  const step = Number.parseFloat(slider.step || "");
  if (Number.isFinite(min)) value = Math.max(min, value);
  if (Number.isFinite(max)) value = Math.min(max, value);
  if (options.snapToStep && Number.isFinite(step) && step > 0) {
    const base = Number.isFinite(min) ? min : 0;
    value = base + Math.round((value - base) / step) * step;
    if (Number.isFinite(min)) value = Math.max(min, value);
    if (Number.isFinite(max)) value = Math.min(max, value);
    const decimals = getPopupSliderStepDecimals(slider);
    value = Number(value.toFixed(decimals));
  }
  return value;
}

function updatePopupSliderDisplays() {
  document.querySelectorAll(".dtc-popup-slider[data-popup-field]").forEach((input) => {
    const output = document.querySelector("[data-slider-value-for='" + input.dataset.popupField + "']");
    if (output && document.activeElement !== output) output.value = formatSliderValue(input);
  });
}

function syncPopupSliderFromReadout(readout, options = {}) {
  const fieldName = readout?.dataset?.sliderValueFor;
  const slider = fieldName ? document.querySelector(".dtc-popup-slider[data-popup-field='" + fieldName + "']") : null;
  if (!slider) return;
  const value = normalizePopupSliderValue(slider, readout.value, {
    snapToStep: options.commit === true,
  });
  if (!Number.isFinite(value)) {
    if (options.commit === true) readout.value = formatSliderValue(slider);
    return;
  }
  slider.value = String(value);
  if (options.commit === true) readout.value = formatSliderValue(slider);
}

function formatPopupNumber(value, decimals) {
  if (!Number.isFinite(value)) return "";
  const rounded = decimals > 0 ? Math.round(value * (10 ** decimals)) / (10 ** decimals) : Math.round(value);
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(decimals);
}

function formatPopupDegrees(value, decimals = 1) {
  const formatted = formatPopupNumber(value, decimals);
  return formatted ? formatted + "°" : "";
}

function formatPopupBearingText(value) {
  return value ? value + "°" : "---";
}

const POPUP_OUTPUT_LABEL_TITLES = {
  ACTION: "Heading and range to target at action point.",
  "ACTION-TO-PDP": "Distance from Action Point to PDP",
  ALTLOSS: "Estimated altitude lost during recovery.",
  "ANGLE OFF": "Angle between attack and ingress heading.",
  AOD: "Aim-off distance.",
  APEX: "Apex altitude.",
  "ATTACK HDG": "Attack heading.",
  "BOMB RANGE": "Manual bomb range, or the range from the selected low/high-drag bomb trajectory approximation.",
  CA: "Climb angle.",
  DA: "Dive angle.",
  "DELAY LOSS": "Altitude lost before pullout during stick duration plus the 2 second recovery delay.",
  GNDC: "Estimated ground clearance after recovery: release altitude minus recovery altitude loss.",
  "GROUND SPEED": "Horizontal speed component.",
  "HDG TO PDP": "HDG from PUP to PDP.",
  "INGRESS HDG": "Ingress heading.",
  "INGRESS ALT": "Ingress altitude AGL.",
  MAP: "Maneuver Aim Point. Distance from MAP to target.",
  "MAP-TO-TGT": "Distance from MAP to target.",
  MRA: "Minimum recovery altitude.",
  "MRA BUFFER": "Safety buffer added to recovery altitude loss when computing MRA.",
  "OA1 OFFSET": "Bearing/range from selected steerpoint reference to the computed OA1 offset aimpoint.",
  "PDP-TO-TGT": "Distance from pull-down point to target.",
  PDWN: "Pull-down altitude.",
  POP: "Bearing/range from computed PUP to target.",
  "POP-TO-PDWN": "Ground distance from PUP to pull-down point.",
  PUP: "Pull-up Point. Distance from PUP to PDP.",
  "PUP OFFSET": "Bearing/range from selected steerpoint reference to computed PUP.",
  "PUP-TO-PDP": "Distance from PUP to PDP.",
  "PUP-TO-TGT": "Distance from PUP to target.",
  "PULL LOSS": "Altitude lost during the 5G recovery pull from dive angle to level.",
  "PULL RADIUS": "Recovery pull radius from release speed and 5G pull assumption.",
  PULL: "Recovery pull G assumption.",
  RANGE: "Action range from target to action point.",
  RADIUS: "Horizontal turn radius.",
  RALT: "Release altitude AGL",
  "RANGE MODEL": "Bomb range source: manual entry or selected low/high-drag approximation.",
  "RECOVERY MODEL": "Recovery assumption used for MRA and ground-clearance estimates: hold through stick, then wait 2 seconds and pull.",
  "REF-TO-PUP": "Distance from selected steerpoint reference to computed PUP.",
  "RELEASE SPEED": "Entered release speed in KTAS.",
  "RELEASE RANGE": "Range from target to first release. MID adds half stick length so the stick center lands on target.",
  RPL: "Ripple pulses in the release stick.",
  SIDE: "Turn direction used to apply angle-off.",
  SPC: "Requested spacing between release pulses.",
  STICK: "Stick reference.",
  "STICK DUR": "Release stick duration.",
  "STICK LEN": "Release stick length.",
  TOF: "Time of fall.",
  "TOF STICK": "Time from first pulse release to final pulse impact.",
  "TRACK ALT": "Release altitude plus altitude lost during the final tracking segment.",
  "TRACK TIME": "Entered time on final used to compute MAP distance and track altitude.",
  TRACKING: "Horizontal distance flown during time on final.",
};

const POPUP_OUTPUT_TOKEN_TITLES = {
  AGL: "Above ground level.",
  BRG: "Bearing.",
  DELAY: "Time delay before recovery pull, or altitude lost during that delay.",
  HDG: "Heading.",
  MSL: "Mean sea level.",
  RNG: "Range.",
};

function getPopupOutputLabelTitle(label) {
  const normalized = cleanOffsetValue(label).toUpperCase();
  if (!normalized) return "";
  if (POPUP_OUTPUT_LABEL_TITLES[normalized]) return POPUP_OUTPUT_LABEL_TITLES[normalized];
  if (POPUP_OUTPUT_TOKEN_TITLES[normalized]) return POPUP_OUTPUT_TOKEN_TITLES[normalized];
  const titles = normalized
    .split(/[^A-Z0-9]+/)
    .map((token) => POPUP_OUTPUT_TOKEN_TITLES[token])
    .filter(Boolean);
  return [...new Set(titles)].join("; ");
}

function popupTitleAttr(label) {
  const title = getPopupOutputLabelTitle(label);
  return title ? " title=\"" + escapeHtml(title) + "\"" : "";
}

function popupMetric(label, value, tone) {
  const className = tone ? " is-" + tone : "";
  const labelHtml = label
    ? "<span class=\"dtc-popup-output-metric-label\"" + popupTitleAttr(label) + ">" + escapeHtml(label) + "</span>"
    : "";
  return "<span class=\"dtc-popup-output-metric" + className + "\">"
    + labelHtml
    + "<strong>" + escapeHtml(value) + "</strong>"
    + "</span>";
}

function popupLine(label, ...metrics) {
  return "<div class=\"dtc-popup-output-line\">"
    + "<span class=\"dtc-popup-output-line-label\"" + popupTitleAttr(label) + ">" + escapeHtml(label) + "</span>"
    + "<span class=\"dtc-popup-output-values\">" + metrics.filter(Boolean).join("") + "</span>"
    + "</div>";
}

function popupSection(title, lines) {
  return "<div class=\"dtc-popup-output-section\">"
    + "<div class=\"dtc-popup-output-section-title\">" + escapeHtml(title) + "</div>"
    + lines.join("")
    + "</div>";
}

function popupMessage(message) {
  return "<div class=\"dtc-popup-output-message\">" + escapeHtml(message) + "</div>";
}

function popupAglMslLine(label, aglFeet, terrainFeet) {
  const aglText = formatPopupNumber(aglFeet, 0) + " ft";
  const mslText = Number.isFinite(terrainFeet)
    ? formatPopupNumber(aglFeet + terrainFeet, 0) + " ft"
    : "MSL pending";
  return popupLine(label, popupMetric("AGL", aglText), popupMetric("MSL", mslText));
}

function formatPopupAglMslText(label, aglFeet, terrainFeet) {
  const aglText = formatPopupNumber(aglFeet, 0) + " ft AGL";
  const mslText = Number.isFinite(terrainFeet)
    ? formatPopupNumber(aglFeet + terrainFeet, 0) + " ft MSL"
    : "MSL pending";
  return label + " " + aglText + " / " + mslText;
}

function formatPopupAglMslCopyText(label, aglFeet, terrainFeet) {
  const aglText = formatPopupNumber(aglFeet, 0) + " AGL";
  const mslText = Number.isFinite(terrainFeet)
    ? formatPopupNumber(aglFeet + terrainFeet, 0) + " MSL"
    : "MSL pending";
  return label + " " + aglText + " / " + mslText;
}

function formatPopupFeet(value) {
  return formatPopupNumber(value, 0) + " ft";
}

function formatPopupNmFromFeet(value) {
  return formatPopupNumber(value / FEET_PER_NM, 1) + " NM";
}

function formatPopupNmCopyFromFeet(value) {
  return formatPopupNumber(value / FEET_PER_NM, 1) + " NM";
}

function formatPopupSeconds(value, decimals = 1) {
  const formatted = formatPopupNumber(value, decimals);
  return formatted ? formatted + " sec" : "N/A";
}

function getRangeModelLabel(rangeModel) {
  if (rangeModel === "manual") return "Manual";
  if (rangeModel === "high_drag") return "High drag approximation";
  return "Low drag approximation";
}

function computeDragBombTrajectory(releaseAltitude, releaseSpeed, diveAngle, rangeModel) {
  const stepSeconds = 0.1;
  const dragScale = rangeModel === "high_drag" ? 1.0 : 0.165;
  const gravity = rangeModel === "high_drag" ? 20.91505 : 32.177;
  const diveRadians = diveAngle * Math.PI / 180;
  let horizontalSpeed = Math.round(Math.cos(diveRadians) * releaseSpeed * FEET_PER_KNOT_SECOND * 100) / 100;
  let verticalSpeedDown = Math.round(Math.sin(diveRadians) * releaseSpeed * FEET_PER_KNOT_SECOND * 100) / 100;
  let rangeFeet = 0;
  let altitude = releaseAltitude;
  let lastStepRange = 0;
  let lastStepAltitudeChange = 0;
  let timeSeconds = 0;
  let guard = 0;
  while (altitude > 0 && guard < 10000) {
    guard += 1;
    const horizontalDrag = dragScale * 140 * Math.abs(horizontalSpeed) / Math.sqrt(horizontalSpeed * horizontalSpeed + 0.1);
    const acceleration = horizontalSpeed > 0 ? -horizontalDrag : 0;
    lastStepRange = horizontalSpeed * stepSeconds + 0.5 * acceleration * stepSeconds * stepSeconds;
    lastStepAltitudeChange = -verticalSpeedDown * stepSeconds - 0.5 * gravity * stepSeconds * stepSeconds;
    rangeFeet += lastStepRange;
    altitude += lastStepAltitudeChange;
    timeSeconds += stepSeconds;
    horizontalSpeed = Math.max(0, horizontalSpeed + acceleration * stepSeconds);
    verticalSpeedDown += gravity * stepSeconds;
  }
  if (guard >= 10000 || !Number.isFinite(altitude) || !Number.isFinite(lastStepAltitudeChange) || lastStepAltitudeChange === 0) return null;
  const overshootFraction = altitude / lastStepAltitudeChange;
  return {
    rangeFeet: rangeFeet - overshootFraction * lastStepRange,
    timeSeconds: timeSeconds - overshootFraction * stepSeconds,
  };
}

function updatePopupInputState() {
  const rangeModel = getPopupValue("rangeModel") === "manual" ? "manual" : "computed";
  const bombRangeInput = document.querySelector("[data-popup-field='bombRange']");
  if (bombRangeInput) {
    bombRangeInput.disabled = rangeModel !== "manual";
    bombRangeInput.title = rangeModel === "manual" ? "Manual bomb range / table value" : "Computed from the selected drag approximation";
  }
}

function computePopupPlan() {
  const mode = getSelectedPopupMode();
  const stptNumber = cleanOffsetValue(dtcSelectedStptNumber);
  if (!stptNumber) return { error: "Select a steerpoint." };
  if (!mode) return { error: "Set selected steerpoint as VIP or VRP first." };

  const diveAngle = getPopupNumber("diveAngle");
  const releaseAltitude = getPopupNumber("releaseAltitude");
  const ingressAltitude = getPopupNumber("ingressAltitude");
  const releaseSpeed = getPopupNumber("releaseSpeed");
  const timeOnFinal = getPopupNumber("timeOnFinal");
  const ripplePulsesRaw = getPopupNumber("ripplePulses");
  const stickSpacing = getPopupNumber("stickSpacing");
  const actionRangeNm = getPopupNumber("actionRangeNm");
  const heading = getPopupNumber("heading");
  const requestedRangeModel = getPopupValue("rangeModel");
  const rangeModel = requestedRangeModel === "manual" || requestedRangeModel === "high_drag" ? requestedRangeModel : "low_drag";
  const headingMode = getPopupValue("headingMode") === "ingress" ? "ingress" : "attack";
  const side = getPopupValue("side") === "left" ? "left" : "right";
  const gProfile = getPopupValue("gProfile") === "high" ? "high" : "low";
  const stickMode = getPopupValue("stickMode") === "start" ? "start" : "mid";
  const manualBombRange = getPopupNumber("bombRange");
  const required = [diveAngle, releaseAltitude, ingressAltitude, releaseSpeed, timeOnFinal, ripplePulsesRaw, stickSpacing, actionRangeNm, heading];
  if (rangeModel === "manual") required.push(manualBombRange);
  if (required.some((value) => !Number.isFinite(value))) return { error: "Enter all pop-up parameters." };
  const ripplePulses = Math.max(1, Math.round(ripplePulsesRaw));
  if (
    diveAngle <= 0 ||
    diveAngle >= 89 ||
    releaseAltitude <= 0 ||
    ingressAltitude < 0 ||
    releaseSpeed <= 0 ||
    timeOnFinal < 0 ||
    ripplePulses < 1 ||
    stickSpacing < 0 ||
    actionRangeNm <= 0 ||
    (rangeModel === "manual" && manualBombRange < 0)
  ) {
    return { error: "Pop-up parameters are outside valid ranges." };
  }
  const bombTrajectory = rangeModel === "manual"
    ? null
    : computeDragBombTrajectory(releaseAltitude, releaseSpeed, diveAngle, rangeModel);
  const bombRange = rangeModel === "manual" ? manualBombRange : bombTrajectory?.rangeFeet;
  const bombTimeOfFall = bombTrajectory?.timeSeconds ?? NaN;
  if (!Number.isFinite(bombRange) || bombRange <= 0) return { error: "Could not compute bomb range." };
  if (rangeModel !== "manual") {
    const bombRangeInput = document.querySelector("[data-popup-field='bombRange']");
    if (bombRangeInput) bombRangeInput.value = String(Math.round(bombRange));
  }

  const selectedCoord = getBmsCoordForStpt(stptNumber);
  if (!selectedCoord) return { error: "Selected steerpoint coordinates are invalid." };
  let targetCoord = selectedCoord;
  if (mode === "vip") {
    targetCoord = projectOffsetFromBmsCoord(selectedCoord, dtcNavOffsets.vip);
    if (!targetCoord) return { error: "VIP-TO-TGT is required before computing pop-up geometry." };
  }

  const diveRadians = diveAngle * Math.PI / 180;
  const groundSpeed = releaseSpeed * Math.cos(diveRadians);
  const groundSpeedFps = groundSpeed * FEET_PER_KNOT_SECOND;
  const stickLength = Math.max(0, ripplePulses - 1) * stickSpacing;
  const stickHalfLength = stickMode === "mid" ? stickLength / 2 : 0;
  const stickDuration = groundSpeedFps > 0 ? stickLength / groundSpeedFps : NaN;
  const releaseReferenceRange = bombRange + stickHalfLength;
  const stickTimeOfFall = Number.isFinite(bombTimeOfFall) && Number.isFinite(stickDuration)
    ? bombTimeOfFall + stickDuration
    : NaN;
  const horizontalTrackingDistance = groundSpeed * 1.69 * timeOnFinal;
  const verticalTrackingDistance = releaseSpeed * 1.69 * timeOnFinal * Math.sin(diveRadians);
  const mapDistance = releaseReferenceRange + horizontalTrackingDistance;
  const actionRangeFeet = actionRangeNm * FEET_PER_NM;
  const aod = releaseAltitude / Math.tan(diveRadians) - releaseReferenceRange;
  if (aod <= 0) return { error: "AOD is negative for this profile. Increase release altitude or reduce bomb range." };
  const climbAngle = diveAngle <= 15 ? diveAngle + 5 : diveAngle + 10;
  const climbRadians = climbAngle * Math.PI / 180;
  const angleOff = 2 * climbAngle;
  const turnG = gProfile === "high" ? 5 : 3.5;
  const trackAltitude = releaseAltitude + verticalTrackingDistance;
  const turnRadius = ((releaseSpeed * 1.69) ** 2) / (32.2 * turnG);
  const recoveryPullDelay = stickDuration + 2;
  const recoveryPullG = 5;
  const releaseSpeedFps = releaseSpeed * FEET_PER_KNOT_SECOND;
  const recoveryDelayAltitudeLoss = releaseSpeedFps * Math.sin(diveRadians) * recoveryPullDelay;
  const recoveryPullRadius = (releaseSpeedFps ** 2) / (32.2 * recoveryPullG);
  const recoveryPullAltitudeLoss = recoveryPullRadius * (1 - Math.cos(diveRadians));
  const recoveryAltitudeLoss = recoveryDelayAltitudeLoss + recoveryPullAltitudeLoss;
  const recoveryGroundClearance = releaseAltitude - recoveryAltitudeLoss;
  const pullDownAltitude = trackAltitude - turnRadius * (Math.cos(diveRadians) - Math.cos(climbRadians));
  const apexAltitude = pullDownAltitude + turnRadius * (1 - Math.cos(climbRadians));
  const popToPullDownDistance = (pullDownAltitude - ingressAltitude) / Math.tan(climbRadians);
  if (popToPullDownDistance <= 0) return { error: "Ingress altitude is above the computed pull-down altitude." };

  let attackHeading;
  let ingressHeading;
  if (headingMode === "attack") {
    attackHeading = normalizeBearing(heading);
    ingressHeading = normalizeBearing(attackHeading + (side === "right" ? -angleOff : angleOff));
  } else {
    ingressHeading = normalizeBearing(heading);
    attackHeading = normalizeBearing(ingressHeading + (side === "right" ? angleOff : -angleOff));
  }

  const turnDirection = side === "left" ? "left" : "right";
  const actionCoord = projectBearingRange(targetCoord, ingressHeading + 180, actionRangeFeet);
  const mapCoord = projectBearingRange(targetCoord, attackHeading + 180, mapDistance);
  const releaseCoord = projectBearingRange(targetCoord, attackHeading + 180, releaseReferenceRange);
  const turnGeometry = solvePopupTurnGeometry(actionCoord, mapCoord, attackHeading, turnRadius, turnDirection);
  if (!turnGeometry) return { error: "Could not solve action-to-MAP turn geometry." };
  const pdpCoord = turnGeometry.pdpCoord;
  const offsetLegMetrics = turnGeometry.offsetLegMetrics;
  const offsetLegHeading = turnGeometry.offsetLegHeading;
  const offsetLegDistance = coordDistanceFeet(actionCoord, pdpCoord);
  if (popToPullDownDistance > offsetLegDistance) {
    return { error: "PUP would fall before the action point. Increase action range or adjust the vertical profile." };
  }
  const pupCoord = projectBearingRange(pdpCoord, offsetLegHeading + 180, popToPullDownDistance);
  const oaCoord = projectBearingRange(targetCoord, attackHeading, aod);
  if (!actionCoord || !pdpCoord || !pupCoord || !oaCoord) return { error: "Could not compute pop-up geometry." };
  const turnArcCoords = turnGeometry.turnArcCoords;
  const rolloutCoord = mapCoord;

  const pupMetrics = bearingRangeBetween(selectedCoord, pupCoord);
  const oaMetrics = bearingRangeBetween(selectedCoord, oaCoord);
  if (!pupMetrics || !oaMetrics) return { error: "Could not compute NAV offset rows." };
  const ingressToOffset = Math.abs(normalizeBearing(offsetLegHeading - ingressHeading));
  const offsetAngle = ingressToOffset > 180 ? 360 - ingressToOffset : ingressToOffset;

  return {
    mode,
    stptNumber,
    selectedCoord,
    targetCoord,
    actionCoord,
    mapCoord,
    releaseCoord,
    pdpCoord,
    pupCoord,
    oaCoord,
    rolloutCoord,
    turnArcCoords,
    offsetLegMetrics,
    pupMetrics,
    oaMetrics,
    values: {
      diveAngle,
      releaseAltitude,
      ingressAltitude,
      releaseSpeed,
      bombRange,
      bombTimeOfFall,
      releaseReferenceRange,
      ripplePulses,
      stickSpacing,
      stickMode,
      stickLength,
      stickDuration,
      stickTimeOfFall,
      rangeModel,
      timeOnFinal,
      actionRangeNm,
      actionRangeFeet,
      groundSpeed,
      horizontalTrackingDistance,
      verticalTrackingDistance,
      mapDistance,
      aod,
      climbAngle,
      angleOff,
      trackAltitude,
      apexAltitude,
      pullDownAltitude,
      popToPullDownDistance,
      turnRadius,
      recoveryPullDelay,
      recoveryPullG,
      recoveryPullRadius,
      recoveryDelayAltitudeLoss,
      recoveryPullAltitudeLoss,
      recoveryAltitudeLoss,
      recoveryGroundClearance,
      recoveryMraAltitude: recoveryAltitudeLoss + POPUP_MRA_BUFFER_FEET,
      recoveryMraBuffer: POPUP_MRA_BUFFER_FEET,
      attackHeading,
      ingressHeading,
      offsetLegHeading,
      offsetAngle,
      turnDirection,
      headingMode,
      side,
      gProfile,
    },
  };
}

function formatPopupOutput(plan, supportOpen = false) {
  if (!plan || plan.error) return popupMessage(plan?.error || "");
  const v = plan.values;
  const pdpTerrainFeet = getCachedPopupTerrainElevationFeet(plan.pdpCoord);
  const releaseTerrainFeet = getCachedPopupTerrainElevationFeet(plan.releaseCoord || plan.targetCoord);
  const referenceToPupFeet = coordDistanceFeet(plan.selectedCoord, plan.pupCoord);
  const pupToPdpFeet = coordDistanceFeet(plan.pupCoord, plan.pdpCoord);
  const pdpToTargetFeet = coordDistanceFeet(plan.pdpCoord, plan.targetCoord);
  const pupToTargetFeet = coordDistanceFeet(plan.pupCoord, plan.targetCoord);
  const pupToTargetMetrics = bearingRangeBetween(plan.pupCoord, plan.targetCoord);
  const mapToTargetFeet = coordDistanceFeet(plan.mapCoord, plan.targetCoord);
  const title = "POP-UP STPT " + plan.stptNumber + " " + plan.mode.toUpperCase();
  const primaryLines = [
    popupLine("POP", popupMetric("BRG", formatPopupBearingText(pupToTargetMetrics?.brg), "primary"), popupMetric("RNG", formatPopupNmFromFeet(pupToTargetFeet), "primary")),
    popupLine("DA", popupMetric("", formatPopupDegrees(v.diveAngle))),
    popupLine("CA", popupMetric("", formatPopupDegrees(v.climbAngle))),
    popupAglMslLine("PDWN", v.pullDownAltitude, pdpTerrainFeet),
    popupAglMslLine("APEX", v.apexAltitude, pdpTerrainFeet),
    popupAglMslLine("RALT", v.releaseAltitude, releaseTerrainFeet),
    popupAglMslLine("MRA", v.recoveryMraAltitude, releaseTerrainFeet),
    popupLine("AOD", popupMetric("", formatPopupFeet(v.aod))),
    popupLine("PUP", popupMetric("", formatPopupFeet(pupToPdpFeet))),
    popupLine("RADIUS", popupMetric("", formatPopupFeet(v.turnRadius))),
    popupLine("MAP", popupMetric("", formatPopupFeet(v.mapDistance))),
    popupLine("ALTLOSS", popupMetric("", formatPopupFeet(v.recoveryAltitudeLoss))),
    popupLine("GNDC", popupMetric("", formatPopupFeet(v.recoveryGroundClearance) + " AGL")),
    popupLine("TOF STICK", popupMetric("", formatPopupSeconds(v.stickTimeOfFall))),
  ];
  const supportLines = [
    popupLine("ACTION", popupMetric("Range", formatPopupNumber(v.actionRangeNm, 1) + " NM"), popupMetric("Ingress HDG", formatPopupDegrees(v.ingressHeading))),
    popupLine("STICK", popupMetric("RPL", formatPopupNumber(v.ripplePulses, 0)), popupMetric("SPC", formatPopupFeet(v.stickSpacing)), popupMetric("Mode", v.stickMode.toUpperCase())),
    popupLine("STICK LEN", popupMetric("", formatPopupFeet(v.stickLength))),
    popupLine("STICK DUR", popupMetric("", formatPopupSeconds(v.stickDuration))),
    popupLine("RELEASE RANGE", popupMetric("", formatPopupFeet(v.releaseReferenceRange))),
    popupLine("REF-TO-PUP", popupMetric("", formatPopupFeet(referenceToPupFeet))),
    popupLine("PUP-TO-PDP", popupMetric("", formatPopupFeet(pupToPdpFeet))),
    popupLine("PUP-TO-TGT", popupMetric("", formatPopupFeet(pupToTargetFeet))),
    popupLine("HDG TO PDP", popupMetric("", formatPopupDegrees(v.offsetLegHeading))),
    popupLine("PUP OFFSET", popupMetric("BRG", formatPopupBearingText(plan.pupMetrics.brg)), popupMetric("RNG", plan.pupMetrics.rng + " ft")),
    popupLine("PDP-TO-TGT", popupMetric("", formatPopupFeet(pdpToTargetFeet))),
    popupLine("ACTION-TO-PDP", popupMetric("", plan.offsetLegMetrics.rng + " ft")),
    popupLine("ANGLE OFF", popupMetric("", formatPopupDegrees(v.angleOff)), popupMetric("Side", v.side.toUpperCase())),
    popupLine("MAP-TO-TGT", popupMetric("", formatPopupFeet(mapToTargetFeet))),
    popupLine("ATTACK HDG", popupMetric("", formatPopupDegrees(v.attackHeading))),
    popupLine("TRACK TIME", popupMetric("", formatPopupSeconds(v.timeOnFinal))),
    popupLine("TRACKING", popupMetric("", formatPopupFeet(v.horizontalTrackingDistance))),
    popupLine("BOMB RANGE", popupMetric("", formatPopupFeet(v.bombRange))),
    popupLine("RECOVERY MODEL", popupMetric("Pull", formatPopupNumber(v.recoveryPullG, 0) + "G"), popupMetric("Delay", formatPopupNumber(v.recoveryPullDelay, 0) + " sec")),
    popupLine("MRA BUFFER", popupMetric("", formatPopupFeet(v.recoveryMraBuffer))),
    popupLine("DELAY LOSS", popupMetric("", formatPopupFeet(v.recoveryDelayAltitudeLoss))),
    popupLine("PULL LOSS", popupMetric("", formatPopupFeet(v.recoveryPullAltitudeLoss))),
    popupLine("PULL RADIUS", popupMetric("", formatPopupFeet(v.recoveryPullRadius))),
    popupLine("RANGE MODEL", popupMetric("", getRangeModelLabel(v.rangeModel))),
    popupLine("INGRESS ALT", popupMetric("", formatPopupNumber(v.ingressAltitude, 0) + " ft AGL")),
    popupLine("RELEASE SPEED", popupMetric("", formatPopupNumber(v.releaseSpeed, 0) + " KTAS")),
    popupLine("GROUND SPEED", popupMetric("", formatPopupNumber(v.groundSpeed, 0) + " KTAS")),
    popupLine("TRACK ALT", popupMetric("", formatPopupNumber(v.trackAltitude, 0) + " ft AGL")),
    popupLine("POP-TO-PDWN", popupMetric("", formatPopupNumber(v.popToPullDownDistance, 0) + " ft")),
    popupLine("OA1 OFFSET", popupMetric("BRG", formatPopupBearingText(plan.oaMetrics.brg)), popupMetric("RNG", plan.oaMetrics.rng + " ft")),
  ];
  return "<div class=\"dtc-popup-output-title\">" + escapeHtml(title) + "</div>"
    + primaryLines.join("")
    + "<div class=\"dtc-popup-output-actions\">"
    + "<button type=\"button\" class=\"dtc-popup-output-copy\" data-popup-copy-output title=\"Copy compact plain-text output\">COPY</button>"
    + "</div>"
    + "<div class=\"dtc-popup-output-support" + (supportOpen ? " is-open" : "") + "\">"
    + supportLines.join("")
    + "</div>"
    + "<button type=\"button\" class=\"dtc-popup-output-help" + (supportOpen ? " is-open" : "") + "\" data-popup-toggle-support title=\"Show support values\">?</button>";
}

function formatPopupOutputText(plan) {
  if (!plan || plan.error) return plan?.error || "";
  const v = plan.values;
  const pdpTerrainFeet = getCachedPopupTerrainElevationFeet(plan.pdpCoord);
  const releaseTerrainFeet = getCachedPopupTerrainElevationFeet(plan.releaseCoord || plan.targetCoord);
  const pupToPdpFeet = coordDistanceFeet(plan.pupCoord, plan.pdpCoord);
  const pupToTargetFeet = coordDistanceFeet(plan.pupCoord, plan.targetCoord);
  const pupToTargetMetrics = bearingRangeBetween(plan.pupCoord, plan.targetCoord);
  const title = "POP-UP STPT " + plan.stptNumber + " " + plan.mode.toUpperCase();
  return [
    title,
    "POP: BRG " + formatPopupNumber(Number.parseFloat(pupToTargetMetrics?.brg), 1) + " / RNG " + formatPopupNmCopyFromFeet(pupToTargetFeet),
    "DA " + formatPopupNumber(v.diveAngle, 1) + " / CA " + formatPopupNumber(v.climbAngle, 1),
    "STICK " + v.stickMode.toUpperCase() + " / RPL " + formatPopupNumber(v.ripplePulses, 0) + " / SPC " + formatPopupNumber(v.stickSpacing, 0),
      formatPopupAglMslCopyText("PDWN", v.pullDownAltitude, pdpTerrainFeet),
	  formatPopupAglMslCopyText("APEX", v.apexAltitude, pdpTerrainFeet),
      formatPopupAglMslCopyText("RALT", v.releaseAltitude, releaseTerrainFeet),
	  formatPopupAglMslCopyText("MRA", v.recoveryMraAltitude, releaseTerrainFeet),
    "AOD " + formatPopupNumber(v.aod, 0) + " / PUP " + formatPopupNumber(pupToPdpFeet, 0),
    "RADIUS " + formatPopupNumber(v.turnRadius, 0) + " / MAP " + formatPopupNumber(v.mapDistance, 0),
    "ALTLOSS " + formatPopupNumber(v.recoveryAltitudeLoss, 0) + " / GNDC " + formatPopupNumber(v.recoveryGroundClearance, 0) + " AGL",
    "TOF STICK: " + formatPopupSeconds(v.stickTimeOfFall),
  ].join("\n");
}

function addDtcPopupConnector(coords, options) {
  if (!dtcPopupMapLayer) return null;
  const latlngs = coords.map((coord) => bmsCoordToMapLatLng(coord)).filter(Boolean);
  if (latlngs.length < 2) return null;
  const connector = L.polyline(latlngs, {
    color: options?.color || "#ffe680",
    weight: options?.weight || 2,
    opacity: 0.92,
    dashArray: options?.dashArray || null,
    interactive: false,
  }).addTo(dtcPopupMapLayer);
  return connector;
}

function formatPopupPointContent(title, lines) {
  const content = ["<b>" + escapeHtml(title) + "</b>"];
  lines.filter(Boolean).forEach((line) => content.push(escapeHtml(line)));
  return content.join("<br>");
}

function formatPopupAglMslLine(label, aglFeet, terrainFeet) {
  const aglText = formatPopupNumber(aglFeet, 0) + " ft AGL";
  const mslText = Number.isFinite(terrainFeet)
    ? formatPopupNumber(aglFeet + terrainFeet, 0) + " ft MSL"
    : "MSL pending";
  return label + ": " + aglText + " / " + mslText;
}

function addDtcPopupMarker(kind, label, coord, title, popupContent, markerOptions) {
  if (!dtcPopupMapLayer) return null;
  const latlng = bmsCoordToMapLatLng(coord);
  if (!latlng) return null;
  const dragOptions = markerOptions?.dragOptions || null;
  const draggable = Boolean(dragOptions && dragOptions.offsetRow && dragOptions.baseCoord);
  const marker = L.marker(latlng, {
    icon: L.divIcon({
      className: "dtc-offset-map-icon dtc-popup-map-icon is-" + kind,
      html: escapeHtml(label || ""),
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    }),
    draggable,
    interactive: Boolean(popupContent || draggable),
    keyboard: false,
    bubblingMouseEvents: false,
    title: title || label || "",
  }).addTo(dtcPopupMapLayer);
  if (popupContent) {
    marker.bindPopup(popupContent, {
      className: "target-stpt-popup",
      closeButton: false,
      autoPan: false,
    });
  }
  if (draggable) {
    marker.on("dragstart", () => {
      marker.closePopup();
      updateOffsetDragTooltip(marker, dragOptions.baseCoord, dragOptions.connector);
    });
    marker.on("drag", () => {
      if (!dragOptions.connector) return;
      const baseLatLng = bmsCoordToMapLatLng(dragOptions.baseCoord);
      if (!baseLatLng) return;
      dragOptions.connector.setLatLngs([baseLatLng, marker.getLatLng()]);
      updateOffsetDragTooltip(marker, dragOptions.baseCoord, dragOptions.connector);
    });
    marker.on("dragend", () => updateOffsetRowFromDraggedMarker(marker, dragOptions.baseCoord, dragOptions.offsetRow, dragOptions));
  }
  return marker;
}

function renderPopupMapLayer(plan) {
  if (typeof L === "undefined" || typeof map === "undefined") return;
  if (!dtcPopupMapLayer) {
    dtcPopupMapLayer = L.layerGroup().addTo(map);
  }
  dtcPopupMapLayer.clearLayers();
  if (!plan || plan.error) return;
  const routeStartCoord = plan.mode === "vip"
    ? plan.selectedCoord
    : projectBearingRange(plan.actionCoord, plan.values.ingressHeading + 180, Math.min(plan.values.actionRangeFeet * 0.5, 12000));
  if (routeStartCoord) {
    addDtcPopupConnector([routeStartCoord, plan.actionCoord]);
  }
  addDtcPopupConnector([plan.actionCoord, plan.pupCoord, plan.pdpCoord]);
  if (Array.isArray(plan.turnArcCoords) && plan.turnArcCoords.length > 1) {
    addDtcPopupConnector(plan.turnArcCoords, { color: "#ffb347", weight: 2.25 });
  }
  addDtcPopupConnector([plan.mapCoord || plan.rolloutCoord || plan.pdpCoord, plan.targetCoord]);
  addDtcPopupConnector([plan.targetCoord, plan.oaCoord], { dashArray: "4 4", weight: 1.5 });
  const pdpTerrainFeet = getCachedPopupTerrainElevationFeet(plan.pdpCoord);
  const releaseTerrainFeet = getCachedPopupTerrainElevationFeet(plan.releaseCoord || plan.targetCoord);
  addDtcPopupMarker("action", "", plan.actionCoord, "Action point", formatPopupPointContent("AP", [
    "Offset: " + formatPopupNumber(plan.values.offsetAngle, 1) + "°",
    "Action range: " + formatPopupNumber(plan.values.actionRangeNm, 1) + " NM",
    "Ingress HDG: " + formatPopupNumber(plan.values.ingressHeading, 1) + "°",
  ]));
  addDtcPopupMarker("pup", "", plan.pupCoord, "Computed PUP", formatPopupPointContent("PUP", [
    "Climb angle: " + formatPopupNumber(plan.values.climbAngle, 1) + "°",
    "HDG to PDP: " + formatPopupNumber(plan.values.offsetLegHeading, 1) + "°",
  ]));
  addDtcPopupMarker("pdp", "", plan.pdpCoord, "PDP", formatPopupPointContent("PDP", [
    formatPopupAglMslLine("PDP", plan.values.pullDownAltitude, pdpTerrainFeet),
    formatPopupAglMslLine("APEX", plan.values.apexAltitude, pdpTerrainFeet),
    "Angle off: " + formatPopupNumber(plan.values.angleOff, 1) + "° " + plan.values.side.toUpperCase(),
  ]));
  addDtcPopupMarker("action", "", plan.mapCoord, "MAP / rollout", formatPopupPointContent("MAP", [
    "Tracking time: " + formatPopupNumber(plan.values.timeOnFinal, 0) + " sec",
    formatPopupAglMslLine("Release ALT", plan.values.releaseAltitude, releaseTerrainFeet),
    "Attack HDG: " + formatPopupNumber(plan.values.attackHeading, 1) + "°",
    "Dive angle: " + formatPopupNumber(plan.values.diveAngle, 1) + "°",
  ]));
  const vipTargetDragOptions = plan.mode === "vip" && dtcNavOffsets.vip
    ? {
      dragOptions: {
        baseCoord: plan.selectedCoord,
        offsetRow: dtcNavOffsets.vip,
        rowKey: "vip",
        stptNumber: plan.stptNumber,
      },
    }
    : null;
  addDtcPopupMarker("tgt", "", plan.targetCoord, "Target", formatPopupPointContent("TGT", [
    "STPT " + plan.stptNumber + " " + plan.mode.toUpperCase(),
    "Attack HDG: " + formatPopupNumber(plan.values.attackHeading, 1) + "°",
  ]), vipTargetDragOptions);
  addDtcPopupMarker("oa", "1", plan.oaCoord, "Computed OA1", formatPopupPointContent("OA1", [
    "AOD: " + formatPopupNumber(plan.values.aod, 0) + " ft",
    "Offset: BRG " + plan.oaMetrics.brg + " RNG " + plan.oaMetrics.rng,
  ]));
}

function renderPopupComputer(statusText) {
  renderPopupClickers();
  updatePopupSliderDisplays();
  updatePopupInputState();
  const panel = document.getElementById("dtc-left-popup");
  if (!panel) return;
  if (statusText != null) dtcPopupStatusText = statusText;
  const hasSelection = cleanOffsetValue(dtcSelectedStptNumber) !== "";
  if (panel.hidden || !hasSelection) {
    dtcPopupLastPlan = null;
    renderPopupMapLayer(null);
    const output = document.getElementById("dtc-popup-output");
    if (output && !hasSelection) output.innerHTML = popupMessage("Select a steerpoint.");
    const applyButton = document.getElementById("dtc-popup-apply");
    if (applyButton) applyButton.disabled = true;
    return;
  }

  const mode = getSelectedPopupMode();
  const label = document.getElementById("dtc-popup-stpt-label");
  if (label) label.textContent = "STPT " + dtcSelectedStptNumber + " " + mode.toUpperCase();
  const plan = computePopupPlan();
  dtcPopupLastPlan = plan && !plan.error ? plan : null;
  const output = document.getElementById("dtc-popup-output");
  if (output) {
    output.innerHTML = formatPopupOutput(plan, dtcPopupSupportOpen);
  }
  const applyButton = document.getElementById("dtc-popup-apply");
  if (applyButton) applyButton.disabled = !dtcPopupLastPlan;
  const status = document.getElementById("dtc-popup-status");
  if (status) status.textContent = dtcPopupStatusText;
  renderPopupMapLayer(plan);
}

async function copyPopupOutputToClipboard() {
  const plan = dtcPopupLastPlan || computePopupPlan();
  if (!plan || plan.error) {
    renderPopupComputer(plan?.error || "Could not compute pop-up output.");
    return;
  }
  const text = formatPopupOutputText(plan);
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    renderPopupComputer("Pop-up output copied to clipboard.");
  } catch (error) {
    renderPopupComputer("Could not copy pop-up output to clipboard.");
  }
}

function togglePopupSupport() {
  dtcPopupSupportOpen = !dtcPopupSupportOpen;
  renderPopupComputer("");
}

async function applyPopupPlan() {
  const plan = dtcPopupLastPlan || computePopupPlan();
  if (!plan || plan.error) {
    renderPopupComputer(plan?.error || "Could not compute pop-up geometry.");
    return;
  }

  const stptKey = cleanOffsetValue(plan.stptNumber);
  dtcNavOffsets.oa[stptKey] = dtcNavOffsets.oa[stptKey] || {};
  const oaRow = blankOffsetRow(stptKey);
  oaRow.brg = plan.oaMetrics.brg;
  oaRow.rng = plan.oaMetrics.rng;
  dtcNavOffsets.oa[stptKey].oa1 = oaRow;

  const pupRow = blankOffsetRow(stptKey);
  pupRow.brg = plan.pupMetrics.brg;
  pupRow.rng = plan.pupMetrics.rng;
  let defaultVrpRow = null;
  if (plan.mode === "vip") {
    dtcNavOffsets.vippup = pupRow;
  } else {
    if (!offsetRowMatchesStpt(dtcNavOffsets.vrp, stptKey) || isZeroOffsetRow(dtcNavOffsets.vrp)) {
      defaultVrpRow = defaultOffsetRow(stptKey, "vrp");
      dtcNavOffsets.vrp = defaultVrpRow;
    }
    dtcNavOffsets.vrppup = pupRow;
  }

  renderOffsetPanel();
  updateOffsetRowElevationFromCoord(oaRow, plan.oaCoord);
  updateOffsetRowElevationFromCoord(pupRow, plan.pupCoord);
  if (defaultVrpRow) updateOffsetRowElevationFromOffset(plan.targetCoord, defaultVrpRow);
  renderPopupComputer("PUP/OA applied to NAV OFFSETS.");
}

