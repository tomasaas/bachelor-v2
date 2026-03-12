"""
ROI (Region of Interest) definitions for extracting cube facelets from camera frames.

Each camera sees 3 faces × 9 facelets = 27 ROIs.
The default ROI grid is auto-generated; override with config.ROI_CAM0 / ROI_CAM1
once you have calibrated positions.

Labelling convention
--------------------
Each ROI carries *two* coordinate systems:

* **cam_row / cam_col** – position in the camera's raw 3×3 grid (what the
  camera actually sees).  This is what you drag in the UI.
* **facelet** – the Kociemba facelet ID after applying the per-face
  orientation transform, e.g. ``U1`` … ``U9``, ``R1`` … ``R9``, etc.

The transform is a pure rotation (0 / 90 / 180 / 270°) configured in
``config.FACE_ORIENTATION``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import config

log = logging.getLogger(__name__)

# ── orientation helpers ──────────────────────────────────────────────────────

def _rotate_grid_pos(row: int, col: int, degrees: int) -> tuple[int, int]:
    """
    Rotate a (row, col) position in a 3×3 grid clockwise by *degrees*.

    Returns the new (row, col) that corresponds to Kociemba reading order.
    """
    d = degrees % 360
    if d == 0:
        return (row, col)
    if d == 90:
        return (col, 2 - row)
    if d == 180:
        return (2 - row, 2 - col)
    if d == 270:
        return (2 - col, row)
    raise ValueError(f"Unsupported rotation: {degrees}")


def camera_to_kociemba(face: str, cam_row: int, cam_col: int) -> tuple[int, int]:
    """Map a camera grid position to Kociemba (row, col) for the given face."""
    deg = config.FACE_ORIENTATION.get(face, 0)
    return _rotate_grid_pos(cam_row, cam_col, deg)


def facelet_label(face: str, koc_row: int, koc_col: int) -> str:
    """Return the Kociemba facelet label, e.g. ``U1`` (1-indexed)."""
    return f"{face}{koc_row * 3 + koc_col + 1}"


# ── ROI dataclass ────────────────────────────────────────────────────────────

@dataclass
class ROI:
    face: str       # U, R, F, D, L, B
    cam_row: int    # 0-2  row in the camera's raw 3×3 grid for this face
    cam_col: int    # 0-2  col in the camera's raw 3×3 grid for this face
    x: int          # top-left x in camera frame (pixels)
    y: int          # top-left y in camera frame (pixels)
    w: int          # width  (pixels)
    h: int          # height (pixels)

    @property
    def koc_row(self) -> int:
        r, _ = camera_to_kociemba(self.face, self.cam_row, self.cam_col)
        return r

    @property
    def koc_col(self) -> int:
        _, c = camera_to_kociemba(self.face, self.cam_row, self.cam_col)
        return c

    @property
    def label(self) -> str:
        """Kociemba facelet label, e.g. ``U1``."""
        return facelet_label(self.face, self.koc_row, self.koc_col)

    @property
    def facelet_index(self) -> int:
        """1-based facelet index within this face (1..9)."""
        return self.koc_row * 3 + self.koc_col + 1

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


# ── default ROI generation ──────────────────────────────────────────────────

# Per-camera face placement: maps face → (centre_x_fraction, centre_y_fraction)
# relative to the 640×480 frame.  Fractions are tuned so the 3×3 grids land
# close to where the physical cube corners actually appear.
#
# Cam 0 (top camera, views one corner):
#   U  → top centre        F  → bottom right      L  → bottom left
# Cam 1 (bottom camera, views opposite corner):
#   R  → top left          B  → top right          D  → bottom centre

_FACE_PLACEMENT: dict[int, dict[str, tuple[float, float]]] = {
    0: {
        "U": (0.50, 0.22),   # top centre
        "L": (0.22, 0.72),   # bottom left
        "F": (0.78, 0.72),   # bottom right
    },
    1: {
        "R": (0.22, 0.25),   # top left
        "B": (0.78, 0.25),   # top right
        "D": (0.50, 0.75),   # bottom centre
    },
}


def _generate_default_rois(
    cam_index: int,
    faces: list[str],
    frame_w: int,
    frame_h: int,
    roi_size: int,
) -> list[ROI]:
    """
    Auto-generate 27 ROIs (3 faces × 9 facelets) for one camera.

    Each face's 3×3 grid is centred at the position given by
    ``_FACE_PLACEMENT[cam_index][face]``.
    """
    rois: list[ROI] = []
    spacing = roi_size + 6          # gap between adjacent ROI boxes
    grid_half = spacing             # offset from centre to outer edge

    placements = _FACE_PLACEMENT.get(cam_index, {})

    for face in faces:
        cx_frac, cy_frac = placements.get(face, (0.5, 0.5))
        cx = int(frame_w * cx_frac)
        cy = int(frame_h * cy_frac)

        for r in range(3):
            for c in range(3):
                x = cx - grid_half + (c - 1) * spacing + spacing // 2 - roi_size // 2
                y = cy - grid_half + (r - 1) * spacing + spacing // 2 - roi_size // 2
                # Clamp inside frame
                x = max(0, min(x, frame_w - roi_size))
                y = max(0, min(y, frame_h - roi_size))
                rois.append(ROI(face=face, cam_row=r, cam_col=c,
                                x=x, y=y, w=roi_size, h=roi_size))
    return rois


# ── persistence ──────────────────────────────────────────────────────────────

_ROI_SAVE_PATH = Path(__file__).resolve().parent.parent / "roi_positions.json"


def _rois_to_dicts(rois: list[ROI]) -> list[dict]:
    return [
        {"face": r.face, "cam_row": r.cam_row, "cam_col": r.cam_col,
         "x": r.x, "y": r.y, "w": r.w, "h": r.h}
        for r in rois
    ]


def _dicts_to_rois(data: list[dict]) -> list[ROI]:
    return [
        ROI(face=d["face"], cam_row=d["cam_row"], cam_col=d["cam_col"],
            x=d["x"], y=d["y"], w=d["w"], h=d["h"])
        for d in data
    ]


def save_rois(cam0_dicts: list[dict], cam1_dicts: list[dict]) -> None:
    """Persist current ROI positions to a JSON file."""
    payload = {"cam0": cam0_dicts, "cam1": cam1_dicts}
    _ROI_SAVE_PATH.write_text(json.dumps(payload, indent=2))
    log.info("ROI positions saved to %s", _ROI_SAVE_PATH)


def load_saved_rois() -> dict[int, list[ROI]] | None:
    """Load previously-saved ROI positions. Returns None if no save exists."""
    if not _ROI_SAVE_PATH.is_file():
        return None
    try:
        data = json.loads(_ROI_SAVE_PATH.read_text())
        result = {
            0: _dicts_to_rois(data.get("cam0", [])),
            1: _dicts_to_rois(data.get("cam1", [])),
        }
        log.info("Loaded saved ROI positions from %s", _ROI_SAVE_PATH)
        return result
    except Exception as exc:
        log.warning("Failed to load saved ROIs: %s", exc)
        return None


def delete_saved_rois() -> None:
    """Remove the saved ROI file so defaults are used on next load."""
    if _ROI_SAVE_PATH.is_file():
        _ROI_SAVE_PATH.unlink()
        log.info("Deleted saved ROI file")


# ── public API ───────────────────────────────────────────────────────────────

def get_default_rois(cam_index: int) -> list[ROI]:
    """Return the auto-generated default ROIs (ignoring any saved file)."""
    faces = config.CAM0_FACES if cam_index == 0 else config.CAM1_FACES
    return _generate_default_rois(
        cam_index, faces, config.CAMERA_WIDTH, config.CAMERA_HEIGHT, config.ROI_SIZE,
    )


def get_rois(cam_index: int) -> list[ROI]:
    """Return ROIs for the given camera, preferring saved positions."""
    # 1. Try config overrides
    saved_cfg = config.ROI_CAM0 if cam_index == 0 else config.ROI_CAM1
    if saved_cfg:
        return [ROI(*args) for args in saved_cfg]

    # 2. Try on-disk saved positions
    saved = load_saved_rois()
    if saved and saved.get(cam_index):
        return saved[cam_index]

    # 3. Fall back to auto-generated defaults
    rois = get_default_rois(cam_index)
    log.info("Auto-generated %d ROIs for camera %d", len(rois), cam_index)
    return rois


# ── Kociemba string assembly ────────────────────────────────────────────────

KOCIEMBA_FACE_ORDER = ["U", "R", "F", "D", "L", "B"]


def all_facelet_labels() -> list[str]:
    """Return all 54 facelet labels in Kociemba order: U1..U9, R1..R9, …"""
    labels = []
    for face in KOCIEMBA_FACE_ORDER:
        for idx in range(1, 10):
            labels.append(f"{face}{idx}")
    return labels
