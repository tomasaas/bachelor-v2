// Rubik's Cube Solver – front-end logic
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── DOM refs ────────────────────────────────────────────────────────────────
const btnPing        = $("#btn-ping");
const btnTorqueOn    = $("#btn-torque-on");
const btnTorqueOff   = $("#btn-torque-off");
const btnScramble    = $("#btn-scramble");
const btnHome        = $("#btn-home");
const btnEmergencyStop = $("#btn-emergency-stop");
const btnRefreshCams = $("#btn-refresh-cams");
const btnUnfreeze    = $("#btn-unfreeze");
const btnDetect      = $("#btn-detect");
const btnRoiUnlock = $("#btn-roi-unlock");
const btnRoiReset  = $("#btn-roi-reset");
const roiSizeSlider = $("#roi-size-slider");
const roiSizeValue = $("#roi-size-value");
const btnSolve     = $("#btn-solve");
const btnAbort     = $("#btn-abort");
const progressBar  = $("#progress-bar");
const progressText = $("#progress-text");
const logOutput    = $("#log-output");
const stateBadge   = $("#state-badge");
const workflowSummary = $("#workflow-summary");
const detectionPanel   = $("#detection-panel");
const cubePreview      = $("#cube-preview");
const cubeStringDisp   = $("#cube-string-display");
const manualCubeStringInput = $("#manual-cube-string");
const cubeStringSource = $("#cube-string-source");
const captureStatus = $("#capture-status");
const roiStatus = $("#roi-status");
const stepStateRoi = $("#step-state-roi");
const stepStateDetect = $("#step-state-detect");
const stepStateReview = $("#step-state-review");
const stepStateSolve = $("#step-state-solve");
const totalCurrentDisplay = $("#total-current-display");
const btnAngleRefCube = $("#btn-angle-ref-cube");
const btnAngleRefServo = $("#btn-angle-ref-servo");
const tabButtons = $$("[data-tab-button]");
const tabPanels = $$("[data-tab-panel]");

// Camera elements
const cam0Img      = $("#cam0");
const cam1Img      = $("#cam1");
const cam0Canvas   = $("#cam0-overlay");
const cam1Canvas   = $("#cam1-overlay");
const cam0Viewport = $("#cam0-viewport");
const cam1Viewport = $("#cam1-viewport");

// ── State ───────────────────────────────────────────────────────────────────
let frozen = false;
let roisUnlocked = false;
let rois = { 0: [], 1: [] };          // ROI definitions per camera
let roiColors = { 0: {}, 1: {} };     // detected colors per ROI label
let detectedCubeString = "";
let previewColorMap = null;            // editable color map used by cube preview
let polling = null;
let dragging = null;                   // { camId, index, offsetX, offsetY }
let faceTelemetry = {};
let angleReference = "cube";

const FACE_ORDER = ["U", "R", "F", "D", "L", "B"];
const FIXED_CENTER_COLORS = { U5: "W", R5: "R", F5: "G", D5: "Y", L5: "O", B5: "B" };
const CYCLE_COLORS = ["W", "Y", "R", "O", "B", "G"];
const VALID_CUBE_CHARS = new Set(["U", "R", "F", "D", "L", "B", "W", "Y", "O", "G"]);
const ANGLE_REFERENCE_STORAGE_KEY = "hardware-angle-reference";
const DETECTION_PREVIEW_PLACEHOLDER =
  "Detected colors will appear here after step 2. You can still paste a full cube-state override on the right.";
const DETECTION_STRING_PLACEHOLDER = "Detected cube string will appear here after color detection.";
const ROI_SIZE = {
  min: 4,
  max: 49,
  default: 25,
};
const ROI_STYLE = {
  liveLineWidth: 2,
  editLineWidth: 3,
  detectedLineWidth: 3,
  labelFont: "10px monospace",
  letterMinSize: 10,
  letterMaxSize: 18,
  letterScale: 0.7,
};
const ANGLE_REFERENCE_CONFIG = {
  cube: {
    label: "cube",
    min: 0,
    max: 270,
    placeholder: "0-270° cube",
    button: btnAngleRefCube,
  },
  servo: {
    label: "servo",
    min: 0,
    max: 300,
    placeholder: "0-300° servo",
    button: btnAngleRefServo,
  },
};
const STEP_STATES = {
  1: stepStateRoi,
  2: stepStateDetect,
  3: stepStateReview,
  4: stepStateSolve,
};

