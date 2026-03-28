import unittest

import config
from motion.moves import ServoAction, manual_move_actions, move_to_actions
from motion.scheduler import Scheduler
from motion.servo_bus import ServoGroup, degrees_to_bits


class _FakeServo:
    def __init__(self):
        self.moves = []

    def move_to(self, position, speed=400, time_ms=0):
        self.moves.append((position, speed, time_ms))
        return True

    def wait_until_stopped(self, timeout=2.0):
        return True


class _FakeGroup:
    def __init__(self):
        self.servo = _FakeServo()
        self.relative_steps = []
        self.stopped = False

    def __getitem__(self, servo_id):
        return self.servo

    def step_servo(self, servo_id, move_degrees, speed=None, time_ms=None, wait=True):
        self.relative_steps.append((servo_id, move_degrees, speed, time_ms, wait))
        return move_degrees

    def emergency_stop(self):
        self.stopped = True


class _FakeBus:
    def __init__(self, position_bits):
        self.position_bits = position_bits
        self.commands = []

    def read_pos(self, servo_id):
        return self.position_bits

    def write_pos(self, servo_id, position, time=0, speed=400):
        self.commands.append((servo_id, position, time, speed))
        return True


class MoveMappingTests(unittest.TestCase):
    def test_home_rounds_to_90_degrees(self):
        home_degrees = round(config.POS_HOME / config.STEPS_PER_DEGREE)
        self.assertEqual(home_degrees, 90)

    def test_f_face_clockwise_uses_calibrated_sign(self):
        expected = -90 * config.FACE_TURN_SIGN["F"]

        manual = manual_move_actions("F")
        solver = move_to_actions("F")

        self.assertEqual(len(manual), 1)
        self.assertEqual(len(solver), 1)
        self.assertEqual(manual[0].move_degrees, expected)
        self.assertEqual(solver[0].move_degrees, expected)

    def test_prime_move_uses_opposite_delta(self):
        expected = 90 * config.FACE_TURN_SIGN["F"]
        actions = move_to_actions("F'")
        self.assertEqual([a.move_degrees for a in actions], [expected])

    def test_double_turn_is_one_180_degree_move(self):
        actions = move_to_actions("F2")
        self.assertEqual([a.move_degrees for a in actions], [180])


class SchedulerRelativeActionTests(unittest.TestCase):
    def test_scheduler_executes_degree_action_via_step_servo(self):
        group = _FakeGroup()
        scheduler = Scheduler(group, check_feedback=True)
        action = ServoAction(servo_id=2, move_degrees=90, speed=456, time_ms=789, settle_ms=0)

        ok = scheduler.execute([[action]], ["F"])

        self.assertTrue(ok)
        self.assertEqual(group.relative_steps, [(2, 90, 456, 789, True)])
        self.assertEqual(group.servo.moves, [])


class ServoWraparoundTests(unittest.TestCase):
    def _run_move(self, start_degrees, move_degrees):
        bus = _FakeBus(degrees_to_bits(start_degrees))
        group = ServoGroup(bus, ids=[1])
        target = group.step_servo(1, move_degrees, speed=500, time_ms=250, wait=False)
        return target, bus.commands

    def test_360_wraps_to_0(self):
        target, commands = self._run_move(270, 90)
        self.assertEqual(target, 0)
        self.assertEqual(commands, [(1, degrees_to_bits(0), 250, 500)])

    def test_450_wraps_to_90(self):
        target, commands = self._run_move(270, 180)
        self.assertEqual(target, 90)
        self.assertEqual(commands, [(1, degrees_to_bits(90), 250, 500)])

    def test_negative_90_wraps_to_270(self):
        target, commands = self._run_move(0, -90)
        self.assertEqual(target, 270)
        self.assertEqual(commands, [(1, degrees_to_bits(270), 250, 500)])

    def test_negative_180_wraps_to_180(self):
        target, commands = self._run_move(0, -180)
        self.assertEqual(target, 180)
        self.assertEqual(commands, [(1, degrees_to_bits(180), 250, 500)])


if __name__ == "__main__":
    unittest.main()
