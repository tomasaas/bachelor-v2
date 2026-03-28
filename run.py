#!/usr/bin/env python3
"""
Rubik's Cube Solver – main entry point.

Starts the Flask web server with camera streams and servo control.
On the RPi5 this is launched automatically on boot (e.g. via systemd).

Usage:
    python run.py
    python run.py --noservos
    python run.py --nocameras
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

import config


class _TerminalNoiseFilter(logging.Filter):
    """Keep the terminal focused on high-level status and warnings."""

    _NOISY_LOGGER_PREFIXES = (
        "detect",
        "motion.sc09",
        "motion.servo_bus",
        "serial",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING and record.name.startswith(self._NOISY_LOGGER_PREFIXES):
            return False

        if record.name.startswith("werkzeug"):
            message = record.getMessage()
            if "GET /servo/positions" in message or "GET /status" in message:
                return False

        return True


def setup_logging() -> None:
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.addFilter(_TerminalNoiseFilter())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            console_handler,
            logging.FileHandler("rubiks.log"),
        ],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the Rubik's Cube Solver web app.",
    )
    parser.add_argument(
        "--noservos",
        action="store_true",
        help="Start without initialising servo hardware.",
    )
    parser.add_argument(
        "--nocameras",
        action="store_true",
        help="Start without initialising camera hardware.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    host = config.FLASK_HOST
    port = config.FLASK_PORT
    serial_port = config.SERIAL_PORT

    setup_logging()
    log = logging.getLogger("main")
    log.info("=== Rubik's Cube Solver starting ===")

    # ── cameras ──────────────────────────────────────────────────────────
    dual_camera = None
    if args.nocameras:
        log.info("Camera initialisation skipped (--nocameras)")
    else:
        from vision.camera import DualCamera
        dual_camera = DualCamera()
        results = dual_camera.open_all()
        for i, ok in enumerate(results):
            log.info("Camera %d: %s", i, "opened" if ok else "FAILED")

    # ── servos ───────────────────────────────────────────────────────────
    servo_group = None
    scheduler = None
    if args.noservos:
        log.info("Servo initialisation skipped (--noservos)")
    else:
        from motion.sc09 import SC09Bus
        from motion.servo_bus import ServoGroup
        from motion.scheduler import Scheduler

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

    log.info("Starting Flask on %s:%d", host, port)
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
