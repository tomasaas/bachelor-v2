"""
Colour classification of cube facelets from ROI samples.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

import config
from vision.roi import ROI

log = logging.getLogger(__name__)

# Kociemba face-colour mapping.
#
# The center stickers define each face's permanent colour. In this rig the
# physical center stickers have been removed for axle holes, so these six
# facelets are treated as fixed instead of being read from the camera.
#
# Standard ordering: U=white, R=red, F=green, D=yellow, L=orange, B=blue.
# Opposite pairs: U/D = W/Y, R/L = R/O, F/B = G/B.
# Adjust only if your cube has a different valid scheme.
FACE_COLORS = {"U": "W", "R": "R", "F": "G", "D": "Y", "L": "O", "B": "B"}
FIXED_CENTER_COLORS = {f"{face}5": color for face, color in FACE_COLORS.items()}
HSVRange = tuple[int, int, int, int, int, int]
ColorRange = HSVRange | list[HSVRange]


def apply_fixed_center_colors(
    colors: dict[str, str],
    *,
    include_missing: bool = False,
) -> dict[str, str]:
    """
    Return a copy of *colors* with center facelets set to their fixed colours.

    ``include_missing`` is useful for the full preview/cube-state map where we
    want all six centers to be known even if a center ROI is unreadable.
    """
    fixed = dict(colors)
    for label, color in FIXED_CENTER_COLORS.items():
        if include_missing or label in fixed:
            fixed[label] = color
    return fixed


def _median_hsv(frame: np.ndarray, roi: ROI) -> np.ndarray:
    """Extract the ROI patch, convert to HSV, return median H/S/V."""
    patch = frame[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return np.median(hsv.reshape(-1, 3), axis=0).astype(int)


def _iter_hsv_ranges(color_range: ColorRange) -> list[HSVRange]:
    """Return a colour definition as a list of HSV ranges."""
    if isinstance(color_range, list):
        return color_range
    return [color_range]


def _hsv_in_range(h: int, s: int, v: int, hsv_range: HSVRange) -> bool:
    """Check whether an HSV sample falls inside one configured range."""
    hl, sl, vl, hh, sh, vh = hsv_range

    if hl <= hh:
        h_in = hl <= h <= hh
    else:
        h_in = h >= hl or h <= hh

    return h_in and sl <= s <= sh and vl <= v <= vh


def _range_distance(h: int, s: int, v: int, hsv_range: HSVRange) -> float:
    """Distance to the middle of one range, used as a tie-breaker."""
    hl, sl, vl, hh, sh, vh = hsv_range
    hc = (hl + hh) / 2
    sc = (sl + sh) / 2
    vc = (vl + vh) / 2
    return abs(h - hc) + abs(s - sc) * 0.5 + abs(v - vc) * 0.3


def classify_color(hsv: np.ndarray) -> str:
    """
    Map an HSV triplet to the nearest cube colour using config thresholds.
    Returns single-char colour code: W, Y, R, O, B, G.
    """
    h, s, v = int(hsv[0]), int(hsv[1]), int(hsv[2])

    best_color = "?"
    best_dist = float("inf")

    for color, color_range in config.COLOR_RANGES.items():
        for hsv_range in _iter_hsv_ranges(color_range):
            if _hsv_in_range(h, s, v, hsv_range):
                dist = _range_distance(h, s, v, hsv_range)
                if dist < best_dist:
                    best_dist = dist
                    best_color = color

    return best_color


def classify_rois(frame: np.ndarray, rois: list[ROI]) -> dict[str, str]:
    """
    Classify every ROI in the frame.
    Returns {roi.label: colour_char}.
    """
    result: dict[str, str] = {}
    for roi in rois:
        hsv = _median_hsv(frame, roi)
        color = classify_color(hsv)
        result[roi.label] = color
        log.debug("ROI %s  HSV=(%d,%d,%d) → %s", roi.label, *hsv, color)
    return result


def build_cube_state(cam0_colors: dict[str, str], cam1_colors: dict[str, str]) -> str:
    """
    Fuse colour maps from both cameras into a 54-char Kociemba cube string.

    Kociemba order: U1-U9, R1-R9, F1-F9, D1-D9, L1-L9, B1-B9
    Each face is read top-left → top-right, row by row.

    The orientation transform (camera grid → Kociemba order) is already
    baked into the ROI ``label`` property, so *cam0_colors* / *cam1_colors*
    keys are already Kociemba facelet labels like ``U1``, ``R5``, etc.

    Colour chars (W/R/G/Y/O/B) are mapped to face letters (U/R/F/D/L/B)
    based on FACE_COLORS.
    """
    from vision.roi import all_facelet_labels

    # Invert FACE_COLORS: colour → face letter
    color_to_face = {v: k for k, v in FACE_COLORS.items()}

    merged = apply_fixed_center_colors({**cam0_colors, **cam1_colors}, include_missing=True)

    chars: list[str] = []
    for label in all_facelet_labels():
        color = merged.get(label, "?")
        fc = color_to_face.get(color, "?")
        chars.append(fc)

    cube_string = "".join(chars)
    log.info("Cube string: %s", cube_string)
    return cube_string
