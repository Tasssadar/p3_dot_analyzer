from p3_camera import P3Camera  # type: ignore
from p3_viewer import apply_colormap, ColormapID  # type: ignore
from dataclasses import dataclass, field
import queue
from typing import Any
import threading
from numpy.typing import NDArray
import time

import cv2
import numpy as np
from logging import getLogger
from pathlib import Path
from datetime import timedelta
from compression import zstd
import struct

logger = getLogger(__name__)

CAMERA_WIDTH = 256
CAMERA_HEIGHT = 192

RENDER_SCALE = 2
RENDER_WIDTH = CAMERA_WIDTH * RENDER_SCALE
RENDER_HEIGHT = CAMERA_HEIGHT * RENDER_SCALE

SAVED_FRAME_SIZE = RENDER_WIDTH * RENDER_HEIGHT * 3 * 2


@dataclass(slots=True, frozen=True)
class CamEvConnectFailed:
    message: str


@dataclass(slots=True, frozen=True)
class CamEvVersion:
    name: str
    version: str


@dataclass(slots=True, frozen=True)
class CamEvRecordingStats:
    duration: timedelta
    frame_count: int
    file_size_bytes: int


CameraEvents = CamEvConnectFailed | CamEvVersion | CamEvRecordingStats


@dataclass(slots=True, frozen=True)
class CamFrame:
    width: int
    height: int
    img: NDArray[np.float32]
    ts: float = field(default_factory=time.time)


@dataclass(slots=True, frozen=True)
class _RecorderFrame:
    raw_thermal: NDArray[np.uint16]
    ts: float = field(default_factory=time.time)


class Recorder:
    def __init__(self, dest_path: Path, frame_period: timedelta) -> None:
        self._frame_period_sec = frame_period.total_seconds()
        self._last_frame_ts = 0.0
        self._start_ts = time.monotonic()
        self._frame_count = 0

        self._thread = threading.Thread(target=self._thread_body)
        self._thread.start()

        self._frames_queue = queue.Queue[_RecorderFrame](maxsize=2)

        self._file = zstd.open(dest_path, "wb", level=5)
        self._stats_lock = threading.Lock()

    def stop(self) -> None:
        self._frames_queue.shutdown()
        self._thread.join()

        self._file.close()

    def on_frame(self, raw_thermal: NDArray[np.uint16]) -> None:
        now = time.monotonic()
        if now - self._last_frame_ts < self._frame_period_sec:
            return

        try:
            self._frames_queue.put_nowait(_RecorderFrame(raw_thermal))
            self._last_frame_ts = now
        except queue.Full:
            logger.warning("Recorder frames queue is full, dropping frame")

    def stats(self) -> CamEvRecordingStats:
        with self._stats_lock:
            return CamEvRecordingStats(
                duration=timedelta(seconds=time.monotonic() - self._start_ts),
                frame_count=self._frame_count,
                file_size_bytes=self._file.tell(),
            )

    def _thread_body(self) -> None:
        while True:
            try:
                frame = self._frames_queue.get(block=False)

                ts_data = struct.pack("<q", int(frame.ts * 1000))
                data = frame.raw_thermal.tobytes("C")
                del frame

                with self._stats_lock:
                    self._file.write(ts_data)
                    print(len(data), SAVED_FRAME_SIZE)
                    self._file.write(data)
                    self._frame_count += 1
                del data
            except queue.ShutDown:
                break


