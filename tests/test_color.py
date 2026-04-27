import unittest

from vision.color import apply_fixed_center_colors, build_cube_state


class FixedCenterColorTests(unittest.TestCase):
    def test_fixed_centers_override_detected_values(self):
        detected = {
            "U5": "?",
            "R5": "G",
            "F5": "B",
            "D5": "W",
            "L5": "Y",
            "B5": "O",
            "U1": "R",
        }

        fixed = apply_fixed_center_colors(detected)

        self.assertEqual(fixed["U5"], "W")
        self.assertEqual(fixed["R5"], "R")
        self.assertEqual(fixed["F5"], "G")
        self.assertEqual(fixed["D5"], "Y")
        self.assertEqual(fixed["L5"], "O")
        self.assertEqual(fixed["B5"], "B")
        self.assertEqual(fixed["U1"], "R")

    def test_cube_state_has_known_center_faces_when_detection_is_unknown(self):
        cube_string = build_cube_state(
            {"U5": "?", "L5": "?"},
            {"R5": "?", "F5": "?", "D5": "?", "B5": "?"},
        )

        self.assertEqual(cube_string[4], "U")
        self.assertEqual(cube_string[13], "R")
        self.assertEqual(cube_string[22], "F")
        self.assertEqual(cube_string[31], "D")
        self.assertEqual(cube_string[40], "L")
        self.assertEqual(cube_string[49], "B")


if __name__ == "__main__":
    unittest.main()
