"""
SC09 / SCS serial-bus servo interface.

Wraps the vendor scservo_sdk (proven working with the example scripts)
to provide a clean, thread-safe API for the rest of the application.

The Waveshare ESP32 Servo Driver must be in **Serial Forwarding** mode.
"""

from __future__ import annotations

import logging
import os
import sys
import threading

# ── vendor SDK import (same pattern as the working example scripts) ──────────
_SDK_DIR = os.path.join(os.path.dirname(__file__), "..", "stservo-env")
if _SDK_DIR not in sys.path:
    sys.path.insert(0, _SDK_DIR)

from scservo_sdk import *  # noqa: E402,F403 – PortHandler, scscl, COMM_SUCCESS, etc.

log = logging.getLogger(__name__)


class SC09Bus:
    """
    Thread-safe interface to SCS/SC09 serial-bus servos.

    Uses the vendor scservo_sdk ``scscl`` packet handler internally –
    the same code path proven in the working example scripts.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        timeout: float = 0.05,   # kept for API compat; vendor SDK handles timing
        retries: int = 2,
    ):
        self._lock = threading.Lock()
        self._retries = retries

        # Initialise exactly like the vendor example scripts
        self.port_handler = PortHandler(port)
        self.packet_handler = scscl(self.port_handler)

        if not self.port_handler.openPort():
            raise RuntimeError(f"Failed to open serial port {port}")
        if not self.port_handler.setBaudRate(baudrate):
            raise RuntimeError(f"Failed to set baudrate {baudrate}")

        log.info("SC09Bus opened %s @ %d baud (vendor SDK)", port, baudrate)

    # ── ping ─────────────────────────────────────────────────────────────

    def ping(self, servo_id: int) -> bool:
        with self._lock:
            model, result, error = self.packet_handler.ping(servo_id)
        ok = result == COMM_SUCCESS
        if ok:
            log.info("Ping servo %d: OK (model %d)", servo_id, model)
        else:
            log.warning("Ping servo %d: FAILED", servo_id)
        return ok

    # ── position moves (proven SDK methods) ──────────────────────────────

    def write_pos(self, servo_id: int, position: int,
                  time: int = 0, speed: int = 400) -> bool:
        """Move servo to position. Mirrors scscl.WritePos() from examples."""
        with self._lock:
            result, error = self.packet_handler.WritePos(
                servo_id, position, time, speed,
            )
        ok = result == COMM_SUCCESS
        if not ok:
            log.warning("WritePos servo %d failed: %s",
                        servo_id, self.packet_handler.getTxRxResult(result))
        return ok

    def reg_write_pos(self, servo_id: int, position: int,
                      time: int = 0, speed: int = 400) -> bool:
        """Buffered position write. Call reg_action() to trigger."""
        with self._lock:
            result, error = self.packet_handler.RegWritePos(
                servo_id, position, time, speed,
            )
        return result == COMM_SUCCESS

    def reg_action(self) -> None:
        """Trigger all buffered reg-writes simultaneously."""
        with self._lock:
            self.packet_handler.RegAction()

    def sync_write_pos(self, data: list[tuple[int, int, int, int]]) -> bool:
        """
        Synchronised position write to multiple servos.
        data: list of (servo_id, position, time, speed).
        """
        with self._lock:
            for sid, pos, t, spd in data:
                self.packet_handler.SyncWritePos(sid, pos, t, spd)
            result = self.packet_handler.groupSyncWrite.txPacket()
            self.packet_handler.groupSyncWrite.clearParam()
        return result == COMM_SUCCESS

    # ── feedback reads ───────────────────────────────────────────────────

    def read_pos(self, servo_id: int) -> int | None:
        with self._lock:
            pos, result, error = self.packet_handler.ReadPos(servo_id)
        if result == COMM_SUCCESS:
            return pos
        return None

    def read_speed(self, servo_id: int) -> int | None:
        with self._lock:
            spd, result, error = self.packet_handler.ReadSpeed(servo_id)
        if result == COMM_SUCCESS:
            return spd
        return None

    def read_pos_speed(self, servo_id: int) -> tuple[int | None, int | None]:
        with self._lock:
            pos, spd, result, error = self.packet_handler.ReadPosSpeed(servo_id)
        if result == COMM_SUCCESS:
            return pos, spd
        return None, None

    def read_moving(self, servo_id: int) -> int | None:
        with self._lock:
            moving, result, error = self.packet_handler.ReadMoving(servo_id)
        if result == COMM_SUCCESS:
            return moving
        return None

    # ── low-level register access ────────────────────────────────────────

    def write_u8(self, servo_id: int, addr: int, value: int) -> bool:
        with self._lock:
            result, error = self.packet_handler.write1ByteTxRx(
                servo_id, addr, value & 0xFF,
            )
        return result == COMM_SUCCESS

    def write_u16(self, servo_id: int, addr: int, value: int) -> bool:
        with self._lock:
            result, error = self.packet_handler.write2ByteTxRx(
                servo_id, addr, value & 0xFFFF,
            )
        return result == COMM_SUCCESS

    def read_u8(self, servo_id: int, addr: int) -> int | None:
        with self._lock:
            val, result, error = self.packet_handler.read1ByteTxRx(servo_id, addr)
        if result == COMM_SUCCESS:
            return val
        return None

    def read_u16(self, servo_id: int, addr: int) -> int | None:
        with self._lock:
            val, result, error = self.packet_handler.read2ByteTxRx(servo_id, addr)
        if result == COMM_SUCCESS:
            return val
        return None

    # ── EEPROM lock/unlock (mirrors vendor examples) ─────────────────────

    def lock_eprom(self, servo_id: int) -> None:
        with self._lock:
            self.packet_handler.LockEprom(servo_id)

    def unlock_eprom(self, servo_id: int) -> None:
        with self._lock:
            self.packet_handler.unLockEprom(servo_id)

    # ── close ────────────────────────────────────────────────────────────

    def close(self) -> None:
        self.port_handler.closePort()
        log.info("SC09Bus closed")
