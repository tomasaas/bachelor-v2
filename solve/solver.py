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


def _normalize_cube_string(cube_string: str) -> str:
    """
    Accept either face-letter notation (URFDLB) or color notation
    (e.g. W/Y/R/O/B/G) and return a face-letter string for Kociemba.

    For color notation, mapping is derived from center stickers in standard
    face order indices: U=4, R=13, F=22, D=31, L=40, B=49.
    """
    cube_string = cube_string.strip().upper()

    if len(cube_string) != 54:
        raise SolveError(
            f"Cube string must be 54 characters, got {len(cube_string)}"
        )

    face_chars = set("URFDLB")
    chars = set(cube_string)
    if chars.issubset(face_chars):
        return cube_string

    if "?" in chars:
        raise SolveError("Cube string contains unknown facelets ('?')")

    # Build color->face mapping from centers in URFDLB order.
    center_indices = {
        "U": 4,
        "R": 13,
        "F": 22,
        "D": 31,
        "L": 40,
        "B": 49,
    }
    center_colors = {face: cube_string[idx] for face, idx in center_indices.items()}

    if len(set(center_colors.values())) != 6:
        raise SolveError(
            "Center stickers are not all unique; cannot derive color-to-face mapping"
        )

    color_to_face = {color: face for face, color in center_colors.items()}
    unknown = chars - set(color_to_face.keys())
    if unknown:
        raise SolveError(
            f"Cube string contains colors not present in centers: {unknown}"
        )

    return "".join(color_to_face[ch] for ch in cube_string)


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
    cube_string = _normalize_cube_string(cube_string)

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
