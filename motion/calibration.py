"""
Servo calibration helpers.

The web UI captures the current physical servo pose as the calibrated logical
90° home state, derives the other legal quarter-turn targets, and writes the
resulting ``SERVO_STATE_BITS`` table back to config.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

import config


CONFIG_PATH = Path(config.__file__).resolve()


def derive_state_bits_from_home(
    home_bits_by_servo: dict[int, int],
    *,
    logical_states: tuple[int, ...] | None = None,
    home_state: int | None = None,
    baseline_state_bits: dict[int, dict[int, int]] | None = None,
) -> dict[int, dict[int, int]]:
    """Derive legal quarter-turn bit targets from measured home positions."""
    states = tuple(logical_states or config.SERVO_LOGICAL_STATES)
    if not states:
        raise ValueError("SERVO_LOGICAL_STATES must not be empty")

    calibrated_home = config.SERVO_HOME_STATE if home_state is None else home_state
    if calibrated_home not in states:
        raise ValueError(f"Home state {calibrated_home} must exist in {states}")

    home_index = states.index(calibrated_home)
    baseline = baseline_state_bits if baseline_state_bits is not None else config.SERVO_STATE_BITS
    calibrated: dict[int, dict[int, int]] = {}

    for servo_id in sorted(home_bits_by_servo):
        home_bits = int(round(home_bits_by_servo[servo_id]))
        _validate_home_bits_for_baseline(servo_id, home_bits, states, calibrated_home, baseline)
        state_bits = _derive_from_baseline(servo_id, home_bits, states, calibrated_home, baseline)
        if state_bits is None:
            state_bits = _derive_uniform_state_bits(home_bits, states, home_index)
        _validate_state_bits(servo_id, state_bits, states)
        calibrated[servo_id] = state_bits

    return calibrated


def _validate_home_bits_for_baseline(
    servo_id: int,
    home_bits: int,
    states: tuple[int, ...],
    home_state: int,
    baseline: dict[int, dict[int, int]],
) -> None:
    home_range = _home_bits_range_for_baseline(servo_id, states, home_state, baseline)
    if home_range is None:
        return

    min_home_bits, max_home_bits = home_range
    if min_home_bits <= home_bits <= max_home_bits:
        return

    face = config.SERVO_FACE.get(servo_id, "?")
    raise ValueError(
        f"Face {face} / servo {servo_id} reads {_format_servo_degrees(home_bits)} servo, "
        f"but logical {home_state}deg home must be between "
        f"{_format_servo_degrees(min_home_bits)} and {_format_servo_degrees(max_home_bits)} "
        "servo so the derived 0/180/270deg positions stay inside servo limits. "
        f"Place this face horizontally near its logical {home_state}deg home and calibrate again."
    )


def _home_bits_range_for_baseline(
    servo_id: int,
    states: tuple[int, ...],
    home_state: int,
    baseline: dict[int, dict[int, int]],
) -> tuple[int, int] | None:
    existing = baseline.get(servo_id)
    if existing is None or home_state not in existing:
        return None
    if any(state not in existing for state in states):
        return None

    existing_home = int(existing[home_state])
    offsets = [int(existing[state]) - existing_home for state in states]
    min_home_bits = max(config.HARD_ANGLE_MIN_BITS - offset for offset in offsets)
    max_home_bits = min(config.HARD_ANGLE_MAX_BITS - offset for offset in offsets)
    return min_home_bits, max_home_bits


def _derive_from_baseline(
    servo_id: int,
    home_bits: int,
    states: tuple[int, ...],
    home_state: int,
    baseline: dict[int, dict[int, int]],
) -> dict[int, int] | None:
    existing = baseline.get(servo_id)
    if existing is None or home_state not in existing:
        return None
    if any(state not in existing for state in states):
        return None

    existing_home = int(existing[home_state])
    return {
        state: home_bits + (int(existing[state]) - existing_home)
        for state in states
    }


def _derive_uniform_state_bits(
    home_bits: int,
    states: tuple[int, ...],
    home_index: int,
) -> dict[int, int]:
    before_home = home_index
    after_home = len(states) - home_index - 1
    quarter_bits = int(round(90 * config.STEPS_PER_DEGREE))
    max_step = quarter_bits
    if before_home:
        max_step = min(max_step, (home_bits - config.HARD_ANGLE_MIN_BITS) // before_home)
    if after_home:
        max_step = min(max_step, (config.HARD_ANGLE_MAX_BITS - home_bits) // after_home)
    if max_step <= 0:
        raise ValueError(f"Cannot derive calibration around home position {home_bits} bits")

    return {
        state: home_bits + ((idx - home_index) * max_step)
        for idx, state in enumerate(states)
    }


def _format_servo_degrees(bits: int) -> str:
    return f"{bits / config.STEPS_PER_DEGREE:.1f}deg"


def save_servo_state_bits(
    state_bits: dict[int, dict[int, int]],
    *,
    path: Path | str = CONFIG_PATH,
) -> None:
    """Replace the SERVO_STATE_BITS assignment in config.py."""
    config_path = Path(path)
    source = config_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assignment = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "SERVO_STATE_BITS" for target in node.targets):
            assignment = node
            break

    if assignment is None or assignment.end_lineno is None:
        raise ValueError(f"Could not find SERVO_STATE_BITS assignment in {config_path}")

    replacement = f"SERVO_STATE_BITS = {_format_state_bits(state_bits)}\n"
    lines = source.splitlines(keepends=True)
    lines[assignment.lineno - 1:assignment.end_lineno] = [replacement]
    config_path.write_text("".join(lines), encoding="utf-8")


def _validate_state_bits(
    servo_id: int,
    state_bits: dict[int, int],
    states: tuple[int, ...],
) -> None:
    previous_bits: int | None = None
    previous_state: int | None = None

    for state in states:
        bits = int(state_bits[state])
        if not config.HARD_ANGLE_MIN_BITS <= bits <= config.HARD_ANGLE_MAX_BITS:
            raise ValueError(
                f"Servo {servo_id} calibration would put logical {state}deg at "
                f"{bits} bits, outside {config.HARD_ANGLE_MIN_BITS}..{config.HARD_ANGLE_MAX_BITS}"
            )
        if previous_bits is not None and bits <= previous_bits:
            raise ValueError(
                f"Servo {servo_id} calibration must increase with logical angle: "
                f"{previous_state}deg={previous_bits}, {state}deg={bits}"
            )
        previous_bits = bits
        previous_state = state


def _format_state_bits(state_bits: dict[int, dict[int, int]]) -> str:
    lines = ["{"]
    for servo_id in sorted(state_bits):
        states = state_bits[servo_id]
        values = ", ".join(
            f"{state}: {int(states[state])}"
            for state in sorted(states)
        )
        face = config.SERVO_FACE.get(servo_id, "")
        comment = f"   # {face}" if face else ""
        lines.append(f"    {servo_id}: {{{values}}},{comment}")
    lines.append("}")
    return "\n".join(lines)
