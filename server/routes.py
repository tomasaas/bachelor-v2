"""
Flask routes – dashboard, camera streams, solve endpoint, status.
"""

from __future__ import annotations

from collections import deque
import logging
import random
import threading
import time

import cv2
import numpy as np
from flask import Blueprint, Response, jsonify, render_template, request

import config
from motion.moves import manual_move_actions, parse_solution, solution_to_actions
from motion.scheduler import Scheduler, SchedulerState

log = logging.getLogger(__name__)
bp = Blueprint("main", __name__)

# ── shared state (set by run.py at startup) ──────────────────────────────────
_dual_camera = None   # vision.camera.DualCamera
_servo_group = None   # motion.servo_bus.ServoGroup
_scheduler: Scheduler | None = None
_solve_thread: threading.Thread | None = None

# Frozen snapshots (stored as numpy arrays)
_frozen_frames: dict[int, np.ndarray | None] = {0: None, 1: None}
_is_frozen = False

# Runtime ROI positions (start from config, can be updated by user)
_runtime_rois: dict[int, list] = {0: [], 1: []}
_rois_initialized = False

# Lightweight progress tracker
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

_face_telemetry_history = {
    face: {
        "torque_pct": deque(),
        "current_pct": deque(),
    }
    for face in config.FACE_SERVO
}
_total_current_history = deque()


def _is_scheduler_busy() -> bool:
    return _scheduler is not None and _scheduler.progress.state == SchedulerState.RUNNING


def _is_busy() -> bool:
    return _progress.get("state") == "RUNNING" or _is_scheduler_busy()


def _prune_history(history: deque, window_s: float, now: float) -> None:
    cutoff = now - window_s
    while history and history[0][0] < cutoff:
        history.popleft()


def _record_history(history: deque, value: float | None, window_s: float, now: float) -> float | None:
    _prune_history(history, window_s, now)
    if value is not None:
        history.append((now, value))
    if not history:
        return None
    return round(max(sample for _, sample in history), 3)


def _ensure_rois():
    """Lazily initialise runtime ROI positions from config/auto-generation."""
    global _rois_initialized
    if _rois_initialized:
        return
    from vision.roi import get_rois
    for cam_id in (0, 1):
        roi_objs = get_rois(cam_id)
        _runtime_rois[cam_id] = [
            {"face": r.face, "cam_row": r.cam_row, "cam_col": r.cam_col,
             "x": r.x, "y": r.y, "w": r.w, "h": r.h,
             "label": r.label, "facelet_index": r.facelet_index}
            for r in roi_objs
        ]
    _rois_initialized = True


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


# ── camera freeze / snapshot ─────────────────────────────────────────────────

@bp.route("/camera/freeze", methods=["POST"])
def camera_freeze():
    """Grab a frame from each camera and store it; stop live streaming to client."""
    global _is_frozen
    if _dual_camera is None:
        return jsonify({"error": "Cameras not initialised"}), 503
    frames = _dual_camera.grab_all()
    for i, frame in enumerate(frames):
        _frozen_frames[i] = frame
    _is_frozen = True
    log.info("Camera feeds frozen")
    return jsonify({"status": "frozen"})


@bp.route("/camera/snapshot/<int:cam_id>")
def camera_snapshot(cam_id: int):
    """Return the frozen JPEG frame for the given camera."""
    if cam_id not in (0, 1):
        return "Invalid camera", 400
    frame = _frozen_frames.get(cam_id)
    if frame is None:
        return "No frozen frame", 404
    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(jpeg.tobytes(), mimetype="image/jpeg")


# ── camera refresh ───────────────────────────────────────────────────────────

@bp.route("/camera/refresh", methods=["POST"])
def camera_refresh():
    """Close and re-open all cameras (useful after hot-plug)."""
    if _dual_camera is None:
        return jsonify({"error": "Cameras not initialised"}), 503
    _dual_camera.close_all()
    results = _dual_camera.open_all()
    status = {str(i): ok for i, ok in enumerate(results)}
    log.info("Camera refresh: %s", status)
    return jsonify({"status": "refreshed", "cameras": status})


