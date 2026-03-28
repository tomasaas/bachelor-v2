"""
Rubik's move notation -> servo action sequences.

Each Kociemba move token (R, R', R2, U, U', ...) maps to one or more
degree-based servo moves that the scheduler executes sequentially.

The key rule is that a Rubik move should leave the cube in the turned
state. For this direct-drive gripper setup that means we must not
"return home" after every token, because that would undo the move.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import config

log = logging.getLogger(__name__)


@dataclass
class ServoAction:
    """One atomic servo command executed by the scheduler."""
    servo_id: int
    position: int | None = None      # absolute target position (0-1023)
    move_degrees: int | None = None  # relative move from the current position
    speed: int = 400                 # position-mode speed
    time_ms: int = 0                 # position-mode running time override
    settle_ms: int = 300             # wait after issuing this action (ms)


SPEED = config.MOVE_SPEED
TIME_MS = config.MOVE_TIME_MS
SETTLE = config.MOVE_SETTLE_MS


def _face_actions(face: str, new_move: int) -> list[ServoAction]:
    """Build one degree-based move for the given face."""
    sid = config.FACE_SERVO[face]
    return [
        ServoAction(
            servo_id=sid,
            move_degrees=new_move,
            speed=SPEED,
            time_ms=TIME_MS,
            settle_ms=SETTLE,
        ),
    ]


def _quarter_turn_degrees(face: str, clockwise: bool) -> int:
    """
    Return the relative degree move for one quarter turn in Rubik notation.

    FACE_TURN_SIGN lets us calibrate faces whose servo mounting reverses
    the physical interpretation of clockwise vs counter-clockwise.
    """
    sign = config.FACE_TURN_SIGN.get(face, 1)
    base = -90 if clockwise else 90
    return sign * base


# ── public API ───────────────────────────────────────────────────────────────

def parse_solution(solution_string: str) -> list[str]:
    """Parse Kociemba output (space-separated tokens) into a list of move tokens."""
    return solution_string.strip().split()


def _parse_token(token: str) -> tuple[str, str]:
    """Parse a Kociemba token into (face, suffix)."""
    if len(token) == 1:
        face, suffix = token, ""
    elif len(token) == 2:
        face, suffix = token[0], token[1]
    else:
        raise ValueError(f"Unknown move token: {token!r}")
    if face not in config.FACE_SERVO:
        raise ValueError(f"Unknown face: {face!r}")
    if suffix not in ("", "'", "2"):
        raise ValueError(f"Unknown move suffix: {suffix!r}")
    return face, suffix


def move_to_degrees(token: str) -> tuple[str, list[int]]:
    """Convert one move token to relative servo moves in degrees."""
    face, suffix = _parse_token(token)

    if suffix == "":
        return face, [_quarter_turn_degrees(face, clockwise=True)]
    if suffix == "'":
        return face, [_quarter_turn_degrees(face, clockwise=False)]
    return face, [180]


def manual_move_actions(token: str) -> list[ServoAction]:
    """
    Convert one move token to ServoActions for manual / GUI control.

    Manual moves and solver moves intentionally use the exact same turn
    semantics so the GUI, scrambler, and Kociemba execution stay aligned.
    """
    face, degree_moves = move_to_degrees(token)
    actions: list[ServoAction] = []
    for new_move in degree_moves:
        actions.extend(_face_actions(face, new_move))
    return actions


def move_to_actions(token: str) -> list[ServoAction]:
    """
    Convert one Kociemba move token to ServoActions for solver execution.

    For this direct-drive mechanism, returning the servo to home after
    every move would reverse the face turn we just performed, so solver
    execution uses the same relative actions as manual control.
    """
    return manual_move_actions(token)


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
