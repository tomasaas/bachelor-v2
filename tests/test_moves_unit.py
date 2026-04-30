import unittest

import config
from motion.moves import ServoAction, manual_move_actions, move_to_actions
from motion.scheduler import Scheduler
from motion.servo_bus import ServoGroup


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
        self.torque_commands = []

    def read_pos(self, servo_id):
        return self.position_bits

    def read_moving(self, servo_id):
        return 0

    def write_pos(self, servo_id, position, time=0, speed=400):
        self.position_bits = position
        self.commands.append((servo_id, position, time, speed))
        return True

    def write_u8(self, servo_id, addr, value):
        self.torque_commands.append((servo_id, addr, value))
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
    def _run_move(self, start_degrees, move_degrees, calibrated_bits=None):
        original_state_bits = {
            sid: dict(bits_by_state)
            for sid, bits_by_state in config.SERVO_STATE_BITS.items()
        }
        try:
            if calibrated_bits is not None:
                config.SERVO_STATE_BITS = {
                    **original_state_bits,
                    1: dict(calibrated_bits),
                }
            bus = _FakeBus(config.SERVO_STATE_BITS[1][start_degrees])
            group = ServoGroup(bus, ids=[1])
            target = group.step_servo(1, move_degrees, speed=500, time_ms=250, wait=False)
            return target, bus.commands, group
        finally:
            config.SERVO_STATE_BITS = original_state_bits

    def test_positive_wrap_uses_three_safe_reverse_hops(self):
        target, commands, _ = self._run_move(270, 90)
        expected = config.SERVO_STATE_BITS[1]
        self.assertEqual(target, 0)
        self.assertEqual(
            commands,
            [
                (1, expected[180], 250, 500),
                (1, expected[90], 250, 500),
                (1, expected[0], 250, 500),
            ],
        )

    def test_double_turn_uses_safe_monotonic_hops(self):
        target, commands, _ = self._run_move(270, 180)
        expected = config.SERVO_STATE_BITS[1]
        self.assertEqual(target, 90)
        self.assertEqual(
            commands,
            [
                (1, expected[180], 250, 500),
                (1, expected[90], 250, 500),
            ],
        )

    def test_negative_wrap_uses_three_safe_forward_hops(self):
        target, commands, _ = self._run_move(0, -90)
        expected = config.SERVO_STATE_BITS[1]
        self.assertEqual(target, 270)
        self.assertEqual(
            commands,
            [
                (1, expected[90], 250, 500),
                (1, expected[180], 250, 500),
                (1, expected[270], 250, 500),
            ],
        )

    def test_negative_180_wraps_to_180(self):
        target, commands, _ = self._run_move(0, -180)
        expected = config.SERVO_STATE_BITS[1]
        self.assertEqual(target, 180)
        self.assertEqual(
            commands,
            [
                (1, expected[90], 250, 500),
                (1, expected[180], 250, 500),
            ],
        )

    def test_home_uses_calibrated_per_servo_target(self):
        calibrated_bits = {0: 18, 90: 325, 180: 632, 270: 939}
        _, _, group = self._run_move(90, 0, calibrated_bits=calibrated_bits)
        group.bus.commands.clear()
        group.all_home()
        self.assertEqual(
            group.bus.commands,
            [(1, calibrated_bits[90], config.MOVE_TIME_MS, config.MOVE_SPEED)],
        )

    def test_feedback_snaps_to_nearest_calibrated_state(self):
        calibrated_bits = {0: 12, 90: 320, 180: 630, 270: 940}
        target, commands, group = self._run_move(90, -90, calibrated_bits=calibrated_bits)
        self.assertEqual(target, 0)
        self.assertEqual(commands, [(1, calibrated_bits[0], 250, 500)])
        self.assertEqual(group.logical_state_for_bits(1, 318), 90)

    def test_relative_move_releases_torque_after_command(self):
        target, _, group = self._run_move(90, -90)
        self.assertEqual(target, 0)
        self.assertEqual(
            group.bus.torque_commands,
            [
                (1, config.Reg.TORQUE_ENABLE, 1),
                (1, config.Reg.TORQUE_ENABLE, 0),
            ],
        )

    def test_cube_degrees_for_bits_interpolates_within_calibrated_segment(self):
        calibrated_bits = {0: 20, 90: 320, 180: 620, 270: 920}
        original_state_bits = {
            sid: dict(bits_by_state)
            for sid, bits_by_state in config.SERVO_STATE_BITS.items()
        }
        try:
            config.SERVO_STATE_BITS = {
                **original_state_bits,
                1: dict(calibrated_bits),
            }
            group = ServoGroup(_FakeBus(170), ids=[1])
            self.assertEqual(group.cube_degrees_for_bits(1, 170), 45.0)
        finally:
            config.SERVO_STATE_BITS = original_state_bits

    def test_bits_for_cube_degrees_interpolates_within_calibrated_segment(self):
        calibrated_bits = {0: 20, 90: 320, 180: 620, 270: 920}
        original_state_bits = {
            sid: dict(bits_by_state)
            for sid, bits_by_state in config.SERVO_STATE_BITS.items()
        }
        try:
            config.SERVO_STATE_BITS = {
                **original_state_bits,
                1: dict(calibrated_bits),
            }
            group = ServoGroup(_FakeBus(calibrated_bits[0]), ids=[1])
            self.assertEqual(group.bits_for_cube_degrees(1, 45), 170)
        finally:
            config.SERVO_STATE_BITS = original_state_bits


if __name__ == "__main__":
    unittest.main()
