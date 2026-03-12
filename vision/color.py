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

# Kociemba face-colour mapping:  center facelets define the face colour.
# Standard ordering: U=white, R=red, F=green, D=yellow, L=orange, B=blue
# Adjust if your cube has a different scheme.
FACE_COLORS = {"U": "W", "R": "R", "F": "G", "D": "Y", "L": "O", "B": "B"}


def _median_hsv(frame: np.ndarray, roi: ROI) -> np.ndarray:
    """Extract the ROI patch, convert to HSV, return median H/S/V."""
    patch = frame[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return np.median(hsv.reshape(-1, 3), axis=0).astype(int)


def classify_color(hsv: np.ndarray) -> str:
    """
    Map an HSV triplet to the nearest cube colour using config thresholds.
    Returns single-char colour code: W, Y, R, O, B, G.
    """
    h, s, v = int(hsv[0]), int(hsv[1]), int(hsv[2])

    best_color = "?"
    best_dist = float("inf")

    for color, (hl, sl, vl, hh, sh, vh) in config.COLOR_RANGES.items():
        # Handle red hue wrap-around
        if hl <= hh:
            h_in = hl <= h <= hh
        else:
            h_in = h >= hl or h <= hh

        if h_in and sl <= s <= sh and vl <= v <= vh:
            # Inside the range – compute centre distance as tiebreaker
            hc = (hl + hh) / 2
            sc = (sl + sh) / 2
            vc = (vl + vh) / 2
            dist = abs(h - hc) + abs(s - sc) * 0.5 + abs(v - vc) * 0.3
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

    merged = {**cam0_colors, **cam1_colors}

    chars: list[str] = []
    for label in all_facelet_labels():
        color = merged.get(label, "?")
        fc = color_to_face.get(color, "?")
        chars.append(fc)

    cube_string = "".join(chars)
    log.info("Cube string: %s", cube_string)
    return cube_string