// ── Helpers ─────────────────────────────────────────────────────────────────
function appendLog(msg) {
  const ts = new Date().toLocaleTimeString();
  logOutput.textContent += `[${ts}] ${msg}\n`;
  logOutput.scrollTop = logOutput.scrollHeight;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function formatAngle(value) {
  return value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}°`;
}

function updateAngleReferenceInputs() {
  const cfg = ANGLE_REFERENCE_CONFIG[angleReference] || ANGLE_REFERENCE_CONFIG.cube;
  $$("[data-face-setpoint]").forEach((input) => {
    input.min = String(cfg.min);
    input.max = String(cfg.max);
    input.placeholder = cfg.placeholder;
    if (!input.value) return;
    const value = Number(input.value);
    if (Number.isNaN(value) || value < cfg.min || value > cfg.max) {
      input.value = "";
    }
  });
}

function showTab(tabName) {
  tabButtons.forEach((button) => {
    const isActive = button.dataset.tabButton === tabName;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });

  tabPanels.forEach((panel) => {
    panel.hidden = panel.dataset.tabPanel !== tabName;
  });
}

function renderServoPositions() {
  for (const [face, info] of Object.entries(faceTelemetry)) {
    const el = document.querySelector(`[data-face-pos="${face}"]`);
    const torqueEl = document.querySelector(`[data-face-torque="${face}"]`);
    const currentEl = document.querySelector(`[data-face-current="${face}"]`);
    if (!el) continue;
    if (info.bits === null || info.bits === undefined) {
      el.textContent = "—";
      el.title = "";
    } else if (angleReference === "servo") {
      el.textContent = `${formatAngle(info.servo_degrees)} servo (${formatAngle(info.cube_degrees)} cube)`;
      el.title = `${info.bits} bits`;
    } else {
      el.textContent = `${formatAngle(info.cube_degrees)} cube (${formatAngle(info.servo_degrees)} servo)`;
      el.title = `${info.bits} bits`;
    }
    if (torqueEl) {
      torqueEl.textContent = info.torque_pct_max_1s === null || info.torque_pct_max_1s === undefined
        ? "Torque 3s max: —"
        : `Torque 3s max: ${info.torque_pct_max_1s}%`;
    }
    if (currentEl) {
      currentEl.textContent = info.current_pct_max_1s === null || info.current_pct_max_1s === undefined
        ? "Current 3s max: —"
        : `Current 3s max: ${info.current_pct_max_1s}%`;
    }
  }
}

function setAngleReference(mode, { persist = true } = {}) {
  angleReference = mode === "servo" ? "servo" : "cube";
  Object.entries(ANGLE_REFERENCE_CONFIG).forEach(([key, cfg]) => {
    cfg.button?.classList.toggle("is-active", key === angleReference);
  });
  if (persist) {
    localStorage.setItem(ANGLE_REFERENCE_STORAGE_KEY, angleReference);
  }
  updateAngleReferenceInputs();
  renderServoPositions();
}

function getManualCubeString() {
  return (manualCubeStringInput?.value || "").trim().toUpperCase();
}

function getSelectedCubeString() {
  return getManualCubeString() || detectedCubeString;
}

function validateCubeString(value) {
  if (!value) {
    return { valid: false, message: "Enter a manual cube state or detect one from the cameras." };
  }
  if (value.length !== 54) {
    return { valid: false, message: `Cube string must be 54 characters, got ${value.length}.` };
  }
  for (const ch of value) {
    if (!VALID_CUBE_CHARS.has(ch)) {
      return { valid: false, message: `Unsupported character '${ch}' in cube string.` };
    }
  }
  return { valid: true, message: "" };
}

function setStateBadge(state) {
  if (!stateBadge) return;
  stateBadge.textContent = state;
  stateBadge.className = state === "IDLE" ? "badge" : `badge ${state.toLowerCase()}`;
}

function resetSolveFeedback() {
  if (polling) return;
  setStateBadge("IDLE");
  progressBar.style.width = "0%";
  progressText.textContent = "Idle";
}

function setCubeStringDisplay(text, placeholder = false) {
  cubeStringDisp.textContent = text;
  cubeStringDisp.classList.toggle("is-placeholder", placeholder);
}

function showCubePreviewPlaceholder(message) {
  cubePreview.innerHTML = "";
  const placeholder = document.createElement("div");
  placeholder.className = "review-placeholder";
  placeholder.textContent = message;
  cubePreview.appendChild(placeholder);
}

function setCameraMode(isFrozen) {
  frozen = isFrozen;
  btnUnfreeze.disabled = !isFrozen;
  cam0Img.classList.toggle("frozen", isFrozen);
  cam1Img.classList.toggle("frozen", isFrozen);

  if (isFrozen) {
    const stamp = Date.now();
    cam0Img.src = `/camera/snapshot/0?${stamp}`;
    cam1Img.src = `/camera/snapshot/1?${stamp}`;
    return;
  }

  cam0Img.src = "/video/0";
  cam1Img.src = "/video/1";
}

function resetDetectedState() {
  roiColors = { 0: {}, 1: {} };
  detectedCubeString = "";
  previewColorMap = null;
  resetSolveFeedback();
  showCubePreviewPlaceholder(DETECTION_PREVIEW_PLACEHOLDER);
  setCubeStringDisplay(DETECTION_STRING_PLACEHOLDER, true);
  drawAllROIs();
  updateSolveControls();
}

async function freezeCameraFrames() {
  if (frozen) return;

  const resp = await post("/camera/freeze");
  if (resp.error) {
    throw new Error(resp.error);
  }
  if (resp.status !== "frozen") {
    throw new Error("Unable to freeze camera feeds.");
  }

  setCameraMode(true);
  updateWorkflowGuide();
  appendLog("Camera feeds frozen");
}

function setStepState(stepNumber, text, state) {
  const stepStateEl = STEP_STATES[stepNumber];
  if (stepStateEl) {
    stepStateEl.textContent = text;
    stepStateEl.dataset.state = state;
  }

  const card = document.querySelector(`[data-step-card="${stepNumber}"]`);
  if (card) card.dataset.state = state;

  const overview = document.querySelector(`[data-overview-step="${stepNumber}"]`);
  if (overview) overview.dataset.state = state;
}

function updateWorkflowGuide(validation = null) {
  const manual = getManualCubeString();
  const selected = manual || detectedCubeString;
  const currentValidation = validation || validateCubeString(selected);
  const hasDetectedState = Boolean(detectedCubeString);
  const hasManualState = Boolean(manual);
  const solveReady = currentValidation.valid;
  const currentState = stateBadge ? (stateBadge.textContent || "IDLE") : "IDLE";

  if (captureStatus) {
    captureStatus.textContent = frozen ? "Frozen capture" : "Live video";
    captureStatus.dataset.state = frozen ? "done" : "active";
  }

  if (roiStatus) {
    roiStatus.textContent = roisUnlocked ? "ROIs unlocked" : "ROIs locked";
    roiStatus.dataset.state = roisUnlocked
      ? "active"
      : (frozen || hasDetectedState || solveReady || currentState === "DONE" ? "done" : "pending");
  }

  if (workflowSummary) {
    if (currentState === "DONE") {
      workflowSummary.textContent = "Solve complete. You can resume live video for a new cube or keep refining the cube state.";
    } else if (currentState === "ERROR") {
      workflowSummary.textContent = "The solve flow hit an error. Review the cube state and try again.";
    } else if (polling) {
      workflowSummary.textContent = "Step 4: solving in progress. Follow the progress bar below.";
    } else if (solveReady) {
      workflowSummary.textContent = hasManualState
        ? "Step 4: manual cube state is ready. Start the solve when you are satisfied."
        : "Step 4: detected cube state is ready. Start the solve when you are satisfied.";
    } else if (hasDetectedState || hasManualState) {
      workflowSummary.textContent = "Step 3: review the cube state. Click stickers or edit the text box until it looks right.";
    } else if (frozen) {
      workflowSummary.textContent = "Step 2: frame captured. Detect colors again or resume live video.";
    } else if (roisUnlocked) {
      workflowSummary.textContent = "Step 1: drag the ROI boxes into place, then click Detect Colors.";
    } else {
      workflowSummary.textContent = "Step 2: click Detect Colors to capture the current frame.";
    }
  }

  let step1State = "optional";
  let step1Text = "Optional";
  if (roisUnlocked) {
    step1State = "active";
    step1Text = "Editing";
  } else if (frozen || hasDetectedState || solveReady || currentState === "DONE") {
    step1State = "done";
    step1Text = "Ready";
  }
  setStepState(1, step1Text, step1State);

  let step2State = "active";
  let step2Text = "Ready";
  if (hasDetectedState) {
    step2State = "done";
    step2Text = "Detected";
  } else if (frozen) {
    step2Text = "Captured";
  }
  setStepState(2, step2Text, step2State);

  let step3State = "pending";
  let step3Text = "Waiting";
  if (hasManualState) {
    step3State = currentValidation.valid ? "done" : "active";
    step3Text = currentValidation.valid ? "Manual override" : "Needs edit";
  } else if (hasDetectedState) {
    step3State = solveReady ? "done" : "active";
    step3Text = solveReady ? "Reviewed" : "Review";
  }
  setStepState(3, step3Text, step3State);

  let step4State = "pending";
  let step4Text = "Blocked";
  if (currentState === "DONE") {
    step4State = "done";
    step4Text = "Complete";
  } else if (currentState === "ERROR") {
    step4State = "error";
    step4Text = "Error";
  } else if (polling) {
    step4State = "active";
    step4Text = "Solving";
  } else if (solveReady) {
    step4State = "active";
    step4Text = "Ready";
  }
  setStepState(4, step4Text, step4State);
}

function updateSolveControls() {
  const manual = getManualCubeString();
  const selected = manual || detectedCubeString;
  const validation = validateCubeString(selected);

  if (cubeStringSource) {
    if (manual) {
      if (validation.valid) {
        cubeStringSource.textContent = "Using manually entered cube state for solve.";
        cubeStringSource.classList.remove("error");
      } else {
        cubeStringSource.textContent = validation.message;
        cubeStringSource.classList.add("error");
      }
    } else if (detectedCubeString) {
      cubeStringSource.textContent = "Using detected cube state for solve.";
      cubeStringSource.classList.remove("error");
    } else {
      cubeStringSource.textContent = "Enter a manual cube state or detect one from the cameras.";
      cubeStringSource.classList.remove("error");
    }
  }

  btnSolve.disabled = Boolean(polling) || !validation.valid;
  updateWorkflowGuide(validation);
}

async function post(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return resp.json();
}

function getCurrentRoiSize() {
  const roiList = [...rois[0], ...rois[1]];
  if (!roiList.length) return clampRoiSize(roiSizeSlider?.value);
  const total = roiList.reduce((sum, roi) => sum + Number(roi.w || roi.h || 0), 0);
  return clampRoiSize(total / roiList.length);
}

function clampRoiSize(size) {
  const value = Number(size);
  if (!Number.isFinite(value)) return ROI_SIZE.default;
  return clamp(Math.round(value), ROI_SIZE.min, ROI_SIZE.max);
}

function updateRoiSizeControls() {
  if (!roiSizeSlider || !roiSizeValue) return;
  const size = getCurrentRoiSize();
  roiSizeSlider.min = String(ROI_SIZE.min);
  roiSizeSlider.max = String(ROI_SIZE.max);
  roiSizeSlider.step = "1";
  roiSizeSlider.value = String(size);
  roiSizeValue.textContent = `${size} px`;
}

function getCameraFrameBounds(camId) {
  const img = getImgForCam(camId);
  return {
    width: img.naturalWidth || 640,
    height: img.naturalHeight || 480,
  };
}

function applyRoiSize(size) {
  const nextSize = clampRoiSize(size);

  for (const camId of [0, 1]) {
    const bounds = getCameraFrameBounds(camId);
    rois[camId] = rois[camId].map((roi) => {
      return {
        ...roi,
        w: nextSize,
        h: nextSize,
        // Keep the top-left corner steady; only the bottom-right corner moves.
        x: clamp(roi.x, 0, bounds.width - nextSize),
        y: clamp(roi.y, 0, bounds.height - nextSize),
      };
    });
  }

  drawAllROIs();
  updateRoiSizeControls();
}

async function saveAllROIs() {
  await saveROIs(0);
  await saveROIs(1);
}

// ── ROI Drawing ─────────────────────────────────────────────────────────────
function getCanvasForCam(camId) {
  return camId === 0 ? cam0Canvas : cam1Canvas;
}
function getViewportForCam(camId) {
  return camId === 0 ? cam0Viewport : cam1Viewport;
}
function getImgForCam(camId) {
  return camId === 0 ? cam0Img : cam1Img;
}

function resetCameraInspect(camId) {
  const viewport = getViewportForCam(camId);
  viewport.classList.remove("is-zooming");
  viewport.style.setProperty("--inspect-x", "50%");
  viewport.style.setProperty("--inspect-y", "50%");
}

function updateCameraInspect(camId, event) {
  if (roisUnlocked) return;

  const viewport = getViewportForCam(camId);
  const rect = viewport.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  const xPct = clamp(((event.clientX - rect.left) / rect.width) * 100, 0, 100);
  const yPct = clamp(((event.clientY - rect.top) / rect.height) * 100, 0, 100);

  viewport.style.setProperty("--inspect-x", `${xPct}%`);
  viewport.style.setProperty("--inspect-y", `${yPct}%`);
  viewport.classList.add("is-zooming");
}

function setupCameraInspect(camId) {
  const viewport = getViewportForCam(camId);

  viewport.addEventListener("mouseenter", (event) => {
    updateCameraInspect(camId, event);
  });

  viewport.addEventListener("mousemove", (event) => {
    updateCameraInspect(camId, event);
  });

  viewport.addEventListener("mouseleave", () => {
    resetCameraInspect(camId);
  });
}

function resizeCanvas(camId) {
  const canvas = getCanvasForCam(camId);
  const viewport = getViewportForCam(camId);
  canvas.width = viewport.clientWidth;
  canvas.height = viewport.clientHeight;
}

function imageToCanvas(camId, ix, iy) {
  // Convert image-space coords to canvas-space coords
  const img = getImgForCam(camId);
  const canvas = getCanvasForCam(camId);
  const imgNat = { w: img.naturalWidth || 640, h: img.naturalHeight || 480 };
  const cw = canvas.width, ch = canvas.height;
  // object-fit: contain scaling
  const scale = Math.min(cw / imgNat.w, ch / imgNat.h);
  const offX = (cw - imgNat.w * scale) / 2;
  const offY = (ch - imgNat.h * scale) / 2;
  return { x: offX + ix * scale, y: offY + iy * scale, scale };
}

function canvasToImage(camId, cx, cy) {
  const img = getImgForCam(camId);
  const canvas = getCanvasForCam(camId);
  const imgNat = { w: img.naturalWidth || 640, h: img.naturalHeight || 480 };
  const cw = canvas.width, ch = canvas.height;
  const scale = Math.min(cw / imgNat.w, ch / imgNat.h);
  const offX = (cw - imgNat.w * scale) / 2;
  const offY = (ch - imgNat.h * scale) / 2;
  return { x: (cx - offX) / scale, y: (cy - offY) / scale };
}

const COLOR_MAP = {
  W: "rgba(255,255,255,0.6)",
  Y: "rgba(240,224,32,0.6)",
  R: "rgba(204,34,34,0.6)",
  O: "rgba(238,136,34,0.6)",
  B: "rgba(34,68,204,0.6)",
  G: "rgba(34,170,68,0.6)",
};
const COLOR_STROKE = {
  W: "#fff", Y: "#cc0", R: "#c22", O: "#e82", B: "#24c", G: "#2a4",
};
const COLOR_TEXT = {
  W: "#222", Y: "#222", R: "#fff", O: "#222", B: "#fff", G: "#fff",
};

function drawDetectedColorLetter(ctx, label, colorKey, x, y, width, height) {
  const boxSize = Math.min(width, height);
  const letterSize = clamp(
    Math.floor(boxSize * ROI_STYLE.letterScale),
    ROI_STYLE.letterMinSize,
    ROI_STYLE.letterMaxSize,
  );

  ctx.save();
  ctx.font = `700 ${letterSize}px monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.lineWidth = ROI_STYLE.detectedLineWidth;
  ctx.strokeStyle = COLOR_TEXT[colorKey] === "#fff" ? "rgba(0,0,0,0.75)" : "rgba(255,255,255,0.85)";
  ctx.fillStyle = COLOR_TEXT[colorKey] || "#fff";
  ctx.strokeText(label, x + width / 2, y + height / 2);
  ctx.fillText(label, x + width / 2, y + height / 2);
  ctx.restore();
}

