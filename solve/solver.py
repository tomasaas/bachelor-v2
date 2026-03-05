"""
Kociemba two-phase solver wrapper.

Input:  54-char facelet string  (UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB)
Output: space-separated move string  (e.g. "R U F2 D' L B2")
"""

from __future__ import annotations

import logging

import kociemba

log = logging.getLogger(__name__)


class SolveError(Exception):
    """Raised when the cube string is invalid or unsolvable."""


def solve(cube_string: str) -> str:
    """
    Validate and solve the cube.

    Parameters
    ----------
    cube_string : str
        54 characters, each one of U R F D L B, in the standard Kociemba
        facelet order.

    Returns
    -------
    str
        Space-separated move tokens, e.g. ``"R U2 F' D L2 B"``.
    """
    cube_string = cube_string.strip().upper()

    if len(cube_string) != 54:
        raise SolveError(
            f"Cube string must be 54 characters, got {len(cube_string)}"
        )

    valid_chars = set("URFDLB")
    bad = set(cube_string) - valid_chars
    if bad:
        raise SolveError(f"Invalid characters in cube string: {bad}")

    # Each face letter must appear exactly 9 times
    for ch in valid_chars:
        count = cube_string.count(ch)
        if count != 9:
            raise SolveError(
                f"Face '{ch}' appears {count} times (expected 9)"
            )

    log.info("Solving cube: %s", cube_string)
    try:
        solution = kociemba.solve(cube_string)
    except Exception as exc:
        raise SolveError(f"Kociemba error: {exc}") from exc

    log.info("Solution: %s", solution)
    return solution