# ── camera detect (uses frozen frames) ───────────────────────────────────────

@bp.route("/camera/detect")
def camera_detect():
    """Run colour classification on the frozen snapshots."""
    from vision.roi import ROI
    from vision.color import classify_rois, build_cube_state

    _ensure_rois()

    cam0_colors: dict[str, str] = {}
    cam1_colors: dict[str, str] = {}

    for cam_id in (0, 1):
        frame = _frozen_frames.get(cam_id)
        if frame is None:
            log.warning("No frozen frame for camera %d", cam_id)
            continue
        roi_dicts = _runtime_rois[cam_id]
        roi_objs = [
            ROI(face=r["face"], cam_row=r["cam_row"], cam_col=r["cam_col"],
                x=r["x"], y=r["y"], w=r["w"], h=r["h"])
            for r in roi_dicts
        ]
        colors = classify_rois(frame, roi_objs)
        if cam_id == 0:
            cam0_colors = colors
        else:
            cam1_colors = colors

    if not cam0_colors and not cam1_colors:
        return jsonify({"error": "No frames available for detection"})

    try:
        cube_string = build_cube_state(cam0_colors, cam1_colors)
    except Exception as exc:
        return jsonify({"error": str(exc)})

    # Build a unified colour map for the frontend preview
    color_map = {**cam0_colors, **cam1_colors}

    return jsonify({
        "cube_string": cube_string,
        "cam0_colors": cam0_colors,
        "cam1_colors": cam1_colors,
        "color_map": color_map,
    })


# ── ROI endpoints ────────────────────────────────────────────────────────────

@bp.route("/rois")
def get_rois_endpoint():
    """Return current ROI positions for both cameras."""
    _ensure_rois()
    return jsonify({
        "cam0": _runtime_rois[0],
        "cam1": _runtime_rois[1],
    })


@bp.route("/rois/update", methods=["POST"])
def update_rois():
    """Update ROI positions and sizes for a camera after UI adjustment."""
    body = request.get_json(silent=True) or {}
    cam_id = body.get("cam_id")
    new_rois = body.get("rois")
    if cam_id not in (0, 1) or not isinstance(new_rois, list):
        return jsonify({"error": "Invalid payload"}), 400

    _ensure_rois()

    # Update positions and size from the client data.
    for i, r in enumerate(new_rois):
        if i < len(_runtime_rois[cam_id]):
            _runtime_rois[cam_id][i]["x"] = int(r.get("x", _runtime_rois[cam_id][i]["x"]))
            _runtime_rois[cam_id][i]["y"] = int(r.get("y", _runtime_rois[cam_id][i]["y"]))
            _runtime_rois[cam_id][i]["w"] = int(r.get("w", _runtime_rois[cam_id][i]["w"]))
            _runtime_rois[cam_id][i]["h"] = int(r.get("h", _runtime_rois[cam_id][i]["h"]))

    # Persist to disk so positions survive server restarts
    from vision.roi import save_rois
    save_rois(_runtime_rois[0], _runtime_rois[1])

    log.info("ROIs updated for camera %d", cam_id)
    return jsonify({"status": "ok"})


@bp.route("/rois/reset", methods=["POST"])
def reset_rois():
    """Reset ROI positions to auto-generated defaults and delete saved file."""
    global _rois_initialized
    from vision.roi import get_default_rois, delete_saved_rois

    delete_saved_rois()

    for cam_id in (0, 1):
        roi_objs = get_default_rois(cam_id)
        _runtime_rois[cam_id] = [
            {"face": r.face, "cam_row": r.cam_row, "cam_col": r.cam_col,
             "x": r.x, "y": r.y, "w": r.w, "h": r.h,
             "label": r.label, "facelet_index": r.facelet_index}
            for r in roi_objs
        ]
    _rois_initialized = True
    log.info("ROIs reset to defaults")
    return jsonify({
        "status": "reset",
        "cam0": _runtime_rois[0],
        "cam1": _runtime_rois[1],
    })


