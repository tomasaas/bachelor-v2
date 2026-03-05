#!/usr/bin/env python3
"""
Standalone motion test – exercises the full pipeline WITHOUT cameras/vision.

Sends a hard-coded (or Kociemba-generated) move sequence to the servos.
Useful for validating servo wiring, move timings, and position calibration.

Usage:
    python tests/test_motion.py                          # Use default test moves
    python tests/test_motion.py --moves "R U F2 D' L"   # Custom move string
    python tests/test_motion.py --scramble               # Generate a random scramble → solve → execute
    python tests/test_motion.py --dry-run                # Print actions without sending to servos
    python tests/test_motion.py --port /dev/ttyUSB0      # Override serial port

Options:
    --port    Serial port        (default from config)
    --baud    Baud rate          (default from config)
    --speed   Servo speed        (override config.MOVE_SPEED)
    --settle  Settle time (ms)   (override config.MOVE_SETTLE_MS)
"""

from __future__ import annotations

import argparse
import logging
import sys
import os
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from motion.sc09 import SC09Bus
from motion.servo_bus import ServoGroup
from motion.moves import parse_solution, solution_to_actions, move_to_actions
from motion.scheduler import Scheduler


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# A short test sequence that exercises every face once
DEFAULT_MOVES = "R U F D L B R' U' F' D' L' B'"


def random_scramble(length: int = 10) -> str:
    faces = list("RURFDLB")
    suffixes = ["", "'", "2"]
    moves = []
    last = ""
    for _ in range(length):
        face = random.choice([f for f in "RUFDLB" if f != last])
        moves.append(face + random.choice(suffixes))
        last = face
    return " ".join(moves)


def main() -> None:
    parser = argparse.ArgumentParser(description="Motion Test (no vision)")
    parser.add_argument("--moves", type=str, default="",
                        help="Space-separated move string")
    parser.add_argument("--scramble", action="store_true",
                        help="Generate random scramble → solve → run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without sending to servos")
    parser.add_argument("--port", default=config.SERIAL_PORT)
    parser.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    parser.add_argument("--speed", type=int, default=0,
                        help="Override move speed")
    parser.add_argument("--settle", type=int, default=0,
                        help="Override settle time (ms)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)

    # Apply speed/settle overrides
    if args.speed:
        config.MOVE_SPEED = args.speed
    if args.settle:
        config.MOVE_SETTLE_MS = args.settle

    # Determine moves
    if args.scramble:
        scramble = random_scramble()
        print(f"Scramble: {scramble}")
        move_string = scramble  # just run the scramble as a test
    elif args.moves:
        move_string = args.moves
    else:
        move_string = DEFAULT_MOVES

    tokens = parse_solution(move_string)
    action_groups = solution_to_actions(move_string)

    total_actions = sum(len(g) for g in action_groups)
    print(f"\nMoves:   {move_string}")
    print(f"Tokens:  {tokens}")
    print(f"Actions: {total_actions} total across {len(action_groups)} move groups\n")

    if args.dry_run:
        for i, (tok, actions) in enumerate(zip(tokens, action_groups)):
            print(f"  [{i+1}] {tok}:")
            for a in actions:
                print(f"      servo={a.servo_id}  pos={a.position}  "
                      f"speed={a.speed}  settle={a.settle_ms}ms")
        print("\n(dry run – no servo commands sent)")
        return

    # Open serial and run
    bus = SC09Bus(port=args.port, baudrate=args.baud, timeout=config.SERIAL_TIMEOUT)
    group = ServoGroup(bus)

    try:
        # Quick ping check
        print("Pinging servos...")
        results = group.ping_all()
        for sid, ok in results.items():
            status = "OK" if ok else "NO RESPONSE"
            print(f"  Servo {sid}: {status}")

        responsive = [sid for sid, ok in results.items() if ok]
        if not responsive:
            print("\nNo servos responded – check wiring and Serial Forwarding mode.")
            return

        # Ensure position mode + torque on
        print("\nSwitching to position mode + torque on...")
        group.all_to_position_mode()
        group.all_torque_on()

        # Home first
        print("Homing all servos...")
        group.all_home()

        # Execute move sequence
        print(f"\nExecuting {len(tokens)} moves...\n")
        scheduler = Scheduler(group, check_feedback=True)
        ok = scheduler.execute(action_groups, tokens)

        if ok:
            print("\nAll moves completed successfully!")
        else:
            print(f"\nExecution stopped: {scheduler.progress.state.name}")
            if scheduler.progress.error:
                print(f"Error: {scheduler.progress.error}")

        # Home after
        print("Returning to home position...")
        group.all_home()

    finally:
        # Safety: torque off
        print("Torque off (safety)...")
        group.all_torque_off()
        bus.close()


if __name__ == "__main__":
    main()
