from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time

import cv2
import numpy as np

from ..ui_helpers import get_temp_at_img

from ..models import BatchAnalysisResult, NamedArea, AreaPStatPoint
from ..state import AppState

WANTED_PERCENTILES = [90, 50, 10]


@dataclass(slots=True)
class DetectedMark:
    """A detected circular or elliptical mark."""

    center_x: float
    center_y: float
    axis_a: float  # semi-major axis
    axis_b: float  # semi-minor axis
    angle: float  # rotation angle in degrees


def detect_colored_marks(
    image_rgba_dpg: np.ndarray,
    base_x: int,
    base_y: int,
    tolerance: int = 30,
    min_area: int = 200,
    max_area: int = 200,
    min_circularity: float = 0.5,
) -> list[DetectedMark]:
    """Detect circular/elliptical marks of a specific color in the image.

    Args:
        image_bgr: Image in BGR format (as loaded by OpenCV).
        base_x: Base point x coordinate in image space.
        base_y: Base point y coordinate in image space.
        tolerance: Tolerance for color matching in HSV space.
        min_area: Minimum contour area to consider.
        max_area: Maximum contour area to consider.
        min_circularity: Minimum circularity threshold (0-1, circle=1).

    Returns:
        List of detected marks with their positions and dimensions.
    """

    # Convert image to HSV
    # rgba: H x W x 4, float32 in [0,1]
    # Convert RGBA -> BGR
    image_bgr = cv2.cvtColor(
        np.clip(image_rgba_dpg * 255.0, 0, 255).astype(np.uint8), cv2.COLOR_RGBA2BGR
    )
    # BGR -> HSV
    image_hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # Get base point temperature (color)
    base = image_hsv[base_y, base_x]

    # We use B&W image only, so we only count with V
    _, _, v = base
    v_tolerance = tolerance

    # Cut off everything below base + tolerance
    lower_bound = np.array(
        [
            0,
            0,
            min(255, int(v) + v_tolerance),
        ]
    )
    upper_bound = np.array(
        [
            179,
            255,
            255,
        ]
    )

    # Create mask for the target color
    mask = cv2.inRange(image_hsv, lower_bound, upper_bound)

    # cv2.imshow("image", mask)
    # cv2.waitKey(0)

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    detected_marks: list[DetectedMark] = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        if area > max_area:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter == 0:
            continue

        # Calculate circularity: 4 * pi * area / perimeter^2
        circularity = 4 * np.pi * area / (perimeter * perimeter)

        if circularity < min_circularity:
            continue

        # Need at least 5 points to fit an ellipse
        if len(contour) >= 5:
            ellipse = cv2.fitEllipse(contour)
            center, axes, angle = ellipse
            detected_marks.append(
                DetectedMark(
                    center_x=center[0],
                    center_y=center[1],
                    axis_a=axes[0]
                    / 2,  # fitEllipse returns full axes, we want semi-axes
                    axis_b=axes[1] / 2,
                    angle=angle,
                )
            )
        else:
            # Fall back to minimum enclosing circle
            (cx, cy), radius = cv2.minEnclosingCircle(contour)
            detected_marks.append(
                DetectedMark(
                    center_x=cx,
                    center_y=cy,
                    axis_a=radius,
                    axis_b=radius,
                    angle=0,
                )
            )

    return detected_marks


def count_marks_in_areas(
    marks: list[DetectedMark],
    named_areas: list[NamedArea],
) -> dict[str, int]:
    """Count how many marks overlap with each named area."""
    counts: dict[str, int] = {}

    for area in named_areas:
        count = 0
        area_x1 = area.x
        area_y1 = area.y
        area_x2 = area.x + area.width
        area_y2 = area.y + area.height

        for mark in marks:
            # Check if mark center is within the area bounds
            if (
                area_x1 <= mark.center_x <= area_x2
                and area_y1 <= mark.center_y <= area_y2
            ):
                count += 1

        counts[area.name] = count

    return counts


def analyze_current_frame(
    app_state: AppState,
) -> tuple[list[DetectedMark], dict[str, int]] | None:
    if not app_state.analysis.enabled:
        return None
    if app_state.analysis.base_x is None or app_state.analysis.base_y is None:
        return None
    if app_state.render.current_frame is None:
        return None
    if (
        app_state.analysis.base_x < 0
        or app_state.analysis.base_y < 0
        or app_state.analysis.base_x >= app_state.render.current_frame.width
        or app_state.analysis.base_y >= app_state.render.current_frame.height
    ):
        return None

    marks = detect_colored_marks(
        app_state.render.current_frame.img.reshape(
            (
                app_state.render.current_frame.height,
                app_state.render.current_frame.width,
                4,
            )
        ),
        app_state.analysis.base_x,
        app_state.analysis.base_y,
        tolerance=app_state.analysis.color_tolerance,
        min_area=app_state.analysis.min_area,
        max_area=app_state.analysis.max_area,
        min_circularity=app_state.analysis.min_circularity,
    )
    counts = count_marks_in_areas(marks, app_state.areas.named_areas)
    return marks, counts


