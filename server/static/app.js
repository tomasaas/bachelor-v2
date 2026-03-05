// Rubik's Cube Solver – front-end logic

const $ = (sel) => document.querySelector(sel);

const btnSolve     = $("#btn-solve");
const btnAbort     = $("#btn-abort");
const btnHome      = $("#btn-home");
const btnPing      = $("#btn-ping");
const btnTorqueOn  = $("#btn-torque-on");
const btnTorqueOff = $("#btn-torque-off");
const cubeInput    = $("#cube-string");
const progressBar  = $("#progress-bar");
const progressText = $("#progress-text");
const logOutput    = $("#log-output");
const stateBadge   = $("#state-badge");

let polling = null;

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

// ── Solve ───────────────────────────────────────────────────────────────────
btnSolve.addEventListener("click", async () => {
  const cs = cubeInput.value.trim();
  const body = cs ? { cube_string: cs } : {};
  appendLog("Starting solve" + (cs ? ` (manual: ${cs})` : " (camera detection)"));
  const res = await post("/solve", body);
  appendLog(`Server: ${JSON.stringify(res)}`);
  startPolling();
});

// ── Abort ───────────────────────────────────────────────────────────────────
btnAbort.addEventListener("click", async () => {
  appendLog("Requesting abort...");
  await post("/abort");
});

// ── Home ────────────────────────────────────────────────────────────────────
btnHome.addEventListener("click", async () => {
  appendLog("Homing all servos...");
  const res = await post("/servo/home");
  appendLog(`Home: ${JSON.stringify(res)}`);
});

// ── Ping ────────────────────────────────────────────────────────────────────
btnPing.addEventListener("click", async () => {
  const resp = await fetch("/servo/ping");
  const data = await resp.json();
  appendLog(`Ping: ${JSON.stringify(data)}`);
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

// ── Status polling ──────────────────────────────────────────────────────────
function startPolling() {
  if (polling) return;
  btnSolve.disabled = true;
  btnAbort.disabled = false;
  polling = setInterval(pollStatus, 500);
}

function stopPolling() {
  if (polling) { clearInterval(polling); polling = null; }
  btnSolve.disabled = false;
  btnAbort.disabled = true;
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

    if (d.state === "DONE" || d.state === "ERROR" || d.state === "IDLE" || d.state === "ABORTING") {
      if (d.error) appendLog(`Error: ${d.error}`);
      if (d.state === "DONE") appendLog("Solve complete!" + (d.solution ? ` (${d.solution})` : ""));
      stopPolling();
    }
  } catch (e) {
    appendLog(`Poll error: ${e}`);
  }
}
