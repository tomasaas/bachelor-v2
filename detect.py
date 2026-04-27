"""
Auto-detect USB devices (servo driver + cameras) regardless of plug order.
The RPi5 has 4 USB-A ports.  Device node numbers (/dev/ttyUSB*, /dev/video*)
"""

from __future__ import annotations

import glob
import logging
import os
import re

log = logging.getLogger(__name__)

# ── Servo driver (Waveshare ESP32 board, CP2102 USB-UART bridge) ─────────────

_SERIAL_BY_ID_DIR = "/dev/serial/by-id/"
_CP2102_PATTERN = re.compile(r"CP210[0-9]|Silicon_Labs", re.IGNORECASE)


def find_servo_port(fallback: str | None = None) -> str | None:
    """Return the serial port for the Waveshare servo driver.

    1. Checks ``/dev/serial/by-id/`` for a CP2102 entry (stable name).
    2. Falls back to the first ``/dev/ttyUSB*`` device.
    3. Returns *fallback* if nothing is found.
    """
    # Stable by-id symlinks (independent of plug order)
    try:
        for name in sorted(os.listdir(_SERIAL_BY_ID_DIR)):
            if _CP2102_PATTERN.search(name):
                path = os.path.join(_SERIAL_BY_ID_DIR, name)
                resolved = os.path.realpath(path)
                log.info("Servo port detected via by-id: %s → %s", name, resolved)
                return resolved
    except FileNotFoundError:
        pass

    # Fallback: first /dev/ttyUSB*
    ports = sorted(glob.glob("/dev/ttyUSB*"))
    if ports:
        log.warning("CP2102 not found in by-id; falling back to %s", ports[0])
        return ports[0]

    log.warning("No serial ports detected")
    return fallback


# ── USB cameras ──────────────────────────────────────────────────────────────

# Platform / on-board device names to skip (RPi5 ISP, codec, etc.)
_PLATFORM_SKIP = re.compile(r"pispbe|rpi|hevc|isp|bcm|codec", re.IGNORECASE)


def find_camera_indices(expected: int = 2) -> list[int]:
    """Return ``/dev/video*`` indices for USB cameras, skipping platform devices.

    Walks ``/sys/class/video4linux/`` to filter by:
      • device name (skip RPi platform devices),
      • sysfs path (must contain ``/usb``),
      • one index per physical USB device (first node = capture node).

    Returns up to *expected* indices, sorted ascending.
    """
    v4l_base = "/sys/class/video4linux"
    if not os.path.isdir(v4l_base):
        log.warning("No V4L2 subsystem found")
        return []

    def _sort_key(name: str) -> int:
        num = name.replace("video", "")
        return int(num) if num.isdigit() else 9999

    indices: list[int] = []
    seen_parents: set[str] = set()

    for entry in sorted(os.listdir(v4l_base), key=_sort_key):
        if not entry.startswith("video") or not entry[5:].isdigit():
            continue
        idx = int(entry[5:])
        sysfs = os.path.join(v4l_base, entry)

        # Read device name — skip known platform / on-board devices
        try:
            with open(os.path.join(sysfs, "name")) as f:
                name = f.read().strip()
        except (FileNotFoundError, OSError):
            continue
        if _PLATFORM_SKIP.search(name):
            continue

        # Confirm it's physically USB-connected
        try:
            real_device = os.path.realpath(os.path.join(sysfs, "device"))
        except OSError:
            continue
        if "/usb" not in real_device:
            continue

        # Each USB camera registers multiple V4L nodes (capture + metadata).
        # Take only the first node per physical USB parent (= the capture node).
        parent = os.path.dirname(real_device)
        if parent in seen_parents:
            continue
        seen_parents.add(parent)

        log.info("USB camera detected: /dev/video%d (%s)", idx, name)
        indices.append(idx)
        if len(indices) >= expected:
            break

    if not indices:
        log.warning("No USB cameras detected")
    return indices
