"""
Move-execution scheduler.

Executes ServoAction sequences deterministically, one action at a time,
with logging, abort handling, and optional feedback checks.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto

from motion.servo_bus import Servo, ServoGroup
from motion.moves import ServoAction

log = logging.getLogger(__name__)


class SchedulerState(Enum):
    IDLE       = auto()
    RUNNING    = auto()
    ABORTING   = auto()
    ERROR      = auto()
    DONE       = auto()


@dataclass
class Progress:
    total_moves: int = 0
    completed_moves: int = 0
    total_actions: int = 0
    completed_actions: int = 0
    current_move: str = ""
    state: SchedulerState = SchedulerState.IDLE
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "total_moves": self.total_moves,
            "completed_moves": self.completed_moves,
            "total_actions": self.total_actions,
            "completed_actions": self.completed_actions,
            "current_move": self.current_move,
            "state": self.state.name,
            "error": self.error,
        }


class Scheduler:
    """
    Deterministic, single-threaded move executor.

    Usage::

        sched = Scheduler(servo_group)
        sched.execute(action_groups, move_tokens)  # blocking
    """

    def __init__(self, group: ServoGroup, check_feedback: bool = False):
        self.group = group
        self.check_feedback = check_feedback
        self._abort = threading.Event()
        self.progress = Progress()

    def abort(self) -> None:
        """Request graceful abort (checked between actions)."""
        log.warning("Scheduler abort requested")
        self._abort.set()

    def safe_state(self) -> None:
        """Emergency: torque off everything immediately."""
        self.group.emergency_stop()
        self.progress.state = SchedulerState.ABORTING

    def execute(
        self,
        action_groups: list[list[ServoAction]],
        move_tokens: list[str] | None = None,
    ) -> bool:
        """
        Execute all action groups sequentially.  Returns True on full
        completion, False on abort or error.
        """
        self._abort.clear()
        self.progress = Progress(
            total_moves=len(action_groups),
            total_actions=sum(len(g) for g in action_groups),
            state=SchedulerState.RUNNING,
        )

        log.info("Scheduler: executing %d moves (%d actions)",
                 self.progress.total_moves, self.progress.total_actions)

        try:
            for i, actions in enumerate(action_groups):
                token = move_tokens[i] if move_tokens and i < len(move_tokens) else f"#{i}"
                self.progress.current_move = token
                log.info("Move %d/%d: %s", i + 1, self.progress.total_moves, token)

                for action in actions:
                    if self._abort.is_set():
                        log.warning("Abort detected – stopping")
                        self.progress.state = SchedulerState.ABORTING
                        self.safe_state()
                        return False

                    self._execute_action(action)
                    self.progress.completed_actions += 1

                self.progress.completed_moves += 1

            self.progress.state = SchedulerState.DONE
            log.info("Scheduler: all moves complete")
            return True

        except Exception as exc:
            log.exception("Scheduler error: %s", exc)
            self.progress.state = SchedulerState.ERROR
            self.progress.error = str(exc)
            self.safe_state()
            return False

    def _execute_action(self, action: ServoAction) -> None:
        servo: Servo = self.group[action.servo_id]

        log.debug(
            "  Action: servo=%d pos=%d speed=%d settle=%dms",
            action.servo_id, action.position, action.speed, action.settle_ms,
        )

        servo.move_to(action.position, speed=action.speed)

        if self.check_feedback:
            servo.wait_until_stopped(timeout=2.0)

        if action.settle_ms > 0:
            time.sleep(action.settle_ms / 1000.0)
