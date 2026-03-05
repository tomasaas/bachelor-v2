"""
High-level servo control built on top of SC09Bus.

Provides named operations: torque, set mode, move to position, spin motor,
read feedback — all with logging.
"""

from __future__ import annotations

import logging
import struct
import time

from config import Reg
from motion.sc09 import SC09Bus

log = logging.getLogger(__name__)


class Servo:
    """Manage a single SC09 servo through the shared bus."""

    def __init__(self, bus: SC09Bus, servo_id: int):
        self.bus = bus
        self.id = servo_id

    # ── torque ───────────────────────────────────────────────────────────

    def torque_on(self) -> bool:
        resp = self.bus.write_u8(self.id, Reg.TORQUE_ENABLE, 1)
        ok = resp is not None and resp.ok
        log.info("Servo %d torque ON → %s", self.id, "OK" if ok else "FAIL")
        return ok

    def torque_off(self) -> bool:
        resp = self.bus.write_u8(self.id, Reg.TORQUE_ENABLE, 0)
        ok = resp is not None and resp.ok
        log.info("Servo %d torque OFF → %s", self.id, "OK" if ok else "FAIL")
        return ok

    # ── mode ─────────────────────────────────────────────────────────────

    def set_position_mode(self) -> bool:
        """Switch to position servo mode (mode=0). Requires EEPROM unlock."""
        self.bus.write_u8(self.id, Reg.LOCK, 0)       # unlock EEPROM
        resp = self.bus.write_u8(self.id, Reg.MODE, 0)
        self.bus.write_u8(self.id, Reg.LOCK, 1)       # re-lock
        ok = resp is not None and resp.ok
        log.info("Servo %d → position mode: %s", self.id, "OK" if ok else "FAIL")
        return ok

    def set_motor_mode(self) -> bool:
        """Switch to continuous-rotation motor mode (mode=1)."""
        self.bus.write_u8(self.id, Reg.LOCK, 0)
        resp = self.bus.write_u8(self.id, Reg.MODE, 1)
        self.bus.write_u8(self.id, Reg.LOCK, 1)
        ok = resp is not None and resp.ok
        log.info("Servo %d → motor mode: %s", self.id, "OK" if ok else "FAIL")
        return ok

    # ── position-mode moves ──────────────────────────────────────────────

    def move_to(self, position: int, speed: int = 400, acceleration: int = 0) -> bool:
        """
        Move to *position* (0-1023) at *speed* (units/sec).
        Servo must be in position mode with torque on.
        """
        position = max(0, min(1023, position))
        speed = max(0, min(1023, speed))

        if acceleration:
            self.bus.write_u8(self.id, Reg.ACCELERATION, acceleration & 0xFF)

        # Write goal position + speed together (4 bytes starting at GOAL_POSITION_L)
        data = struct.pack("<HH", position, 0)  # position + running_time
        self.bus.write_register(self.id, Reg.GOAL_POSITION_L, data)
        resp = self.bus.write_u16(self.id, Reg.RUNNING_SPEED_L, speed)
        ok = resp is not None and resp.ok
        log.info(
            "Servo %d move_to pos=%d speed=%d → %s",
            self.id, position, speed, "OK" if ok else "FAIL",
        )
        return ok

    def wait_until_stopped(self, timeout: float = 3.0, poll_interval: float = 0.05) -> bool:
        """Poll MOVING register until servo stops or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            moving = self.bus.read_u8(self.id, Reg.MOVING)
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
        resp = self.bus.write_u16(self.id, Reg.RUNNING_SPEED_L, raw)
        ok = resp is not None and resp.ok
        log.info("Servo %d motor speed=%d (raw=0x%04X) → %s", self.id, speed, raw, "OK" if ok else "FAIL")
        return ok

    def stop_motor(self) -> bool:
        return self.set_motor_speed(0)

    # ── feedback / status ────────────────────────────────────────────────

    def read_position(self) -> int | None:
        return self.bus.read_u16(self.id, Reg.PRESENT_POSITION_L)

    def read_speed(self) -> int | None:
        return self.bus.read_u16(self.id, Reg.PRESENT_SPEED_L)

    def read_load(self) -> int | None:
        return self.bus.read_u16(self.id, Reg.PRESENT_LOAD_L)

    def read_voltage(self) -> int | None:
        return self.bus.read_u8(self.id, Reg.PRESENT_VOLTAGE)

    def read_temperature(self) -> int | None:
        return self.bus.read_u8(self.id, Reg.PRESENT_TEMPERATURE)

    def read_status(self) -> dict:
        """Read all feedback registers into a dict."""
        return {
            "id": self.id,
            "position": self.read_position(),
            "speed": self.read_speed(),
            "load": self.read_load(),
            "voltage": self.read_voltage(),
            "temperature": self.read_temperature(),
        }


class ServoGroup:
    """Convenience wrapper around all 6 cube-face servos."""

    def __init__(self, bus: SC09Bus, ids: list[int] | None = None):
        from config import SERVO_IDS
        self.bus = bus
        self.ids = ids or SERVO_IDS
        self.servos: dict[int, Servo] = {sid: Servo(bus, sid) for sid in self.ids}

    def __getitem__(self, servo_id: int) -> Servo:
        return self.servos[servo_id]

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

    def all_home(self, home: int = 512, speed: int = 300) -> None:
        """Move all servos to home position."""
        for s in self.servos.values():
            s.move_to(home, speed)
        # Wait for all to finish
        for s in self.servos.values():
            s.wait_until_stopped()

    def emergency_stop(self) -> None:
        """Immediately disable torque on all servos."""
        log.warning("EMERGENCY STOP – all torque off")
        for s in self.servos.values():
            s.torque_off()