function drawROIs(camId) {
  const canvas = getCanvasForCam(camId);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  for (const roi of rois[camId]) {
    const tl = imageToCanvas(camId, roi.x, roi.y);
    const br = imageToCanvas(camId, roi.x + roi.w, roi.y + roi.h);
    const rw = br.x - tl.x;
    const rh = br.y - tl.y;

    const colorKey = roiColors[camId][roi.label];
    if (colorKey && COLOR_MAP[colorKey]) {
      ctx.fillStyle = COLOR_MAP[colorKey];
      ctx.fillRect(tl.x, tl.y, rw, rh);
      ctx.strokeStyle = COLOR_STROKE[colorKey];
      ctx.lineWidth = ROI_STYLE.detectedLineWidth;
    } else {
      ctx.strokeStyle = roisUnlocked ? "#0f0" : "rgba(0,255,0,0.5)";
      ctx.lineWidth = roisUnlocked ? ROI_STYLE.editLineWidth : ROI_STYLE.liveLineWidth;
    }
    ctx.strokeRect(tl.x, tl.y, rw, rh);

    if (colorKey && COLOR_MAP[colorKey]) {
      drawDetectedColorLetter(ctx, roi.label, colorKey, tl.x, tl.y, rw, rh);
    } else {
      ctx.fillStyle = "#fff";
      ctx.font = ROI_STYLE.labelFont;
      ctx.fillText(roi.label, tl.x + 2, tl.y + 10);
    }
  }
}

