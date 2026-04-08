"""
High-level servo control built on top of SC09Bus (vendor SDK wrapper).

Provides named operations: torque, set mode, move to position, spin motor,
read feedback — all with logging.

Uses the vendor scscl SDK methods (WritePos, ReadPos, ReadMoving, etc.)
which are proven working from the example scripts.
"""

from __future__ import annotations

import logging
import time

import config
from motion.sc09 import SC09Bus

log = logging.getLogger(__name__)

# Register addresses used for direct register access
# (these match the scscl SDK constants SCSCL_*)
_TORQUE_ENABLE = 40
_LOCK          = 48
_MIN_ANGLE_L   = 9     # 2 bytes – for mode switching via angle limits
_MAX_ANGLE_L   = 11    # 2 bytes
_PRESENT_VOLTAGE     = 62
_PRESENT_TEMPERATURE = 63
_PRESENT_LOAD_L      = 60
_PRESENT_CURRENT_L   = 69
_RUNNING_SPEED_L     = 46


def bits_to_degrees(bits: int) -> float:
    """Convert SC09 position bits to degrees."""
    return bits / config.STEPS_PER_DEGREE


def degrees_to_bits(degrees: float) -> int:
    """Convert degrees to the nearest SC09 position bit value."""
    return int(round(degrees * config.STEPS_PER_DEGREE))


def round_to_nearest_ten(degrees: float) -> int:
    """Round a degree measurement to the nearest 10 degrees."""
    return int(round(degrees / 10.0) * 10)


def quarter_steps_from_degrees(move_degrees: int) -> int:
    """Convert a relative move into quarter-turn steps."""
    move_degrees = int(move_degrees)
    if move_degrees % 90 != 0:
        raise ValueError(
            f"Servo moves must be multiples of 90 degrees, got {move_degrees}"
        )
    return move_degrees // 90


