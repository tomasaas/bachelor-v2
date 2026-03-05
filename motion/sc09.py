"""
Low-level SC09 / SCS serial-bus servo protocol.

Packet format (instruction):
  [0xFF][0xFF][ID][Length][Instruction][Param …][Checksum]

Packet format (status response):
  [0xFF][0xFF][ID][Length][Error][Param …][Checksum]

Length = count(params) + 2   (includes instruction/error + checksum)
Checksum = ~(ID + Length + Instruction/Error + Σparams) & 0xFF

The Waveshare ESP32 Servo Driver in **Serial Forwarding** mode acts as a
transparent USB-serial ↔ servo-bus bridge, so we send/receive raw packets
via /dev/ttyUSB0 (or similar).
"""

from __future__ import annotations

import logging
import struct
import threading
import time
from dataclasses import dataclass

import serial

log = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────

HEADER = b"\xff\xff"

INST_PING       = 0x01
INST_READ       = 0x02
INST_WRITE      = 0x03
INST_REG_WRITE  = 0x04
INST_ACTION     = 0x05
INST_SYNC_WRITE = 0x83

BROADCAST_ID    = 0xFE

# Error bit masks in the status packet
ERR_VOLTAGE     = 1 << 0
ERR_ANGLE       = 1 << 1
ERR_OVERHEAT    = 1 << 2
ERR_RANGE       = 1 << 3
ERR_CHECKSUM    = 1 << 4
ERR_OVERLOAD    = 1 << 5
ERR_INSTRUCTION = 1 << 6

# ── helpers ──────────────────────────────────────────────────────────────────

def _checksum(servo_id: int, length: int, payload: bytes) -> int:
    """Compute SCS-protocol checksum."""
    return (~(servo_id + length + sum(payload))) & 0xFF


def _build_packet(servo_id: int, instruction: int, params: bytes = b"") -> bytes:
    length = len(params) + 2
    payload = bytes([instruction]) + params
    chk = _checksum(servo_id, length, payload)
    return HEADER + bytes([servo_id, length]) + payload + bytes([chk])


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass
class StatusPacket:
    servo_id: int
    error: int
    data: bytes

    @property
    def ok(self) -> bool:
        return self.error == 0

    def error_flags(self) -> list[str]:
        names = []
        for bit, name in [
            (ERR_VOLTAGE, "VOLTAGE"), (ERR_ANGLE, "ANGLE"),
            (ERR_OVERHEAT, "OVERHEAT"), (ERR_RANGE, "RANGE"),
            (ERR_CHECKSUM, "CHECKSUM"), (ERR_OVERLOAD, "OVERLOAD"),
            (ERR_INSTRUCTION, "INSTRUCTION"),
        ]:
            if self.error & bit:
                names.append(name)
        return names

    def u8(self, offset: int = 0) -> int:
        return self.data[offset]

    def u16(self, offset: int = 0) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]


# ── SC09 bus class ───────────────────────────────────────────────────────────

