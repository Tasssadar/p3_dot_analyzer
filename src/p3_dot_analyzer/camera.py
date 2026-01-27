from p3_camera import P3Camera  # type: ignore
from p3_viewer import ColormapID  # type: ignore
from dataclasses import dataclass, field
import queue
import threading
from numpy.typing import NDArray
import time

from .render import render, RenderConfig
import numpy as np
from logging import getLogger
from pathlib import Path
from datetime import timedelta
import struct
import mmap
from datetime import datetime

logger = getLogger(__name__)

CAMERA_WIDTH = 256
CAMERA_HEIGHT = 192

RENDER_SCALE = 2
RENDER_WIDTH = CAMERA_WIDTH * RENDER_SCALE
RENDER_HEIGHT = CAMERA_HEIGHT * RENDER_SCALE

# 2 bytes per pixel
SAVED_FRAME_SIZE = 8 + (CAMERA_WIDTH * CAMERA_HEIGHT * 2)


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
    raw_thermal: NDArray[np.uint16]
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

        self._frames_queue = queue.Queue[_RecorderFrame](maxsize=2)

        self._file = open(dest_path, "wb")
        self._stats_lock = threading.Lock()

        self._thread = threading.Thread(target=self._thread_body)
        self._thread.start()

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
                frame = self._frames_queue.get()

                ts_data = struct.pack("<q", int(frame.ts * 1000))
                data = frame.raw_thermal.tobytes("C")
                del frame

                with self._stats_lock:
                    self._file.write(ts_data)
                    self._file.write(data)
                    self._frame_count += 1
                del data
            except queue.ShutDown:
                break


class RecordingReader:
    def __init__(self, path: Path) -> None:
        self._file = open(path, "rb")
        self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self._frame_count = len(self._mmap) // SAVED_FRAME_SIZE

    def close(self) -> None:
        self._file.close()

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def ts_start(self) -> datetime:
        return self._read_ts(0)

    @property
    def ts_end(self) -> datetime:
        return self._read_ts(self._frame_count - 1)

    def _read_ts(self, index: int) -> datetime:
        start = index * SAVED_FRAME_SIZE
        buf = self._mmap[start : start + 8]
        unpacked = struct.unpack(
            "<q",
            buf,
        )

        return datetime.fromtimestamp(float(unpacked[0]) / 1000)

    def read_frame(self, index: int, config: RenderConfig) -> CamFrame:
        ts = self._read_ts(index)
        data_start = index * SAVED_FRAME_SIZE + 8
        data_end = data_start + CAMERA_WIDTH * CAMERA_HEIGHT * 2

        raw_thermal = np.frombuffer(self._mmap[data_start:data_end], dtype=np.uint16)
        raw_thermal = raw_thermal.reshape((CAMERA_HEIGHT, CAMERA_WIDTH))

        img = render(config, raw_thermal, RENDER_WIDTH, RENDER_HEIGHT)
        return CamFrame(
            width=RENDER_WIDTH,
            height=RENDER_HEIGHT,
            img=img,
            raw_thermal=raw_thermal,
            ts=ts.timestamp(),
        )


class Camera:
    def __init__(self) -> None:
        self._p3 = P3Camera()
        self._queue_events: queue.Queue[CameraEvents] = queue.Queue(maxsize=32)
        self._last_frame: CamFrame | None = None
        self._last_frame_lock = threading.Lock()

        self._ev_stop_thread = threading.Event()

        self._render_config = RenderConfig(
            temp_min=0,
            temp_max=35,
            colormap=ColormapID.WHITE_HOT,
        )

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

    def set_render_config(self, config: RenderConfig) -> None:
        self._render_config = config

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

                    img = render(
                        self._render_config, thermal_raw, RENDER_WIDTH, RENDER_HEIGHT
                    )

                    with self._last_frame_lock:
                        self._last_frame = CamFrame(
                            RENDER_WIDTH, RENDER_HEIGHT, img, thermal_raw
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
