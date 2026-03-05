"""
Rubik's move notation → servo action sequences.

Each Kociemba move token (R, R', R2, U, U', …) maps to a list of
ServoAction steps that the scheduler executes sequentially.

The default mapping assumes a 6-gripper mechanism where each servo
controls one face.  Position values are relative to HOME and must be
calibrated per-mechanism.  Edit the PROFILES dict below to match your
hardware.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import config

log = logging.getLogger(__name__)


@dataclass
class ServoAction:
    """One atomic servo command executed by the scheduler."""
    servo_id: int
    position: int          # absolute target position (0-1023)
    speed: int = 400       # position-mode speed
    settle_ms: int = 300   # wait after issuing this action (ms)


# ── position profiles (calibrate per-mechanism) ─────────────────────────────

HOME  = config.POS_HOME
Q_CW  = config.POS_QUARTER_CW    # +90° from home
Q_CCW = config.POS_QUARTER_CCW   # –90° from home
HALF  = config.POS_HALF           # +180° from home
SPEED = config.MOVE_SPEED
SETTLE = config.MOVE_SETTLE_MS


def _face_actions(face: str, delta: int) -> list[ServoAction]:
    """
    Build action list for rotating *face* by *delta* position units from home.
    Returns: [move to target, (pause built-in via settle_ms)].
    Caller is responsible for returning to home afterwards if needed.
    """
    sid = config.FACE_SERVO[face]
    target = max(0, min(1023, HOME + delta))
    return [
        ServoAction(servo_id=sid, position=target, speed=SPEED, settle_ms=SETTLE),
    ]


def _face_return_home(face: str) -> list[ServoAction]:
    sid = config.FACE_SERVO[face]
    return [
        ServoAction(servo_id=sid, position=HOME, speed=SPEED, settle_ms=SETTLE),
    ]


# ── public API ───────────────────────────────────────────────────────────────

def parse_solution(solution_string: str) -> list[str]:
    """Parse Kociemba output (space-separated tokens) into a list of move tokens."""
    return solution_string.strip().split()


def move_to_actions(token: str) -> list[ServoAction]:
    """
    Convert one Kociemba move token to a sequence of ServoActions.

    Supported tokens: U U' U2  D D' D2  R R' R2  L L' L2  F F' F2  B B' B2
    """
    if len(token) == 1:
        face, suffix = token, ""
    elif len(token) == 2:
        face, suffix = token[0], token[1]
    else:
        raise ValueError(f"Unknown move token: {token!r}")

    if face not in config.FACE_SERVO:
        raise ValueError(f"Unknown face: {face!r}")

    if suffix == "":
        # Clockwise 90°
        actions = _face_actions(face, Q_CW)
    elif suffix == "'":
        # Counter-clockwise 90°
        actions = _face_actions(face, Q_CCW)
    elif suffix == "2":
        # Half turn (180°)
        actions = _face_actions(face, HALF)
    else:
        raise ValueError(f"Unknown move suffix: {suffix!r}")

    # Return to home after each independent move so the mechanism is ready
    # for the next move on any face.
    actions += _face_return_home(face)
    return actions


def solution_to_actions(solution_string: str) -> list[list[ServoAction]]:
    """
    Full pipeline: Kociemba solution string → list of action groups.
    Each group = one Rubik's move = a sequence of ServoActions.
    """
    tokens = parse_solution(solution_string)
    groups: list[list[ServoAction]] = []
    for tok in tokens:
        groups.append(move_to_actions(tok))
        log.debug("Token %s → %d actions", tok, len(groups[-1]))
    log.info("Solution has %d moves, %d total actions",
             len(groups), sum(len(g) for g in groups))
    return groups