function drawAllROIs() {
  resizeCanvas(0);
  resizeCanvas(1);
  drawROIs(0);
  drawROIs(1);
}

// ── Load default ROIs from server ───────────────────────────────────────────
async function loadROIs() {
  try {
    const resp = await fetch("/rois");
    const data = await resp.json();
    rois[0] = data.cam0 || [];
    rois[1] = data.cam1 || [];
    applyRoiSize(getCurrentRoiSize());
    appendLog(`Loaded ${rois[0].length + rois[1].length} ROIs`);
  } catch (e) {
    appendLog("Failed to load ROIs: " + e);
  }
}

// ── ROI Dragging (when unlocked) ────────────────────────────────────────────
function setupROIDragging(camId) {
  const canvas = getCanvasForCam(camId);

  canvas.addEventListener("mousedown", (e) => {
    if (!roisUnlocked) return;
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const imgPt = canvasToImage(camId, cx, cy);

    // Find which ROI was clicked
    for (let i = rois[camId].length - 1; i >= 0; i--) {
      const r = rois[camId][i];
      if (imgPt.x >= r.x && imgPt.x <= r.x + r.w &&
          imgPt.y >= r.y && imgPt.y <= r.y + r.h) {
        dragging = {
          camId, index: i,
          offsetX: imgPt.x - r.x,
          offsetY: imgPt.y - r.y,
        };
        e.preventDefault();
        return;
      }
    }
  });

  canvas.addEventListener("mousemove", (e) => {
    if (!dragging || dragging.camId !== camId) return;
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const imgPt = canvasToImage(camId, cx, cy);

    const r = rois[camId][dragging.index];
    r.x = Math.round(Math.max(0, imgPt.x - dragging.offsetX));
    r.y = Math.round(Math.max(0, imgPt.y - dragging.offsetY));
    drawROIs(camId);
  });

  canvas.addEventListener("mouseup", () => {
    if (dragging && dragging.camId === camId) {
      dragging = null;
      // Save updated positions
      saveROIs(camId);
    }
  });

  canvas.addEventListener("mouseleave", () => {
    if (dragging && dragging.camId === camId) {
      dragging = null;
      saveROIs(camId);
    }
  });
}

