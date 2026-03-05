"""
Flask routes – dashboard, camera streams, solve endpoint, status.
"""

from __future__ import annotations

import logging
import threading

from flask import Blueprint, Response, jsonify, render_template, request

import config
from motion.moves import parse_solution, solution_to_actions
from motion.scheduler import Scheduler, SchedulerState

log = logging.getLogger(__name__)
bp = Blueprint("main", __name__)

# ── shared state (set by run.py at startup) ──────────────────────────────────
# These are injected before the first request.
_dual_camera = None   # vision.camera.DualCamera
_servo_group = None   # motion.servo_bus.ServoGroup
_scheduler: Scheduler | None = None
_solve_thread: threading.Thread | None = None

# Lightweight progress tracker – works even without a scheduler.
_progress = {
    "state": "IDLE",
    "error": "",
    "solution": "",
    "total_moves": 0,
    "completed_moves": 0,
    "total_actions": 0,
    "completed_actions": 0,
    "current_move": "",
}


def init_hardware(dual_camera, servo_group, scheduler):
    global _dual_camera, _servo_group, _scheduler
    _dual_camera = dual_camera
    _servo_group = servo_group
    _scheduler = scheduler


# ── pages ────────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("index.html")


# ── camera streams ───────────────────────────────────────────────────────────

@bp.route("/video/<int:cam_id>")
def video_feed(cam_id: int):
    if _dual_camera is None or cam_id not in (0, 1):
        return "Camera not available", 503
    return Response(
        _dual_camera.mjpeg_generator(cam_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ── solve endpoint ───────────────────────────────────────────────────────────

@bp.route("/solve", methods=["POST"])
def solve():
    """
    Full pipeline:  capture → detect → kociemba → execute.
    Accepts optional JSON body ``{"cube_string": "..."}`` to skip vision and
    supply the cube state directly (useful for testing).
    """
    global _solve_thread

    if _progress["state"] == "RUNNING":
        return jsonify({"error": "Solve already in progress"}), 409

    body = request.get_json(silent=True) or {}
    cube_string = body.get("cube_string", "")

    def _run(cs: str):
        global _progress
        _progress = {
            "state": "RUNNING", "error": "", "solution": "",
            "total_moves": 0, "completed_moves": 0,
            "total_actions": 0, "completed_actions": 0,
            "current_move": "detecting" if not cs else "solving",
        }
        try:
            # Step 1: get cube string (vision or supplied)
            if not cs:
                cs = _detect_cube()

            log.info("Cube string: %s", cs)
            _progress["current_move"] = "solving"

            # Step 2: solve
            from solve.solver import solve as kociemba_solve, SolveError
            try:
                solution = kociemba_solve(cs)
            except SolveError as exc:
                log.error("Solve failed: %s", exc)
                _progress["state"] = "ERROR"
                _progress["error"] = str(exc)
                return

            _progress["solution"] = solution
            log.info("Solution: %s", solution)

            # Step 3: convert to actions
            tokens = parse_solution(solution)
            action_groups = solution_to_actions(solution)
            _progress["total_moves"] = len(tokens)
            _progress["total_actions"] = sum(len(g) for g in action_groups)

            # Step 4: execute
            if _scheduler:
                _scheduler.execute(action_groups, tokens)
            else:
                log.warning("No servos – solution computed but cannot execute: %s", solution)
                _progress["completed_moves"] = len(tokens)
                _progress["completed_actions"] = _progress["total_actions"]

            _progress["state"] = "DONE"
            _progress["current_move"] = ""

        except Exception as exc:
            log.exception("Solve pipeline error: %s", exc)
            _progress["state"] = "ERROR"
            _progress["error"] = str(exc)

    _solve_thread = threading.Thread(target=_run, args=(cube_string,), daemon=True)
    _solve_thread.start()

    return jsonify({"status": "started", "cube_string": cube_string or "(detecting)"})


def _detect_cube() -> str:
    """Capture from available cameras, classify ROIs, build cube string."""
    from vision.roi import get_rois
    from vision.color import classify_rois, build_cube_state

    if _dual_camera is None:
        raise RuntimeError("Cameras not initialised – start with cameras or supply a cube_string")

    frames = _dual_camera.grab_all()

    cam0_colors: dict[str, str] = {}
    cam1_colors: dict[str, str] = {}
    available = []
    for i, frame in enumerate(frames):
        if frame is None:
            log.warning("Camera %d returned no frame – skipping", i)
            continue
        rois = get_rois(i)
        colors = classify_rois(frame, rois)
        if i == 0:
            cam0_colors = colors
        else:
            cam1_colors = colors
        available.append(i)

    if not available:
        raise RuntimeError("No cameras returned frames")

    # Both cameras are needed to see all 6 faces
    if len(available) < 2:
        missing_faces = config.CAM1_FACES if 0 in available else config.CAM0_FACES
        raise RuntimeError(
            f"Only camera {available[0]} available – faces {missing_faces} cannot be detected. "
            f"Connect camera {1 - available[0]} or supply a cube_string manually."
        )

    return build_cube_state(cam0_colors, cam1_colors)


# ── status ───────────────────────────────────────────────────────────────────

@bp.route("/status")
def status():
    if _scheduler is not None:
        # Merge scheduler progress with local progress
        d = _scheduler.progress.as_dict()
        if _progress.get("solution"):
            d["solution"] = _progress["solution"]
        return jsonify(d)
    return jsonify(_progress)


# ── abort ────────────────────────────────────────────────────────────────────

@bp.route("/abort", methods=["POST"])
def abort():
    global _progress
    if _scheduler:
        _scheduler.abort()
    _progress["state"] = "IDLE"
    _progress["error"] = ""
    _progress["current_move"] = ""
    return jsonify({"status": "abort_requested"})


# ── servo utilities (for manual testing via GUI) ─────────────────────────────

@bp.route("/servo/ping")
def servo_ping():
    if _servo_group is None:
        return jsonify({"error": "Servos not initialised"}), 503
    results = _servo_group.ping_all()
    return jsonify({str(k): v for k, v in results.items()})


@bp.route("/servo/home", methods=["POST"])
def servo_home():
    if _servo_group is None:
        return jsonify({"error": "Servos not initialised"}), 503
    _servo_group.all_home()
    return jsonify({"status": "homed"})


@bp.route("/servo/torque", methods=["POST"])
def servo_torque():
    """POST JSON: {"id": 1, "on": true}  or  {"all": true, "on": false}"""
    if _servo_group is None:
        return jsonify({"error": "Servos not initialised"}), 503
    body = request.get_json(silent=True) or {}
    on = body.get("on", True)
    if body.get("all"):
        if on:
            _servo_group.all_torque_on()
        else:
            _servo_group.all_torque_off()
    else:
        sid = body.get("id")
        if sid is None:
            return jsonify({"error": "Missing 'id' or 'all'"}), 400
        servo = _servo_group[int(sid)]
        servo.torque_on() if on else servo.torque_off()
    return jsonify({"status": "ok"})
