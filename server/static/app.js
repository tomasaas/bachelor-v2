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
const btnRefreshCams = $("#btn-refresh-cams");
const btnFreeze      = $("#btn-freeze");
const btnUnfreeze    = $("#btn-unfreeze");
const btnDetect    = $("#btn-detect");
const btnRoiUnlock = $("#btn-roi-unlock");
const btnRoiReset  = $("#btn-roi-reset");
const btnSolve     = $("#btn-solve");
const btnAbort     = $("#btn-abort");
const progressBar  = $("#progress-bar");
const progressText = $("#progress-text");
const logOutput    = $("#log-output");
const stateBadge   = $("#state-badge");
const detectionPanel   = $("#detection-panel");
const cubePreview      = $("#cube-preview");
const cubeStringDisp   = $("#cube-string-display");

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
let polling = null;
let dragging = null;                   // { camId, index, offsetX, offsetY }

// ── Helpers ─────────────────────────────────────────────────────────────────
function appendLog(msg) {
  const ts = new Date().toLocaleTimeString();
  logOutput.textContent += `[${ts}] ${msg}\n`;
  logOutput.scrollTop = logOutput.scrollHeight;
}

async function post(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return resp.json();
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
      ctx.lineWidth = 2;
    } else {
      ctx.strokeStyle = roisUnlocked ? "#0f0" : "rgba(0,255,0,0.5)";
      ctx.lineWidth = roisUnlocked ? 2 : 1;
    }
    ctx.strokeRect(tl.x, tl.y, rw, rh);

    // Label
    ctx.fillStyle = "#fff";
    ctx.font = "10px monospace";
    ctx.fillText(roi.label, tl.x + 2, tl.y + 10);
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
    drawAllROIs();
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

// ── Freeze / Unfreeze ───────────────────────────────────────────────────────
btnFreeze.addEventListener("click", async () => {
  try {
    const resp = await post("/camera/freeze");
    if (resp.status === "frozen") {
      frozen = true;
      btnFreeze.disabled = true;
      btnUnfreeze.disabled = false;
      btnDetect.disabled = false;
      cam0Img.classList.add("frozen");
      cam1Img.classList.add("frozen");
      // Switch to frozen snapshot endpoints
      cam0Img.src = "/camera/snapshot/0?" + Date.now();
      cam1Img.src = "/camera/snapshot/1?" + Date.now();
      appendLog("Camera feeds frozen");
    }
  } catch (e) {
    appendLog("Freeze error: " + e);
  }
});

btnUnfreeze.addEventListener("click", () => {
  frozen = false;
  btnFreeze.disabled = false;
  btnUnfreeze.disabled = true;
  btnDetect.disabled = true;
  btnSolve.disabled = true;
  cam0Img.classList.remove("frozen");
  cam1Img.classList.remove("frozen");
  cam0Img.src = "/video/0";
  cam1Img.src = "/video/1";
  detectionPanel.style.display = "none";
  roiColors = { 0: {}, 1: {} };
  detectedCubeString = "";
  drawAllROIs();
  appendLog("Camera feeds unfrozen");
});

// ── Detect Colors ───────────────────────────────────────────────────────────
btnDetect.addEventListener("click", async () => {
  appendLog("Detecting colors from frozen snapshots...");
  try {
    const resp = await fetch("/camera/detect");
    const data = await resp.json();
    if (data.error) {
      appendLog("Detection error: " + data.error);
      return;
    }
    // Store colors and redraw ROIs with colour fills
    roiColors[0] = data.cam0_colors || {};
    roiColors[1] = data.cam1_colors || {};
    detectedCubeString = data.cube_string || "";
    drawAllROIs();

    // Show cube preview
    showCubePreview(data.cube_string, data.color_map);
    btnSolve.disabled = false;
    appendLog("Detected cube: " + detectedCubeString);
  } catch (e) {
    appendLog("Detection error: " + e);
  }
});

function showCubePreview(cubeString, colorMap) {
  detectionPanel.style.display = "block";
  cubeStringDisp.textContent = cubeString || "";
  cubePreview.innerHTML = "";

  if (!colorMap) return;

  const faces = ["U", "R", "F", "D", "L", "B"];
  for (const face of faces) {
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
        const color = colorMap[label] || "X";
        const cell = document.createElement("div");
        cell.className = "facelet color-" + color;
        cell.title = `${label}: ${color}`;
        grid.appendChild(cell);
      }
    }
    wrap.appendChild(grid);
    cubePreview.appendChild(wrap);
  }
}

// ── ROI Unlock toggle ───────────────────────────────────────────────────────
btnRoiUnlock.addEventListener("click", () => {
  roisUnlocked = !roisUnlocked;
  btnRoiUnlock.textContent = roisUnlocked ? "Lock ROIs" : "Unlock ROIs";
  cam0Canvas.classList.toggle("unlocked", roisUnlocked);
  cam1Canvas.classList.toggle("unlocked", roisUnlocked);
  drawAllROIs();
  appendLog(roisUnlocked ? "ROIs unlocked – drag to reposition" : "ROIs locked");
});
// ── ROI Reset to defaults ───────────────────────────────────────────────────────
btnRoiReset.addEventListener("click", async () => {
  if (!confirm("Reset all ROI positions to defaults?")) return;
  try {
    const resp = await post("/rois/reset");
    rois[0] = resp.cam0 || [];
    rois[1] = resp.cam1 || [];
    drawAllROIs();
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

// ── Solve ───────────────────────────────────────────────────────────────────
btnSolve.addEventListener("click", async () => {
  if (!detectedCubeString) {
    appendLog("No cube state detected – freeze and detect first");
    return;
  }
  appendLog("Starting solve with detected state: " + detectedCubeString);
  const res = await post("/solve", { cube_string: detectedCubeString });
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
  btnSolve.disabled = true;
  btnAbort.disabled = false;
  polling = setInterval(pollStatus, 500);
}

function stopPolling() {
  if (polling) { clearInterval(polling); polling = null; }
  btnAbort.disabled = true;
  // Re-enable solve only if we still have a cube string
  if (detectedCubeString) btnSolve.disabled = false;
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

    stateBadge.textContent = d.state;
    stateBadge.className = "badge " + d.state.toLowerCase();

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

// ── Init ────────────────────────────────────────────────────────────────────
setupROIDragging(0);
setupROIDragging(1);
loadROIs();