async function saveROIs(camId) {
  try {
    await post("/rois/update", { cam_id: camId, rois: rois[camId] });
  } catch (e) {
    appendLog("ROI save error: " + e);
  }
}

btnUnfreeze.addEventListener("click", () => {
  setCameraMode(false);
  resetDetectedState();
  appendLog("Live video resumed");
});

// ── Detect Colors / Auto Freeze ─────────────────────────────────────────────
btnDetect.addEventListener("click", async () => {
  const captureNewFrame = !frozen;
  btnDetect.disabled = true;

  try {
    if (captureNewFrame) {
      resetDetectedState();
      appendLog("Capturing current camera frames...");
      await freezeCameraFrames();
      appendLog("Detecting colors from the captured frame...");
    } else {
      appendLog("Detecting colors from the frozen frame...");
    }

    const resp = await fetch("/camera/detect");
    const data = await resp.json();
    if (data.error) {
      throw new Error(data.error);
    }

    // Store colors and redraw ROIs with colour fills
    roiColors[0] = data.cam0_colors || {};
    roiColors[1] = data.cam1_colors || {};
    detectedCubeString = data.cube_string || "";
    resetSolveFeedback();
    drawAllROIs();

    // Show cube preview
    showCubePreview(data.cube_string, data.color_map);
    updateSolveControls();
    appendLog("Detected cube: " + detectedCubeString);
  } catch (e) {
    appendLog("Detection error: " + e);
  } finally {
    btnDetect.disabled = false;
  }
});

