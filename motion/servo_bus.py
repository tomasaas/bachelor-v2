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

    def __getitem__(self, servo_id: int) -> Servo:
        return self.servos[servo_id]

    def initialize(self) -> None:
        """
        Run the full startup sequence:
        1. Ping all servos (warn if serial forwarding appears inactive).
        2. Set servo (position) mode on every servo.
        3. Enable torque on every servo.
        4. Home all servos to centre position (512).
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

        # 4. Home all servos so they start at a known centre position
        log.info("Homing all servos to position %d…", config.POS_HOME)
        self.all_home(home=config.POS_HOME, speed=config.MOVE_SPEED)

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

    def all_home(self, home: int = 512, speed: int = 1500) -> None:
        """Move all servos to home position."""
        for s in self.servos.values():
            s.move_to(home, speed, time_ms=config.MOVE_TIME_MS)
        # Wait for all to finish
        for s in self.servos.values():
            s.wait_until_stopped()

    def emergency_stop(self) -> None:
        """Immediately disable torque on all servos."""
        log.warning("EMERGENCY STOP – all torque off")
        for s in self.servos.values():
            s.torque_off()
