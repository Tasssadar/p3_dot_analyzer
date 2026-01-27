from __future__ import annotations

from collections.abc import Callable

import dearpygui.dearpygui as dpg  # type: ignore

from .models import AppState
from datetime import datetime


def update_status(app_state: AppState, message: str) -> None:
    """Update the status text display."""
    dpg.set_value(app_state.status_text_tag, message)


def screen_to_image_coords(
    app_state: AppState, screen_x: float, screen_y: float
) -> tuple[int, int]:
    """Convert screen coordinates to image pixel coordinates.

    Returns clamped coordinates if outside the image bounds.
    """
    if app_state.current_frame is None:
        return (0, 0)

    # Get drawlist screen position
    dl_pos = dpg.get_item_rect_min(app_state.image_drawlist_tag)

    # Convert to local drawlist coords
    local_x = screen_x - dl_pos[0]
    local_y = screen_y - dl_pos[1]

    # Bounds check against current image dimensions
    if local_x < 0 or local_y < 0:
        return (0, 0)
    if (
        local_x >= app_state.current_frame.width
        or local_y >= app_state.current_frame.height
    ):
        return (app_state.current_frame.width, app_state.current_frame.height)

    return (int(local_x), int(local_y))


def sample_color_at(
    app_state: AppState, img_x: int, img_y: int
) -> tuple[int, int, int] | None:
    """Sample the RGB color at the given image coordinates."""
    if app_state.current_frame is None:
        return None

    # Bounds check
    h, w = app_state.current_frame.img.shape[:2]
    if img_x < 0 or img_x >= w or img_y < 0 or img_y >= h:
        return None

    # OpenCV loads images in BGR format
    bgr = app_state.current_frame.img[img_y, img_x]
    # Convert to RGB
    return (int(bgr[2]), int(bgr[1]), int(bgr[0]))


def update_color_display(app_state: AppState) -> None:
    """Update the color swatch and text display with the selected color."""
    if app_state.selected_color is None:
        dpg.set_value(app_state.color_text_tag, "No color selected")
        # Draw a gray swatch to indicate no selection
        dpg.configure_item(
            app_state.color_swatch_tag,
            fill=(128, 128, 128, 255),
        )
    else:
        r, g, b = app_state.selected_color
        dpg.set_value(app_state.color_text_tag, f"RGB({r}, {g}, {b})")
        # Update the swatch color
        dpg.configure_item(
            app_state.color_swatch_tag,
            fill=(r, g, b, 255),
        )


def render_frame(
    app_state: AppState,
    on_image_loaded: Callable[[AppState], None] | None = None,
) -> None:
    """Load and display the current image from the repository.

    Args:
        app_state: The application state.
        on_image_loaded: Optional callback called after image is loaded,
            typically used to redraw overlays.
    """

    if app_state.current_frame is None:
        return

    dpg.set_value(
        app_state.timestamp_text_tag,
        datetime.fromtimestamp(app_state.current_frame.ts).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    )

    # Update the dynamic texture and draw command
    dpg.configure_item(
        app_state.texture_tag,
        width=app_state.current_frame.width,
        height=app_state.current_frame.height,
    )
    dpg.set_value(app_state.texture_tag, app_state.current_frame.img)

    # Draw image from (0, 0) to (width, height) in the drawlist's space
    if dpg.does_item_exist(app_state.image_draw_tag):
        dpg.configure_item(
            app_state.image_draw_tag,
            pmin=(0, 0),
            pmax=(app_state.current_frame.width, app_state.current_frame.height),
        )
    if dpg.does_item_exist(app_state.recording_draw_tag):
        dpg.configure_item(
            app_state.recording_draw_tag,
            pmin=(0, 0),
            pmax=(app_state.current_frame.width, app_state.current_frame.height),
        )

    # Call optional callback (e.g., to redraw area overlays)
    if on_image_loaded is not None:
        on_image_loaded(app_state)