function showCubePreview(cubeString, colorMap) {
  previewColorMap = colorMap ? { ...colorMap } : null;

  detectedCubeString = buildCubeStringFromColorMap(previewColorMap) || cubeString || "";
  resetSolveFeedback();
  setCubeStringDisplay(detectedCubeString || "Detected cube string will appear here after color detection.");
  updateSolveControls();
  cubePreview.innerHTML = "";

  if (!previewColorMap) {
    showCubePreviewPlaceholder("No color preview is available yet. Paste a cube-state override to solve manually.");
    return;
  }

  for (const face of FACE_ORDER) {
    const wrap = document.createElement("div");
    const title = document.createElement("div");
    title.className = "face-grid-title";
    title.textContent = face;
    wrap.appendChild(title);

    const grid = document.createElement("div");
    grid.className = "face-grid";
    for (let r = 0; r < 3; r++) {
      for (let c = 0; c < 3; c++) {
        const idx = r * 3 + c + 1;
        const label = `${face}${idx}`;
        const fixedColor = FIXED_CENTER_COLORS[label];
        const color = fixedColor || previewColorMap[label] || "X";
        const cell = document.createElement("div");
        cell.className = "facelet color-" + color;
        cell.title = fixedColor ? `${label}: ${color} (fixed center)` : `${label}: ${color}`;
        cell.dataset.label = label;
        cell.dataset.color = color;
        if (fixedColor) {
          previewColorMap[label] = fixedColor;
        } else {
          cell.addEventListener("click", () => cycleFaceletColor(cell));
        }
        grid.appendChild(cell);
      }
    }
    wrap.appendChild(grid);
    cubePreview.appendChild(wrap);
  }
}

function buildCubeStringFromColorMap(colorMap) {
  if (!colorMap) return "";
  let result = "";
  for (const face of FACE_ORDER) {
    for (let idx = 1; idx <= 9; idx++) {
      const label = `${face}${idx}`;
      result += FIXED_CENTER_COLORS[label] || colorMap[label] || "X";
    }
  }
  return result;
}

function getNextColor(color) {
  const pos = CYCLE_COLORS.indexOf(color);
  return pos === -1 ? CYCLE_COLORS[0] : CYCLE_COLORS[(pos + 1) % CYCLE_COLORS.length];
}

function cycleFaceletColor(cell) {
  const label = cell.dataset.label;
  if (!label || !previewColorMap) return;
  if (FIXED_CENTER_COLORS[label]) return;

  const current = previewColorMap[label] || cell.dataset.color || "W";
  const next = getNextColor(current);

  previewColorMap[label] = next;
  cell.dataset.color = next;
  cell.className = "facelet color-" + next;
  cell.title = `${label}: ${next}`;

  detectedCubeString = buildCubeStringFromColorMap(previewColorMap);
  resetSolveFeedback();
  setCubeStringDisplay(detectedCubeString);
  updateSolveControls();
}

manualCubeStringInput?.addEventListener("input", () => {
  resetSolveFeedback();
  updateSolveControls();
});

