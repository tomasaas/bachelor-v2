import unittest

from solve.solver import _normalize_cube_string


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


if __name__ == "__main__":
    unittest.main()
