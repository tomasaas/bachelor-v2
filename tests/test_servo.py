#!/usr/bin/env python3
"""
Standalone SC09 servo test CLI.

Run on the RPi5 with the Waveshare board in Serial Forwarding mode.

Usage examples:

    python tests/test_servo.py ping              # Ping all 6 servos
    python tests/test_servo.py ping 3            # Ping servo 3
    python tests/test_servo.py status 1          # Read all feedback from servo 1
    python tests/test_servo.py torque 1 on       # Torque on for servo 1
    python tests/test_servo.py torque 1 off      # Torque off
    python tests/test_servo.py pos 1 512 300     # Move servo 1 to pos 512 at speed 300
    python tests/test_servo.py motor 1 500       # Motor mode: spin CW at speed 500
    python tests/test_servo.py motor 1 -500      # Motor mode: spin CCW
    python tests/test_servo.py motor 1 0         # Stop motor
    python tests/test_servo.py mode 1 pos        # Switch servo 1 to position mode
    python tests/test_servo.py mode 1 motor      # Switch servo 1 to motor mode
    python tests/test_servo.py home              # Home all servos to centre (512)

Options:
    --port /dev/ttyUSB0    Serial port (default from config)
    --baud 1000000         Baud rate   (default from config)
"""

from __future__ import annotations

import argparse
import logging
import sys
import os

# Allow running from repo root or tests/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from motion.sc09 import SC09Bus
from motion.servo_bus import Servo, ServoGroup


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="SC09 Servo Test CLI")
    parser.add_argument("command", choices=[
        "ping", "status", "torque", "pos", "motor", "mode", "home",
    ])
    parser.add_argument("args", nargs="*", help="Command arguments (see docstring)")
    parser.add_argument("--port", default=config.SERIAL_PORT)
    parser.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)

    bus = SC09Bus(port=args.port, baudrate=args.baud, timeout=config.SERIAL_TIMEOUT)
    group = ServoGroup(bus)

    try:
        cmd = args.command
        cargs = args.args

        if cmd == "ping":
            if cargs:
                sid = int(cargs[0])
                ok = bus.ping(sid)
                print(f"Servo {sid}: {'OK' if ok else 'NO RESPONSE'}")
            else:
                results = group.ping_all()
                for sid, ok in results.items():
                    print(f"  Servo {sid}: {'OK' if ok else 'NO RESPONSE'}")

        elif cmd == "status":
            sid = int(cargs[0]) if cargs else 1
            servo = Servo(bus, sid)
            st = servo.read_status()
            print(f"Servo {sid} status:")
            for k, v in st.items():
                print(f"  {k}: {v}")

        elif cmd == "torque":
            sid = int(cargs[0]) if len(cargs) > 0 else 1
            on = (cargs[1].lower() in ("on", "1", "true")) if len(cargs) > 1 else True
            servo = Servo(bus, sid)
            if on:
                servo.torque_on()
            else:
                servo.torque_off()
            print(f"Servo {sid} torque {'ON' if on else 'OFF'}")

        elif cmd == "pos":
            sid = int(cargs[0]) if len(cargs) > 0 else 1
            position = int(cargs[1]) if len(cargs) > 1 else 512
            speed = int(cargs[2]) if len(cargs) > 2 else 300
            servo = Servo(bus, sid)
            servo.move_to(position, speed)
            print(f"Servo {sid} → position {position} speed {speed}")

        elif cmd == "motor":
            sid = int(cargs[0]) if len(cargs) > 0 else 1
            speed = int(cargs[1]) if len(cargs) > 1 else 0
            servo = Servo(bus, sid)
            servo.set_motor_speed(speed)
            print(f"Servo {sid} motor speed {speed}")

        elif cmd == "mode":
            sid = int(cargs[0]) if len(cargs) > 0 else 1
            mode_str = cargs[1].lower() if len(cargs) > 1 else "pos"
            servo = Servo(bus, sid)
            if mode_str in ("pos", "position"):
                servo.set_position_mode()
                print(f"Servo {sid} → position mode")
            elif mode_str in ("motor", "wheel"):
                servo.set_motor_mode()
                print(f"Servo {sid} → motor mode")
            else:
                print(f"Unknown mode: {mode_str}")

        elif cmd == "home":
            print("Homing all servos to 512...")
            group.all_home()
            print("Done")

    finally:
        bus.close()


if __name__ == "__main__":
    main()