roiSizeSlider?.addEventListener("input", () => {
  applyRoiSize(roiSizeSlider.value);
});

roiSizeSlider?.addEventListener("change", async () => {
  applyRoiSize(roiSizeSlider.value);
  await saveAllROIs();
  appendLog(`ROI size set to ${roiSizeSlider.value} px`);
});

// ── ROI Unlock toggle ───────────────────────────────────────────────────────
btnRoiUnlock.addEventListener("click", () => {
  roisUnlocked = !roisUnlocked;
  btnRoiUnlock.textContent = roisUnlocked ? "Lock ROIs" : "Unlock ROIs";
  cam0Canvas.classList.toggle("unlocked", roisUnlocked);
  cam1Canvas.classList.toggle("unlocked", roisUnlocked);
  if (roisUnlocked) {
    resetCameraInspect(0);
    resetCameraInspect(1);
  }
  drawAllROIs();
  updateSolveControls();
  appendLog(roisUnlocked ? "ROIs unlocked – drag to reposition" : "ROIs locked");
});
// ── ROI Reset to defaults ───────────────────────────────────────────────────────
btnRoiReset.addEventListener("click", async () => {
  if (!confirm("Reset all ROI positions to defaults?")) return;
  try {
    const resp = await post("/rois/reset");
    rois[0] = resp.cam0 || [];
    rois[1] = resp.cam1 || [];
    applyRoiSize(getCurrentRoiSize());
    updateSolveControls();
    appendLog("ROIs reset to default positions");
  } catch (e) {
    appendLog("ROI reset error: " + e);
  }
});
// ── Manual face rotation ────────────────────────────────────────────────────
$$("[data-move]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const move = btn.dataset.move;
    appendLog(`Manual move: ${move}`);
    btn.disabled = true;
    try {
      const res = await post("/servo/move", { move });
      appendLog(`Move result: ${JSON.stringify(res)}`);
    } catch (e) {
      appendLog(`Move error: ${e}`);
    }
    btn.disabled = false;
  });
});

$$("[data-face-setpoint-btn]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const face = btn.dataset.faceSetpointBtn;
    const input = document.querySelector(`[data-face-setpoint="${face}"]`);
    const raw = input?.value?.trim() || "";
    const degrees = Number(raw);
    const cfg = ANGLE_REFERENCE_CONFIG[angleReference] || ANGLE_REFERENCE_CONFIG.cube;

    if (!raw || Number.isNaN(degrees)) {
      appendLog(`Setpoint error (${face}): enter a ${cfg.label} angle from ${cfg.min} to ${cfg.max}`);
      input?.focus();
      return;
    }
    if (degrees < cfg.min || degrees > cfg.max) {
      appendLog(`Setpoint error (${face}): ${cfg.label} angle must be between ${cfg.min} and ${cfg.max}`);
      input?.focus();
      return;
    }

    appendLog(`Manual ${cfg.label} setpoint: ${face} -> ${degrees}°`);
    btn.disabled = true;
    if (input) input.disabled = true;
    try {
      const res = await post("/servo/setpoint", { face, degrees, reference: angleReference });
      appendLog(`Setpoint result: ${JSON.stringify(res)}`);
      pollServoPositions();
    } catch (e) {
      appendLog(`Setpoint error: ${e}`);
    }
    btn.disabled = false;
    if (input) input.disabled = false;
  });
});

btnAngleRefCube?.addEventListener("click", () => setAngleReference("cube"));
btnAngleRefServo?.addEventListener("click", () => setAngleReference("servo"));

$$("[data-face-setpoint]").forEach((input) => {
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const face = input.dataset.faceSetpoint;
    document.querySelector(`[data-face-setpoint-btn="${face}"]`)?.click();
  });
});

// ── Scramble ────────────────────────────────────────────────────────────────
btnScramble.addEventListener("click", async () => {
  appendLog("Scrambling cube (random sequence)...");
  btnScramble.disabled = true;
  try {
    const res = await post("/servo/scramble");
    appendLog(`Scramble: ${JSON.stringify(res)}`);
    startPolling();
  } catch (e) {
    appendLog(`Scramble error: ${e}`);
  }
  btnScramble.disabled = false;
});

// ── Ping ────────────────────────────────────────────────────────────────────
btnPing.addEventListener("click", async () => {
  const resp = await fetch("/servo/ping");
  const data = await resp.json();
  appendLog("Ping: " + JSON.stringify(data));
});

// ── Refresh Cameras ─────────────────────────────────────────────────────────
btnRefreshCams.addEventListener("click", async () => {
  appendLog("Refreshing cameras...");
  btnRefreshCams.disabled = true;
  try {
    const res = await post("/camera/refresh");
    if (res.error) {
      appendLog("Refresh error: " + res.error);
    } else {
      appendLog("Cameras refreshed: " + JSON.stringify(res.cameras));
      // Reload live feeds
      cam0Img.src = "/video/0?" + Date.now();
      cam1Img.src = "/video/1?" + Date.now();
    }
  } catch (e) {
    appendLog("Refresh error: " + e);
  }
  btnRefreshCams.disabled = false;
});

