import unittest

from solve.solver import SolveError, _normalize_cube_string


class SolverInputTests(unittest.TestCase):
    def test_normalize_cube_string_removes_manual_formatting_whitespace(self):
        formatted = "\n".join(
            [
                "UUUUUUUUU",
                "RRRRRRRRR",
                "FFFFFFFFF",
                "DDDDDDDDD",
                "LLLLLLLLL",
                "BBBBBBBBB",
            ]
        )

        self.assertEqual(
            _normalize_cube_string(formatted),
            "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB",
        )

    def test_normalize_color_string_derives_mapping_from_unique_centers(self):
        cube_string = "wwgwwgwwgrrrrrrrrrggyggyggyyybyybyybooooooooowbbwbbwbb"

        self.assertEqual(
            _normalize_cube_string(cube_string),
            "UUFUUFUUFRRRRRRRRRFFDFFDFFDDDBDDBDDBLLLLLLLLLUBBUBBUBB",
        )

    def test_duplicate_center_error_reports_received_centers(self):
        cube_string = "WWGWWGWWGRRRRRRRRRGGYGGYGGYYYBYBYBYBOOOOOOOOOWBBWBWBBB"

        with self.assertRaises(SolveError) as ctx:
            _normalize_cube_string(cube_string)

        self.assertIn(
            "U=W, R=R, F=G, D=B, L=O, B=B",
            str(ctx.exception),
        )


if __name__ == "__main__":
    unittest.main()