# ── solve endpoint ───────────────────────────────────────────────────────────

@bp.route("/solve", methods=["POST"])
def solve():
    global _solve_thread

    if _is_busy():
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
            if not cs:
                cs = _detect_cube()

            log.info("Cube string: %s", cs)
            _progress["current_move"] = "solving"

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

            tokens = parse_solution(solution)
            action_groups = solution_to_actions(solution)
            _progress["total_moves"] = len(tokens)
            _progress["total_actions"] = sum(len(g) for g in action_groups)

            if _scheduler:
                ok = _scheduler.execute(action_groups, tokens)
                if not ok:
                    sched_state = _scheduler.progress.state.name
                    _progress["state"] = sched_state
                    _progress["error"] = _scheduler.progress.error
                    _progress["current_move"] = ""
                    return
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
        d = _scheduler.progress.as_dict()
        if _progress.get("solution"):
            d["solution"] = _progress["solution"]

        # If solve failed (or is still solving) before scheduler execution
        # started, scheduler remains IDLE; expose pipeline progress instead.
        if d.get("state") == "IDLE" and _progress.get("state") in {
            "RUNNING", "ERROR", "DONE", "ABORTING"
        }:
            return jsonify(_progress)

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


# ── servo utilities ──────────────────────────────────────────────────────────

@bp.route("/servo/ping")
def servo_ping():
    if _servo_group is None:
        return jsonify({"error": "Servos not initialised"}), 503
    results = _servo_group.ping_all()
    return jsonify({str(k): v for k, v in results.items()})


@bp.route("/servo/positions")
def servo_positions():
    """Read current servo telemetry for every face."""
    if _servo_group is None:
        return jsonify({"error": "Servos not initialised"}), 503
    now = time.monotonic()
    faces = {}
    total_current_a = 0.0
    for face, sid in config.FACE_SERVO.items():
        servo = _servo_group[sid]
        bits = servo.read_position()
        degrees = round(bits / config.STEPS_PER_DEGREE, 1) if bits is not None else None
        load_raw = servo.read_load()
        current_raw = servo.read_current()
        torque_pct = servo.load_raw_to_percent(load_raw)
        current_a = servo.current_raw_to_amps(current_raw)
        current_pct = servo.current_raw_to_percent(current_raw)

        torque_pct_max_1s = _record_history(
            _face_telemetry_history[face]["torque_pct"],
            torque_pct,
            config.FACE_TELEMETRY_WINDOW_S,
            now,
        )
        current_pct_max_1s = _record_history(
            _face_telemetry_history[face]["current_pct"],
            current_pct,
            config.FACE_TELEMETRY_WINDOW_S,
            now,
        )

        if current_a is not None:
            total_current_a += current_a

        faces[face] = {
            "bits": bits,
            "degrees": degrees,
            "torque_pct_max_1s": torque_pct_max_1s,
            "current_pct_max_1s": current_pct_max_1s,
            "current_a": current_a,
        }

    total_current_a_max_5s = _record_history(
        _total_current_history,
        round(total_current_a, 3),
        config.TOTAL_CURRENT_WINDOW_S,
        now,
    )

    return jsonify({
        "faces": faces,
        "total_current_a": round(total_current_a, 3),
        "total_current_a_max_5s": total_current_a_max_5s,
    })


@bp.route("/servo/home", methods=["POST"])
def servo_home():
    if _servo_group is None:
        return jsonify({"error": "Servos not initialised"}), 503
    _servo_group.all_home(home=config.POS_HOME, speed=config.MOVE_SPEED)
    return jsonify({"status": "homed", "home_bits": config.POS_HOME})


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


# ── single manual move ──────────────────────────────────────────────────────

