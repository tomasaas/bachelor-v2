"""
ROI (Region of Interest) definitions for extracting cube facelets from camera frames.

Each camera sees 3 faces × 9 facelets = 27 ROIs.
The default ROI grid is auto-generated; override with config.ROI_CAM0 / ROI_CAM1
once you have calibrated positions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import config

log = logging.getLogger(__name__)


@dataclass
class ROI:
    face: str     # U, R, F, D, L, B
    row: int      # 0-2  (row within the face)
    col: int      # 0-2  (col within the face)
    x: int        # top-left x in camera frame
    y: int        # top-left y in camera frame
    w: int        # width
    h: int        # height

    @property
    def label(self) -> str:
        return f"{self.face}[{self.row},{self.col}]"

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


def _generate_default_rois(
    faces: list[str],
    frame_w: int,
    frame_h: int,
    roi_size: int,
) -> list[ROI]:
    """
    Auto-generate a 3×9 ROI grid spread evenly across the frame.
    Each face occupies a horizontal band; facelets are in a 3×3 sub-grid.
    This is a rough starting layout – calibrate for your camera angles.
    """
    rois: list[ROI] = []
    n_faces = len(faces)
    band_h = frame_h // n_faces

    for fi, face in enumerate(faces):
        band_top = fi * band_h + (band_h - 3 * roi_size) // 2
        band_left = (frame_w - 3 * roi_size * 2) // 2
        for r in range(3):
            for c in range(3):
                x = band_left + c * roi_size * 2
                y = band_top + r * roi_size + r * 4  # small gap
                rois.append(ROI(face=face, row=r, col=c, x=x, y=y, w=roi_size, h=roi_size))
    return rois


def get_rois(cam_index: int) -> list[ROI]:
    """Return the ROI list for the given camera (0 or 1)."""
    saved = config.ROI_CAM0 if cam_index == 0 else config.ROI_CAM1
    if saved:
        return [ROI(*args) for args in saved]

    faces = config.CAM0_FACES if cam_index == 0 else config.CAM1_FACES
    rois = _generate_default_rois(
        faces, config.CAMERA_WIDTH, config.CAMERA_HEIGHT, config.ROI_SIZE,
    )
    log.info("Auto-generated %d ROIs for camera %d", len(rois), cam_index)
    return rois