@dataclass(slots=True)
class _LoadAndDetectResult:
    image_index: int
    timestamp: float
    marks: list[DetectedMark] | None
    base_temp_c: float


def _load_and_detect(
    app_state: AppState,
    image_index: int,
) -> _LoadAndDetectResult:
    assert app_state.recording.reader is not None
    # Load image
    frame = app_state.recording.reader.read_frame(
        image_index, app_state.build_render_config()
    )

    if frame is None:
        raise RuntimeError(f"Failed to load frame {image_index}")

    assert app_state.analysis.base_x is not None
    assert app_state.analysis.base_y is not None

    # Detect marks
    marks = detect_colored_marks(
        frame.img.reshape((frame.height, frame.width, 4)),
        app_state.analysis.base_x,
        app_state.analysis.base_y,
        tolerance=app_state.analysis.color_tolerance,
        min_area=app_state.analysis.min_area,
        max_area=app_state.analysis.max_area,
        min_circularity=app_state.analysis.min_circularity,
    )
    base_temp = get_temp_at_img(
        app_state, frame, app_state.analysis.base_x, app_state.analysis.base_y
    )
    assert base_temp is not None

    return _LoadAndDetectResult(
        image_index=image_index,
        timestamp=frame.ts,
        marks=marks,
        base_temp_c=base_temp,
    )


@dataclass(slots=True)
class _BatchPoint:
    timestamp: float
    base_temp_c: float
    area_counts: dict[str, int]


def run_batch_analysis(
    app_state: AppState,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """Run batch analysis on all images with sampling."""
    # Check prerequisites
    if app_state.analysis.base_x is None or app_state.analysis.base_y is None:
        return

    if not app_state.areas.named_areas:
        return

    reader = app_state.recording.reader
    if not reader or not reader.frame_count:
        return

    sampling_rate = max(1, min(100, app_state.analysis.batch_sampling_rate))

    # Initialize result storage
    points: list[_BatchPoint] = []
    area_max_counts: dict[str, int] = {
        area.name: 0 for area in app_state.areas.named_areas
    }

    # Get indices to process based on sampling
    indices_to_process = list(range(0, reader.frame_count, sampling_rate))
    total = len(indices_to_process)

    last_progress_time = 0.0

    with ThreadPoolExecutor(max_workers=os.process_cpu_count()) as executor:
        futures = [
            executor.submit(_load_and_detect, app_state, i) for i in indices_to_process
        ]

        progress_idx = 0
        start_ts = reader.ts_start.timestamp()
        for fut in as_completed(futures):
            r = fut.result()
            progress_idx += 1

            # Report progress
            now = time.monotonic()
            if now - last_progress_time > 0.3:
                last_progress_time = now
                if progress_callback is not None:
                    progress_callback(progress_idx, total)

            if r.marks is None:
                counts = {area.name: 0 for area in app_state.areas.named_areas}
            else:
                # Count marks in areas
                counts = count_marks_in_areas(r.marks, app_state.areas.named_areas)

                for area_name, c in counts.items():
                    if c > area_max_counts[area_name]:
                        area_max_counts[area_name] = c

            points.append(
                _BatchPoint(
                    timestamp=r.timestamp - start_ts,
                    area_counts=counts,
                    base_temp_c=r.base_temp_c,
                )
            )

    points.sort(key=lambda p: p.timestamp)

    timestamps = [p.timestamp for p in points]

    area_counts_res: dict[str, list[int]] = {
        area.name: [] for area in app_state.areas.named_areas
    }
    area_min_counts = area_max_counts.copy()

    percentiles_stack = {
        area.name: list(WANTED_PERCENTILES) for area in app_state.areas.named_areas
    }

    percentile_for_area: dict[int, dict[str, AreaPStatPoint]] = {
        pct: {} for pct in WANTED_PERCENTILES
    }

    for p in points:
        for area_name, c in p.area_counts.items():
            amax = area_max_counts[area_name]
            if amax == 0:
                area_counts_res[area_name].append(0)
                continue

            amin = area_min_counts[area_name]
            cur = amax - c
            if cur < amin:
                area_min_counts[area_name] = cur
            else:
                cur = amin

            cur_pct = int(cur / amax * 100)

            pct_stack_for_area = percentiles_stack[area_name]
            while pct_stack_for_area and cur_pct <= pct_stack_for_area[0]:
                pct = pct_stack_for_area.pop(0)
                percentile_for_area[pct][area_name] = AreaPStatPoint(
                    p.timestamp, p.base_temp_c, cur
                )

            area_counts_res[area_name].append(cur_pct)

    # Store result
    app_state.analysis.batch_result = BatchAnalysisResult(
        timestamps=timestamps,
        area_counts=area_counts_res,
        percentile_for_area=percentile_for_area,
    )