// ── Torque ──────────────────────────────────────────────────────────────────
btnTorqueOn.addEventListener("click", async () => {
  await post("/servo/torque", { all: true, on: true });
  appendLog("Torque ON (all)");
});
btnTorqueOff.addEventListener("click", async () => {
  await post("/servo/torque", { all: true, on: false });
  appendLog("Torque OFF (all)");
});

// ── Home ────────────────────────────────────────────────────────────────────
btnHome.addEventListener("click", async () => {
  appendLog("Homing all servos...");
  const res = await post("/servo/home");
  appendLog("Home: " + JSON.stringify(res));
});

// ── Emergency stop ─────────────────────────────────────────────────────────
btnEmergencyStop?.addEventListener("click", async () => {
  appendLog("EMERGENCY STOP requested");
  btnEmergencyStop.disabled = true;
  try {
    const res = await post("/emergency-stop");
    appendLog("Emergency stop: " + JSON.stringify(res));
    setStateBadge("IDLE");
    resetSolveFeedback();
    stopPolling();
    updateWorkflowGuide();
  } catch (e) {
    appendLog("Emergency stop error: " + e);
  }
  btnEmergencyStop.disabled = false;
});

// ── Solve ───────────────────────────────────────────────────────────────────
btnSolve.addEventListener("click", async () => {
  const cubeString = getSelectedCubeString();
  const validation = validateCubeString(cubeString);
  if (!validation.valid) {
    appendLog(validation.message);
    return;
  }
  appendLog(`Starting solve with ${getManualCubeString() ? "manual" : "detected"} state: ${cubeString}`);
  const res = await post("/solve", { cube_string: cubeString });
  appendLog("Server: " + JSON.stringify(res));
  startPolling();
});

// ── Abort ───────────────────────────────────────────────────────────────────
btnAbort.addEventListener("click", async () => {
  appendLog("Requesting abort...");
  await post("/abort");
});

// ── Status polling ──────────────────────────────────────────────────────────
function startPolling() {
  if (polling) return;
  updateSolveControls();
  setStateBadge("RUNNING");
  progressText.textContent = "RUNNING — waiting for status...";
  updateWorkflowGuide();
  btnSolve.disabled = true;
  btnAbort.disabled = false;
  polling = setInterval(pollStatus, 500);
}

function stopPolling() {
  if (polling) { clearInterval(polling); polling = null; }
  btnAbort.disabled = true;
  updateSolveControls();
}

async function pollStatus() {
  try {
    const resp = await fetch("/status");
    const d = await resp.json();
    const pct = d.total_actions
      ? Math.round((d.completed_actions / d.total_actions) * 100)
      : 0;
    progressBar.style.width = pct + "%";
    progressText.textContent =
      `${d.state} — Move ${d.completed_moves}/${d.total_moves} ` +
      `(action ${d.completed_actions}/${d.total_actions}) — ${d.current_move}`;

    setStateBadge(d.state);
    updateWorkflowGuide();

    if (["DONE", "ERROR", "IDLE"].includes(d.state)) {
      if (d.error) appendLog("Error: " + d.error);
      if (d.state === "DONE") appendLog("Solve complete!" + (d.solution ? ` (${d.solution})` : ""));
      stopPolling();
    }
  } catch (e) {
    appendLog("Poll error: " + e);
  }
}

// ── Window resize → redraw ──────────────────────────────────────────────────
window.addEventListener("resize", drawAllROIs);

tabButtons.forEach((button) => {
  button.addEventListener("click", () => showTab(button.dataset.tabButton));
});

// ── Servo live telemetry ────────────────────────────────────────────────────
async function pollServoPositions() {
  try {
    const resp = await fetch("/servo/positions");
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.error) return;
    faceTelemetry = data.faces || {};
    renderServoPositions();
    if (totalCurrentDisplay) {
      totalCurrentDisplay.textContent = data.total_current_a_max_5s === null || data.total_current_a_max_5s === undefined
        ? "Total current 3s max: —"
        : `Total current 3s max: ${data.total_current_a_max_5s.toFixed(3)} A`;
    }
  } catch (_) {
    // silently ignore – servos may not be connected
  }
}
setInterval(pollServoPositions, 500);
pollServoPositions();

// ── Init ────────────────────────────────────────────────────────────────────
showTab("solver");
setAngleReference(localStorage.getItem(ANGLE_REFERENCE_STORAGE_KEY) || "cube", { persist: false });
setupCameraInspect(0);
setupCameraInspect(1);
setupROIDragging(0);
setupROIDragging(1);
loadROIs();
showCubePreviewPlaceholder(
  DETECTION_PREVIEW_PLACEHOLDER
);
setCubeStringDisplay(DETECTION_STRING_PLACEHOLDER, true);
updateRoiSizeControls();
updateSolveControls();