class SC09Bus:
    """
    Thread-safe, low-level interface to SCS/SC09 serial-bus servos.

    Assumes the Waveshare ESP32 board is in Serial Forwarding mode,
    acting as a transparent USB↔servo-bus bridge.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 1_000_000,
        timeout: float = 0.05,
        retries: int = 2,
    ):
        self._lock = threading.Lock()
        self._retries = retries
        self._ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=timeout,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )
        log.info("SC09Bus opened %s @ %d baud", port, baudrate)

    # ── low-level transact ───────────────────────────────────────────────

    def _flush(self) -> None:
        self._ser.reset_input_buffer()

    def _send(self, pkt: bytes) -> None:
        self._ser.write(pkt)
        self._ser.flush()

    def _recv(self, servo_id: int) -> StatusPacket | None:
        """
        Read one status/response packet.  Returns None on timeout or
        checksum mismatch.
        """
        # Read header bytes – scan for 0xFF 0xFF
        hdr = self._ser.read(2)
        if len(hdr) < 2 or hdr != HEADER:
            # Try to realign: read one more byte at a time
            buf = hdr
            for _ in range(10):
                b = self._ser.read(1)
                if not b:
                    return None
                buf += b
                idx = buf.find(HEADER)
                if idx >= 0:
                    buf = buf[idx:]
                    break
            else:
                return None
            if len(buf) < 2:
                return None

        # Read ID + Length
        meta = self._ser.read(2)
        if len(meta) < 2:
            return None
        rid, length = meta[0], meta[1]

        if length < 2 or length > 64:
            log.warning("Bad length %d from servo %d", length, rid)
            return None

        # Read remaining bytes (error + params + checksum)
        remaining = self._ser.read(length)
        if len(remaining) < length:
            log.warning("Short read: expected %d, got %d", length, len(remaining))
            return None

        error = remaining[0]
        params = remaining[1:-1]
        chk_recv = remaining[-1]
        chk_calc = _checksum(rid, length, remaining[:-1])

        if chk_recv != chk_calc:
            log.warning(
                "Checksum mismatch from servo %d: recv=0x%02X calc=0x%02X",
                rid, chk_recv, chk_calc,
            )
            return None

        return StatusPacket(servo_id=rid, error=error, data=params)

    def transact(
        self, servo_id: int, instruction: int, params: bytes = b""
    ) -> StatusPacket | None:
        """Send instruction packet, read status response (with retries)."""
        pkt = _build_packet(servo_id, instruction, params)
        for attempt in range(1, self._retries + 1):
            with self._lock:
                self._flush()
                self._send(pkt)
                if servo_id == BROADCAST_ID:
                    return StatusPacket(servo_id=BROADCAST_ID, error=0, data=b"")
                resp = self._recv(servo_id)
            if resp is not None:
                return resp
            log.debug("Retry %d/%d for servo %d", attempt, self._retries, servo_id)
            time.sleep(0.005)
        log.warning("No response from servo %d after %d attempts", servo_id, self._retries)
        return None

    def write_only(
        self, servo_id: int, instruction: int, params: bytes = b""
    ) -> None:
        """Send a packet without waiting for response (broadcast-like)."""
        pkt = _build_packet(servo_id, instruction, params)
        with self._lock:
            self._flush()
            self._send(pkt)

    # ── convenience methods ──────────────────────────────────────────────

    def ping(self, servo_id: int) -> bool:
        resp = self.transact(servo_id, INST_PING)
        if resp and resp.ok:
            log.info("Ping servo %d: OK", servo_id)
            return True
        log.warning("Ping servo %d: FAILED", servo_id)
        return False

    def read_register(self, servo_id: int, addr: int, length: int) -> StatusPacket | None:
        return self.transact(servo_id, INST_READ, bytes([addr, length]))

    def write_register(self, servo_id: int, addr: int, data: bytes) -> StatusPacket | None:
        return self.transact(servo_id, INST_WRITE, bytes([addr]) + data)

    def write_u8(self, servo_id: int, addr: int, value: int) -> StatusPacket | None:
        return self.write_register(servo_id, addr, bytes([value & 0xFF]))

    def write_u16(self, servo_id: int, addr: int, value: int) -> StatusPacket | None:
        return self.write_register(servo_id, addr, struct.pack("<H", value & 0xFFFF))

    def read_u8(self, servo_id: int, addr: int) -> int | None:
        resp = self.read_register(servo_id, addr, 1)
        if resp and resp.ok and len(resp.data) >= 1:
            return resp.u8()
        return None

    def read_u16(self, servo_id: int, addr: int) -> int | None:
        resp = self.read_register(servo_id, addr, 2)
        if resp and resp.ok and len(resp.data) >= 2:
            return resp.u16()
        return None

    def reg_write(self, servo_id: int, addr: int, data: bytes) -> None:
        """Buffered write – executes on ACTION command."""
        self.write_only(servo_id, INST_REG_WRITE, bytes([addr]) + data)

    def action(self) -> None:
        """Trigger all buffered reg-writes simultaneously."""
        self.write_only(BROADCAST_ID, INST_ACTION)

    def sync_write(self, addr: int, length: int, id_data: list[tuple[int, bytes]]) -> None:
        """
        Sync-write to multiple servos at once.
        id_data: list of (servo_id, data_bytes) – each data_bytes must be ``length`` long.
        """
        params = bytes([addr, length])
        for sid, data in id_data:
            params += bytes([sid]) + data
        self.write_only(BROADCAST_ID, INST_SYNC_WRITE, params)

    def close(self) -> None:
        if self._ser.is_open:
            self._ser.close()
            log.info("SC09Bus closed")
