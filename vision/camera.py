"""
Camera capture and MJPEG streaming for two cameras.
"""

from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

import config

log = logging.getLogger(__name__)


class Camera:
    """Thread-safe wrapper around a single OpenCV VideoCapture."""

    def __init__(self, index: int):
        self.index = index
        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None

    def open(self) -> bool:
        with self._lock:
            self._cap = cv2.VideoCapture(self.index)
            if self._cap.isOpened():
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
                log.info("Camera %d opened", self.index)
                return True
            log.error("Camera %d failed to open", self.index)
            return False

    def close(self) -> None:
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None

    def grab(self) -> np.ndarray | None:
        with self._lock:
            if self._cap is None or not self._cap.isOpened():
                return None
            ok, frame = self._cap.read()
            if ok:
                self._frame = frame
                return frame
            return None

    @property
    def last_frame(self) -> np.ndarray | None:
        return self._frame


class DualCamera:
    """Manages both cameras, provides capture and MJPEG generators."""

    def __init__(self, indices: list[int] | None = None):
        if indices is None:
            indices = config.CAMERA_INDICES
        if indices == "auto":
            from detect import find_camera_indices
            indices = find_camera_indices(expected=2)
            log.info("Auto-detected camera indices: %s", indices)
        self.cams = [Camera(i) for i in indices]

    def open_all(self) -> list[bool]:
        return [cam.open() for cam in self.cams]

    def close_all(self) -> None:
        for cam in self.cams:
            cam.close()

    def grab_all(self) -> list[np.ndarray | None]:
        return [cam.grab() for cam in self.cams]

    def mjpeg_generator(self, cam_index: int):
        """
        Yield MJPEG frames for Flask streaming response.
        cam_index: 0 or 1.
        """
        cam = self.cams[cam_index]
        while True:
            frame = cam.grab()
            if frame is None:
                time.sleep(0.1)
                continue
            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + jpeg.tobytes()
                + b"\r\n"
            )
