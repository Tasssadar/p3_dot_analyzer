"""Analysis UI helpers for overlays and results."""

from __future__ import annotations

from collections.abc import Callable

import dearpygui.dearpygui as dpg  # type: ignore

from .state import AppState
from .services.analysis_service import DetectedMark, analyze_current_frame


def draw_analysis_overlays(app_state: AppState, marks: list[DetectedMark]) -> None:
    """Draw overlay indicators on detected marks.

    Args:
        app_state: The application state.
        marks: List of detected marks to draw.
    """
    # Clear existing analysis overlays
    for tag in app_state.analysis.overlay_tags:
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)
    app_state.analysis.overlay_tags.clear()

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
            parent=app_state.ui.image_drawlist_tag,
        )
        app_state.analysis.overlay_tags.append(tag)


def run_analysis(
    app_state: AppState,
    update_areas_list: Callable[[AppState], None] | None = None,
) -> None:
    """Run the full analysis pipeline.

    This is the main entry point for analysis. It:
    1. Detects colored marks in the current image
    2. Draws overlays on detected marks
    3. Counts marks per named area and updates the UI

    Args:
        app_state: The application state.
    """
    # Clear previous analysis results
    clear_analysis_overlays(app_state)
    app_state.analysis.area_mark_counts.clear()

    result = analyze_current_frame(app_state)
    if result is None:
        if update_areas_list is not None:
            update_areas_list(app_state)
        return

    marks, counts = result
    draw_analysis_overlays(app_state, marks)
    app_state.analysis.area_mark_counts = counts

    if update_areas_list is not None:
        update_areas_list(app_state)


def clear_analysis_overlays(app_state: AppState) -> None:
    """Clear all analysis overlays from the image.

    Args:
        app_state: The application state.
    """
    for tag in app_state.analysis.overlay_tags:
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)
    app_state.analysis.overlay_tags.clear()