@bp.route("/servo/move", methods=["POST"])
def servo_move():
    """Execute a single Rubik's move (e.g. "R", "U'"). Runs sequentially."""
    if _servo_group is None:
        return jsonify({"error": "Servos not initialised"}), 503
    if _is_busy():
        return jsonify({"error": "Busy – wait for current operation"}), 409

    body = request.get_json(silent=True) or {}
    move = body.get("move", "")
    if not move:
        return jsonify({"error": "Missing 'move'"}), 400

    try:
        actions = manual_move_actions(move)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    def _run_move():
        global _progress
        _progress = {
            "state": "RUNNING", "error": "", "solution": "",
            "total_moves": 1, "completed_moves": 0,
            "total_actions": len(actions), "completed_actions": 0,
            "current_move": move,
        }
        try:
            if _scheduler is not None:
                ok = _scheduler.execute([actions], [move])
                sched = _scheduler.progress
                _progress.update({
                    "state": sched.state.name,
                    "error": sched.error,
                    "total_moves": sched.total_moves,
                    "completed_moves": sched.completed_moves,
                    "total_actions": sched.total_actions,
                    "completed_actions": sched.completed_actions,
                    "current_move": sched.current_move,
                })
                if not ok:
                    return
            else:
                for action in actions:
                    if action.move_degrees is None:
                        raise RuntimeError("Manual move actions must be degree-based moves")
                    _servo_group.step_servo(
                        action.servo_id,
                        action.move_degrees,
                        speed=action.speed,
                        time_ms=action.time_ms,
                        wait=True,
                    )
                    _progress["completed_actions"] += 1
                    if action.settle_ms > 0:
                        time.sleep(action.settle_ms / 1000.0)
                _progress["state"] = "DONE"
                _progress["completed_moves"] = 1
        except Exception as exc:
            log.exception("Manual move error: %s", exc)
            _progress["state"] = "ERROR"
            _progress["error"] = str(exc)
        _progress["current_move"] = ""

    t = threading.Thread(target=_run_move, daemon=True)
    t.start()
    return jsonify({"status": "started", "move": move})


# ── scramble ─────────────────────────────────────────────────────────────────

@bp.route("/servo/scramble", methods=["POST"])
def servo_scramble():
    """Generate a random scramble (20 moves) and execute it sequentially."""
    if _servo_group is None:
        return jsonify({"error": "Servos not initialised"}), 503
    if _is_busy():
        return jsonify({"error": "Busy"}), 409

    faces = list(config.FACE_SERVO.keys())
    suffixes = ["", "'", "2"]
    scramble_tokens = []
    last_face = ""
    for _ in range(20):
        face = random.choice([f for f in faces if f != last_face])
        suffix = random.choice(suffixes)
        scramble_tokens.append(face + suffix)
        last_face = face

    scramble_string = " ".join(scramble_tokens)
    log.info("Scramble: %s", scramble_string)

    def _run_scramble():
        global _progress
        _progress = {
            "state": "RUNNING", "error": "", "solution": "",
            "total_moves": len(scramble_tokens), "completed_moves": 0,
            "total_actions": 0, "completed_actions": 0,
            "current_move": "scrambling",
        }
        try:
            action_groups = solution_to_actions(scramble_string)
            _progress["total_actions"] = sum(len(g) for g in action_groups)
            if _scheduler:
                _scheduler.execute(action_groups, scramble_tokens)
            _progress["state"] = "DONE"
            _progress["completed_moves"] = len(scramble_tokens)
            _progress["completed_actions"] = _progress["total_actions"]
        except Exception as exc:
            log.exception("Scramble error: %s", exc)
            _progress["state"] = "ERROR"
            _progress["error"] = str(exc)
        _progress["current_move"] = ""

    t = threading.Thread(target=_run_scramble, daemon=True)
    t.start()
    return jsonify({"status": "scrambling", "sequence": scramble_string})
