#!/usr/bin/env python3
"""
Rubik's Cube Solver – main entry point.

Starts the Flask web server with camera streams and servo control.
On the RPi5 this is launched automatically on boot (e.g. via systemd).

Usage:
    python run.py
    python run.py --no-servos          # Start without servo connection (GUI-only dev)
    python run.py --no-cameras         # Start without cameras (servo testing)
    python run.py --port 5000          # Override Flask port
    python run.py --serial /dev/ttyUSB1  # Override serial device
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

import config


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("rubiks.log"),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rubik's Cube Solver Server")
    parser.add_argument("--no-servos", action="store_true",
                        help="Skip servo initialisation")
    parser.add_argument("--no-cameras", action="store_true",
                        help="Skip camera initialisation")
    parser.add_argument("--port", type=int, default=config.FLASK_PORT)
    parser.add_argument("--host", default=config.FLASK_HOST)
    parser.add_argument("--serial", default=config.SERIAL_PORT,
                        help="Serial port for servo driver")
    args = parser.parse_args()

    setup_logging()
    log = logging.getLogger("main")
    log.info("=== Rubik's Cube Solver starting ===")

    # ── cameras ──────────────────────────────────────────────────────────
    dual_camera = None
    if not args.no_cameras:
        from vision.camera import DualCamera
        dual_camera = DualCamera()
        results = dual_camera.open_all()
        for i, ok in enumerate(results):
            log.info("Camera %d: %s", i, "opened" if ok else "FAILED")
    else:
        log.info("Cameras skipped (--no-cameras)")

    # ── servos ───────────────────────────────────────────────────────────
    servo_group = None
    scheduler = None
    if not args.no_servos:
        from motion.sc09 import SC09Bus
        from motion.servo_bus import ServoGroup
        from motion.scheduler import Scheduler

        serial_port = args.serial
        if serial_port == "auto":
            from detect import find_servo_port
            serial_port = find_servo_port()
            if serial_port:
                log.info("Auto-detected servo port: %s", serial_port)
            else:
                log.error("No servo driver detected (is USB cable plugged in?)")

        if serial_port:
            try:
                bus = SC09Bus(
                    port=serial_port,
                    baudrate=config.SERIAL_BAUD,
                    timeout=config.SERIAL_TIMEOUT,
                )
                servo_group = ServoGroup(bus)
                servo_group.initialize()
                scheduler = Scheduler(servo_group, check_feedback=True)
            except Exception as exc:
                log.error("Servo init failed: %s (continuing without servos)", exc)
    else:
        log.info("Servos skipped (--no-servos)")

    # ── Flask ────────────────────────────────────────────────────────────
    from server.app import create_app
    from server.routes import init_hardware

    init_hardware(dual_camera, servo_group, scheduler)
    app = create_app()

    # Clean shutdown on Ctrl+C (avoids OpenCV SIGABRT)
    def _shutdown(sig, frame):
        log.info("Shutting down...")
        if servo_group:
            servo_group.shutdown()
        if dual_camera:
            dual_camera.close_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("Starting Flask on %s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