class Camera:
    def __init__(self) -> None:
        self._p3 = P3Camera()
        self._queue_events: queue.Queue[CameraEvents] = queue.Queue(maxsize=32)
        self._last_frame: CamFrame | None = None
        self._last_frame_lock = threading.Lock()

        self._ev_stop_thread = threading.Event()

        self._temp_min: float = 0
        self._temp_max: float = 35

        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self._camera_thread = threading.Thread(target=self._camera_thread_body)

        self._recorder_lock = threading.Lock()
        self._recorder: Recorder | None = None
        self._recorder_paused = False
        self._recorder_stats_ts = 0.0

    def start(self) -> None:
        self._camera_thread.start()

    def stop(self) -> None:
        if self._recorder is not None:
            self._recorder.stop()
            self._recorder = None
        self._ev_stop_thread.set()
        self._camera_thread.join()

    def take_frame(self) -> CamFrame | None:
        with self._last_frame_lock:
            if self._last_frame is None:
                return None
            frame = self._last_frame
            self._last_frame = None
        return frame

    def get_event(self) -> CameraEvents | None:
        try:
            return self._queue_events.get(block=False)
        except queue.Empty:
            return None

    def start_recording(self, dest_path: Path, frame_period: timedelta) -> None:
        with self._recorder_lock:
            if self._recorder is not None:
                raise ValueError("Recording already started")
            self._recorder = Recorder(dest_path, frame_period)

    def stop_recording(self) -> None:
        with self._recorder_lock:
            if self._recorder is None:
                raise ValueError("Recording not started")
            self._recorder.stop()
            self._recorder = None

    def pause_recording(self, paused: bool) -> None:
        with self._recorder_lock:
            self._recorder_paused = paused

    def _camera_thread_body(self) -> None:
        while not self._ev_stop_thread.is_set():
            try:
                self._p3.connect()
            except Exception as e:
                self._queue_events.put(CamEvConnectFailed(str(e)))
                self._ev_stop_thread.wait(0.5)
                continue

            try:
                name, version = self._p3.init()
                self._queue_events.put(CamEvVersion(name, version))

                self._p3.start_streaming()

                last_thermal: NDArray[np.uint16] | None = None

                while not self._ev_stop_thread.is_set():
                    _ir_brightness, thermal_raw = self._p3.read_frame_both()
                    if thermal_raw is None:
                        continue

                    thermal_raw = self.tnr(thermal_raw, last_thermal)
                    last_thermal = thermal_raw

                    with self._recorder_lock:
                        if self._recorder is not None and not self._recorder_paused:
                            self._recorder.on_frame(thermal_raw)

                            if time.monotonic() - self._recorder_stats_ts > 1.0:
                                self._queue_events.put(self._recorder.stats())
                                self._recorder_stats_ts = time.monotonic()

                    img = self._render(thermal_raw)

                    with self._last_frame_lock:
                        self._last_frame = CamFrame(
                            RENDER_WIDTH,
                            RENDER_HEIGHT,
                            img,
                        )
            except Exception as e:
                logger.exception("Error in camera thread")
                self._queue_events.put(CamEvConnectFailed(str(e)))
            finally:
                try:
                    self._p3.disconnect()
                except Exception:
                    self._p3.dev = None

    @staticmethod
    def tnr(
        img: NDArray[np.uint16],
        prev_img: NDArray[np.uint16] | None,
        alpha: float = 0.5,
    ) -> NDArray[np.uint16]:
        """Apply Temporal Noise Reduction.

        Blends current frame with previous frame to reduce temporal noise.

        Args:
            img: Current frame.
            prev_img: Previous frame (or None for first frame).
            alpha: Blending factor (0=all previous, 1=all current, default 0.3).

        Returns:
            Filtered frame.

        """
        if prev_img is None:
            return img

        result = alpha * img.astype(np.float32) + (1 - alpha) * prev_img.astype(
            np.float32
        )
        return result.astype(np.uint16)

    @staticmethod
    def _dde(
        img_u8: NDArray[np.uint8],
        strength: float = 0.5,
        kernel_size: int = 3,
    ) -> NDArray[np.uint8]:
        """Apply Digital Detail Enhancement (edge sharpening).

        Uses unsharp masking: enhanced = original + strength * (original - blurred)

        Args:
            img_u8: Input 8-bit image.
            strength: Enhancement strength (0.0-1.0, default 0.5).
            kernel_size: Kernel size for high-pass filter (default 3).

        Returns:
            Enhanced 8-bit image.

        """
        if strength <= 0:
            return img_u8

        # Create blurred version
        ksize = kernel_size | 1  # Ensure odd
        blurred = cv2.GaussianBlur(img_u8, (ksize, ksize), 0)

        # Unsharp mask
        img_f = img_u8.astype(np.float32)
        blurred_f = blurred.astype(np.float32)
        enhanced = img_f + strength * (img_f - blurred_f)

        return np.clip(enhanced, 0, 255).astype(np.uint8)

    def _agc_fixed(
        self,
        img: NDArray[np.uint16],
    ) -> NDArray[np.uint8]:
        """AGC with fixed temperature range (Celsius)."""
        raw_min = (self._temp_min + 273.15) * 64
        raw_max = (self._temp_max + 273.15) * 64
        normalized = (img.astype(np.float32) - raw_min) / (raw_max - raw_min)
        return (np.clip(normalized, 0.0, 1.0) * 255).astype(np.uint8)  # type: ignore

    def _render(self, thermal: NDArray[np.uint16]) -> NDArray[np.float32]:
        img = self._agc_fixed(thermal)
        # Optional CLAHE for local contrast enhancement
        clahe_result: Any = self._clahe.apply(img)
        # Ensure result is a numpy array (CLAHE may return cv2.UMat on some platforms)
        img = np.asarray(clahe_result, dtype=np.uint8)

        # DDE: edge enhancement
        img = self._dde(img)

        img = apply_colormap(img, ColormapID.WHITE_HOT)

        # transform for dearpygui
        img = np.asarray(
            cv2.resize(
                img,
                (RENDER_WIDTH, RENDER_HEIGHT),
                interpolation=cv2.INTER_LINEAR,
            ),
            dtype=np.uint8,
        )

        texture = np.empty((RENDER_HEIGHT, RENDER_WIDTH, 4), dtype=np.float32)
        texture[..., :3] = img[..., ::-1]  # BGR -> RGB
        texture[..., 3] = 255.0  # set alpha
        # normalize to 0-1 for dearpygui
        texture = texture.reshape(-1) / 255.0

        return texture
