import tempfile
import unittest
from pathlib import Path

import config
from motion.calibration import derive_state_bits_from_home, save_servo_state_bits


class ServoCalibrationTests(unittest.TestCase):
    def test_derive_state_bits_from_home_uses_current_home_state(self):
        baseline = {1: {0: 25, 90: 319, 180: 613, 270: 907}}

        state_bits = derive_state_bits_from_home({1: 320}, baseline_state_bits=baseline)

        self.assertEqual(
            state_bits[1],
            {
                0: 26,
                90: 320,
                180: 614,
                270: 908,
            },
        )

    def test_derive_state_bits_rejects_out_of_range_targets(self):
        with self.assertRaises(ValueError) as ctx:
            derive_state_bits_from_home({1: 100})
        message = str(ctx.exception)
        self.assertIn("Face D / servo 1", message)
        self.assertIn("logical 90deg home", message)
        self.assertIn("Place this face horizontally", message)

    def test_save_servo_state_bits_replaces_only_assignment(self):
        source = """before = 1\nSERVO_STATE_BITS = {\n    1: {0: 1, 90: 2, 180: 3, 270: 4},\n}\nafter = 2\n"""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.py"
            path.write_text(source, encoding="utf-8")

            save_servo_state_bits(
                {1: {0: 13, 90: 320, 180: 627, 270: 934}},
                path=path,
            )

            updated = path.read_text(encoding="utf-8")

        self.assertIn("before = 1\n", updated)
        self.assertIn("after = 2\n", updated)
        self.assertIn("1: {0: 13, 90: 320, 180: 627, 270: 934},", updated)
        self.assertNotIn("90: 2", updated)


if __name__ == "__main__":
    unittest.main()