class Servo:
    """Manage a single SC09 servo through the shared bus."""

    def __init__(self, bus: SC09Bus, servo_id: int):
        self.bus = bus
        self.id = servo_id

    # ── torque ───────────────────────────────────────────────────────────

    def torque_on(self) -> bool:
        ok = self.bus.write_u8(self.id, _TORQUE_ENABLE, 1)
        log.info("Servo %d torque ON → %s", self.id, "OK" if ok else "FAIL")
        return ok

    def torque_off(self) -> bool:
        ok = self.bus.write_u8(self.id, _TORQUE_ENABLE, 0)
        log.info("Servo %d torque OFF → %s", self.id, "OK" if ok else "FAIL")
        return ok

    # ── mode ─────────────────────────────────────────────────────────────

    def set_position_mode(self) -> bool:
        """Switch to position servo mode.

        For SCSCL servos, mode is controlled through angle limits:
          min < max  → position (servo) mode
          min == max == 0  → wheel / motor mode
        Register 33 does NOT exist in the SCSCL protocol.
        """
        self.bus.unlock_eprom(self.id)
        ok1 = self.bus.write_u16(self.id, _MIN_ANGLE_L, 0)
        ok2 = self.bus.write_u16(self.id, _MAX_ANGLE_L, 1023)
        self.bus.lock_eprom(self.id)
        ok = ok1 and ok2
        log.info("Servo %d → position mode (angle limits 0-1023): %s",
                 self.id, "OK" if ok else "FAIL")
        return ok

    def set_motor_mode(self) -> bool:
        """Switch to continuous-rotation motor mode.

        Uses the vendor SDK’s PWMMode (sets min/max angle limits to 0).
        """
        self.bus.unlock_eprom(self.id)
        ok1 = self.bus.write_u16(self.id, _MIN_ANGLE_L, 0)
        ok2 = self.bus.write_u16(self.id, _MAX_ANGLE_L, 0)
        self.bus.lock_eprom(self.id)
        ok = ok1 and ok2
        log.info("Servo %d → motor mode (angle limits 0-0): %s",
                 self.id, "OK" if ok else "FAIL")
        return ok

    # ── position-mode moves ──────────────────────────────────────────────

    def move_to(
        self,
        position: int,
        speed: int = 400,
        acceleration: int = 0,
        time_ms: int = 0,
    ) -> bool:
        """
        Move to *position* (0-1023) at *speed*.
        Uses the vendor SDK WritePos (same as read_write.py example).
        Note: speed is a 16-bit register (vendor examples use up to 2400).
        """
        position = max(0, min(1023, position))
        speed = max(0, min(0xFFFF, speed))
        time_ms = max(0, min(0xFFFF, int(time_ms)))
        ok = self.bus.write_pos(self.id, position, time=time_ms, speed=speed)
        log.info(
            "Servo %d move_to pos=%d speed=%d time=%dms → %s",
            self.id, position, speed, time_ms, "OK" if ok else "FAIL",
        )
        return ok

    def wait_until_stopped(self, timeout: float = 3.0, poll_interval: float = 0.05) -> bool:
        """Poll MOVING register until servo stops or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            moving = self.bus.read_moving(self.id)
            if moving is not None and moving == 0:
                return True
            time.sleep(poll_interval)
        log.warning("Servo %d: wait_until_stopped timed out", self.id)
        return False

    # ── motor-mode commands ──────────────────────────────────────────────

    def set_motor_speed(self, speed: int) -> bool:
        """
        Set motor speed.  speed > 0 → CW, speed < 0 → CCW.
        Range: -1023 .. +1023.  0 = stop.
        Bit 10 of the raw register value encodes direction.
        """
        if speed >= 0:
            raw = min(speed, 1023)
        else:
            raw = min(abs(speed), 1023) | 0x0400   # bit 10 = CCW
        ok = self.bus.write_u16(self.id, _RUNNING_SPEED_L, raw)
        log.info("Servo %d motor speed=%d (raw=0x%04X) → %s",
                 self.id, speed, raw, "OK" if ok else "FAIL")
        return ok

    def stop_motor(self) -> bool:
        return self.set_motor_speed(0)

    # ── feedback / status ────────────────────────────────────────────────

    def read_position(self) -> int | None:
        return self.bus.read_pos(self.id)

    def read_position_degrees(self) -> float | None:
        position = self.read_position()
        if position is None:
            return None
        return bits_to_degrees(position)

    def read_speed(self) -> int | None:
        return self.bus.read_speed(self.id)

    def read_load(self) -> int | None:
        return self.bus.read_u16(self.id, _PRESENT_LOAD_L)

    def read_current(self) -> int | None:
        return self.bus.read_u16(self.id, _PRESENT_CURRENT_L)

    def read_voltage(self) -> int | None:
        return self.bus.read_u8(self.id, _PRESENT_VOLTAGE)

    def read_temperature(self) -> int | None:
        return self.bus.read_u8(self.id, _PRESENT_TEMPERATURE)

    def read_status(self) -> dict:
        """Read all feedback registers into a dict."""
        return {
            "id": self.id,
            "position": self.read_position(),
            "speed": self.read_speed(),
            "load": self.read_load(),
            "current": self.read_current(),
            "voltage": self.read_voltage(),
            "temperature": self.read_temperature(),
        }

    @staticmethod
    def load_raw_to_percent(raw: int | None) -> float | None:
        if raw is None:
            return None
        magnitude = raw & 0x03FF
        return min(100.0, round((magnitude / config.SC09_LOAD_RAW_FULL_SCALE) * 100.0, 1))

    @staticmethod
    def current_raw_to_amps(raw: int | None) -> float | None:
        if raw is None:
            return None
        magnitude = raw & 0x7FFF
        return round(magnitude * config.SC09_CURRENT_RAW_TO_A, 3)

    @staticmethod
    def current_raw_to_percent(raw: int | None) -> float | None:
        amps = Servo.current_raw_to_amps(raw)
        if amps is None:
            return None
        return min(100.0, round((amps / config.SC09_LOCKED_ROTOR_CURRENT_A) * 100.0, 1))


class ServoGroup:
    """Convenience wrapper around all 6 cube-face servos."""

    def __init__(self, bus: SC09Bus, ids: list[int] | None = None):
        from config import SERVO_IDS
        self.bus = bus
        self.ids = ids or SERVO_IDS
        self.servos: dict[int, Servo] = {sid: Servo(bus, sid) for sid in self.ids}
        self.logical_states = tuple(config.SERVO_LOGICAL_STATES)
        if not self.logical_states:
            raise ValueError("config.SERVO_LOGICAL_STATES must not be empty")
        self.state_to_index = {
            state: idx for idx, state in enumerate(self.logical_states)
        }
        self.home_state = config.SERVO_HOME_STATE
        if self.home_state not in self.state_to_index:
            raise ValueError(
                f"config.SERVO_HOME_STATE={self.home_state} must exist in "
                f"config.SERVO_LOGICAL_STATES={self.logical_states}"
            )
        self.state_bits: dict[int, dict[int, int]] = {
            sid: self._load_state_bits(sid)
            for sid in self.ids
        }
        self.commanded_states: dict[int, int] = {
            sid: self.home_state for sid in self.ids
        }
        self.commanded_degrees: dict[int, int] = dict(self.commanded_states)

    def __getitem__(self, servo_id: int) -> Servo:
        return self.servos[servo_id]

    def _load_state_bits(self, servo_id: int) -> dict[int, int]:
        raw = config.SERVO_STATE_BITS.get(servo_id)
        if raw is None:
            raise ValueError(f"Missing config.SERVO_STATE_BITS entry for servo {servo_id}")

        state_bits: dict[int, int] = {}
        previous_bits: int | None = None
        previous_state: int | None = None
        for state in self.logical_states:
            if state not in raw:
                raise ValueError(
                    f"Servo {servo_id} is missing calibrated bits for logical {state} degrees"
                )
            bits = int(raw[state])
            if not config.HARD_ANGLE_MIN_BITS <= bits <= config.HARD_ANGLE_MAX_BITS:
                raise ValueError(
                    f"Servo {servo_id} logical {state} target {bits} is outside "
                    f"{config.HARD_ANGLE_MIN_BITS}..{config.HARD_ANGLE_MAX_BITS}"
                )
            if previous_bits is not None and bits <= previous_bits:
                raise ValueError(
                    f"Servo {servo_id} calibrated targets must increase with logical "
                    f"angle: {previous_state}deg={previous_bits}, {state}deg={bits}"
                )
            state_bits[state] = bits
            previous_bits = bits
            previous_state = state
        return state_bits

    def home_targets(self) -> dict[int, int]:
        """Return each servo's calibrated home target."""
        return {
            sid: self.state_bits[sid][self.home_state]
            for sid in self.ids
        }

    def logical_state_for_bits(self, servo_id: int, position_bits: int | None) -> int:
        """Snap raw feedback to the nearest calibrated logical state."""
        if position_bits is None:
            return self.commanded_states.get(servo_id, self.home_state)
        return min(
            self.logical_states,
            key=lambda state: abs(position_bits - self.state_bits[servo_id][state]),
        )

    def current_logical_state(self, servo_id: int) -> int:
        """Return the current logical quarter-turn state from feedback when available."""
        position_bits = self[servo_id].read_position()
        state = self.logical_state_for_bits(servo_id, position_bits)
        self.commanded_states[servo_id] = state
        self.commanded_degrees[servo_id] = state
        return state

    def _state_path(self, current_state: int, target_state: int) -> list[int]:
        if current_state == target_state:
            return []
        current_index = self.state_to_index[current_state]
        target_index = self.state_to_index[target_state]
        step = 1 if target_index > current_index else -1
        return [
            self.logical_states[idx]
            for idx in range(current_index + step, target_index + step, step)
        ]

    def initialize(self) -> None:
        """
        Run the full startup sequence:
        1. Ping all servos (warn if serial forwarding appears inactive).
        2. Set servo (position) mode on every servo.
        3. Enable torque on every servo.
        4. Home all servos
        """
        import config

        # 1. Check connectivity / serial forwarding
        ping_results = self.ping_all()
        alive = [sid for sid, ok in ping_results.items() if ok]
        dead  = [sid for sid, ok in ping_results.items() if not ok]

        if not alive:
            log.warning(
                "ALL servo pings failed – is the Waveshare ESP32 driver "
                "in Serial Forwarding mode?  No servos will respond until "
                "forwarding is enabled on the driver board."
            )
        elif dead:
            log.warning(
                "Servos not responding: %s  (check wiring / IDs)", dead
            )

        # 2. Position (servo) mode
        log.info("Setting all servos to position mode…")
        self.all_to_position_mode()

        # 3. Torque on
        log.info("Enabling torque on all servos…")
        self.all_torque_on()

        # 4. Home all servos so they start at a known calibrated position
        log.info(
            "Homing all servos to logical %d° state using calibrated targets %s…",
            self.home_state,
            self.home_targets(),
        )
        self.all_home(speed=config.MOVE_SPEED)

        log.info(
            "Servo init complete: speed=%d, %d/%d servos alive",
            config.MOVE_SPEED, len(alive), len(self.ids),
        )

    def shutdown(self) -> None:
        """Release torque on all servos (safe state for power-off)."""
        log.info("Releasing torque on all servos…")
        self.all_torque_off()
        self.bus.close()
        log.info("Servo shutdown complete")

    def ping_all(self) -> dict[int, bool]:
        return {sid: self.bus.ping(sid) for sid in self.ids}

    def all_torque_on(self) -> None:
        for s in self.servos.values():
            s.torque_on()

    def all_torque_off(self) -> None:
        for s in self.servos.values():
            s.torque_off()

    def all_to_position_mode(self) -> None:
        for s in self.servos.values():
            s.set_position_mode()

    def all_to_motor_mode(self) -> None:
        for s in self.servos.values():
            s.set_motor_mode()

    def all_home(self, home: int | None = None, speed: int = config.MOVE_SPEED) -> None:
        """Move all servos to their calibrated home position sequentially."""
        for s in self.servos.values():
            target_bits = int(home) if home is not None else self.state_bits[s.id][self.home_state]
            s.move_to(target_bits, speed, time_ms=config.MOVE_TIME_MS)
            s.wait_until_stopped()
            self.commanded_states[s.id] = self.home_state
            self.commanded_degrees[s.id] = self.home_state

    def step_servo(
        self,
        servo_id: int,
        move_degrees: int,
        speed: int | None = None,
        time_ms: int | None = None,
        wait: bool = True,
    ) -> int:
        """Move one servo by a relative logical quarter-turn, using safe hops."""
        servo = self[servo_id]
        current_state = self.current_logical_state(servo_id)
        quarter_steps = quarter_steps_from_degrees(move_degrees)
        if quarter_steps % len(self.logical_states) == 0:
            log.info(
                "Servo %d move=%ddeg is a no-op at logical %ddeg",
                servo_id,
                move_degrees,
                current_state,
            )
            return current_state

        current_index = self.state_to_index[current_state]
        target_state = self.logical_states[
            (current_index + quarter_steps) % len(self.logical_states)
        ]
        state_path = self._state_path(current_state, target_state)
        move_speed = speed if speed is not None else config.MOVE_SPEED
        move_time_ms = time_ms if time_ms is not None else config.MOVE_TIME_MS

        log.info(
            "Servo %d logical=%ddeg move=%ddeg -> target=%ddeg via %s",
            servo_id,
            current_state,
            move_degrees,
            target_state,
            state_path,
        )

        for hop_index, state in enumerate(state_path, start=1):
            target_bits = self.state_bits[servo_id][state]
            log.info(
                "Servo %d hop %d/%d -> logical %ddeg (%d bits)",
                servo_id,
                hop_index,
                len(state_path),
                state,
                target_bits,
            )
            servo.move_to(
                target_bits,
                speed=move_speed,
                time_ms=move_time_ms,
            )
            if wait or len(state_path) > 1:
                servo.wait_until_stopped()
            self.commanded_states[servo_id] = state
            self.commanded_degrees[servo_id] = state

        return target_state

    def emergency_stop(self) -> None:
        """Immediately disable torque on all servos."""
        log.warning("EMERGENCY STOP – all torque off")
        for s in self.servos.values():
            s.torque_off()
