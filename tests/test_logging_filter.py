#!/usr/bin/env python3
"""Regression tests for the terminal logging filter."""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from run import _TerminalNoiseFilter


def make_record(name: str, level: int, message: str) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 0, message, (), None)


def test_filters_servo_info_logs() -> None:
    flt = _TerminalNoiseFilter()

    assert not flt.filter(make_record("motion.sc09", logging.INFO, "SC09Bus opened /dev/ttyUSB0 @ 115200 baud (vendor SDK)"))
    assert not flt.filter(make_record("motion.servo_bus", logging.INFO, "Servo 1 torque ON -> OK"))
    assert not flt.filter(make_record("detect", logging.INFO, "Servo port detected via by-id: foo -> /dev/ttyUSB0"))


def test_keeps_warnings_and_useful_logs() -> None:
    flt = _TerminalNoiseFilter()

    assert flt.filter(make_record("motion.sc09", logging.WARNING, "Ping servo 1: FAILED"))
    assert flt.filter(make_record("main", logging.INFO, "Starting Flask on 0.0.0.0:5000"))


def test_filters_werkzeug_polling_requests() -> None:
    flt = _TerminalNoiseFilter()

    assert not flt.filter(make_record("werkzeug", logging.INFO, '"GET /status HTTP/1.1" 200 -'))
    assert flt.filter(make_record("werkzeug", logging.INFO, '"GET /health HTTP/1.1" 200 -'))


if __name__ == "__main__":
    test_filters_servo_info_logs()
    test_keeps_warnings_and_useful_logs()
    test_filters_werkzeug_polling_requests()
    print("logging filter checks passed")