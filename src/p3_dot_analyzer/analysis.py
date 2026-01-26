"""Analysis module for detecting colored circular/elliptical marks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Callable
import time
import cv2
import dearpygui.dearpygui as dpg  # type: ignore
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

if TYPE_CHECKING:
    from .models import AppState, NamedArea


@dataclass
class DetectedMark:
    """A detected circular or elliptical mark."""

    center_x: float
    center_y: float
    axis_a: float  # semi-major axis
    axis_b: float  # semi-minor axis
    angle: float  # rotation angle in degrees


def detect_colored_marks(
    image_bgr: np.ndarray,
    target_rgb: tuple[int, int, int],
    tolerance: int = 30,
    min_area: int = 200,
    min_circularity: float = 0.5,
) -> list[DetectedMark]:
    """Detect circular/elliptical marks of a specific color in the image.

    Args:
        image_bgr: Image in BGR format (as loaded by OpenCV).
        target_rgb: Target color in RGB format.
        tolerance: Tolerance for color matching in HSV space.
        min_area: Minimum contour area to consider.
        min_circularity: Minimum circularity threshold (0-1, circle=1).

    Returns:
        List of detected marks with their positions and dimensions.
    """
    # Convert target RGB to BGR then to HSV
    target_bgr = np.array(
        [[[target_rgb[2], target_rgb[1], target_rgb[0]]]], dtype=np.uint8
    )
    target_hsv = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2HSV)[0][0]

    # Convert image to HSV
    image_hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # Create color range with tolerance
    h, s, v = target_hsv
    # Hue wraps around at 180, so handle that specially
    h_tolerance = min(tolerance // 2, 20)  # Hue is 0-179 in OpenCV
    s_tolerance = tolerance
    v_tolerance = tolerance

    lower_bound = np.array(
        [
            max(0, int(h) - h_tolerance),
            max(0, int(s) - s_tolerance),
            max(0, int(v) - v_tolerance),
        ]
    )
    upper_bound = np.array(
        [
            min(179, int(h) + h_tolerance),
            min(255, int(s) + s_tolerance),
            min(255, int(v) + v_tolerance),
        ]
    )

    # Create mask for the target color
    mask = cv2.inRange(image_hsv, lower_bound, upper_bound)

    # Handle hue wrap-around for red colors (hue near 0 or 180)
    if h < h_tolerance:
        # Also include high hue values
        lower2 = np.array(
            [
                180 - (h_tolerance - int(h)),
                max(0, int(s) - s_tolerance),
                max(0, int(v) - v_tolerance),
            ],
            dtype=np.int64,
        )
        upper2 = np.array(
            [179, min(255, s + s_tolerance), min(255, v + v_tolerance)], dtype=np.int64
        )
        mask2 = cv2.inRange(image_hsv, lower2, upper2)
        mask = cv2.bitwise_or(mask, mask2)
    elif h > 179 - h_tolerance:
        # Also include low hue values
        lower2 = np.array([0, max(0, s - s_tolerance), max(0, v - v_tolerance)])
        upper2 = np.array(
            [
                h_tolerance - (179 - h),
                min(255, s + s_tolerance),
                min(255, v + v_tolerance),
            ]
        )
        mask2 = cv2.inRange(image_hsv, lower2, upper2)
        mask = cv2.bitwise_or(mask, mask2)

    # Morphological operations to clean up noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detected_marks: list[DetectedMark] = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
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


def draw_analysis_overlays(app_state: AppState, marks: list[DetectedMark]) -> None:
    """Draw overlay indicators on detected marks.

    Args:
        app_state: The application state.
        marks: List of detected marks to draw.
    """
    # Clear existing analysis overlays
    for tag in app_state.analysis_overlay_tags:
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)
    app_state.analysis_overlay_tags.clear()

    # Draw each detected mark
    for i, mark in enumerate(marks):
        tag = f"analysis_mark_{i}"

        # Calculate ellipse bounding box for drawing
        # DearPyGui doesn't have native ellipse drawing, so we'll use a circle
        # approximation or draw as a rectangle outline
        radius = max(mark.axis_a, mark.axis_b)

        # Draw a circle around the detected mark
        dpg.draw_circle(
            center=(mark.center_x, mark.center_y),
            radius=radius + 3,  # Slightly larger than the mark
            color=(255, 255, 0, 255),  # Yellow outline
            thickness=2,
            tag=tag,
            parent=app_state.image_drawlist_tag,
        )
        app_state.analysis_overlay_tags.append(tag)


def count_marks_in_areas(
    marks: list[DetectedMark],
    named_areas: list[NamedArea],
) -> dict[str, int]:
    """Count how many marks overlap with each named area.

    Args:
        marks: List of detected marks.
        named_areas: List of named areas to check.

    Returns:
        Dictionary mapping area name to count of overlapping marks.
    """
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


def run_analysis(app_state: AppState) -> None:
    """Run the full analysis pipeline.

    This is the main entry point for analysis. It:
    1. Detects colored marks in the current image
    2. Draws overlays on detected marks
    3. Counts marks per named area and updates the UI

    Args:
        app_state: The application state.
    """
    # Import here to avoid circular imports
    from .named_areas import update_areas_list

    # Clear previous analysis results
    clear_analysis_overlays(app_state)
    app_state.area_mark_counts.clear()

    # Check prerequisites
    if not app_state.analysis_mode_enabled:
        update_areas_list(app_state)
        return

    if app_state.selected_color is None:
        update_areas_list(app_state)
        return

    if app_state.current_image_data is None:
        update_areas_list(app_state)
        return

    # Detect marks
    marks = detect_colored_marks(
        app_state.current_image_data,
        app_state.selected_color,
        tolerance=app_state.color_tolerance,
        min_area=app_state.min_area,
        min_circularity=app_state.min_circularity,
    )

    # Draw overlays
    draw_analysis_overlays(app_state, marks)

    # Count marks in areas
    app_state.area_mark_counts = count_marks_in_areas(marks, app_state.named_areas)

    # Update the areas list UI
    update_areas_list(app_state)


def clear_analysis_overlays(app_state: AppState) -> None:
    """Clear all analysis overlays from the image.

    Args:
        app_state: The application state.
    """
    for tag in app_state.analysis_overlay_tags:
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)
    app_state.analysis_overlay_tags.clear()


def _load_and_detect(
    app_state: AppState, image_index: int, image_path: Path
) -> tuple[int, list[DetectedMark] | None]:
    # Load image
    image_bgr = cv2.imread(str(image_path))

    if image_bgr is None:
        # If image fails to load, record zeros
        return (image_index, None)

    assert app_state.selected_color

    # Detect marks
    marks = detect_colored_marks(
        image_bgr,
        app_state.selected_color,
        tolerance=app_state.color_tolerance,
        min_area=app_state.min_area,
        min_circularity=app_state.min_circularity,
    )
    return (image_index, marks)


def run_batch_analysis(
    app_state: AppState,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """Run batch analysis on all images with sampling.

    This function iterates through all images (with the configured sampling rate),
    detects colored marks, and counts marks per named area at each timestamp.

    Args:
        app_state: The application state.
        progress_callback: Optional callback(current, total) for progress updates.
    """
    from .models import BatchAnalysisResult, IMAGES_PER_SECOND

    # Check prerequisites
    if app_state.selected_color is None:
        return

    if not app_state.named_areas:
        return

    paths = app_state.repo.get_paths()
    if not paths:
        return

    sampling_rate = max(1, min(100, app_state.batch_sampling_rate))

    # Initialize result storage
    timestamps: list[float] = []
    area_counts: dict[str, list[int]] = {
        area.name: [] for area in app_state.named_areas
    }

    # Get indices to process based on sampling
    indices_to_process = list(range(0, len(paths), sampling_rate))
    total = len(indices_to_process)

    last_progress_time = 0.0

    with ThreadPoolExecutor(max_workers=os.process_cpu_count()) as executor:
        futures = [
            executor.submit(_load_and_detect, app_state, i, paths[i])
            for i in indices_to_process
        ]

        progress_idx = 0
        for fut in as_completed(futures):
            image_index, marks = fut.result()
            progress_idx += 1

            # Report progress
            now = time.monotonic()
            if now - last_progress_time > 0.3:
                last_progress_time = now
                if progress_callback is not None:
                    progress_callback(progress_idx, total)

            # Calculate timestamp
            timestamp = image_index / IMAGES_PER_SECOND
            timestamps.append(timestamp)

            if marks is None:
                for area_name in area_counts:
                    area_counts[area_name].append(0)
                continue

            # Count marks in areas
            counts = count_marks_in_areas(marks, app_state.named_areas)

            # Store counts for each area
            for area in app_state.named_areas:
                area_counts[area.name].append(counts.get(area.name, 0))

    # Store result
    app_state.batch_result = BatchAnalysisResult(
        timestamps=timestamps,
        area_counts=area_counts,
    )
